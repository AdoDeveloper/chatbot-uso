#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# Setup nativo (sin Docker) - Chatbot USO
#
# Instala y configura: MySQL 8.0, Redis 7, Qdrant v1.17.1, Python 3.12,
# Node.js 24, Nginx. Deja los servicios como systemd units, listos para
# recibir el código de la app y arrancar.
#
# Distros soportadas (detectadas automáticamente vía /etc/os-release):
#   - Debian/Ubuntu (apt)          - Debian 11+, Ubuntu 20.04+
#   - RHEL/Rocky/AlmaLinux/Fedora (dnf) - EL 9+, Fedora 38+
#   - openSUSE Leap/Tumbleweed (zypper)
#
# Uso:
#   sudo bash setup-base.sh
#
# Requiere: acceso root, dominio ya apuntando al VPS (para el paso final de
# certbot, ejecutado en setup-services.sh).
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: ejecutar como root (sudo bash setup-base.sh)"
    exit 1
fi

# ── Detección de familia de distro ─────────────────────────────────────────────
if [ ! -f /etc/os-release ]; then
    echo "ERROR: /etc/os-release no encontrado - distro no reconocida."
    exit 1
fi
# shellcheck source=/dev/null
source /etc/os-release

case "${ID}:${ID_LIKE:-}" in
    debian:*|ubuntu:*|*:*debian*)
        PKG_FAMILY="apt"
        ;;
    rhel:*|centos:*|rocky:*|almalinux:*|fedora:*|*:*rhel*|*:*fedora*)
        PKG_FAMILY="dnf"
        ;;
    opensuse*:*|sles:*|*:*suse*)
        PKG_FAMILY="zypper"
        ;;
    *)
        echo "ERROR: distro no soportada (ID=${ID}, ID_LIKE=${ID_LIKE:-ninguno})."
        echo "Soportadas: Debian/Ubuntu, RHEL/Rocky/AlmaLinux/Fedora, openSUSE."
        exit 1
        ;;
esac
echo "Distro detectada: ${PRETTY_NAME} -> familia de paquetes: ${PKG_FAMILY}"

APP_USER="chatbot"
APP_DIR="/opt/chatbot"
MYSQL_ROOT_PASS="$(openssl rand -hex 16)"
MYSQL_APP_PASS="$(openssl rand -hex 16)"
REDIS_PASS="$(openssl rand -hex 16)"
QDRANT_API_KEY="$(openssl rand -hex 32)"
SECRETS_FILE="/root/chatbot-secrets.txt"

# ── Nombres de servicio/paquete/config que difieren por familia ───────────────
case "${PKG_FAMILY}" in
    apt)
        REDIS_SERVICE="redis-server"
        REDIS_CONF="/etc/redis/redis.conf"
        MYSQL_SERVICE="mysql"
        MYSQL_CONF_DIR="/etc/mysql/mysql.conf.d"
        ;;
    dnf)
        REDIS_SERVICE="redis"
        REDIS_CONF="/etc/redis/redis.conf"
        MYSQL_SERVICE="mysqld"
        MYSQL_CONF_DIR="/etc/my.cnf.d"
        ;;
    zypper)
        REDIS_SERVICE="redis"
        REDIS_CONF="/etc/redis/redis.conf"
        MYSQL_SERVICE="mysql"
        MYSQL_CONF_DIR="/etc/my.cnf.d"
        ;;
esac

echo "══════════════════════════════════════════════════════════════"
echo " 1/8 - Paquetes base"
echo "══════════════════════════════════════════════════════════════"
case "${PKG_FAMILY}" in
    apt)
        apt update
        apt upgrade -y
        apt install -y curl wget gnupg2 ca-certificates lsb-release software-properties-common \
            build-essential git ufw unzip
        ;;
    dnf)
        dnf -y makecache
        dnf -y upgrade
        dnf -y groupinstall "Development Tools" 2>/dev/null || dnf -y install gcc gcc-c++ make
        dnf -y install curl wget gnupg2 ca-certificates git unzip firewalld epel-release
        systemctl enable --now firewalld
        ;;
    zypper)
        zypper --non-interactive refresh
        zypper --non-interactive update
        zypper --non-interactive install -t pattern devel_basis
        zypper --non-interactive install curl wget gpg2 ca-certificates git unzip firewalld
        systemctl enable --now firewalld
        ;;
esac

echo "══════════════════════════════════════════════════════════════"
echo " 2/8 - MySQL 8.0"
echo "══════════════════════════════════════════════════════════════"
case "${PKG_FAMILY}" in
    apt)
        # Ubuntu 24.04 / Debian 12+ ya traen MySQL 8.0 en el repo nativo.
        apt install -y mysql-server
        ;;
    dnf)
        # EL9/Fedora: mysql-server 8.0 está en AppStream, sin módulo que deshabilitar.
        dnf -y install mysql-server
        ;;
    zypper)
        # openSUSE no trae MySQL Community Server en el repo base - se usa MariaDB
        # como reemplazo binario-compatible con MySQL 8 (mismo protocolo/cliente).
        zypper --non-interactive install mariadb mariadb-client
        MYSQL_SERVICE="mariadb"
        ;;
esac

mkdir -p "${MYSQL_CONF_DIR}"
# innodb_buffer_pool_size ajustado a un VPS de ~16 GB RAM (KVM 4 o equivalente).
# Ajustar a la baja si el servidor tiene menos memoria disponible.
cat > "${MYSQL_CONF_DIR}/chatbot.cnf" <<'EOF'
[mysqld]
innodb_buffer_pool_size = 4G
innodb_redo_log_capacity = 268435456
max_connections = 150
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci
bind-address = 127.0.0.1
EOF

systemctl enable --now "${MYSQL_SERVICE}"
systemctl restart "${MYSQL_SERVICE}"

mysql --user=root <<SQL
ALTER USER 'root'@'localhost' IDENTIFIED BY '${MYSQL_ROOT_PASS}';
CREATE DATABASE IF NOT EXISTS chatbot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'chatbot'@'localhost' IDENTIFIED BY '${MYSQL_APP_PASS}';
GRANT ALL PRIVILEGES ON chatbot.* TO 'chatbot'@'localhost';
FLUSH PRIVILEGES;
SQL

echo "══════════════════════════════════════════════════════════════"
echo " 3/8 - Redis 7"
echo "══════════════════════════════════════════════════════════════"
case "${PKG_FAMILY}" in
    apt)    apt install -y redis-server ;;
    dnf)    dnf -y install redis ;;
    zypper) zypper --non-interactive install redis ;;
esac

# Mismos parámetros que docker-compose.yml: appendonly, maxmemory 512mb, LRU.
sed -i 's/^# *maxmemory .*/maxmemory 512mb/' "${REDIS_CONF}"
sed -i 's/^maxmemory .*/maxmemory 512mb/' "${REDIS_CONF}"
grep -q '^maxmemory ' "${REDIS_CONF}" || echo "maxmemory 512mb" >> "${REDIS_CONF}"
sed -i 's/^# *maxmemory-policy .*/maxmemory-policy allkeys-lru/' "${REDIS_CONF}"
sed -i 's/^maxmemory-policy .*/maxmemory-policy allkeys-lru/' "${REDIS_CONF}"
grep -q '^maxmemory-policy ' "${REDIS_CONF}" || echo "maxmemory-policy allkeys-lru" >> "${REDIS_CONF}"
sed -i 's/^appendonly .*/appendonly yes/' "${REDIS_CONF}"
sed -i "s/^# *requirepass .*/requirepass ${REDIS_PASS}/" "${REDIS_CONF}"
sed -i "s/^requirepass .*/requirepass ${REDIS_PASS}/" "${REDIS_CONF}"
grep -q '^requirepass ' "${REDIS_CONF}" || echo "requirepass ${REDIS_PASS}" >> "${REDIS_CONF}"
sed -i 's/^bind .*/bind 127.0.0.1 -::1/' "${REDIS_CONF}"

systemctl enable --now "${REDIS_SERVICE}"
systemctl restart "${REDIS_SERVICE}"

echo "══════════════════════════════════════════════════════════════"
echo " 4/8 - Qdrant v1.17.1 (binario musl estático - mismo para todas las distros)"
echo "══════════════════════════════════════════════════════════════"
# Se usa el tarball *-unknown-linux-musl (enlazado estático, sin dependencia
# de la GLIBC del sistema) en vez del .deb/gnu: el .deb solo instala vía dpkg
# (no sirve en dnf/zypper) y el binario "gnu" requiere GLIBC 2.38+, que
# distros como Ubuntu 22.04/Debian 11 (GLIBC 2.35/2.31) no tienen. El musl
# corre igual en cualquier distro/glibc, confirmado contra un despliegue real.
QDRANT_VERSION="1.17.1"
useradd -r -s /usr/sbin/nologin -m -d /var/lib/qdrant qdrant 2>/dev/null || true
mkdir -p /var/lib/qdrant/storage /var/lib/qdrant/snapshots /etc/qdrant

wget -q "https://github.com/qdrant/qdrant/releases/download/v${QDRANT_VERSION}/qdrant-x86_64-unknown-linux-musl.tar.gz" \
    -O /tmp/qdrant.tar.gz
tar -xzf /tmp/qdrant.tar.gz -C /tmp
install -m 0755 /tmp/qdrant /usr/bin/qdrant
rm -f /tmp/qdrant.tar.gz /tmp/qdrant

cat > /etc/qdrant/config.yaml <<EOF
service:
  host: 127.0.0.1
  http_port: 6333
  grpc_port: 6334
  api_key: ${QDRANT_API_KEY}
storage:
  storage_path: /var/lib/qdrant/storage
  snapshots_path: /var/lib/qdrant/snapshots
  quantization:
    always_ram: true
log_level: INFO
EOF

chown -R qdrant:qdrant /var/lib/qdrant /etc/qdrant

cat > /etc/systemd/system/qdrant.service <<'EOF'
[Unit]
Description=Qdrant vector database
After=network.target

[Service]
Type=simple
User=qdrant
Group=qdrant
ExecStart=/usr/bin/qdrant --config-path /etc/qdrant/config.yaml
Restart=on-failure
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now qdrant

echo "══════════════════════════════════════════════════════════════"
echo " 5/8 - Python 3.12"
echo "══════════════════════════════════════════════════════════════"
case "${PKG_FAMILY}" in
    apt)
        apt install -y python3.12 python3.12-venv python3-pip default-libmysqlclient-dev \
            libmagic1 pkg-config
        ;;
    dnf)
        # EL9/Fedora: python3.12 puede requerir el módulo AppStream o estar ya
        # como default según versión - se instala explícito y se cae a python3
        # si el paquete versionado no existe en el repo.
        dnf -y install python3.12 python3.12-devel python3-pip mysql-devel file-devel pkgconf-pkg-config \
            || dnf -y install python3 python3-devel python3-pip mysql-devel file-devel pkgconf-pkg-config
        ;;
    zypper)
        zypper --non-interactive install python312 python312-devel python312-pip \
            libmysqlclient-devel file-devel pkg-config \
            || zypper --non-interactive install python3 python3-devel python3-pip \
                libmysqlclient-devel file-devel pkg-config
        ;;
esac

# Resuelve el binario real de Python 3.12 (o el python3 disponible como fallback)
# para que setup-services.sh use el mismo intérprete sin adivinar la ruta.
PYTHON_BIN="$(command -v python3.12 || command -v python3)"
echo "Python detectado: ${PYTHON_BIN} ($(${PYTHON_BIN} --version))"

echo "══════════════════════════════════════════════════════════════"
echo " 6/8 - Node.js 24 LTS (repos oficiales de NodeSource)"
echo "══════════════════════════════════════════════════════════════"
case "${PKG_FAMILY}" in
    apt)
        mkdir -p /etc/apt/keyrings
        # --batch --yes evita que gpg quede colgado esperando confirmación
        # interactiva de sobreescritura si el archivo ya existe de un intento
        # previo (reintentar el script sin este flag se cuelga sin avisar).
        curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key -o /tmp/nodesource-repo.gpg.key
        gpg --batch --yes --dearmor -o /etc/apt/keyrings/nodesource.gpg /tmp/nodesource-repo.gpg.key
        rm -f /tmp/nodesource-repo.gpg.key
        echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_24.x nodistro main" \
            > /etc/apt/sources.list.d/nodesource.list
        apt update
        apt install -y nodejs
        ;;
    dnf)
        curl -fsSL https://rpm.nodesource.com/setup_24.x -o /tmp/nodesource_setup.sh
        bash /tmp/nodesource_setup.sh
        rm -f /tmp/nodesource_setup.sh
        dnf -y install nodejs
        ;;
    zypper)
        # NodeSource no publica repo zypper - se usa el binario oficial de nodejs.org.
        NODE_VER="24.20.0"
        ARCH="$(uname -m)"; [ "${ARCH}" = "x86_64" ] && ARCH="x64"
        wget -q "https://nodejs.org/dist/v${NODE_VER}/node-v${NODE_VER}-linux-${ARCH}.tar.xz" -O /tmp/node.tar.xz
        tar -C /usr/local --strip-components=1 -xf /tmp/node.tar.xz
        rm -f /tmp/node.tar.xz
        ;;
esac
echo "Node instalado: $(node --version) / npm $(npm --version)"

echo "══════════════════════════════════════════════════════════════"
echo " 7/8 - Nginx + certbot + firewall"
echo "══════════════════════════════════════════════════════════════"
case "${PKG_FAMILY}" in
    apt)
        apt install -y nginx certbot python3-certbot-nginx
        # Puerto numérico en vez del perfil "OpenSSH": ese perfil solo existe si
        # openssh-server está instalado (ausente en algunos hosts mínimos/WSL).
        ufw allow 22/tcp
        ufw allow 80/tcp
        ufw allow 443/tcp
        ufw --force enable
        ;;
    dnf)
        # certbot depende de epel-release, ya instalado en el paso 1.
        dnf -y install nginx certbot python3-certbot-nginx
        firewall-cmd --permanent --add-service=ssh
        firewall-cmd --permanent --add-service=http
        firewall-cmd --permanent --add-service=https
        firewall-cmd --reload
        # SELinux (enforcing por default en EL9): permite que nginx haga proxy_pass
        # a los puertos locales del backend/frontend.
        command -v setsebool >/dev/null && setsebool -P httpd_can_network_connect on || true
        ;;
    zypper)
        zypper --non-interactive install nginx python3-certbot python3-certbot-nginx
        firewall-cmd --permanent --add-service=ssh
        firewall-cmd --permanent --add-service=http
        firewall-cmd --permanent --add-service=https
        firewall-cmd --reload
        ;;
esac
systemctl enable nginx

# Límite al journal: por defecto crece hasta el 10% del disco sin techo fijo.
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/chatbot.conf <<'EOF'
[Journal]
SystemMaxUse=500M
MaxRetentionSec=1month
EOF
systemctl restart systemd-journald

echo "══════════════════════════════════════════════════════════════"
echo " 8/8 - Usuario de la app y directorios"
echo "══════════════════════════════════════════════════════════════"
useradd -r -m -d "${APP_DIR}" -s /bin/bash "${APP_USER}" 2>/dev/null || true
mkdir -p "${APP_DIR}"/{backend,frontend,uploads}
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

cat > "${SECRETS_FILE}" <<EOF
# Generado por setup-base.sh - $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Distro: ${PRETTY_NAME} (familia: ${PKG_FAMILY})
# Guardar en un gestor de contraseñas y borrar este archivo del servidor.
PKG_FAMILY=${PKG_FAMILY}
PYTHON_BIN=${PYTHON_BIN}
MYSQL_SERVICE=${MYSQL_SERVICE}
REDIS_SERVICE=${REDIS_SERVICE}

MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASS}
MYSQL_PASSWORD=${MYSQL_APP_PASS}
REDIS_PASSWORD=${REDIS_PASS}
QDRANT_API_KEY=${QDRANT_API_KEY}

DATABASE_URL=mysql+aiomysql://chatbot:${MYSQL_APP_PASS}@127.0.0.1:3306/chatbot
REDIS_URL=redis://:${REDIS_PASS}@127.0.0.1:6379/0
QDRANT_URL=http://127.0.0.1:6333
EOF
chmod 600 "${SECRETS_FILE}"

echo ""
echo "══════════════════════════════════════════════════════════════"
echo " Listo. Servicios base instalados y corriendo:"
systemctl is-active "${MYSQL_SERVICE}" "${REDIS_SERVICE}" qdrant nginx | paste -sd ' '
echo ""
echo " Credenciales generadas en: ${SECRETS_FILE}"
echo " Usuario de la app: ${APP_USER} (home: ${APP_DIR})"
echo ""
echo " Siguiente paso: copiar el código a ${APP_DIR}, y correr:"
echo "   sudo bash setup-services.sh tu-dominio.cloud"
echo "══════════════════════════════════════════════════════════════"
