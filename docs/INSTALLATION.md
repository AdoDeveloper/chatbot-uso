# Instalación para desarrollo

Guía para levantar el chatbot en un entorno local de desarrollo usando Docker Compose (recomendado) o WSL2 manual.

---

## Opción A — Docker Compose (recomendado)

La forma más rápida. Requiere Docker Desktop 24+ con Docker Compose v2.

### Requisitos

- Docker Desktop 24+ (Windows 11 con WSL2 backend, macOS, o Linux)
- 8 GB RAM mínimo (los modelos de IA ocupan ~1.7 GB por worker)
- 15 GB de disco libre (imágenes + modelos)

> **En Windows**: clonar el repo dentro del filesystem de WSL2 (`~/chatbot-uso-v2`), **no** en `/mnt/c/`. El I/O cruzado NTFS↔WSL2 es 5-10× más lento y corrompe permisos de volúmenes Docker.

### Pasos

```bash
# 1. Clonar
git clone <URL_DEL_REPOSITORIO> chatbot-uso-v2
cd chatbot-uso-v2

# 2. Variables de entorno
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local

# 3. Editar backend/.env — ajustar mínimo:
#    SECRET_KEY           → openssl rand -hex 32
#    FIRST_ADMIN_EMAIL    → su correo
#    FIRST_ADMIN_PASSWORD → contraseña temporal

# 4. Levantar todo
docker compose up -d

# 5. Verificar que el backend esté listo (tarda ~3-5 min el primer arranque)
docker compose logs -f backend
# Esperar: "Application startup complete."

# 6. Abrir el panel
# http://localhost:3000
```

### Comandos útiles

```bash
make up              # Levantar todo
make down            # Detener todo
make logs            # Ver logs de todos los servicios
make restart         # Reiniciar servicios
make migrate         # Correr migraciones manualmente
make infra           # Solo MySQL + Redis + Qdrant (para dev local sin Docker del app)
make dev-backend     # Backend con hot-reload (requiere make infra primero)
make dev-frontend    # Frontend con hot-reload
```

---

## Opción B — WSL2 manual (sin Docker)

Para desarrollo local en Windows con WSL2 Ubuntu 22.04 sin usar Docker.

### Requisitos del sistema

| Recurso | Mínimo |
| --- | --- |
| RAM | 8 GB |
| Disco | 20 GB libres |
| OS WSL2 | Ubuntu 22.04 LTS |
| Python | 3.12 |
| Node.js | 20 LTS |

### 1. Preparar WSL2

Si aún no tiene Ubuntu 22.04 en WSL2:

```powershell
# En PowerShell como administrador
wsl --install -d Ubuntu-22.04
wsl --set-default-version 2
```

Después de reiniciar, abrir la terminal de Ubuntu.

**Importante — evitar conflicto de paths con Windows:** añadir a `/etc/wsl.conf`:

```ini
[interop]
appendWindowsPath=false
```

Reiniciar WSL (`wsl --shutdown`) y verificar: `which node` debe dar `/usr/bin/node` (no una ruta de Windows).

### 2. Instalar dependencias del sistema

```bash
sudo apt update && sudo apt upgrade -y

# Ubuntu 22.04 trae Python 3.10 de fábrica — 3.12 requiere el PPA deadsnakes.
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y \
    python3.12 python3.12-venv python3.12-dev python3-pip \
    mysql-server redis-server \
    build-essential git curl wget
```

#### Node.js 20

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
node --version  # debe ser v20.x
```

### 3. MySQL

```bash
sudo systemctl enable --now mysql

sudo mysql <<'SQL'
CREATE DATABASE chatbot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'chatbot'@'localhost' IDENTIFIED BY 'dev_password_123';
GRANT ALL PRIVILEGES ON chatbot.* TO 'chatbot'@'localhost';
FLUSH PRIVILEGES;
SQL
```

> En desarrollo puede usar una contraseña simple. En producción use `openssl rand -hex 16`.

#### Nota WSL2 + Redis

En WSL2, systemd a veces no recibe correctamente la notificación `Type=notify` de Redis. Si `sudo systemctl start redis-server` falla, editar `/etc/redis/redis.conf` y añadir/cambiar:

```
daemonize no
supervised no
```

Luego crear override: `sudo systemctl edit redis-server` y añadir:

```ini
[Service]
Type=simple
```

Reiniciar: `sudo systemctl restart redis-server` y verificar: `redis-cli ping` → `PONG`.

### 4. Qdrant

Qdrant no está en apt. Instalar el binario manualmente:

```bash
# Ubuntu 22.04 (GLIBC 2.35): usar v1.12.6 obligatoriamente.
# Ubuntu 24.04+ puede usar versiones más recientes.
# Verificar GLIBC: ldd --version
sudo mkdir -p /opt/qdrant/storage
cd /tmp
wget https://github.com/qdrant/qdrant/releases/download/v1.12.6/qdrant-x86_64-unknown-linux-gnu.tar.gz
sudo tar xzf qdrant-x86_64-unknown-linux-gnu.tar.gz -C /opt/qdrant
rm qdrant-x86_64-unknown-linux-gnu.tar.gz
```

Arrancar en background para desarrollo:

```bash
QDRANT__SERVICE__API_KEY=dev_qdrant_key \
QDRANT__STORAGE__STORAGE_PATH=/opt/qdrant/storage \
/opt/qdrant/qdrant &

# Verificar
curl http://localhost:6333/  # → {"title":"qdrant - vector search engine"...}
```

### 5. Backend (FastAPI)

```bash
cd /ruta/al/proyecto/backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn
```

#### Variables de entorno

```bash
cp .env.example .env
```

Editar `.env` con los valores de desarrollo:

```env
APP_NAME="Chatbot RAG API"
ENVIRONMENT=development
DEBUG=true

SECRET_KEY=dev_secret_key_32chars_minimo_aqui_x
DATABASE_URL=mysql+aiomysql://chatbot:dev_password_123@localhost:3306/chatbot
REDIS_URL=redis://localhost:6379/0
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=dev_qdrant_key

ALLOWED_ORIGINS=["http://localhost:3000"]
WIDGET_BASE_URL=http://localhost:8000

FIRST_ADMIN_EMAIL=admin@dev.local
FIRST_ADMIN_PASSWORD=DevPassword123!
```

#### Pre-descargar modelos (obligatorio antes del primer arranque)

Los modelos (~2 GB) deben descargarse antes de arrancar el backend. Si se dejan para el primer arranque, falla con `AttributeError: type object 'tqdm' has no attribute '_lock'` porque el prewarm corre en un thread y choca con la descarga multi-hilo de fastembed.

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

# spaCy para detección de PII (opcional pero recomendado)
python3 -m spacy download es_core_news_sm
```

#### Migraciones y arranque

```bash
alembic upgrade head

# Modo desarrollo (hot-reload):
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Verificar:
curl http://localhost:8000/api/v1/health/live  # → {"status":"ok"}
```

### 6. Frontend (Next.js)

```bash
cd /ruta/al/proyecto/frontend
npm install
cp .env.example .env.local
```

Editar `.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

```bash
# Modo desarrollo (hot-reload):
npm run dev
# → http://localhost:3000
```

---

## Variables de entorno — referencia

### Backend (`backend/.env`)

| Variable | Descripción | Ejemplo dev |
| --- | --- | --- |
| `SECRET_KEY` | JWT signing. Mínimo 32 chars. | `openssl rand -hex 32` |
| `DATABASE_URL` | MySQL con aiomysql | `mysql+aiomysql://chatbot:pass@localhost:3306/chatbot` |
| `REDIS_URL` | Redis con auth opcional en dev | `redis://localhost:6379/0` |
| `QDRANT_URL` | URL del servicio Qdrant | `http://localhost:6333` |
| `QDRANT_API_KEY` | API key de Qdrant | `dev_qdrant_key` |
| `ALLOWED_ORIGINS` | Dominios CORS permitidos | `["http://localhost:3000"]` |
| `FIRST_ADMIN_EMAIL` | Email del primer admin (seed) | `admin@dev.local` |
| `FIRST_ADMIN_PASSWORD` | Contraseña inicial del admin | `DevPassword123!` |
| `WORKERS` | Workers de Gunicorn | `1` (dev), `2` (prod 8 GB+) |
| `SMTP_*` | Envío de correo: invitaciones, escalamientos y notificaciones (opcional) | — |

### Frontend (`frontend/.env.local`)

| Variable | Descripción |
| --- | --- |
| `NEXT_PUBLIC_API_URL` | URL pública del backend (sin `/api/v1`) |
| `NEXT_PUBLIC_APP_URL` | Origen público del panel para callbacks OAuth |

---

## Verificación rápida

```bash
# Backend
curl http://localhost:8000/api/v1/health/live
# → {"status":"ok"}

# Frontend
curl -I http://localhost:3000
# → HTTP/1.1 307 Temporary Redirect (a /login)
```

Abrir `http://localhost:3000` y entrar con las credenciales de `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD`. El sistema pedirá cambiar la contraseña en el primer login.

### Limpieza de dependencias Node entre WSL y Windows

`node_modules` no debe compartirse entre Windows y WSL porque Vite/Rollup
instalan paquetes nativos por plataforma.

En WSL/Linux:

```bash
cd frontend && npm install
cd ../widget && npm install
```

En Windows PowerShell/CMD, reinstale desde Windows si va a ejecutar Node allí.
Si cambia de entorno, borre `node_modules` del paquete afectado y vuelva a
ejecutar `npm install` desde el entorno correcto.
