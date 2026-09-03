#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# Paso 2 del setup nativo: instala la app (backend + frontend), crea los
# systemd units, migra la BD, descarga los modelos de embeddings y configura
# nginx como reverse proxy (equivalente nativo de nginx/nginx.conf).
#
# Multi-distro: reutiliza PKG_FAMILY/PYTHON_BIN detectados por setup-base.sh
# (Debian/Ubuntu, RHEL/Rocky/AlmaLinux/Fedora, openSUSE).
#
# Requisitos previos: haber corrido setup-base.sh, y haber copiado el
# código del repo a /opt/chatbot/backend y /opt/chatbot/frontend (rsync/git).
#
# Uso:
#   sudo bash setup-services.sh tu-dominio.cloud
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: ejecutar como root (sudo bash setup-services.sh <dominio>)"
    exit 1
fi

DOMAIN="${1:?Uso: sudo bash setup-services.sh tu-dominio.cloud}"
APP_USER="chatbot"
APP_DIR="/opt/chatbot"
SECRETS_FILE="/root/chatbot-secrets.txt"

if [ ! -f "${SECRETS_FILE}" ]; then
    echo "ERROR: ${SECRETS_FILE} no existe - corre primero setup-base.sh"
    exit 1
fi
# shellcheck source=/dev/null
source "${SECRETS_FILE}"

: "${PKG_FAMILY:?SECRETS_FILE incompleto - vuelve a correr setup-base.sh}"
: "${PYTHON_BIN:?SECRETS_FILE incompleto - vuelve a correr setup-base.sh}"

if [ ! -d "${APP_DIR}/backend/app" ] || [ ! -f "${APP_DIR}/frontend/package.json" ]; then
    echo "ERROR: copia el código a ${APP_DIR}/backend y ${APP_DIR}/frontend antes de continuar"
    echo "  ejemplo: rsync -a ./backend/ ${APP_DIR}/backend/ && rsync -a ./frontend/ ${APP_DIR}/frontend/"
    exit 1
fi

echo "══════════════════════════════════════════════════════════════"
echo " 1/6 - Backend: venv + dependencias (${PYTHON_BIN})"
echo "══════════════════════════════════════════════════════════════"
cd "${APP_DIR}/backend"
sudo -u "${APP_USER}" "${PYTHON_BIN}" -m venv venv
sudo -u "${APP_USER}" venv/bin/pip install --upgrade pip
sudo -u "${APP_USER}" venv/bin/pip install -r requirements.txt

# .env del backend - mismas claves que backend/.env.example, con las
# credenciales reales generadas en el paso 1 y apuntando a localhost
# (todos los servicios corren nativos en el mismo host, sin red Docker).
if [ ! -f "${APP_DIR}/backend/.env" ]; then
    cat > "${APP_DIR}/backend/.env" <<EOF
ENVIRONMENT=production
DEBUG=false
SECRET_KEY=$(openssl rand -hex 32)
DATABASE_URL=${DATABASE_URL}
REDIS_URL=${REDIS_URL}
QDRANT_URL=${QDRANT_URL}
QDRANT_API_KEY=${QDRANT_API_KEY}
HF_HUB_OFFLINE=1
FIRST_ADMIN_EMAIL=admin@${DOMAIN}
FIRST_ADMIN_PASSWORD=$(openssl rand -hex 12)
ALLOWED_ORIGINS=["https://${DOMAIN}"]
WIDGET_BASE_URL=https://${DOMAIN}
EOF
    chown "${APP_USER}:${APP_USER}" "${APP_DIR}/backend/.env"
    chmod 600 "${APP_DIR}/backend/.env"
    echo "  -> .env generado. Admin: admin@${DOMAIN} / ver contraseña en el archivo .env"
fi

echo "══════════════════════════════════════════════════════════════"
echo " 2/6 - Migraciones + pre-descarga de modelos de embeddings"
echo "══════════════════════════════════════════════════════════════"
sudo -u "${APP_USER}" bash -c "cd '${APP_DIR}/backend' && venv/bin/alembic upgrade head"

sudo -u "${APP_USER}" bash -c "
cd '${APP_DIR}/backend'
HF_HUB_OFFLINE=0 venv/bin/python -c \"
from fastembed import TextEmbedding, SparseTextEmbedding
cache = '${APP_DIR}/backend/.cache/fastembed'
TextEmbedding('intfloat/multilingual-e5-large', cache_dir=cache)
SparseTextEmbedding('Qdrant/bm25', cache_dir=cache)
print('Modelos descargados.')
\"
"

echo "══════════════════════════════════════════════════════════════"
echo " 3/6 - Frontend: build de producción (standalone Next.js)"
echo "══════════════════════════════════════════════════════════════"
cd "${APP_DIR}/frontend"
sudo -u "${APP_USER}" env NEXT_PUBLIC_API_URL="https://${DOMAIN}" \
    NEXT_PUBLIC_APP_URL="https://${DOMAIN}" \
    npm ci
sudo -u "${APP_USER}" env NEXT_PUBLIC_API_URL="https://${DOMAIN}" \
    NEXT_PUBLIC_APP_URL="https://${DOMAIN}" \
    npm run build

echo "══════════════════════════════════════════════════════════════"
echo " 4/6 - systemd units: backend y frontend"
echo "══════════════════════════════════════════════════════════════"
cat > /etc/systemd/system/chatbot-backend.service <<EOF
[Unit]
Description=Chatbot backend (FastAPI/uvicorn)
After=network.target ${MYSQL_SERVICE}.service ${REDIS_SERVICE}.service qdrant.service
Requires=${MYSQL_SERVICE}.service ${REDIS_SERVICE}.service qdrant.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}/backend
EnvironmentFile=${APP_DIR}/backend/.env
Environment=HF_HUB_OFFLINE=1
Environment=HOME=${APP_DIR}/backend
ExecStart=${APP_DIR}/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --timeout-graceful-shutdown 30
Restart=on-failure
RestartSec=5
TimeoutStopSec=35

[Install]
WantedBy=multi-user.target
EOF

# Un solo proceso uvicorn, sin --workers: el circuit breaker del LLM gateway y
# el semáforo de concurrencia del chat viven en memoria del proceso (mismo
# criterio que backend/entrypoint.sh - ver comentario ahí).

cat > /etc/systemd/system/chatbot-frontend.service <<EOF
[Unit]
Description=Chatbot frontend (Next.js standalone)
After=network.target chatbot-backend.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}/frontend/.next/standalone
Environment=NODE_ENV=production
Environment=NEXT_TELEMETRY_DISABLED=1
Environment=PORT=3000
Environment=HOSTNAME=127.0.0.1
ExecStart=$(command -v node)/server.js
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
# ExecStart de arriba se corrige abajo: $(command -v node) es la ruta al
# binario, no un directorio - se reescribe con la ruta real de node y server.js.
sed -i "s#ExecStart=.*/server.js#ExecStart=$(command -v node) ${APP_DIR}/frontend/.next/standalone/server.js#" \
    /etc/systemd/system/chatbot-frontend.service

systemctl daemon-reload
systemctl enable --now chatbot-backend
systemctl enable --now chatbot-frontend

echo "══════════════════════════════════════════════════════════════"
echo " 5/6 - Nginx (equivalente nativo de nginx/nginx.conf)"
echo "══════════════════════════════════════════════════════════════"
case "${PKG_FAMILY}" in
    apt)
        NGINX_SITE_DIR="/etc/nginx/sites-available"
        NGINX_ENABLED_DIR="/etc/nginx/sites-enabled"
        mkdir -p "${NGINX_SITE_DIR}" "${NGINX_ENABLED_DIR}"
        NGINX_CONF_PATH="${NGINX_SITE_DIR}/chatbot"
        ;;
    dnf|zypper)
        # RHEL/openSUSE nginx no usa sites-available/enabled por default -
        # se deja el vhost directo en conf.d, incluido por nginx.conf.
        NGINX_CONF_PATH="/etc/nginx/conf.d/chatbot.conf"
        ;;
esac

cat > "${NGINX_CONF_PATH}" <<EOF
upstream chatbot_backend  { server 127.0.0.1:8000; keepalive 32; }
upstream chatbot_frontend { server 127.0.0.1:3000; keepalive 16; }

limit_req_zone \$binary_remote_addr zone=auth_zone:10m rate=10r/m;
limit_req_zone \$binary_remote_addr zone=chat_zone:10m rate=30r/m;

server {
    listen 80;
    server_name ${DOMAIN};

    client_max_body_size 55m;

    add_header X-Content-Type-Options  "nosniff"         always;
    add_header X-Frame-Options         "DENY"            always;
    add_header X-XSS-Protection        "0"               always;
    add_header Referrer-Policy         "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy      "camera=(), microphone=(), geolocation=()" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: http: https:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;

    location /api/v1/auth/login {
        limit_req zone=auth_zone burst=5 nodelay;
        proxy_pass         http://chatbot_backend;
        proxy_http_version 1.1;
        proxy_set_header   Connection        "";
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
    }

    location /api/v1/widget/public/chat {
        limit_req zone=chat_zone burst=10 nodelay;
        proxy_pass         http://chatbot_backend;
        proxy_http_version 1.1;
        proxy_set_header   Connection        "";
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
        proxy_buffering off;
        proxy_cache     off;
    }

    # Solo /api/v1/ (backend FastAPI) - /api/auth/callback/microsoft es una ruta
    # de Next.js (frontend/src/app/api/auth/callback/microsoft/route.ts) y debe
    # caer al location / de más abajo, no aquí.
    location /api/v1/ {
        proxy_pass         http://chatbot_backend;
        proxy_http_version 1.1;
        proxy_set_header   Connection        "";
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 120s;
        proxy_buffering off;
        proxy_cache     off;
    }

    location /widget/ {
        proxy_pass         http://chatbot_backend;
        proxy_http_version 1.1;
        proxy_set_header   Connection "";
        proxy_set_header   Host       \$host;
        add_header X-Content-Type-Options  "nosniff"         always;
        add_header X-Frame-Options         "DENY"            always;
        add_header X-XSS-Protection        "0"               always;
        add_header Referrer-Policy         "strict-origin-when-cross-origin" always;
        add_header Permissions-Policy      "camera=(), microphone=(), geolocation=()" always;
        add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: http: https:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;
        expires    5m;
        add_header Cache-Control "public, max-age=300, must-revalidate";
    }

    location /uploads/ {
        proxy_pass         http://chatbot_backend;
        proxy_http_version 1.1;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        expires            7d;
        add_header         Cache-Control "public, immutable";
    }

    location / {
        proxy_pass         http://chatbot_frontend;
        proxy_http_version 1.1;
        proxy_set_header   Connection        "";
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
    }
}
EOF

if [ "${PKG_FAMILY}" = "apt" ]; then
    ln -sf "${NGINX_CONF_PATH}" "${NGINX_ENABLED_DIR}/chatbot"
    rm -f "${NGINX_ENABLED_DIR}/default"
fi
nginx -t
systemctl reload nginx || systemctl restart nginx

echo "══════════════════════════════════════════════════════════════"
echo " 6/6 - SSL (Let's Encrypt / certbot)"
echo "══════════════════════════════════════════════════════════════"
echo " El DNS de ${DOMAIN} debe apuntar YA a la IP de este servidor."
echo " Ejecutando certbot (modificará el bloque server automáticamente)..."
certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos -m "admin@${DOMAIN}" --redirect || {
    echo "AVISO: certbot falló - probablemente el DNS aún no propaga."
    echo "  Reintenta manualmente: certbot --nginx -d ${DOMAIN}"
}

echo ""
echo "══════════════════════════════════════════════════════════════"
echo " Listo. Servicios de la app:"
systemctl is-active chatbot-backend chatbot-frontend nginx | paste -sd ' '
echo ""
echo " https://${DOMAIN}"
echo " Admin: revisar ${APP_DIR}/backend/.env (FIRST_ADMIN_EMAIL/PASSWORD)"
echo " Logs:  journalctl -u chatbot-backend -f"
echo "        journalctl -u chatbot-frontend -f"
echo "══════════════════════════════════════════════════════════════"
