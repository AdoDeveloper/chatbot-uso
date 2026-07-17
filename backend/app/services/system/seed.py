from __future__ import annotations

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


async def _db_lock(db: AsyncSession, name: str) -> None:
    """Serializa workers en el startup usando un lock a nivel de base de datos.

    MySQL  → GET_LOCK(name, 30)     — lock de sesión, liberado en RELEASE_LOCK o al cerrar la conexión
    SQLite → sin lock (conexión única en tests)
    """
    from app.core.config import get_settings
    url = get_settings().DATABASE_URL
    if url.startswith("mysql"):
        await db.execute(text("SELECT GET_LOCK(:n, 30)"), {"n": name})

async def seed_first_admin(db: AsyncSession) -> None:
    """Crea el primer admin si la tabla de usuarios está vacía.

    Usa un lock de base de datos para serializar entre workers de Gunicorn.
    """
    try:
        await _db_lock(db, _SEED_LOCK_NAME)

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
            "seed.admin_created — cambia la contraseña en el primer login",
            email=settings.FIRST_ADMIN_EMAIL,
        )

    except Exception:
        await db.rollback()
        logger.exception("seed.admin_failed — el admin inicial NO fue creado")
        raise


async def seed_defaults(db: AsyncSession) -> None:
    """Crea registros por defecto para widget, notificaciones y escalamiento.

    Idempotente: puede llamarse en cada arranque del servidor sin efectos
    secundarios si los registros ya existen.

    Serializado con _db_lock: con WORKERS>1 todos los workers ejecutan el
    lifespan a la vez; sin el lock, ambos veían las tablas vacías e insertaban
    a la vez (choque contra uq_escalation_channels_type y duplicados silenciosos
    en widget_config). El lock se libera al cerrar la conexión (MySQL) o en
    COMMIT (PG); el worker que espera ve los counts > 0 y no inserta nada.
    """
    import uuid as _uuid
    from sqlalchemy import select as _sel

    await _db_lock(db, _DEFAULTS_LOCK_NAME)

    # Widget config
    wc_count = await db.scalar(_sel(func.count()).select_from(WidgetConfig))
    if not wc_count:
        db.add(WidgetConfig())

    # Reglas de notificación por evento (correo + in-app).
    for event in NotificationEvent:
        email_exists = await db.scalar(
            _sel(NotificationRule.id).where(
                NotificationRule.event == event,
                NotificationRule.channel == NotificationChannel.email,
            )
        )
        if not email_exists:
            db.add(NotificationRule(
                id=_uuid.uuid4(),
                event=event,
                channel=NotificationChannel.email,
                enabled=False,
            ))
        inapp_exists = await db.scalar(
            _sel(NotificationRule.id).where(
                NotificationRule.event == event,
                NotificationRule.channel == NotificationChannel.in_app,
            )
        )
        if not inapp_exists:
            db.add(NotificationRule(
                id=_uuid.uuid4(),
                event=event,
                channel=NotificationChannel.in_app,
                enabled=True,
            ))

    # Escalation rules por defecto
    er_count = await db.scalar(_sel(func.count()).select_from(EscalationRule))
    if not er_count:
        db.add(EscalationRule(
            id=_uuid.uuid4(),
            name="Sin respuesta tras 2 intentos",
            description="Si el chatbot no encuentra respuesta en 2 turnos consecutivos",
            trigger_type=EscalationTrigger.no_answer,
            enabled=True,
        ))
        db.add(EscalationRule(
            id=_uuid.uuid4(),
            name="Usuario solicita agente",
            description='Detecta frases como "quiero hablar con alguien"',
            trigger_type=EscalationTrigger.user_request,
            enabled=True,
        ))

    await db.commit()
