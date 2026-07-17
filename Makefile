# ──────────────────────────────────────────────────────────────────────────────
# Uso rápido
#   make setup          → prepara el .env (solo la primera vez)
#   make up             → levanta todo en local  (http://localhost)
#   make prod SERVER=x  → despliega en servidor  (http://x)
#   make down           → detiene el stack
#   make logs           → sigue los logs en tiempo real
# ──────────────────────────────────────────────────────────────────────────────

SERVER       ?= localhost
FRONTEND_API_URL ?= http://$(SERVER)
FRONTEND_APP_URL ?= $(FRONTEND_API_URL)

.PHONY: help setup up down prod build logs restart ps \
        infra dev-backend dev-frontend migrate \
        shell-backend shell-db

# ── Ayuda ──────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  Comandos principales"
	@echo "  ─────────────────────────────────────────────────────────"
	@echo "  make setup                  Prepara el .env (solo la primera vez)"
	@echo "  make up                     Levanta el stack completo en local"
	@echo "                              Accede en http://localhost"
	@echo "  make prod SERVER=<ip>       Despliega en un servidor"
	@echo "                              Accede en http://<ip>"
	@echo "  make down                   Detiene todos los contenedores"
	@echo "  make logs                   Sigue los logs en tiempo real"
	@echo ""
	@echo "  Desarrollo local (infra en Docker, apps en terminal)"
	@echo "  ─────────────────────────────────────────────────────────"
	@echo "  make infra                  Solo MySQL + Redis + Qdrant"
	@echo "  make dev-backend            Backend con hot-reload (requiere infra)"
	@echo "  make dev-frontend           Frontend con hot-reload"
	@echo "  make migrate                Aplica migraciones de base de datos"
	@echo ""
	@echo "  Utilidades"
	@echo "  ─────────────────────────────────────────────────────────"
	@echo "  make build                  Reconstruye las imágenes"
	@echo "  make restart                Reinicia todos los contenedores"
	@echo "  make ps                     Estado de los contenedores"
	@echo "  make shell-backend          Shell dentro del contenedor backend"
	@echo "  make shell-db               mysql CLI dentro del contenedor mysql"
	@echo ""

# ── Setup ──────────────────────────────────────────────────────────────────────
setup:
	@echo "Setup manual:"
	@echo "  cp backend/.env.example backend/.env"
	@echo "  cp frontend/.env.example frontend/.env.local"
	@echo "  Edita backend/.env con SECRET_KEY, FIRST_ADMIN_EMAIL y FIRST_ADMIN_PASSWORD."
	@echo "  Luego ejecuta: docker compose up -d --build"

# ── Stack completo — local ─────────────────────────────────────────────────────
up:
	docker compose up -d --build

# ── Stack completo — servidor ──────────────────────────────────────────────────
prod:
	@echo "Desplegando con FRONTEND_API_URL=$(FRONTEND_API_URL) ..."
	@echo "Panel público FRONTEND_APP_URL=$(FRONTEND_APP_URL)"
	FRONTEND_API_URL=$(FRONTEND_API_URL) FRONTEND_APP_URL=$(FRONTEND_APP_URL) \
	  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# ── Parar ──────────────────────────────────────────────────────────────────────
down:
	docker compose down

# ── Build manual ───────────────────────────────────────────────────────────────
build:
	docker compose build

# ── Observabilidad ─────────────────────────────────────────────────────────────
logs:
	docker compose logs -f

restart:
	docker compose restart

ps:
	docker compose ps

# ── Desarrollo local (infra en Docker, apps en terminal) ───────────────────────
infra:
	docker compose up -d mysql redis qdrant

dev-backend:
	cd backend && uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

migrate:
	cd backend && alembic upgrade head

# ── Utilidades ─────────────────────────────────────────────────────────────────
shell-backend:
	docker compose exec backend sh

shell-db:
	docker compose exec mysql mysql -u chatbot -pchatbot chatbot
