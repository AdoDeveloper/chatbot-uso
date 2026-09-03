#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# Primer boot: clona el repo y encadena setup-base.sh + setup-services.sh en
# un solo comando. Pensado para un VPS recién provisionado (Ubuntu 24.04).
#
# Uso (como root, en el VPS):
#   curl -fsSL https://raw.githubusercontent.com/AdoDeveloper/chatbot-uso/master/deploy/native/bootstrap.sh | bash -s -- tu-dominio.cloud
#
# O manualmente:
#   git clone https://github.com/AdoDeveloper/chatbot-uso.git /root/chatbot-uso
#   bash /root/chatbot-uso/deploy/native/bootstrap.sh tu-dominio.cloud
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: ejecutar como root"
    exit 1
fi

DOMAIN="${1:?Uso: bootstrap.sh tu-dominio.cloud}"
REPO_URL="https://github.com/AdoDeveloper/chatbot-uso.git"
CLONE_DIR="/root/chatbot-uso"
APP_DIR="/opt/chatbot"

echo "══════════════════════════════════════════════════════════════"
echo " 1/4 - Clonando repositorio"
echo "══════════════════════════════════════════════════════════════"
if [ -d "${CLONE_DIR}" ]; then
    echo "El repo ya existe en ${CLONE_DIR}, actualizando..."
    git -C "${CLONE_DIR}" pull
else
    apt-get update -qq && apt-get install -y -qq git
    git clone "${REPO_URL}" "${CLONE_DIR}"
fi

echo "══════════════════════════════════════════════════════════════"
echo " 2/4 - setup-base.sh (paquetes del sistema)"
echo "══════════════════════════════════════════════════════════════"
bash "${CLONE_DIR}/deploy/native/setup-base.sh"

echo "══════════════════════════════════════════════════════════════"
echo " 3/4 - Copiando código de la app a ${APP_DIR}"
echo "══════════════════════════════════════════════════════════════"
rsync -a --exclude node_modules --exclude venv --exclude .venv --exclude .git --exclude .next \
    "${CLONE_DIR}/backend/" "${APP_DIR}/backend/"
rsync -a --exclude node_modules --exclude .git --exclude .next \
    "${CLONE_DIR}/frontend/" "${APP_DIR}/frontend/"
chown -R chatbot:chatbot "${APP_DIR}/backend" "${APP_DIR}/frontend"

echo "══════════════════════════════════════════════════════════════"
echo " 4/4 - setup-services.sh (app, systemd, nginx, SSL)"
echo "══════════════════════════════════════════════════════════════"
bash "${CLONE_DIR}/deploy/native/setup-services.sh" "${DOMAIN}"

echo ""
echo "══════════════════════════════════════════════════════════════"
echo " Bootstrap completo. https://${DOMAIN}"
echo "══════════════════════════════════════════════════════════════"
