# Chatbot RAG — Universidad de Sonsonate

Chatbot institucional con pipeline RAG (Retrieval-Augmented Generation) y panel de administración para la Universidad de Sonsonate (USO).

**Stack**: FastAPI · Next.js 15 · MySQL 8 · Qdrant · Redis · multilingual-e5-large · Adaptive RAG (LangGraph)

---

## Índice

- [Quick start con Docker](#quick-start-con-docker)
- [Documentación](#documentación)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Variables de entorno críticas](#variables-de-entorno-críticas)

---

## Requisitos generales

| Recurso | Mínimo | Recomendado |
| --- | --- | --- |
| RAM | 8 GB | 16 GB |
| CPU | 4 cores | 8 cores |
| Disco | 15 GB | 30 GB |
| OS | Linux / macOS / Windows 11 con WSL2 | Ubuntu 22.04 LTS |
| Python | 3.12 | 3.12 |
| Node.js | 20 LTS | 20 LTS |

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

# 3. Editar backend/.env — ajustar mínimo:
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
make up              # Levantar todo
make down            # Detener todo
make logs            # Ver logs
make restart         # Reiniciar servicios
make migrate         # Correr migraciones manualmente
make infra           # Solo MySQL + Redis + Qdrant
make dev-backend     # Backend con hot-reload (requiere make infra)
make dev-frontend    # Frontend con hot-reload
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
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | Entorno de desarrollo local con Docker Compose o WSL2 manual |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Despliegue en producción en Ubuntu Server sin Docker (systemd, nginx, HTTPS, backups) |

---

## Estructura del repositorio

```text
chatbot-uso/
├── backend/                FastAPI + SQLAlchemy + Alembic
│   ├── app/                Código de la API
│   ├── alembic/            Migraciones de BD
│   ├── tests/              pytest
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── entrypoint.sh
│   └── .env.example
├── frontend/               Next.js 15 + Tailwind v4 + shadcn/ui
│   ├── src/                Código del panel de administración
│   ├── package.json
│   ├── Dockerfile
│   └── .env.example
├── widget/                 SDK Preact embebible (Shadow DOM)
├── docs/                   Documentación técnica
├── docker-compose.yml      Stack completo para desarrollo
├── Makefile                Atajos
└── README.md               Este archivo
```

---

## Variables de entorno críticas

### Backend (`backend/.env`)

| Variable | Descripción |
| --- | --- |
| `SECRET_KEY` | JWT signing — generar con `openssl rand -hex 32` |
| `DATABASE_URL` | MySQL: `mysql+aiomysql://user:pass@host:3306/db` |
| `REDIS_URL` | Redis: `redis://:password@host:6379/0` |
| `QDRANT_URL` | URL del servicio Qdrant |
| `QDRANT_API_KEY` | API key de Qdrant |
| `ALLOWED_ORIGINS` | Dominios CORS: `["https://admin.usonsonate.edu.sv"]` |
| `FIRST_ADMIN_EMAIL` | Email del primer admin (seed) |
| `FIRST_ADMIN_PASSWORD` | Contraseña inicial del admin |
| `WORKERS` | Workers Gunicorn: 1 (4 GB RAM), 2 (8 GB+) |

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

### Scripts administrativos

`backend/scripts/update_system_prompt.py` es una utilidad manual para actualizar
el prompt del sistema desde CLI. No forma parte del arranque automático.
