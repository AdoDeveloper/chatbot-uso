from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import (
    EscalationTrigger,
    NotificationChannel,
    NotificationEvent,
    UserRole,
)
from app.models.escalation_rule import EscalationRule
from app.models.notification_rule import NotificationRule
from app.models.user import User
from app.models.widget_config import WidgetConfig
from app.services.users import service as user_service

logger = structlog.get_logger(__name__)

_SEED_LOCK_NAME = "chatbot_seed_admin"
_DEFAULTS_LOCK_NAME = "chatbot_seed_defaults"


@asynccontextmanager
async def _named_lock(name: str):
    """GET_LOCK en una conexión propia: el commit de la sesión la devolvería al pool con el bloqueo tomado."""
    if not get_settings().DATABASE_URL.startswith("mysql"):
        yield
        return
    from app.db.session import engine
    async with engine.connect() as conn:
        await conn.execute(text("SELECT GET_LOCK(:n, 30)"), {"n": name})
        try:
            yield
        finally:
            await conn.execute(text("SELECT RELEASE_LOCK(:n)"), {"n": name})


async def seed_first_admin(db: AsyncSession) -> None:
    """Crea el primer admin si la tabla de usuarios está vacía."""
    async with _named_lock(_SEED_LOCK_NAME):
        await _seed_first_admin(db)


async def _seed_first_admin(db: AsyncSession) -> None:
    try:
        count = await db.scalar(select(func.count()).select_from(User))
        if count:
            return

        settings = get_settings()

        if not settings.FIRST_ADMIN_EMAIL:
            raise ValueError(
                "FIRST_ADMIN_EMAIL no está definida en .env. "
                "Define el email del primer admin antes de arrancar."
            )

        password = settings.FIRST_ADMIN_PASSWORD
        if not password:
            raise ValueError(
                "FIRST_ADMIN_PASSWORD no está definida en .env. "
                "Define una contraseña segura antes de arrancar."
            )

        logger.warning(
            "seed.admin_creating",
            email=settings.FIRST_ADMIN_EMAIL,
        )

        # Derivar nombre del prefijo del email (admin@dominio.com → Admin)
        email_prefix = settings.FIRST_ADMIN_EMAIL.split("@")[0]
        full_name = email_prefix.replace(".", " ").replace("_", " ").title() or "Administrador"

        user = await user_service.create(
            db,
            email=settings.FIRST_ADMIN_EMAIL,
            full_name=full_name,
            password=password,
            role=UserRole.admin,
        )
        user.must_change_password = True
        await db.commit()

        logger.warning(
            "seed.admin_created - cambia la contraseña en el primer login",
            email=settings.FIRST_ADMIN_EMAIL,
        )

    except Exception:
        await db.rollback()
        logger.exception("seed.admin_failed - el admin inicial NO fue creado")
        raise


async def seed_defaults(db: AsyncSession) -> None:
    """Crea registros por defecto para widget, notificaciones y escalamiento."""
    async with _named_lock(_DEFAULTS_LOCK_NAME):
        wc_count = await db.scalar(select(func.count()).select_from(WidgetConfig))
        if not wc_count:
            db.add(WidgetConfig())

        for event in NotificationEvent:
            email_exists = await db.scalar(
                select(NotificationRule.id).where(
                    NotificationRule.event == event,
                    NotificationRule.channel == NotificationChannel.email,
                )
            )
            if not email_exists:
                db.add(NotificationRule(
                    id=uuid.uuid4(),
                    event=event,
                    channel=NotificationChannel.email,
                    enabled=False,
                ))
            inapp_exists = await db.scalar(
                select(NotificationRule.id).where(
                    NotificationRule.event == event,
                    NotificationRule.channel == NotificationChannel.in_app,
                )
            )
            if not inapp_exists:
                db.add(NotificationRule(
                    id=uuid.uuid4(),
                    event=event,
                    channel=NotificationChannel.in_app,
                    enabled=True,
                ))

        er_count = await db.scalar(select(func.count()).select_from(EscalationRule))
        if not er_count:
            db.add(EscalationRule(
                id=uuid.uuid4(),
                name="Sin respuesta tras 2 intentos",
                description="Si el chatbot no encuentra respuesta en 2 turnos consecutivos",
                trigger_type=EscalationTrigger.no_answer,
                enabled=True,
            ))
            db.add(EscalationRule(
                id=uuid.uuid4(),
                name="Usuario solicita agente",
                description='Detecta frases como "quiero hablar con alguien"',
                trigger_type=EscalationTrigger.user_request,
                enabled=True,
            ))

        await db.commit()
