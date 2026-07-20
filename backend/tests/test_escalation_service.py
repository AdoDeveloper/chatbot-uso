"""Tests unitarios para app/services/escalation/service.py y engine.py.

test_escalation_router.py y test_escalation_router_extra.py cubren estos
módulos solo indirectamente vía HTTP (y en el caso de dispatch_escalation,
mockeándolo por completo). test_escalation_triggers.py cubre el motor de
reglas (engine.py) solo para los triggers no_answer y negative_feedback, vía
detect_escalation. Este archivo cubre directamente:

- engine.py: user_request, keyword_detected, confidence_below, loop_detected,
  trigger no soportado, y schema_for_trigger para cada tipo.
- service.py: dispatch_escalation con admins reales en BD (envío de email
  mockeado), notificación a múltiples admins, admin sin email, fallo de
  envío, fallo en mark_escalated (conversation_id inválido / conversación
  inexistente), y _build_html (incluye contact_info y payload sin él).
"""
from __future__ import annotations

import uuid

import pytest

from app.models.enums import EscalationTrigger, NotificationChannel, UserRole
from app.models.notification_log import NotificationLog
from app.models.user import User
from app.services.escalation import engine, service


# ---------------------------------------------------------------------------
# engine.py — evaluadores no cubiertos por test_escalation_triggers.py
# ---------------------------------------------------------------------------

class TestUserRequestTrigger:
    def test_matches_default_keywords(self):
        matches, detail = engine.evaluate_rule(
            trigger_type=EscalationTrigger.user_request,
            trigger_config={},
            context={"user_message": "quiero hablar con un humano por favor"},
        )
        assert matches is True
        assert "humano" in detail

    def test_matches_custom_keywords_list(self):
        matches, detail = engine.evaluate_rule(
            trigger_type=EscalationTrigger.user_request,
            trigger_config={"keywords": ["urgente"]},
            context={"user_message": "esto es urgente"},
        )
        assert matches is True
        assert "urgente" in detail

    def test_matches_custom_keywords_csv_string(self):
        matches, detail = engine.evaluate_rule(
            trigger_type=EscalationTrigger.user_request,
            trigger_config={"keywords": "urgente, queja"},
            context={"user_message": "tengo una queja"},
        )
        assert matches is True
        assert "queja" in detail

    def test_no_match_without_keywords_in_message(self):
        matches, detail = engine.evaluate_rule(
            trigger_type=EscalationTrigger.user_request,
            trigger_config={},
            context={"user_message": "cual es el horario de atencion"},
        )
        assert matches is False
        assert "Ninguna keyword" in detail

    def test_no_match_without_user_message(self):
        matches, detail = engine.evaluate_rule(
            trigger_type=EscalationTrigger.user_request,
            trigger_config={},
            context={},
        )
        assert matches is False
        assert "Sin mensaje de usuario" in detail


class TestKeywordDetectedTrigger:
    def test_no_match_without_keywords_configured(self):
        matches, detail = engine.evaluate_rule(
            trigger_type=EscalationTrigger.keyword_detected,
            trigger_config={},
            context={"user_message": "algo"},
        )
        assert matches is False
        assert "no tiene keywords" in detail

    def test_no_match_without_user_message(self):
        matches, detail = engine.evaluate_rule(
            trigger_type=EscalationTrigger.keyword_detected,
            trigger_config={"keywords": ["denuncia"]},
            context={},
        )
        assert matches is False
        assert "Sin mensaje de usuario" in detail

    def test_matches_configured_keyword(self):
        matches, detail = engine.evaluate_rule(
            trigger_type=EscalationTrigger.keyword_detected,
            trigger_config={"keywords": ["denuncia", "demanda"]},
            context={"user_message": "quiero poner una denuncia"},
        )
        assert matches is True
        assert "denuncia" in detail

    def test_matches_keywords_as_csv_string(self):
        matches, detail = engine.evaluate_rule(
            trigger_type=EscalationTrigger.keyword_detected,
            trigger_config={"keywords": "denuncia,demanda"},
            context={"user_message": "voy a poner una demanda"},
        )
        assert matches is True

    def test_no_match_keyword_absent(self):
        matches, detail = engine.evaluate_rule(
            trigger_type=EscalationTrigger.keyword_detected,
            trigger_config={"keywords": ["denuncia"]},
            context={"user_message": "hola buenos dias"},
        )
        assert matches is False
        assert "Ninguna keyword crítica" in detail


class TestConfidenceBelowTrigger:
    def test_not_enough_scores(self):
        matches, detail = engine.evaluate_rule(
            trigger_type=EscalationTrigger.confidence_below,
            trigger_config={"consecutive": 3},
            context={"rag_scores": [0.01, 0.01]},
        )
        assert matches is False
        assert "Solo hay 2 respuestas" in detail

    def test_matches_when_all_below_threshold(self):
        matches, detail = engine.evaluate_rule(
            trigger_type=EscalationTrigger.confidence_below,
            trigger_config={"threshold": 0.02, "consecutive": 2},
            context={"rag_scores": [0.05, 0.01, 0.015]},
        )
        assert matches is True
        assert "< 0.02" in detail

    def test_no_match_when_one_score_above_threshold(self):
        matches, detail = engine.evaluate_rule(
            trigger_type=EscalationTrigger.confidence_below,
            trigger_config={"threshold": 0.02, "consecutive": 2},
            context={"rag_scores": [0.05, 0.03]},
        )
        assert matches is False
        assert "Confianza reciente OK" in detail

    def test_default_config_values(self):
        matches, _ = engine.evaluate_rule(
            trigger_type=EscalationTrigger.confidence_below,
            trigger_config={},
            context={"rag_scores": [0.001, 0.001]},
        )
        assert matches is True


class TestLoopDetectedTrigger:
    def test_not_enough_answers(self):
        matches, detail = engine.evaluate_rule(
            trigger_type=EscalationTrigger.loop_detected,
            trigger_config={"repetitions": 2},
            context={"bot_answers": ["a", "a"]},
        )
        assert matches is False
        assert "Solo hay 2 respuestas" in detail

    def test_empty_last_answer(self):
        matches, detail = engine.evaluate_rule(
            trigger_type=EscalationTrigger.loop_detected,
            trigger_config={"repetitions": 1},
            context={"bot_answers": ["a", ""]},
        )
        assert matches is False
        assert "vacía" in detail

    def test_matches_repeated_answers(self):
        matches, detail = engine.evaluate_rule(
            trigger_type=EscalationTrigger.loop_detected,
            trigger_config={"repetitions": 2},
            context={"bot_answers": ["No entiendo", "No entiendo", "No entiendo"]},
        )
        assert matches is True
        assert "repetida 3 veces" in detail

    def test_matches_case_insensitive_and_whitespace(self):
        matches, detail = engine.evaluate_rule(
            trigger_type=EscalationTrigger.loop_detected,
            trigger_config={"repetitions": 1},
            context={"bot_answers": ["Hola ", " HOLA"]},
        )
        assert matches is True

    def test_no_match_when_answers_differ(self):
        matches, detail = engine.evaluate_rule(
            trigger_type=EscalationTrigger.loop_detected,
            trigger_config={"repetitions": 2},
            context={"bot_answers": ["a", "b", "c"]},
        )
        assert matches is False
        assert "repetida solo 1 vez" in detail

    def test_stops_counting_at_first_different_answer(self):
        # 3 repeticiones de "x" al final, pero se pide un umbral de 5:
        # no debe alcanzarlo aunque haya respuestas iguales más atrás.
        matches, detail = engine.evaluate_rule(
            trigger_type=EscalationTrigger.loop_detected,
            trigger_config={"repetitions": 4},
            context={"bot_answers": ["x", "y", "x", "x", "x"]},
        )
        assert matches is False
        assert "repetida solo 3 vez" in detail


class TestUnsupportedTrigger:
    def test_returns_false_for_unknown_trigger(self):
        matches, detail = engine.evaluate_rule(
            trigger_type="not_a_real_trigger",
            trigger_config={},
            context={},
        )
        assert matches is False
        assert "no soportado" in detail


class TestSchemaForTrigger:
    @pytest.mark.parametrize("trigger", list(EscalationTrigger))
    def test_known_triggers_have_non_empty_schema(self, trigger):
        schema = engine.schema_for_trigger(trigger)
        assert isinstance(schema, dict)
        assert len(schema) > 0

    def test_unknown_trigger_returns_empty_schema(self):
        assert engine.schema_for_trigger("bogus") == {}

    def test_no_answer_schema_fields(self):
        schema = engine.schema_for_trigger(EscalationTrigger.no_answer)
        assert schema["wait_seconds"]["default"] == 120

    def test_confidence_below_schema_has_two_fields(self):
        schema = engine.schema_for_trigger(EscalationTrigger.confidence_below)
        assert "threshold" in schema
        assert "consecutive" in schema


# ---------------------------------------------------------------------------
# service.py — dispatch_escalation y _build_html
# ---------------------------------------------------------------------------

@pytest.fixture
async def two_admins(db_session):
    a1 = User(
        id=uuid.uuid4(), email="admin1@example.com", hashed_password="x",
        full_name="Admin Uno", role=UserRole.admin, is_active=True,
    )
    a2 = User(
        id=uuid.uuid4(), email="admin2@example.com", hashed_password="x",
        full_name="Admin Dos", role=UserRole.admin, is_active=True,
    )
    db_session.add_all([a1, a2])
    await db_session.commit()
    return [a1, a2]


@pytest.fixture
async def inactive_admin(db_session):
    a = User(
        id=uuid.uuid4(), email="inactivo@example.com", hashed_password="x",
        full_name="Admin Inactivo", role=UserRole.admin, is_active=False,
    )
    db_session.add(a)
    await db_session.commit()
    return a


@pytest.fixture
async def non_admin_user(db_session):
    from app.core.security import hash_password
    u = User(
        id=uuid.uuid4(), email="editor@example.com", hashed_password=hash_password("Test1234!"),
        full_name="Editor", role=UserRole.editor, is_active=True,
    )
    db_session.add(u)
    await db_session.commit()
    return u


class TestDispatchEscalationNotifiesAdmins:
    async def test_sends_email_to_each_active_admin_and_logs(self, db_session, two_admins, monkeypatch):
        sent_to = []

        async def _fake_send_email(*, to, subject, body_html, **kwargs):
            sent_to.append(to)
            return True

        monkeypatch.setattr(service.smtp, "send_email", _fake_send_email)

        await service.dispatch_escalation(
            db_session,
            conversation_id="",
            question="Como recupero mi contraseña?",
            reason="Solicitud de agente humano",
        )

        assert set(sent_to) == {"admin1@example.com", "admin2@example.com"}

        result = await db_session.execute(
            NotificationLog.__table__.select()
        )
        logs = result.fetchall()
        email_logs = [row for row in logs if row.channel == NotificationChannel.email.value]
        in_app_logs = [row for row in logs if row.channel == NotificationChannel.in_app.value]

        assert len(email_logs) == 2
        assert all(row.status == "sent" for row in email_logs)
        assert len(in_app_logs) == 1
        assert in_app_logs[0].status == "sent"
        assert in_app_logs[0].target == "in_app"

    async def test_skips_admins_without_email_but_no_error(self, db_session, monkeypatch):
        # User.email es NOT NULL en BD; "" es igual de falsy para el chequeo
        # `if not admin.email` del servicio, sin violar la restricción.
        admin_no_email = User(
            id=uuid.uuid4(), email="", hashed_password="x",
            full_name="Sin correo", role=UserRole.admin, is_active=True,
        )
        db_session.add(admin_no_email)
        await db_session.commit()

        calls = []

        async def _fake_send_email(*, to, subject, body_html, **kwargs):
            calls.append(to)
            return True

        monkeypatch.setattr(service.smtp, "send_email", _fake_send_email)

        await service.dispatch_escalation(
            db_session, conversation_id="", question="q", reason="r",
        )
        assert calls == []

    async def test_ignores_inactive_and_non_admin_users(
        self, db_session, inactive_admin, non_admin_user, monkeypatch
    ):
        calls = []

        async def _fake_send_email(*, to, subject, body_html, **kwargs):
            calls.append(to)
            return True

        monkeypatch.setattr(service.smtp, "send_email", _fake_send_email)

        await service.dispatch_escalation(
            db_session, conversation_id="", question="q", reason="r",
        )
        assert calls == []

    async def test_logs_failed_status_when_send_email_returns_false(self, db_session, two_admins, monkeypatch):
        async def _fake_send_email(*, to, subject, body_html, **kwargs):
            return False

        monkeypatch.setattr(service.smtp, "send_email", _fake_send_email)

        await service.dispatch_escalation(
            db_session, conversation_id="", question="q", reason="r",
        )

        result = await db_session.execute(NotificationLog.__table__.select())
        email_logs = [row for row in result.fetchall() if row.channel == NotificationChannel.email.value]
        assert len(email_logs) == 2
        assert all(row.status == "failed" for row in email_logs)
        assert all("No se pudo enviar" in (row.error_message or "") for row in email_logs)

    async def test_logs_failed_status_when_send_email_raises(self, db_session, two_admins, monkeypatch):
        async def _raising_send_email(*, to, subject, body_html, **kwargs):
            raise RuntimeError("smtp connection refused")

        monkeypatch.setattr(service.smtp, "send_email", _raising_send_email)

        await service.dispatch_escalation(
            db_session, conversation_id="", question="q", reason="r",
        )

        result = await db_session.execute(NotificationLog.__table__.select())
        email_logs = [row for row in result.fetchall() if row.channel == NotificationChannel.email.value]
        assert len(email_logs) == 2
        assert all(row.status == "failed" for row in email_logs)
        assert all("smtp connection refused" in (row.error_message or "") for row in email_logs)

    async def test_no_admins_still_logs_in_app_entry(self, db_session, monkeypatch):
        calls = []

        async def _fake_send_email(*, to, subject, body_html, **kwargs):
            calls.append(to)
            return True

        monkeypatch.setattr(service.smtp, "send_email", _fake_send_email)

        await service.dispatch_escalation(
            db_session, conversation_id="", question="q", reason="r",
        )
        assert calls == []

        result = await db_session.execute(NotificationLog.__table__.select())
        rows = result.fetchall()
        assert len(rows) == 1
        assert rows[0].channel == NotificationChannel.in_app.value


class TestDispatchEscalationLifecycle:
    async def test_marks_conversation_escalated_when_id_valid(self, db_session, two_admins, monkeypatch):
        from app.models.chat_conversation import ChatConversation
        from app.models.enums import ConversationStatus

        conv = ChatConversation(id=uuid.uuid4(), session_id=str(uuid.uuid4()))
        db_session.add(conv)
        await db_session.commit()

        async def _fake_send_email(*, to, subject, body_html, **kwargs):
            return True
        monkeypatch.setattr(service.smtp, "send_email", _fake_send_email)

        await service.dispatch_escalation(
            db_session,
            conversation_id=str(conv.id),
            question="pregunta",
            reason="motivo",
            trigger_type="user_request",
        )

        await db_session.refresh(conv)
        assert conv.status == ConversationStatus.escalated
        assert conv.escalated_at is not None

    async def test_invalid_conversation_id_does_not_raise(self, db_session, two_admins, monkeypatch):
        """conversation_id que no es un UUID válido: mark_escalated falla con
        ValueError, se captura y loguea, y el dispatch de notificaciones sigue
        adelante con normalidad (no debe propagar la excepción)."""
        async def _fake_send_email(*, to, subject, body_html, **kwargs):
            return True
        monkeypatch.setattr(service.smtp, "send_email", _fake_send_email)

        await service.dispatch_escalation(
            db_session,
            conversation_id="not-a-uuid",
            question="pregunta",
            reason="motivo",
        )

        result = await db_session.execute(NotificationLog.__table__.select())
        email_logs = [row for row in result.fetchall() if row.channel == NotificationChannel.email.value]
        assert len(email_logs) == 2

    async def test_nonexistent_conversation_id_does_not_raise(self, db_session, two_admins, monkeypatch):
        """UUID válido pero de una conversación inexistente: mark_escalated
        levanta HTTPException 404 desde lifecycle._load; dispatch_escalation
        la traga (except (ValueError, Exception)) y continúa notificando."""
        async def _fake_send_email(*, to, subject, body_html, **kwargs):
            return True
        monkeypatch.setattr(service.smtp, "send_email", _fake_send_email)

        await service.dispatch_escalation(
            db_session,
            conversation_id=str(uuid.uuid4()),
            question="pregunta",
            reason="motivo",
        )

        result = await db_session.execute(NotificationLog.__table__.select())
        email_logs = [row for row in result.fetchall() if row.channel == NotificationChannel.email.value]
        assert len(email_logs) == 2


class TestBuildHtml:
    def test_includes_reason_question_and_conversation_id(self):
        html = service._build_html({
            "conversation_id": "abc-123",
            "question": "Cómo cancelo mi matrícula?",
            "reason": "Palabra clave crítica",
        })
        assert "abc-123" in html
        assert "Cómo cancelo mi matrícula?" in html
        assert "Palabra clave crítica" in html
        assert "Conversación escalada" in html

    def test_includes_contact_info_email(self):
        html = service._build_html({
            "conversation_id": "abc-123",
            "question": "q",
            "reason": "r",
            "contact_info": {"type": "email", "value": "user@example.com"},
        })
        assert "Contacto por correo electrónico" in html
        assert "user@example.com" in html

    def test_includes_contact_info_whatsapp(self):
        html = service._build_html({
            "conversation_id": "abc-123",
            "question": "q",
            "reason": "r",
            "contact_info": {"type": "whatsapp", "value": "+50370000000"},
        })
        assert "Contacto por WhatsApp" in html
        assert "+50370000000" in html

    def test_no_contact_info_key_omitted_from_table(self):
        html = service._build_html({
            "conversation_id": "abc-123",
            "question": "q",
            "reason": "r",
        })
        assert "Contacto por" not in html

    def test_escapes_html_in_question(self):
        html = service._build_html({
            "conversation_id": "abc-123",
            "question": "<script>alert(1)</script>",
            "reason": "r",
        })
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
