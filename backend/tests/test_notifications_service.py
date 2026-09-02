"""Tests unitarios para app/services/notifications/service.py y templates.py.

Ejercita send_notification, _email_recipients, _html_body, _text_body,
_daily_digest_body, y los helpers de templates.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.enums import NotificationChannel, NotificationEvent, UserRole
from app.models.notification_rule import NotificationRule
from app.services.notifications import service, templates

pytestmark = pytest.mark.asyncio


class TestEmailRecipients:
    async def test_returns_active_admin_emails(self, db_session, make_user):
        await make_user(email="admin1@test.com", role=UserRole.admin)
        await make_user(email="admin2@test.com", role=UserRole.admin)
        await make_user(role=UserRole.viewer)

        emails = await service._email_recipients(db_session)
        assert "admin1@test.com" in emails
        assert "admin2@test.com" in emails
        assert len(emails) == 2

    async def test_returns_empty_when_no_active_admins(self, db_session):
        emails = await service._email_recipients(db_session)
        assert emails == []

    async def test_target_overrides_admin_list(self, db_session, make_user):
        await make_user(email="admin1@test.com", role=UserRole.admin)
        emails = await service._email_recipients(db_session, "coordinacion@uso.edu.sv")
        assert emails == ["coordinacion@uso.edu.sv"]
        assert "admin1@test.com" not in emails

    async def test_target_supports_comma_separated_list(self, db_session):
        emails = await service._email_recipients(db_session, "a@uso.edu.sv, b@uso.edu.sv")
        assert emails == ["a@uso.edu.sv", "b@uso.edu.sv"]

    async def test_blank_target_falls_back_to_admin_list(self, db_session, make_user):
        await make_user(email="admin1@test.com", role=UserRole.admin)
        emails = await service._email_recipients(db_session, "   ")
        assert emails == ["admin1@test.com"]


class TestSendNotification:
    async def test_skips_when_no_rules(self, db_session):
        with patch("app.services.notifications.service.smtp.send_email", AsyncMock()) as send:
            await service.send_notification(
                db_session,
                event=NotificationEvent.doc_ready,
                payload={"document": "test.pdf"},
            )
        send.assert_not_awaited()

    async def test_sends_email_when_rule_exists(self, db_session, make_user):
        await make_user(email="admin@test.com", role=UserRole.admin)
        db_session.add(NotificationRule(
            event=NotificationEvent.doc_ready,
            channel=NotificationChannel.email,
            enabled=True,
        ))
        await db_session.commit()

        with patch("app.services.notifications.service.smtp.send_email", AsyncMock(return_value=True)):
            await service.send_notification(
                db_session,
                event=NotificationEvent.doc_ready,
                payload={"document": "test.pdf", "source_name": "test"},
            )

    async def test_uses_rule_target_instead_of_all_admins(self, db_session, make_user):
        """Integración: send_notification debe respetar email_rule.target en
        vez de reenviar siempre a todos los admins activos."""
        await make_user(email="admin@test.com", role=UserRole.admin)
        db_session.add(NotificationRule(
            event=NotificationEvent.doc_ready,
            channel=NotificationChannel.email,
            enabled=True,
            target="coordinacion@uso.edu.sv",
        ))
        await db_session.commit()

        with patch("app.services.notifications.service.smtp.send_email", AsyncMock(return_value=True)) as send:
            await service.send_notification(
                db_session,
                event=NotificationEvent.doc_ready,
                payload={"document": "test.pdf", "source_name": "test"},
            )

        sent_to = [call.kwargs.get("to") for call in send.await_args_list]
        assert sent_to == ["coordinacion@uso.edu.sv"]
        assert "admin@test.com" not in sent_to

    async def test_creates_email_log_on_failure(self, db_session, make_user):
        from app.models.notification_log import NotificationLog
        await make_user(email="admin@test.com", role=UserRole.admin)
        db_session.add(NotificationRule(
            event=NotificationEvent.doc_ready,
            channel=NotificationChannel.email,
            enabled=True,
        ))
        await db_session.commit()

        with patch("app.services.notifications.service.smtp.send_email", AsyncMock(return_value=False)):
            await service.send_notification(
                db_session,
                event=NotificationEvent.doc_ready,
                payload={"document": "test.pdf"},
            )

        logs = (await db_session.execute(
            __import__("sqlalchemy").select(NotificationLog)
        )).scalars().all()
        assert any(log.status == "failed" for log in logs)

    async def test_creates_in_app_log_per_recipient(self, db_session, make_user):
        # doc_ready es visible para admin y editor (audience.py); el fan-out crea una fila individual por cada destinatario activo.
        admin = await make_user(email="admin@test.com", role=UserRole.admin)
        editor = await make_user(email="editor@test.com", role=UserRole.editor)
        await make_user(email="viewer@test.com", role=UserRole.viewer)  # no ve doc_ready
        db_session.add(NotificationRule(
            event=NotificationEvent.doc_ready,
            channel=NotificationChannel.in_app,
            enabled=True,
        ))
        await db_session.commit()
        from app.models.notification_log import NotificationLog

        await service.send_notification(
            db_session,
            event=NotificationEvent.doc_ready,
            payload={"document": "test.pdf"},
        )

        logs = (await db_session.execute(
            __import__("sqlalchemy").select(NotificationLog)
        )).scalars().all()
        inapp_logs = [log for log in logs if log.target == "in_app"]
        recipients = {log.user_id for log in inapp_logs}
        assert recipients == {admin.id, editor.id}

    async def test_email_and_in_app_rows_share_trigger_id(self, db_session, make_user):
        """Todas las filas de un mismo send_notification() (correo + cada
        destinatario in_app) deben compartir trigger_id - es lo que permite
        al historial (GET /notifications) agruparlas como un único disparo
        en vez de mostrarlas como entregas sueltas sin relación entre sí."""
        from app.models.notification_log import NotificationLog

        await make_user(email="admin@test.com", role=UserRole.admin)
        await make_user(email="editor@test.com", role=UserRole.editor)
        db_session.add(NotificationRule(
            event=NotificationEvent.doc_ready, channel=NotificationChannel.email, enabled=True,
        ))
        db_session.add(NotificationRule(
            event=NotificationEvent.doc_ready, channel=NotificationChannel.in_app, enabled=True,
        ))
        await db_session.commit()

        with patch("app.services.notifications.service.smtp.send_email", AsyncMock(return_value=True)):
            await service.send_notification(
                db_session, event=NotificationEvent.doc_ready, payload={"document": "test.pdf"},
            )

        logs = (await db_session.execute(
            __import__("sqlalchemy").select(NotificationLog)
        )).scalars().all()
        assert len(logs) == 3  # 1 email + 2 in_app (admin, editor)
        trigger_ids = {log.trigger_id for log in logs}
        assert len(trigger_ids) == 1

    async def test_two_separate_calls_get_different_trigger_ids(self, db_session, make_user):
        """Dos disparos distintos (dos llamadas a send_notification) no
        deben compartir trigger_id, ni siquiera para el mismo evento -
        cada uno es un envío independiente en el historial."""
        from app.models.notification_log import NotificationLog

        await make_user(email="admin@test.com", role=UserRole.admin)
        db_session.add(NotificationRule(
            event=NotificationEvent.doc_ready, channel=NotificationChannel.email, enabled=True,
        ))
        await db_session.commit()

        with patch("app.services.notifications.service.smtp.send_email", AsyncMock(return_value=True)):
            await service.send_notification(
                db_session, event=NotificationEvent.doc_ready, payload={"document": "a.pdf"},
            )
            await service.send_notification(
                db_session, event=NotificationEvent.doc_ready, payload={"document": "b.pdf"},
            )

        logs = (await db_session.execute(
            __import__("sqlalchemy").select(NotificationLog)
        )).scalars().all()
        assert len(logs) == 2
        assert logs[0].trigger_id != logs[1].trigger_id


class TestMeta:
    def test_known_event_returns_subject(self):
        meta = service._meta(NotificationEvent.doc_ready)
        assert meta["subject"] == "Documento procesado correctamente"

    def test_unknown_event_returns_fallback(self):
        fake_event = MagicMock()
        fake_event.value = "fake_event"
        meta = service._meta(fake_event)
        assert "Notificación" in meta["subject"]

    def test_subject_for_event(self):
        assert service._subject_for_event(NotificationEvent.escalation) == "Conversación escalada"


class TestLabeledRows:
    def test_known_keys_translated(self):
        result = service._labeled_rows({"document": "test.pdf", "error": "fail"})
        assert "Documento" in result
        assert "Detalle del error" in result

    def test_unknown_keys_capitalized(self):
        result = service._labeled_rows({"unknown_key": "val"})
        assert "Unknown key" in result

    def test_real_payload_keys_all_translated(self):
        """Las claves que realmente arma cada send_notification(...) en
        producción deben tener entrada en _FIELD_LABELS - si un payload real
        usa una clave sin traducir, el correo muestra el nombre técnico crudo
        (ej. "source_id") en vez de una etiqueta legible."""
        real_payload_keys = {
            "service", "error", "since",  # monitoring/alerts.py service_down
            "providers",  # monitoring/alerts.py notify_provider_down
            "current_requests_last_hour", "limit_per_hour", "percent",  # rate_limit_threshold
            "source_id", "source_name", "chunks",  # ingestion/service.py doc_ready
            "conversation_id", "question", "reason",  # escalation/service.py
        }
        for key in real_payload_keys:
            assert key in service._FIELD_LABELS, f"{key!r} sin traducción en _FIELD_LABELS"


class TestHtmlBody:
    def test_returns_valid_html_for_standard_event(self):
        html = service._html_body(NotificationEvent.doc_ready, {"document": "test.pdf"})
        assert "test.pdf" in html
        assert "<!DOCTYPE html>" in html
        assert "Documento procesado correctamente" in html

    def test_returns_digest_body_for_unanswered_digest(self):
        html = service._html_body(
            NotificationEvent.unanswered_digest,
            {"total_open": 5, "new_open": 2, "resolved_today": 1},
        )
        assert "5" in html
        assert "<!DOCTYPE html>" in html

    def test_escalation_email_includes_contact_email(self):
        html = service._html_body(NotificationEvent.escalation, {
            "reason": "Solicitud de contacto del usuario",
            "question": "¿Cuándo abren inscripciones?",
            "contact_email": "usuario@example.com",
            "conversation_id": "abc-123",
        })
        assert "usuario@example.com" in html
        assert "Contacto por correo electrónico" in html

    def test_escalation_email_includes_contact_whatsapp(self):
        html = service._html_body(NotificationEvent.escalation, {
            "reason": "Solicitud de contacto del usuario",
            "question": "¿Cuándo abren inscripciones?",
            "contact_whatsapp": "+50377777777",
            "conversation_id": "abc-123",
        })
        assert "+50377777777" in html
        assert "Contacto por WhatsApp" in html


class TestDailyDigestBody:
    def test_zero_open_returns_no_action_message(self):
        m = service._meta(NotificationEvent.unanswered_digest)
        html = service._daily_digest_body(m, {"total_open": 0})
        assert "No se requiere" in html

    def test_with_open_questions_renders_stats(self):
        m = service._meta(NotificationEvent.unanswered_digest)
        html = service._daily_digest_body(
            m, {"total_open": 3, "new_open": 1, "resolved_today": 2, "escalated_today": 0},
        )
        assert "3" in html
        assert "1" in html

    def test_with_topics_renders_topic_list(self):
        m = service._meta(NotificationEvent.unanswered_digest)
        html = service._daily_digest_body(
            m, {"total_open": 3, "top_topics": [("admisiones", 5), ("pagos", 3)]},
        )
        assert "admisiones" in html
        assert "pagos" in html

    def test_with_recent_questions_renders_quotes(self):
        m = service._meta(NotificationEvent.unanswered_digest)
        html = service._daily_digest_body(
            m, {"total_open": 3, "recent_questions": ["¿Cuándo abren?", "¿Costo?"]},
        )
        assert "¿Cuándo abren?" in html
        assert "¿Costo?" in html


class TestHumanizeSince:
    """Convierte el ISO 8601 UTC crudo del payload a una fecha legible en
    hora local y a un "hace cuánto" - antes el correo mostraba el timestamp
    tal cual llegaba de la BD (ej. "2026-08-31T22:05:42.634191+00:00")."""

    def test_returns_readable_date_not_raw_iso(self):
        readable, _ago = service._humanize_since("2026-08-31T22:05:42.634191+00:00")
        assert "2026-08-31T22:05:42" not in readable
        assert "2026" in readable
        assert "ago" in readable.lower()  # "31 de ago de 2026"

    def test_recent_timestamp_reports_minutes(self):
        from datetime import datetime, timedelta, timezone
        five_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        _readable, ago = service._humanize_since(five_min_ago)
        assert "minuto" in ago

    def test_old_timestamp_reports_days(self):
        from datetime import datetime, timedelta, timezone
        three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        _readable, ago = service._humanize_since(three_days_ago)
        assert "día" in ago

    def test_malformed_input_falls_back_to_raw_string(self):
        readable, ago = service._humanize_since("no es una fecha")
        assert readable == "no es una fecha"
        assert ago == ""


class TestProviderDownBody:
    """El correo de provider_down separa los proveedores en chips
    individuales (no una sola línea con comas) y muestra la fecha en
    formato legible - antes usaba el detail_table genérico que mostraba
    "Groq Produccion, Ollama gpt-oss 20B" como texto corrido y el ISO
    crudo sin conversión de zona horaria ni "hace cuánto"."""

    def test_providers_rendered_as_separate_tables(self):
        m = service._meta(NotificationEvent.provider_down)
        html = service._provider_down_body(m, {
            "providers": "Groq Produccion, Ollama gpt-oss 20B",
            "error": "El servicio de IA no está disponible.",
            "since": "2026-08-31T22:05:42.634191+00:00",
        })
        assert "Groq Produccion" in html
        assert "Ollama gpt-oss 20B" in html
        # Una tabla detail_table por proveedor, no una línea con comas ni un chip compartido.
        assert html.count("<table") >= 4  # render_email wrapper + N tablas de proveedor + fecha

    def test_single_provider_uses_singular_heading(self):
        m = service._meta(NotificationEvent.provider_down)
        html = service._provider_down_body(m, {
            "providers": "Groq Produccion", "error": "boom", "since": "2026-08-31T22:05:42+00:00",
        })
        assert "Proveedor intentado" in html
        assert "Proveedores intentados" not in html

    def test_multiple_providers_uses_plural_heading(self):
        m = service._meta(NotificationEvent.provider_down)
        html = service._provider_down_body(m, {
            "providers": "Groq, Mistral", "error": "boom", "since": "2026-08-31T22:05:42+00:00",
        })
        assert "Proveedores intentados" in html

    def test_since_is_humanized_not_raw_iso(self):
        m = service._meta(NotificationEvent.provider_down)
        html = service._provider_down_body(m, {
            "providers": "Groq",
            "error": "boom",
            "since": "2026-08-31T22:05:42.634191+00:00",
        })
        assert "2026-08-31T22:05:42.634191" not in html
        assert "Tiempo transcurrido" in html

    def test_error_detail_rendered_when_present(self):
        m = service._meta(NotificationEvent.provider_down)
        html = service._provider_down_body(m, {
            "providers": "Groq",
            "error": "El servicio de IA no está disponible en este momento.",
            "since": "2026-08-31T22:05:42.634191+00:00",
        })
        assert "no está disponible en este momento" in html

    def test_placeholder_error_is_not_rendered_as_a_block(self):
        m = service._meta(NotificationEvent.provider_down)
        html = service._provider_down_body(m, {
            "providers": "Groq", "error": "(sin detalle)", "since": "2026-08-31T22:05:42+00:00",
        })
        assert "(sin detalle)" not in html

    def test_dispatches_through_html_body(self):
        """_html_body debe enrutar a _provider_down_body para este evento,
        no caer en el detail_table genérico."""
        html = service._html_body(NotificationEvent.provider_down, {
            "providers": "Groq, Mistral", "error": "boom", "since": "2026-08-31T22:05:42+00:00",
        })
        assert "Groq" in html
        assert "Mistral" in html
        assert "Tiempo transcurrido" in html


class TestChipList:
    def test_renders_each_item(self):
        html = templates.chip_list(["Groq Produccion", "Mistral Free"])
        assert "Groq Produccion" in html
        assert "Mistral Free" in html

    def test_empty_list_returns_empty_string(self):
        assert templates.chip_list([]) == ""


class TestTextBody:
    def test_renders_with_intro_and_action(self):
        text = service._text_body(NotificationEvent.doc_ready, {"document": "test.pdf"})
        assert "test.pdf" in text
        assert "Documento procesado correctamente" in text

    def test_renders_without_action(self):
        text = service._text_body(
            NotificationEvent.unanswered_digest,
            {"total_open": 0},
        )
        assert "Universidad de Sonsonate" in text


class TestTemplates:
    def test_render_email_contains_brand(self):
        html = templates.render_email(title="Test", content="<p>Content</p>")
        assert templates.BRAND_NAME in html
        assert "<!DOCTYPE html>" in html

    def test_heading_returns_html(self):
        h = templates.heading("Título")
        assert "Título" in h

    def test_paragraph_returns_html(self):
        p = templates.paragraph("Texto de prueba")
        assert "Texto de prueba" in p

    def test_detail_table(self):
        html = templates.detail_table({"Clave": "Valor"}, heading_text="Detalle")
        assert "Detalle" in html
        assert "Clave" in html
        assert "Valor" in html

    def test_button_returns_html(self):
        html = templates.button("Click", "https://example.com")
        assert "Click" in html
        assert "example.com" in html

    def test_stat_grid(self):
        html = templates.stat_grid([(10, "Total"), (5, "Nuevos")])
        assert "10" in html
        assert "Total" in html
        assert "5" in html
        assert "Nuevos" in html

    def test_topic_list(self):
        html = templates.topic_list([("admisiones", 10), ("pagos", 5)])
        assert "admisiones" in html
        assert "pagos" in html

    def test_topic_list_empty(self):
        assert templates.topic_list([]) == ""

    def test_quote_list(self):
        html = templates.quote_list(["¿Pregunta 1?", "¿Pregunta 2?"])
        assert "¿Pregunta 1?" in html
        assert "¿Pregunta 2?" in html

    def test_quote_list_empty(self):
        assert templates.quote_list([]) == ""

    def test_muted_note(self):
        html = templates.muted_note("Nota al pie")
        assert "Nota al pie" in html
