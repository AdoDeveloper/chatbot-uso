# Chatbot RAG - Universidad de Sonsonate

Chatbot institucional con pipeline RAG (Retrieval-Augmented Generation) y panel de administración para la Universidad de Sonsonate (USO).

**Stack**: FastAPI · Next.js 15 · MySQL 8 · Qdrant · Redis · multilingual-e5-large · Adaptive RAG (LangGraph)

---

## Índice

- [Requisitos generales](#requisitos-generales)
- [Quick start con Docker](#quick-start-con-docker)
- [Documentación](#documentación)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Variables de entorno críticas](#variables-de-entorno-críticas)
- [Scripts administrativos](#scripts-administrativos)

---

## Requisitos generales

| Recurso | Mínimo | Recomendado |
| --- | --- | --- |
| RAM | 8 GB | 16 GB |
| CPU | 4 cores | 8 cores |
| Disco | 15 GB | 30 GB |
| OS | Linux / macOS / Windows 11 con WSL2 | Ubuntu 24.04 LTS |
| Python | 3.12 | 3.12 |
| Node.js | 24 LTS | 24 LTS |

El backend descarga ~2 GB de modelos de embeddings la primera vez.

---

## Quick start con Docker

**Requisitos**: Docker Desktop 24+ con Docker Compose v2.

> En Windows: clonar dentro del filesystem de WSL2 (`~/chatbot-uso`), **no** en `/mnt/c/`. El I/O cruzado NTFS↔WSL2 es 5-10× más lento.

```bash
# 1. Clonar
git clone <URL_DEL_REPOSITORIO> chatbot-uso
cd chatbot-uso

# 2. Variables de entorno
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local

# 3. Editar backend/.env - ajustar mínimo:
#    SECRET_KEY           → openssl rand -hex 32
#    FIRST_ADMIN_EMAIL    → su correo
#    FIRST_ADMIN_PASSWORD → contraseña temporal

# 4. Levantar todo
docker compose up -d

# 5. Verificar (tarda ~3-5 min el primer arranque)
curl http://localhost:8000/api/v1/health/live
# → {"status":"ok"}

# 6. Abrir el panel
# http://localhost:3000
```

### Comandos útiles (Makefile)

```bash
make setup             # Prepara el .env (solo la primera vez)
make up                # Levantar todo
make prod SERVER=<ip>  # Desplegar en un servidor
make down              # Detener todo
make build              # Reconstruir las imágenes
make logs               # Ver logs
make restart            # Reiniciar servicios
make ps                 # Estado de los contenedores
make migrate            # Correr migraciones manualmente
make infra              # Solo MySQL + Redis + Qdrant
make dev-backend        # Backend con hot-reload (requiere make infra)
make dev-frontend       # Frontend con hot-reload
make shell-backend      # Shell dentro del contenedor backend
make shell-db           # mysql CLI dentro del contenedor mysql
```

### Limpieza de dependencias Node en WSL/Windows

Rollup/Vite instalan binarios nativos por sistema operativo. Si aparece un
error como `Cannot find module @rollup/rollup-linux-x64-gnu`, reinstala
dependencias en el mismo entorno donde ejecutarás Node.

```bash
# WSL/Linux
cd frontend && npm install
cd ../widget && npm install
```

En Windows PowerShell/CMD, haga la reinstalación desde Windows. No mezcle el
mismo `node_modules` entre Windows y WSL; si trabaja principalmente en WSL,
evite correr `npm install` desde Windows dentro del mismo checkout.

### Health checks

| Endpoint | Uso |
| --- | --- |
| `/api/v1/health` | Compatibilidad: liveness simple |
| `/api/v1/health/live` | Liveness formal para contenedor/uptime |
| `/api/v1/health/ready` | Readiness: verifica MySQL, Redis y Qdrant |

---

## Documentación

| Documento | Contenido |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Diagramas de despliegue, flujo del chat, ingestión, modelo de datos y Adaptive RAG |
| [docs/API.md](docs/API.md) | Referencia de los endpoints REST del backend |
| [docs/MANUAL-USUARIO.md](docs/MANUAL-USUARIO.md) | Guía del panel de administración para el usuario final |
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | Entorno de desarrollo local con Docker Compose o WSL2 manual |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Despliegue en producción en Ubuntu Server sin Docker (systemd, nginx, HTTPS, backups) |
| [deploy/native/README.md](deploy/native/README.md) | Scripts de despliegue nativo automatizados, multi-distro (apt/dnf/zypper) |

---

## Estructura del repositorio

```text
chatbot-uso/
├── backend/                FastAPI + SQLAlchemy + Alembic
│   ├── app/                Código de la API
│   ├── alembic/            Migraciones de BD
│   ├── scripts/            Utilidades de instalación (esquema y datos semilla)
│   ├── tests/              pytest
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── entrypoint.sh
│   └── .env.example
├── frontend/               Next.js 15 + Tailwind v4 + shadcn/ui
│   ├── src/                Código del panel de administración
│   ├── e2e/                Pruebas end-to-end (Playwright)
│   ├── package.json
│   ├── Dockerfile
│   └── .env.example
├── widget/                 SDK Preact embebible (Shadow DOM)
├── deploy/native/          Scripts de despliegue nativo (sin Docker)
├── nginx/                  Configuración del proxy inverso
├── docs/                   Documentación técnica
├── docker-compose.yml      Stack completo para desarrollo
├── docker-compose.prod.yml Ajustes de producción (límites de memoria, réplicas)
├── docker-compose.ci.yml   Override del E2E en CI (caché de modelos)
├── Makefile                Atajos
└── README.md               Este archivo
```

---

## Variables de entorno críticas

### Backend (`backend/.env`)

| Variable | Descripción |
| --- | --- |
| `SECRET_KEY` | JWT signing - generar con `openssl rand -hex 32` |
| `DATABASE_URL` | MySQL: `mysql+aiomysql://user:pass@host:3306/db` |
| `REDIS_URL` | Redis: `redis://:password@host:6379/0` |
| `QDRANT_URL` | URL del servicio Qdrant |
| `QDRANT_API_KEY` | API key de Qdrant |
| `ALLOWED_ORIGINS` | Dominios CORS: `["https://admin.usonsonate.edu.sv"]` |
| `FIRST_ADMIN_EMAIL` | Email del primer admin (seed) |
| `FIRST_ADMIN_PASSWORD` | Contraseña inicial del admin |

### Docker Compose / Makefile

| Variable | Descripción |
| --- | --- |
| `FRONTEND_API_URL` | URL pública usada por el navegador para llamar a la API |
| `FRONTEND_APP_URL` | Origen público del panel para callbacks OAuth; si se omite hereda `FRONTEND_API_URL` |
| `BACKEND_MEM_LIMIT` | Límite de memoria del backend en `docker-compose.prod.yml` |

### Frontend (`frontend/.env.local`)

| Variable | Descripción |
| --- | --- |
| `NEXT_PUBLIC_API_URL` | URL pública del backend (sin `/api/v1`) |
| `NEXT_PUBLIC_APP_URL` | Origen público del panel para callbacks OAuth |

---

## Scripts administrativos

Utilidades de instalación en `backend/scripts/`, para poblar una instancia
nueva. Ninguna forma parte del arranque automático: se ejecutan a mano cuando
hacen falta y es seguro repetirlas.

| Script | Uso |
| --- | --- |
| `init_db.py` | Crear el esquema y sembrar los datos iniciales |
| `seed_provider_catalog.py` | Poblar el catálogo de tipos de proveedor LLM (URL base y headers por defecto) |
