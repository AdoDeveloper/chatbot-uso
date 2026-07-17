# Despliegue en producción — Ubuntu Server

Guía para desplegar el chatbot en un servidor Ubuntu 22.04 LTS sin Docker, accesible por dominio público con HTTPS.

> **Destinatario:** equipo de TI de la Universidad de Sonsonate.

---

## 0. Nota crítica sobre la memoria

El sistema carga modelos de IA en memoria (embeddings multilingües + BM25 + reranker + detección de PII). **Cada worker del backend consume ~1.7 GB.**

| RAM del servidor | Workers recomendados |
| --- | --- |
| 4 GB | 1 (obligatorio — con 2 hay riesgo de OOM) |
| 8 GB | 2 |
| 16 GB+ | 4 |

Con 4 GB se recomienda configurar **swap de 2 GB** como red de seguridad (ver §1.3).

### 0.1 Capacidad y concurrencia de chats

**Diseño: cola, no rechazo.** El endpoint de chat usa un `asyncio.Semaphore`
(`LLM_MAX_CONCURRENCY`) que limita cuántas conversaciones usan un proveedor
LLM al mismo tiempo. Las peticiones que exceden el límite **esperan en cola**
hasta `LLM_QUEUE_TIMEOUT_SECONDS` (no reciben un error de inmediato) — el
usuario percibe una respuesta más lenta en horas pico, nunca un rechazo,
salvo que la cola se sature por completo durante ese tiempo de espera.
Este es el patrón documentado oficialmente para `asyncio.Semaphore`: `acquire()`
bloquea y espera en vez de lanzar una excepción
([Python docs, asyncio synchronization primitives](https://docs.python.org/3/library/asyncio-sync.html)).

El semáforo se adquiere al principio del request, antes de tocar la base de
datos — así el pico de conexiones a MySQL (guardrails, config, caché) nunca
supera `LLM_MAX_CONCURRENCY` tampoco, y el pool de conexiones no necesita
dimensionarse contra la concurrencia pico de usuarios, solo contra
`LLM_MAX_CONCURRENCY` con margen.

El pool de MySQL (`DB_POOL_SIZE + DB_MAX_OVERFLOW`) se dimensiona generoso
a propósito para que nunca sea el cuello de botella real: MySQL soporta
cientos de conexiones concurrentes con recursos modestos (~1 MB de stack
por hilo en MySQL 8.0.27+, según la documentación oficial,
["How MySQL Uses Memory"](https://dev.mysql.com/doc/refman/8.0/en/memory-use.html));
verificar `max_connections` (`SHOW VARIABLES LIKE 'max_connections';`, 151 por
defecto) antes de subir el pool por encima de 100.

Medido en pruebas de carga reales contra el endpoint público del widget
(`LLM_MAX_CONCURRENCY=30`, `DB_POOL_SIZE=50`, `DB_MAX_OVERFLOW=50`):

| Concurrencia real | Resultado |
| --- | --- |
| 9 chats | 9/9 exitosos, ~3s |
| 60 chats (2× el límite) | 60/60 exitosos — la mitad esperó en cola, nadie fue rechazado |
| 150 chats (5× el límite) | 110/150 exitosos (esperaron su turno), 40 con `503` tras agotar la cola de 45s |

`LLM_MAX_CONCURRENCY` debe ajustarse según la cuota real del proveedor LLM
contratado — un valor alto en el semáforo no sirve de nada si el proveedor
externo tiene un rate limit más estricto (ver, por ejemplo, la
[documentación oficial de rate limits de Groq](https://console.groq.com/docs/rate-limits),
que en su plan gratuito limita a 30 peticiones/min y 8,000 tokens/min para
modelos grandes — verificar el plan contratado antes de subir este valor).

**Límite aparte, no relacionado con la cola de chats:** el circuit breaker
de proveedores LLM (`app/services/ai/llm_gateway.py`) guarda su estado en
memoria del proceso. Con `WORKERS=1` esto es irrelevante. Si se sube a
`WORKERS>1` (servidores de 8 GB+), cada worker lleva su propio conteo de
fallos por proveedor de forma independiente — un proveedor caído puede
tardar más en "abrirse" globalmente, o abrirse en un worker y no en otro.
No bloquea el uso con varios workers, pero es una limitación a tener en
cuenta si se diagnostica un comportamiento inconsistente del fallback entre
proveedores en ese escenario.

---

## 1. Preparar el servidor

### 1.1 Paquetes base

```bash
sudo apt update && sudo apt upgrade -y

# Ubuntu 22.04 trae Python 3.10 de fábrica — 3.12 requiere el PPA deadsnakes.
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y \
    python3.12 python3.12-venv python3.12-dev python3-pip \
    mysql-server redis-server \
    nginx certbot python3-certbot-nginx \
    build-essential git curl wget
```

### 1.2 Node.js 20

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
node --version  # debe ser v20.x
```

### 1.3 Swap (recomendado con 4 GB de RAM)

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## 2. Código fuente

```bash
sudo mkdir -p /opt/chatbot
sudo chown $USER:$USER /opt/chatbot
git clone <URL_DEL_REPOSITORIO> /opt/chatbot
cd /opt/chatbot
```

---

## 3. MySQL

```bash
sudo systemctl enable --now mysql

# Generar password antes: openssl rand -hex 16
sudo mysql <<'SQL'
CREATE DATABASE chatbot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'chatbot'@'localhost' IDENTIFIED BY 'PASSWORD_MYSQL';
GRANT ALL PRIVILEGES ON chatbot.* TO 'chatbot'@'localhost';
FLUSH PRIVILEGES;
SQL
```

---

## 4. Redis

Editar `/etc/redis/redis.conf`:

```text
requirepass PASSWORD_REDIS
maxmemory 512mb
maxmemory-policy allkeys-lru
appendonly yes
```

```bash
sudo systemctl enable --now redis-server
sudo systemctl restart redis-server
# Verificar:
redis-cli -a PASSWORD_REDIS ping  # → PONG
```

> Generar password con `openssl rand -hex 16`.

---

## 5. Qdrant

Qdrant no está en apt; se instala su binario y se registra como servicio systemd.

> **Compatibilidad GLIBC:** Ubuntu 22.04 LTS trae GLIBC 2.35. Las versiones de Qdrant ≥ 1.13 requieren GLIBC 2.38 y fallan con `version GLIBC_2.38 not found`. Usar **v1.12.6** en Ubuntu 22.04. En Ubuntu 24.04 (GLIBC 2.39) se puede usar la última versión. Verificar: `ldd --version`.

```bash
sudo mkdir -p /opt/qdrant/storage
cd /tmp
wget https://github.com/qdrant/qdrant/releases/download/v1.12.6/qdrant-x86_64-unknown-linux-gnu.tar.gz
sudo tar xzf qdrant-x86_64-unknown-linux-gnu.tar.gz -C /opt/qdrant
rm qdrant-x86_64-unknown-linux-gnu.tar.gz
```

Crear `/etc/systemd/system/qdrant.service`:

```ini
[Unit]
Description=Qdrant Vector Database
After=network.target
# Si el servicio falla 5 veces en 60s, systemd deja de reintentar y lo marca
# como failed en vez de reiniciar en bucle infinito con Restart=always.
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=/opt/qdrant
Environment=QDRANT__SERVICE__API_KEY=API_KEY_QDRANT
Environment=QDRANT__STORAGE__STORAGE_PATH=/opt/qdrant/storage
ExecStart=/opt/qdrant/qdrant
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now qdrant
```

> Generar API key con `openssl rand -hex 32`.

---

## 6. Backend (FastAPI)

### 6.1 Entorno Python

```bash
cd /opt/chatbot/backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn
```

### 6.2 Archivo `.env`

Crear `/opt/chatbot/backend/.env`:

```env
APP_NAME="Chatbot RAG API"
ENVIRONMENT=production
DEBUG=false

# Generar con: openssl rand -hex 32
SECRET_KEY=GENERAR_CON_OPENSSL

# MySQL (debe coincidir con §3)
DATABASE_URL=mysql+aiomysql://chatbot:PASSWORD_MYSQL@localhost:3306/chatbot

# Pool de conexiones a MySQL. Máximo simultáneo = DB_POOL_SIZE + DB_MAX_OVERFLOW.
# Se dimensiona generoso a propósito: la concurrencia real de chats la limita
# LLM_MAX_CONCURRENCY (abajo), no este pool. Ver §0.1.
DB_POOL_SIZE=50
DB_MAX_OVERFLOW=50

# Máximo de conversaciones que usan un proveedor LLM al mismo tiempo. Las que
# exceden ESPERAN en cola (no se rechazan) hasta LLM_QUEUE_TIMEOUT_SECONDS.
# Ajustar según la cuota real del proveedor contratado — ver §0.1.
LLM_MAX_CONCURRENCY=30
LLM_QUEUE_TIMEOUT_SECONDS=45

# Redis (debe coincidir con §4)
REDIS_URL=redis://:PASSWORD_REDIS@localhost:6379/0

# Qdrant (debe coincidir con §5)
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=API_KEY_QDRANT

# Dominio público del panel (sustituir por el real)
ALLOWED_ORIGINS=["https://chatbot.usonsonate.edu.sv"]
WIDGET_BASE_URL=https://chatbot.usonsonate.edu.sv

# Primer administrador (se crea solo en el primer arranque)
FIRST_ADMIN_EMAIL=admin@usonsonate.edu.sv
FIRST_ADMIN_PASSWORD=CONTRASEÑA_FUERTE_INICIAL

# Con 4 GB de RAM: 1 solo worker. Con 8 GB: 2.
WORKERS=1

# SMTP (opcional — para invitaciones)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=correo@usonsonate.edu.sv
SMTP_PASSWORD=APP_PASSWORD
SMTP_FROM=noreply@usonsonate.edu.sv
SMTP_TLS=true
```

```bash
chmod 600 /opt/chatbot/backend/.env
```

> Con `ENVIRONMENT=production`, el sistema **no arranca** si `SECRET_KEY` es insegura o si `DEBUG=true`.

### 6.3 Migraciones de base de datos

```bash
cd /opt/chatbot/backend
source .venv/bin/activate
alembic upgrade head
```

### 6.4 Pre-descargar modelos (obligatorio)

Los modelos (~2 GB) deben descargarse antes de arrancar el servicio. Si se omite este paso, el backend falla con `AttributeError: type object 'tqdm' has no attribute '_lock'` porque el prewarm corre en un thread y choca con la descarga multi-hilo de fastembed.

```bash
# Con el venv activo:
python3 -c "
from fastembed import TextEmbedding, SparseTextEmbedding
TextEmbedding('intfloat/multilingual-e5-large')
SparseTextEmbedding('Qdrant/bm25')
print('Embeddings descargados.')
"

python3 -c "
from flashrank import Ranker
Ranker(model_name='ms-marco-MultiBERT-L-12')
print('Reranker descargado.')
"

# spaCy para detección de PII (recomendado)
python3 -m spacy download es_core_news_sm
```

> Una vez descargados, el servicio systemd incluye `HF_HUB_OFFLINE=1` para que use el caché local y no revalide contra HuggingFace en cada arranque.

### 6.5 Servicio systemd

Crear `/etc/systemd/system/chatbot-backend.service`:

```ini
[Unit]
Description=Chatbot RAG Backend (FastAPI)
After=network.target mysql.service redis-server.service qdrant.service
Requires=mysql.service redis-server.service qdrant.service
# Si el servicio falla 5 veces en 60s, systemd deja de reintentar y lo marca
# como failed en vez de reiniciar en bucle infinito con Restart=always.
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/chatbot/backend
EnvironmentFile=/opt/chatbot/backend/.env
Environment=HF_HUB_OFFLINE=1
ExecStart=/opt/chatbot/backend/.venv/bin/gunicorn app.main:app \
    --bind 127.0.0.1:8000 \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers 1 \
    --timeout 300 \
    --graceful-timeout 30
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo chown -R www-data:www-data /opt/chatbot/backend
sudo systemctl daemon-reload
sudo systemctl enable --now chatbot-backend
```

> Ajustar `--workers` según la RAM disponible (ver §0).

---

## 7. Frontend (Next.js)

### 7.1 Compilar

```bash
cd /opt/chatbot/frontend
NEXT_PUBLIC_API_URL=https://chatbot.usonsonate.edu.sv \
NEXT_PUBLIC_APP_URL=https://chatbot.usonsonate.edu.sv \
npm install
NEXT_PUBLIC_API_URL=https://chatbot.usonsonate.edu.sv \
NEXT_PUBLIC_APP_URL=https://chatbot.usonsonate.edu.sv \
npm run build
```

### 7.2 Servicio systemd

Crear `/etc/systemd/system/chatbot-frontend.service`:

```ini
[Unit]
Description=Chatbot RAG Frontend (Next.js)
After=network.target
# Si el servicio falla 5 veces en 60s, systemd deja de reintentar y lo marca
# como failed en vez de reiniciar en bucle infinito con Restart=always.
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/chatbot/frontend
Environment=NODE_ENV=production
Environment=NEXT_TELEMETRY_DISABLED=1
Environment=PORT=3000
Environment=HOSTNAME=0.0.0.0
ExecStart=/usr/bin/node /opt/chatbot/frontend/.next/standalone/server.js
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo chown -R www-data:www-data /opt/chatbot/frontend
sudo systemctl daemon-reload
sudo systemctl enable --now chatbot-frontend
```

---

## 8. Widget embebible (opcional)

Si se usará el widget de chat en otros sitios:

```bash
cd /opt/chatbot/widget
npm install
npm run build
sudo mkdir -p /opt/chatbot/backend/static/widget
sudo cp dist/widget.js /opt/chatbot/backend/static/widget/
sudo systemctl restart chatbot-backend
```

---

## 9. Nginx + HTTPS

### 9.1 Configuración

Crear `/etc/nginx/sites-available/chatbot`:

```nginx
upstream chatbot_backend  { server 127.0.0.1:8000; keepalive 32; }
upstream chatbot_frontend { server 127.0.0.1:3000; keepalive 16; }

server {
    listen 80;
    server_name chatbot.usonsonate.edu.sv;

    client_max_body_size 55m;

    # ── Security headers (sincronizar con nginx/nginx.conf del repo) ───────────
    # OJO: un add_header dentro de un location anula TODOS los heredados; por eso
    # se re-declaran en /widget/.
    add_header X-Content-Type-Options  "nosniff" always;
    add_header X-Frame-Options         "DENY"    always;
    add_header X-XSS-Protection        "0"       always;
    add_header Referrer-Policy         "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy      "camera=(), microphone=(), geolocation=()" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;
    # Descomentar tras configurar HTTPS con certbot (sección 10):
    # add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;

    location /api/ {
        proxy_pass         http://chatbot_backend;
        proxy_http_version 1.1;
        proxy_set_header   Connection        "";
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 120s;
        # Sin streaming SSE: el chat responde con un unico JSON completo.
        # Buffering desactivado igual — no afecta una respuesta JSON normal.
        proxy_buffering off;
        proxy_cache     off;
    }

    location /widget/ {
        proxy_pass         http://chatbot_backend;
        proxy_http_version 1.1;
        proxy_set_header   Connection "";
        proxy_set_header   Host       $host;
        # Re-declarar los headers de seguridad (un add_header local anula los del server)
        add_header X-Content-Type-Options  "nosniff" always;
        add_header X-Frame-Options         "DENY"    always;
        add_header X-XSS-Protection        "0"       always;
        add_header Referrer-Policy         "strict-origin-when-cross-origin" always;
        add_header Permissions-Policy      "camera=(), microphone=(), geolocation=()" always;
        add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;
        expires    1d;
        add_header Cache-Control "public, max-age=86400";
    }

    location / {
        proxy_pass         http://chatbot_frontend;
        proxy_http_version 1.1;
        proxy_set_header   Connection        "";
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/chatbot /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

### 9.2 Certificado HTTPS (Let's Encrypt)

> El dominio debe apuntar (registro DNS A) a la IP pública del servidor **antes** de ejecutar certbot.

```bash
sudo certbot --nginx -d chatbot.usonsonate.edu.sv
```

Certbot configura HTTPS automáticamente y gestiona la renovación.

---

## 10. Hardening

### MySQL

- Usar contraseñas generadas con `openssl rand -hex 16` (no los ejemplos de la guía).
- Conexiones restringidas a `localhost` (ya configurado con `'chatbot'@'localhost'`).

### Redis

- `requirepass` con password de 32+ caracteres.
- Bind solo a `127.0.0.1`.
- Considerar `rename-command FLUSHALL ""` para evitar borrado accidental.

### Qdrant

- `QDRANT__SERVICE__API_KEY` siempre configurado.
- Bind a `127.0.0.1` o restringir con firewall.

### Backend FastAPI

- `DEBUG=false` y `ENVIRONMENT=production` en `.env`.
- `ALLOWED_ORIGINS` con la lista exacta de dominios (no usar `*`).

### Firewall

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
# Los puertos 3000, 8000, 3306, 6379, 6333 quedan cerrados al exterior.
```

---

## 11. Backups

### Backup MySQL

```bash
# Crear /etc/cron.daily/chatbot-mysql-backup con:
#!/bin/bash
DATE=$(date +%Y%m%d-%H%M)
mkdir -p /var/backups/chatbot
MYSQL_PWD="$MYSQL_PASSWORD" mysqldump --single-transaction --routines --triggers \
    -u chatbot -h 127.0.0.1 chatbot | gzip > /var/backups/chatbot/db-${DATE}.sql.gz
find /var/backups/chatbot -name 'db-*.sql.gz' -mtime +14 -delete
```

```bash
chmod +x /etc/cron.daily/chatbot-mysql-backup
```

**Restore:**

```bash
gunzip < /var/backups/chatbot/db-20260426-0300.sql.gz | \
    MYSQL_PWD="$MYSQL_PASSWORD" mysql -u chatbot chatbot
```

### Qdrant (vectores)

```bash
# Snapshot via API (incremental):
curl -X POST http://localhost:6333/collections/chatbot_sources/snapshots

# O copiar el directorio de storage:
rsync -a /opt/qdrant/storage/ /var/backups/chatbot/qdrant/
```

### Uploads (PDFs subidos)

```bash
rsync -a /opt/chatbot/backend/uploads/ /var/backups/chatbot/uploads/
```

---

## 12. Monitoreo

| Servicio | Comando de logs |
| --- | --- |
| Backend | `sudo journalctl -u chatbot-backend -f` |
| Frontend | `sudo journalctl -u chatbot-frontend -f` |
| MySQL | `sudo tail -f /var/log/mysql/error.log` |
| Nginx | `sudo tail -f /var/log/nginx/error.log` |

**Healthcheck externo:** configurar UptimeRobot u otra herramienta para monitorear `https://chatbot.usonsonate.edu.sv/api/v1/health/live` → debe responder `{"status":"ok"}`.

---

## 13. Actualizaciones

```bash
cd /opt/chatbot
git pull

# Backend
cd backend
source .venv/bin/activate
pip install --no-cache-dir -r requirements.txt
alembic upgrade head
sudo systemctl restart chatbot-backend

# Frontend
cd ../frontend
npm install
NEXT_PUBLIC_API_URL=https://chatbot.usonsonate.edu.sv \
NEXT_PUBLIC_APP_URL=https://chatbot.usonsonate.edu.sv \
npm run build
sudo systemctl restart chatbot-frontend
```

---

## 14. Verificación final

```bash
# Estado de los 5 servicios
sudo systemctl status mysql redis-server qdrant chatbot-backend chatbot-frontend

# Logs en vivo del backend
sudo journalctl -u chatbot-backend -f
```

Pruebas funcionales:

1. `https://chatbot.usonsonate.edu.sv` → carga el login del panel.
2. Entrar con `FIRST_ADMIN_EMAIL` → fuerza cambio de contraseña.
3. `https://chatbot.usonsonate.edu.sv/api/v1/health/ready` → `{"status":"ok", "checks": {...}}`.

> Nota: con `ENVIRONMENT=production` la documentación interactiva (`/api/docs`,
> `/api/redoc`) queda **deshabilitada** a propósito; no usarla como verificación.

---

## 15. Checklist de go-live

### Bloqueantes — no entrar a producción sin esto

- [ ] `SECRET_KEY` generada con `openssl rand -hex 32`, no el valor de ejemplo.
- [ ] `ENVIRONMENT=production` y `DEBUG=false` en el `.env` del servidor.
- [ ] `.env` con `chmod 600` y fuera del repositorio.
- [ ] HTTPS activo con certificado válido; `http://` redirige a `https://`.
- [ ] HSTS habilitado en nginx (`Strict-Transport-Security`).
- [ ] `WORKERS=1` confirmado en servidor de 4 GB.
- [ ] Los 5 servicios systemd habilitados con `systemctl enable` (arrancan tras reinicio).
- [ ] Backup automático corriendo y probado con una restauración real.

### Importantes — completar en los primeros días

- [ ] Contraseña del primer admin cambiada tras el primer login.
- [ ] `ALLOWED_ORIGINS` con solo el dominio real del panel.
- [ ] SMTP probado (invitaciones y notificaciones).
- [ ] Modelo spaCy instalado (`es_core_news_sm`) para detección de PII completa.
- [ ] Prueba de carga básica con usuarios concurrentes esperados.

### Verificación funcional (humo)

- [ ] El panel carga en `https://<dominio>` y muestra el login.
- [ ] Login funciona y fuerza cambio de contraseña.
- [ ] Se sube un documento de prueba, se aprueba y queda indexado.
- [ ] El chatbot responde una pregunta cubierta por ese documento (RAG end-to-end).
- [ ] Un guardrail bloquea un intento de inyección de prompt.
- [ ] El widget embebido carga y responde en una página externa de prueba.

---

## 16. Credenciales a generar antes de empezar

```bash
openssl rand -hex 32   # SECRET_KEY
openssl rand -hex 16   # PASSWORD_MYSQL
openssl rand -hex 16   # PASSWORD_REDIS
openssl rand -hex 32   # API_KEY_QDRANT
```

Más `FIRST_ADMIN_PASSWORD` (≥12 chars, mayúscula, minúscula, dígito y símbolo).

---

## 17. Mantenimiento rápido

| Tarea | Comando |
| --- | --- |
| Reiniciar backend | `sudo systemctl restart chatbot-backend` |
| Ver logs backend | `sudo journalctl -u chatbot-backend -f` |
| Backup de la BD | `mysqldump -u chatbot -p chatbot > backup.sql` |
| Backup vectorial | `rsync -a /opt/qdrant/storage/ /var/backups/qdrant/` |
| Rollback de código | `git checkout <commit>` → actualizar deps → reiniciar servicios |

---

## 18. Entorno de desarrollo (WSL)

Para desarrollo se usa **WSL (Ubuntu 22.04)** sobre Windows, con los mismos servicios (`mysql`, `redis-server`, `qdrant`, `chatbot-backend`, `chatbot-frontend`) gestionados por systemd, pero con dos diferencias respecto a producción:

- **Backend con Uvicorn directo** (sin Gunicorn): un solo proceso, suficiente para desarrollo. El `ExecStart` del servicio apunta a `uvicorn app.main:app --host 127.0.0.1 --port 8000`.
- **Sin reverse proxy ni HTTPS**: se accede directo a `localhost:3000` (frontend) y `localhost:8000` (backend).

### Flujo de sincronización (Windows → WSL)

El código se edita en Windows y se despliega a WSL:

```bash
# Backend: copiar fuente y reiniciar
cp <archivo>.py /opt/chatbot/backend/app/...
sudo systemctl restart chatbot-backend

# Frontend: build nativo en WSL y desplegar el .next compilado
cd ~/chatbot-uso-v2/frontend && npm run build
rsync -a --delete .next/ /opt/chatbot/frontend/.next/
sudo systemctl restart chatbot-frontend
```

> **Nota sobre `node_modules`**: no copiar `node_modules` desde Windows a WSL — los enlaces simbólicos y binarios nativos se corrompen al cruzar el sistema de archivos NTFS. Ejecutar `npm install` directamente en WSL.

### Variable `HF_HUB_OFFLINE`

`HF_HUB_OFFLINE=1` es **seguro** una vez los modelos están en caché (`~/.cache/fastembed/`): el arranque usa el caché local sin revalidar contra HuggingFace. fastembed gestiona el modo offline internamente; no requiere comprobaciones adicionales.
