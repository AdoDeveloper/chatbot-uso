"""Tests del wizard de bienvenida.

Cubre la lógica del endpoint `/auth/onboarding-status` que decide en qué paso
está cada admin y el endpoint `/auth/onboarding-dismiss` que permite saltarlo.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.enums import (
    ConversationStatus, MessageRole, ReviewStatus, SourceStatus, SourceType, UserRole,
)
from app.models.chat_conversation import ChatConversation
from app.models.chat_message import ChatMessage
from app.models.llm_provider import LLMProvider
from app.models.source import Source


@pytest.fixture
async def admin_user(make_user):
    return await make_user(role=UserRole.admin)


async def _create_provider(db_session, *, is_active: bool = False) -> LLMProvider:
    p = LLMProvider(
        id=uuid.uuid4(),
        name="Test provider",
        provider_type="groq",
        model_name="llama-3.3-70b-versatile",
        api_key_encrypted="fake-encrypted-key",
        is_active=is_active,
        priority=1 if is_active else None,
    )
    db_session.add(p)
    await db_session.commit()
    return p


async def _create_source(
    db_session,
    *,
    review_status: ReviewStatus = ReviewStatus.pendiente_revision,
) -> Source:
    s = Source(
        id=uuid.uuid4(),
        name="Manual de prueba",
        type=SourceType.pdf,
        status=SourceStatus.ready,
        review_status=review_status,
        chunk_count=10,
    )
    db_session.add(s)
    await db_session.commit()
    return s


async def _create_message(db_session) -> None:
    conv = ChatConversation(
        id=uuid.uuid4(),
        session_id="test-session",
        status=ConversationStatus.active,
    )
    db_session.add(conv)
    await db_session.commit()
    msg = ChatMessage(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        role=MessageRole.user,
        content="¿Cuándo abren las inscripciones?",
    )
    db_session.add(msg)
    await db_session.commit()


class TestOnboardingStatus:
    async def test_step_1_when_no_providers(self, client, admin_user, auth_headers):
        """Sistema vacío: paso 1 = configurar proveedor LLM."""
        r = await client.get(
            "/api/v1/auth/onboarding-status",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["step"] == 1
        assert body["providers_configured"] is False
        assert body["providers_active"] is False
        assert body["sources_uploaded"] is False
        assert body["sources_approved"] is False
        assert body["messages_sent"] == 0
        assert body["dismissed"] is False

    async def test_step_2_when_provider_inactive(
        self, client, db_session, admin_user, auth_headers
    ):
        """Proveedor existe pero inactivo: paso 2 = activar/probar."""
        await _create_provider(db_session, is_active=False)
        r = await client.get(
            "/api/v1/auth/onboarding-status",
            headers=auth_headers(admin_user),
        )
        assert r.json()["step"] == 2
        assert r.json()["providers_configured"] is True
        assert r.json()["providers_active"] is False

    async def test_step_3_when_no_sources(
        self, client, db_session, admin_user, auth_headers
    ):
        """Proveedor activo pero sin fuentes: paso 3 = subir documento."""
        await _create_provider(db_session, is_active=True)
        r = await client.get(
            "/api/v1/auth/onboarding-status",
            headers=auth_headers(admin_user),
        )
        assert r.json()["step"] == 3

    async def test_step_4_when_sources_unapproved(
        self, client, db_session, admin_user, auth_headers
    ):
        """Fuente subida pero pendiente de revisión: paso 4 = aprobar."""
        await _create_provider(db_session, is_active=True)
        await _create_source(db_session, review_status=ReviewStatus.pendiente_revision)
        r = await client.get(
            "/api/v1/auth/onboarding-status",
            headers=auth_headers(admin_user),
        )
        assert r.json()["step"] == 4
        assert r.json()["sources_uploaded"] is True
        assert r.json()["sources_approved"] is False

    async def test_step_5_when_no_messages(
        self, client, db_session, admin_user, auth_headers
    ):
        """Todo listo excepto la primera pregunta: paso 5 = probar el bot."""
        await _create_provider(db_session, is_active=True)
        await _create_source(db_session, review_status=ReviewStatus.aprobada)
        r = await client.get(
            "/api/v1/auth/onboarding-status",
            headers=auth_headers(admin_user),
        )
        assert r.json()["step"] == 5
        assert r.json()["sources_approved"] is True
        assert r.json()["messages_sent"] == 0

    async def test_step_done_when_all_configured(
        self, client, db_session, admin_user, auth_headers
    ):
        """Sistema operativo: step = 'done', no mostrar wizard."""
        await _create_provider(db_session, is_active=True)
        await _create_source(db_session, review_status=ReviewStatus.aprobada)
        await _create_message(db_session)
        r = await client.get(
            "/api/v1/auth/onboarding-status",
            headers=auth_headers(admin_user),
        )
        assert r.json()["step"] == "done"
        assert r.json()["messages_sent"] == 1

    async def test_unauthenticated_request_rejected(self, client):
        r = await client.get("/api/v1/auth/onboarding-status")
        assert r.status_code in (401, 403)


class TestOnboardingDismiss:
    async def test_admin_can_dismiss(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/auth/onboarding-dismiss",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True, "message": None}

    async def test_dismiss_persists_in_status(
        self, client, admin_user, auth_headers
    ):
        """Tras dismiss, /onboarding-status retorna dismissed: true (aunque
        step siga siendo 1, el frontend usa esto para no mostrar el wizard)."""
        await client.post(
            "/api/v1/auth/onboarding-dismiss",
            headers=auth_headers(admin_user),
        )
        r = await client.get(
            "/api/v1/auth/onboarding-status",
            headers=auth_headers(admin_user),
        )
        assert r.json()["dismissed"] is True

    async def test_dismiss_is_per_user(
        self, client, db_session, make_user, auth_headers
    ):
        """Dismiss de un admin no afecta a otros admins."""
        admin_a = await make_user(role=UserRole.admin, email="a@test.local")
        admin_b = await make_user(role=UserRole.admin, email="b@test.local")

        await client.post(
            "/api/v1/auth/onboarding-dismiss",
            headers=auth_headers(admin_a),
        )

        r = await client.get(
            "/api/v1/auth/onboarding-status",
            headers=auth_headers(admin_b),
        )
        assert r.json()["dismissed"] is False

    async def test_unauthenticated_dismiss_rejected(self, client):
        r = await client.post("/api/v1/auth/onboarding-dismiss")
        assert r.status_code in (401, 403)
