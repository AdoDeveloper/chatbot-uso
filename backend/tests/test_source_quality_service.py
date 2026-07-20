"""Tests unitarios directos para app/services/ingestion/source_quality.py.

Siembra datos reales (Source, ChatConversation, ChatMessage) via db_session
y llama quality_report/find_duplicate/classify_error/file_hash directamente,
verificando el resultado exacto.

test_sources_router_extra.py::TestQualityReport ya cubre el endpoint
/quality de forma superficial (solo checa que "total_chunks" esté en la
respuesta). Aquí se prueba el servicio en profundidad: hits_7d, last_used_at,
manejo de sources_json con distintas formas, y el bloque 76-122 completo.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.chat_conversation import ChatConversation
from app.models.chat_message import ChatMessage
from app.models.enums import (
    ConversationStatus,
    MessageRole,
    ReviewStatus,
    SourceStatus,
    SourceType,
)
from app.models.source import Source
from app.services.ingestion.source_quality import (
    classify_error,
    file_hash,
    find_duplicate,
    quality_report,
)


def _make_source(**kwargs) -> Source:
    defaults = dict(
        id=uuid.uuid4(),
        name="Reglamento academico",
        type=SourceType.pdf,
        status=SourceStatus.ready,
        review_status=ReviewStatus.aprobada,
        chunk_count=12,
    )
    defaults.update(kwargs)
    return Source(**defaults)


async def _make_conversation(db_session) -> ChatConversation:
    conv = ChatConversation(
        id=uuid.uuid4(),
        session_id=f"sess-{uuid.uuid4().hex[:8]}",
        status=ConversationStatus.active,
    )
    db_session.add(conv)
    await db_session.commit()
    await db_session.refresh(conv)
    return conv


async def _make_message(db_session, conv, *, sources_json, created_at=None) -> ChatMessage:
    msg = ChatMessage(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        role=MessageRole.assistant,
        content="Respuesta de prueba",
        sources_json=sources_json,
    )
    db_session.add(msg)
    await db_session.commit()
    await db_session.refresh(msg)
    if created_at is not None:
        # created_at tiene server_default=func.now(); para simular mensajes
        # antiguos hay que forzar el valor tras el insert inicial.
        from sqlalchemy import update
        await db_session.execute(
            update(ChatMessage).where(ChatMessage.id == msg.id).values(created_at=created_at)
        )
        await db_session.commit()
        await db_session.refresh(msg)
    return msg


# ---------------------------------------------------------------------------
# file_hash
# ---------------------------------------------------------------------------

class TestFileHash:
    def test_returns_sha256_hex(self):
        import hashlib
        content = b"contenido de prueba"
        assert file_hash(content) == hashlib.sha256(content).hexdigest()

    def test_different_content_different_hash(self):
        assert file_hash(b"a") != file_hash(b"b")

    def test_empty_content_matches_known_sha256(self):
        assert file_hash(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


# ---------------------------------------------------------------------------
# classify_error
# ---------------------------------------------------------------------------

class TestClassifyError:
    def test_none_message_returns_all_none(self):
        assert classify_error(None) == (None, None, None)

    def test_empty_message_returns_all_none(self):
        assert classify_error("") == (None, None, None)

    def test_password_pattern_matches(self):
        code, friendly, hint = classify_error("Error: PDF password protected")
        assert code == "PDF_ENCRYPTED"
        assert "protegido con contraseña" in friendly
        assert hint

    def test_encrypted_pattern_matches(self):
        code, friendly, hint = classify_error("file is encrypted")
        assert code == "PDF_ENCRYPTED"

    def test_openai_pattern_matches(self):
        code, _, _ = classify_error("Timeout calling openai API")
        assert code == "EMBEDDING_ERROR"

    def test_qdrant_pattern_matches(self):
        code, _, _ = classify_error("Connection refused to qdrant host")
        assert code == "VECTOR_STORE_ERROR"

    def test_memory_pattern_matches(self):
        code, _, _ = classify_error("out of memory while parsing")
        assert code == "OUT_OF_MEMORY"

    def test_token_pattern_matches(self):
        code, _, _ = classify_error("exceeded max token limit")
        assert code == "TOO_MANY_TOKENS"

    def test_encoding_pattern_matches(self):
        code, _, _ = classify_error("invalid encoding detected")
        assert code == "ENCODING_ERROR"

    def test_xlsx_pattern_matches(self):
        code, _, _ = classify_error("bad xlsx structure")
        assert code == "XLSX_PARSE_ERROR"

    def test_unrecognized_message_returns_raw_message_only(self):
        code, friendly, hint = classify_error("un error totalmente desconocido")
        assert code is None
        assert friendly == "un error totalmente desconocido"
        assert hint is None

    def test_case_insensitive_matching(self):
        code, _, _ = classify_error("PDF PASSWORD required")
        assert code == "PDF_ENCRYPTED"

    def test_first_matching_pattern_wins(self):
        # "encrypted" y "password" ambos aparecen; el orden de _ERROR_PATTERNS
        # define cuál gana (password está primero en la lista).
        code, friendly, _ = classify_error("password encrypted file")
        assert code == "PDF_ENCRYPTED"
        assert friendly == "El PDF está protegido con contraseña."


# ---------------------------------------------------------------------------
# find_duplicate
# ---------------------------------------------------------------------------

class TestFindDuplicate:
    async def test_finds_source_with_matching_hash(self, db_session):
        s = _make_source(content_hash="abc123")
        db_session.add(s)
        await db_session.commit()

        found = await find_duplicate(db_session, "abc123")
        assert found is not None
        assert found.id == s.id

    async def test_no_match_returns_none(self, db_session):
        found = await find_duplicate(db_session, "no-existe-este-hash")
        assert found is None

    async def test_excludes_given_id(self, db_session):
        s = _make_source(content_hash="dupe456")
        db_session.add(s)
        await db_session.commit()

        found = await find_duplicate(db_session, "dupe456", exclude_id=s.id)
        assert found is None

    async def test_ignores_soft_deleted_sources(self, db_session):
        s = _make_source(content_hash="deleted789", deleted_at=datetime.now(timezone.utc))
        db_session.add(s)
        await db_session.commit()

        found = await find_duplicate(db_session, "deleted789")
        assert found is None


# ---------------------------------------------------------------------------
# quality_report — foco principal: bloque 76-122
# ---------------------------------------------------------------------------

class TestQualityReport:
    async def test_source_not_found_returns_error_dict(self, db_session):
        result = await quality_report(db_session, uuid.uuid4())
        assert result == {"error": "Source no encontrada"}

    async def test_source_with_no_messages_has_zero_hits_and_no_last_used(self, db_session):
        s = _make_source(chunk_count=7)
        db_session.add(s)
        await db_session.commit()

        result = await quality_report(db_session, s.id)
        assert result["source_id"] == str(s.id)
        assert result["name"] == s.name
        assert result["total_chunks"] == 7
        assert result["last_used_at"] is None
        assert result["hits_7d"] == 0
        assert result["review_status"] == "aprobada"

    async def test_matches_by_source_id_sets_last_used_and_hits(self, db_session):
        s = _make_source()
        db_session.add(s)
        await db_session.commit()
        conv = await _make_conversation(db_session)
        await _make_message(
            db_session, conv, sources_json=[{"source_id": str(s.id), "source_name": "otro"}],
        )

        result = await quality_report(db_session, s.id)
        assert result["last_used_at"] is not None
        assert result["hits_7d"] == 1

    async def test_matches_by_source_name_when_source_id_absent(self, db_session):
        s = _make_source(name="Guia de matricula unica")
        db_session.add(s)
        await db_session.commit()
        conv = await _make_conversation(db_session)
        await _make_message(
            db_session, conv, sources_json=[{"source_name": "Guia de matricula unica"}],
        )

        result = await quality_report(db_session, s.id)
        assert result["last_used_at"] is not None
        assert result["hits_7d"] == 1

    async def test_non_matching_sources_json_does_not_count_as_hit(self, db_session):
        s = _make_source()
        db_session.add(s)
        await db_session.commit()
        conv = await _make_conversation(db_session)
        await _make_message(
            db_session, conv,
            sources_json=[{"source_id": str(uuid.uuid4()), "source_name": "otra fuente"}],
        )

        result = await quality_report(db_session, s.id)
        assert result["last_used_at"] is None
        assert result["hits_7d"] == 0

    async def test_malformed_sources_json_entries_are_skipped_not_raised(self, db_session):
        s = _make_source()
        db_session.add(s)
        await db_session.commit()
        conv = await _make_conversation(db_session)
        # Lista con elementos que no son dict — debe ignorarlos sin lanzar.
        await _make_message(db_session, conv, sources_json=["no-es-un-dict", 123, None])

        result = await quality_report(db_session, s.id)
        assert result["last_used_at"] is None
        assert result["hits_7d"] == 0

    async def test_hits_7d_excludes_messages_older_than_7_days(self, db_session):
        s = _make_source()
        db_session.add(s)
        await db_session.commit()
        conv = await _make_conversation(db_session)

        old_time = datetime.now(timezone.utc) - timedelta(days=10)
        await _make_message(
            db_session, conv,
            sources_json=[{"source_id": str(s.id)}],
            created_at=old_time,
        )

        result = await quality_report(db_session, s.id)
        # last_used_at sigue reportando el mensaje mas reciente que matchee
        # (sin límite de fecha), pero hits_7d sí filtra por ventana de 7 dias.
        assert result["last_used_at"] is not None
        assert result["hits_7d"] == 0

    async def test_multiple_hits_within_7_days_are_all_counted(self, db_session):
        s = _make_source()
        db_session.add(s)
        await db_session.commit()
        conv = await _make_conversation(db_session)

        for _ in range(3):
            await _make_message(db_session, conv, sources_json=[{"source_id": str(s.id)}])

        result = await quality_report(db_session, s.id)
        assert result["hits_7d"] == 3

    async def test_last_used_picks_most_recent_matching_message(self, db_session):
        s = _make_source()
        db_session.add(s)
        await db_session.commit()
        conv = await _make_conversation(db_session)

        older = datetime.now(timezone.utc) - timedelta(days=2)
        newer = datetime.now(timezone.utc) - timedelta(hours=1)
        await _make_message(
            db_session, conv, sources_json=[{"source_id": str(s.id)}], created_at=older,
        )
        msg2 = await _make_message(
            db_session, conv, sources_json=[{"source_id": str(s.id)}], created_at=newer,
        )

        result = await quality_report(db_session, s.id)
        assert result["last_used_at"] == msg2.created_at.isoformat()

    async def test_review_status_serialized_as_plain_string(self, db_session):
        s = _make_source(review_status=ReviewStatus.pendiente_revision)
        db_session.add(s)
        await db_session.commit()

        result = await quality_report(db_session, s.id)
        assert result["review_status"] == "pendiente_revision"

    async def test_zero_chunk_count_reported_as_zero_not_falsy_error(self, db_session):
        s = _make_source(chunk_count=0)
        db_session.add(s)
        await db_session.commit()

        result = await quality_report(db_session, s.id)
        assert result["total_chunks"] == 0
        assert "error" not in result
