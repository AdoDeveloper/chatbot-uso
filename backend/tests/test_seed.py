from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models.enums import NotificationChannel, NotificationEvent, UserRole
from app.models.escalation_rule import EscalationRule
from app.models.notification_rule import NotificationRule
from app.models.user import User
from app.models.widget_config import WidgetConfig
from app.services.system import seed

pytestmark = pytest.mark.asyncio


async def test_seed_first_admin_creates_admin_from_settings(db_session, monkeypatch):
    """Contra una BD limpia, seed_first_admin crea el admin con el email/rol
    definidos en settings y lo marca para forzar cambio de contraseña."""
    from app.core.config import get_settings

    monkeypatch.setenv("FIRST_ADMIN_EMAIL", "root@example.com")
    monkeypatch.setenv("FIRST_ADMIN_PASSWORD", "Sup3rSecret!")
    get_settings.cache_clear()

    await seed.seed_first_admin(db_session)

    user = await db_session.scalar(
        select(User).where(User.email == "root@example.com")
    )
    assert user is not None
    assert user.role == UserRole.admin
    assert user.must_change_password is True
    assert user.full_name == "Root"

    get_settings.cache_clear()


async def test_seed_first_admin_is_idempotent(db_session, monkeypatch):
    """Correrlo dos veces no crea un segundo admin ni falla: la segunda
    llamada ve count > 0 y retorna temprano."""
    from app.core.config import get_settings

    monkeypatch.setenv("FIRST_ADMIN_EMAIL", "root@example.com")
    monkeypatch.setenv("FIRST_ADMIN_PASSWORD", "Sup3rSecret!")
    get_settings.cache_clear()

    await seed.seed_first_admin(db_session)
    await seed.seed_first_admin(db_session)

    count = await db_session.scalar(select(func.count()).select_from(User))
    assert count == 1

    get_settings.cache_clear()


async def test_seed_first_admin_skips_when_users_exist(db_session, make_user, monkeypatch):
    """Si ya hay usuarios (de cualquier origen), no crea al admin de settings,
    incluso si FIRST_ADMIN_EMAIL apunta a otro correo."""
    from app.core.config import get_settings

    await make_user(email="existing@example.com", role=UserRole.viewer)

    monkeypatch.setenv("FIRST_ADMIN_EMAIL", "root@example.com")
    monkeypatch.setenv("FIRST_ADMIN_PASSWORD", "Sup3rSecret!")
    get_settings.cache_clear()

    await seed.seed_first_admin(db_session)

    count = await db_session.scalar(select(func.count()).select_from(User))
    assert count == 1
    admin = await db_session.scalar(
        select(User).where(User.email == "root@example.com")
    )
    assert admin is None

    get_settings.cache_clear()


async def test_seed_first_admin_requires_email_configured(db_session, monkeypatch):
    """Sin FIRST_ADMIN_EMAIL no debe crear un admin con placeholder silencioso;
    se espera un error explícito."""
    from app.core.config import get_settings

    monkeypatch.setenv("FIRST_ADMIN_EMAIL", "")
    monkeypatch.setenv("FIRST_ADMIN_PASSWORD", "Sup3rSecret!")
    get_settings.cache_clear()

    with pytest.raises(ValueError):
        await seed.seed_first_admin(db_session)

    count = await db_session.scalar(select(func.count()).select_from(User))
    assert count == 0

    get_settings.cache_clear()


async def test_seed_first_admin_requires_password_configured(db_session, monkeypatch):
    """Sin FIRST_ADMIN_PASSWORD tampoco debe crear el admin."""
    from app.core.config import get_settings

    monkeypatch.setenv("FIRST_ADMIN_EMAIL", "root@example.com")
    monkeypatch.setenv("FIRST_ADMIN_PASSWORD", "")
    get_settings.cache_clear()

    with pytest.raises(ValueError):
        await seed.seed_first_admin(db_session)

    count = await db_session.scalar(select(func.count()).select_from(User))
    assert count == 0

    get_settings.cache_clear()


async def test_seed_defaults_runs_clean(db_session):
    """seed_defaults corre sin error contra una BD limpia y crea widget config,
    reglas de notificación por cada evento/canal, y reglas de escalamiento."""
    await seed.seed_defaults(db_session)

    wc_count = await db_session.scalar(select(func.count()).select_from(WidgetConfig))
    assert wc_count == 1

    rule_count = await db_session.scalar(select(func.count()).select_from(NotificationRule))
    assert rule_count == len(list(NotificationEvent)) * 2

    email_rules = (
        await db_session.scalars(
            select(NotificationRule).where(
                NotificationRule.channel == NotificationChannel.email
            )
        )
    ).all()
    assert all(r.enabled is False for r in email_rules)

    inapp_rules = (
        await db_session.scalars(
            select(NotificationRule).where(
                NotificationRule.channel == NotificationChannel.in_app
            )
        )
    ).all()
    assert all(r.enabled is True for r in inapp_rules)

    er_count = await db_session.scalar(select(func.count()).select_from(EscalationRule))
    assert er_count == 2


async def test_seed_defaults_is_idempotent(db_session):
    """Correr seed_defaults dos veces no duplica widget config, reglas de
    notificación ni reglas de escalamiento."""
    await seed.seed_defaults(db_session)
    await seed.seed_defaults(db_session)

    wc_count = await db_session.scalar(select(func.count()).select_from(WidgetConfig))
    assert wc_count == 1

    rule_count = await db_session.scalar(select(func.count()).select_from(NotificationRule))
    assert rule_count == len(list(NotificationEvent)) * 2

    er_count = await db_session.scalar(select(func.count()).select_from(EscalationRule))
    assert er_count == 2
