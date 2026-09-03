# Despliegue nativo (sin Docker)

Alternativa al `docker-compose.yml` del proyecto: instala MySQL, Redis, Qdrant,
backend y frontend directo sobre el sistema operativo, gestionados por systemd.

Versiones verificadas contra `requirements.txt` / `package.json` / CI del
proyecto al momento de escribir esto: MySQL 8.0, Redis 7, **Qdrant v1.17.1**
(coincide con `qdrant-client==1.17.1` y la imagen `qdrant/qdrant:v1.17.1` del
compose), Python 3.12, Node 24.

## Distros soportadas

`setup-base.sh` detecta la familia de distro vía `/etc/os-release` y ramifica
cada paso de instalación en consecuencia - no hay que elegir nada a mano:

| Familia | Distros | Gestor | Notas |
|---|---|---|---|
| `apt` | Debian 11+, Ubuntu 20.04+ | apt | MySQL 8.0 en repo nativo (Ubuntu 24.04+/Debian 12+); en versiones más viejas puede traer 8.0 igualmente vía repo oficial de Oracle si el paquete nativo no alcanza |
| `dnf` | RHEL/Rocky/AlmaLinux 9+, Fedora 38+ | dnf | Requiere EPEL (se habilita solo) para certbot; SELinux se ajusta con `setsebool httpd_can_network_connect on` |
| `zypper` | openSUSE Leap/Tumbleweed | zypper | Usa MariaDB (protocolo/cliente compatible con MySQL 8) en vez de MySQL Community Server, que no está en el repo base |

Node 24 se instala vía NodeSource en `apt`/`dnf`; en `zypper` (sin repo
NodeSource propio) se descarga el binario oficial de nodejs.org directo.

## Uso

```bash
# 1. En el servidor, como root:
sudo bash setup-base.sh
# Detecta la distro, instala MySQL/Redis/Qdrant/Python/Node/Nginx/certbot,
# crea el usuario "chatbot" y genera credenciales en /root/chatbot-secrets.txt

# 2. Copiar el código al servidor (desde tu máquina):
rsync -a --exclude node_modules --exclude venv --exclude .git \
    ./backend/  root@TU_IP:/opt/chatbot/backend/
rsync -a --exclude node_modules --exclude .next --exclude .git \
    ./frontend/ root@TU_IP:/opt/chatbot/frontend/

# 3. De vuelta en el servidor, como root:
sudo bash setup-services.sh tu-dominio.cloud
# Crea el venv, instala deps, migra la BD, descarga modelos, build del
# frontend, systemd units, nginx (multi-distro) y SSL vía certbot.
```

## Qué NO automatiza este script

- **Backups**: `docker-compose.prod.yml` trae un contenedor `backup` con
  `mysqldump` + retención de 7 días. En nativo, arma esto con un cronjob:
  `crontab -e` como root, `0 3 * * * mysqldump -u root -p... chatbot | gzip > /var/backups/chatbot_$(date +\%Y\%m\%d).sql.gz`.
- **Actualizar código**: cada deploy nuevo es repetir el `rsync` +
  `venv/bin/pip install -r requirements.txt` (si cambiaron deps) +
  `npm run build` + `systemctl restart chatbot-backend chatbot-frontend`.
- **Renovación de SSL**: certbot instala su propio timer de systemd
  (`systemctl list-timers | grep certbot`) - no requiere acción manual.

## Diferencias con el stack Docker

| | Docker (`docker-compose.yml`) | Nativo (estos scripts) |
|---|---|---|
| Aislamiento | Cada servicio en su contenedor | Todo en el mismo SO |
| `innodb_buffer_pool_size` | 512M (comparte RAM con contenedores) | 4G (más margen en un VPS de ~16 GB dedicado) |
| Reinicio de un servicio | `docker compose restart X` | `systemctl restart chatbot-X` |
| Logs | `docker compose logs X` | `journalctl -u chatbot-X -f` |
| Rollback | `docker compose down && checkout anterior && up` | manual (sin imágenes versionadas) |
| Reproducibilidad vs CI | Alta (mismo compose en test.yml y prod) | Media (el CI usa contenedores de servicio) |
| Portabilidad de distro | N/A (mismas imágenes en cualquier host con Docker) | Depende de `PKG_FAMILY` - ver tabla de arriba |

## Node.js: 24 LTS, no el 20 que fija `package.json`

Los scripts instalan **Node 24** (Active LTS, soporte hasta abril 2028), no el
20.x que declara `package.json`/CI del repo. Next.js 15.5.25 solo exige
`>=18.18`, así que no hay incompatibilidad real; Node 20 ya no recibe parches
de seguridad. `package.json` y `test.yml`/`frontend/Dockerfile` del repo
también fueron actualizados a Node 24 para no divergir entre este flujo
nativo, Docker y CI.
