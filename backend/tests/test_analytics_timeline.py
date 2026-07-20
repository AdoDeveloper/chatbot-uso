"""Tests del endpoint /analytics/timeline ("Actividad reciente").

No existía ningún test para este endpoint — un bug real llegó a producción
sin que nada lo detectara: los `href` generados apuntaban a rutas que no
existen en el frontend (`/dashboard/history/{id}`, `/dashboard/sources/{id}`)
en vez de las rutas reales (`/dashboard/conversaciones?id={id}`,
`/dashboard/conocimiento/documentos/{id}/chunks`). Estos tests fijan el
contrato exacto de esas URLs para que un cambio de rutas en el frontend sin
actualizar el backend (o viceversa) rompa el test en vez de solo el enlace
del usuario en producción.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.chat_conversation import ChatConversation
from app.models.enums import ConversationStatus, SourceStatus, SourceType, UserRole
from app.models.source import Source


@pytest.fixture
async def admin_user(make_user):
    return await make_user(role=UserRole.admin)


class TestAnalyticsTimeline:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/analytics/timeline")
        assert r.status_code == 401

    async def test_empty_returns_no_events(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/analytics/timeline", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["events"] == []

    async def test_ready_source_links_to_real_chunks_route(self, client, admin_user, auth_headers, db_session):
        src = Source(
            id=uuid.uuid4(), name="Manual de Aranceles", type=SourceType.pdf,
            status=SourceStatus.ready, chunk_count=5,
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(src)
        await db_session.commit()

        r = await client.get("/api/v1/analytics/timeline", headers=auth_headers(admin_user))
        assert r.status_code == 200
        events = r.json()["events"]
        source_events = [e for e in events if e["type"] == "source_ingested"]
        assert len(source_events) == 1
        assert source_events[0]["href"] == f"/dashboard/conocimiento/documentos/{src.id}/chunks"

    async def test_escalated_conversation_links_to_real_conversations_route(
        self, client, admin_user, auth_headers, db_session
    ):
        conv = ChatConversation(
            id=uuid.uuid4(), session_id="sess-abc123",
            status=ConversationStatus.escalated,
            last_message_at=datetime.now(timezone.utc),
        )
        db_session.add(conv)
        await db_session.commit()

        r = await client.get("/api/v1/analytics/timeline", headers=auth_headers(admin_user))
        assert r.status_code == 200
        events = r.json()["events"]
        escalation_events = [e for e in events if e["type"] == "escalation"]
        assert len(escalation_events) == 1
        assert escalation_events[0]["href"] == f"/dashboard/conversaciones?id={conv.id}"

    async def test_events_outside_window_are_excluded(self, client, admin_user, auth_headers, db_session):
        old = datetime.now(timezone.utc) - timedelta(days=60)
        src = Source(
            id=uuid.uuid4(), name="Fuente vieja", type=SourceType.pdf,
            status=SourceStatus.ready, chunk_count=1, updated_at=old,
        )
        db_session.add(src)
        await db_session.commit()

        r = await client.get("/api/v1/analytics/timeline?days=30", headers=auth_headers(admin_user))
        assert r.status_code == 200
        ids = [e["id"] for e in r.json()["events"]]
        assert f"source_ready:{src.id}" not in ids
