"""Inicializa la base de datos desde cero: migraciones + datos semilla.

Uso:
    python -m scripts.init_db

Equivalente a lo que ya hace entrypoint.sh en Docker (alembic upgrade head
seguido del seeding que corre en el lifespan de FastAPI), pero como comando
único para entornos sin Docker que necesiten levantar una instalación nueva
sin arrancar el servidor.

Es seguro correrlo repetidamente: tanto `alembic upgrade head` como cada
función de seed son idempotentes.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def run_migrations() -> None:
    print("==> Aplicando migraciones (alembic upgrade head)...")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
    )
    if result.returncode != 0:
        print("ERROR: alembic upgrade head falló.")
        sys.exit(result.returncode)
    print("Migraciones aplicadas.")


async def run_seed() -> None:
    from app.db.session import AsyncSessionLocal
    from app.services.system.rbac import seed_rbac
    from app.services.system.seed import seed_defaults, seed_first_admin
    from app.services.system.settings import seed_default_settings

    print("==> Sembrando datos iniciales...")
    async with AsyncSessionLocal() as db:
        await seed_first_admin(db)
        await seed_defaults(db)
        await seed_default_settings(db)
        await seed_rbac(db)
    print("Datos iniciales listos.")


def main() -> None:
    run_migrations()
    asyncio.run(run_seed())
    print("==> Base de datos inicializada.")


if __name__ == "__main__":
    main()
