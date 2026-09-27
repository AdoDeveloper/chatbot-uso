"""Tests unitarios de app.services.notifications.smtp."""
from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-please")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from unittest.mock import AsyncMock

import aiosmtplib
import pytest

from app.services.notifications.smtp import SMTPSettings, get_smtp_config, send_email


def _cfg(**overrides) -> SMTPSettings:
    base = dict(
        host="smtp.example.org",
        port=587,
        user="bot@example.org",
        password="s3cr3t",
        from_email="bot@example.org",
        tls=True,
    )
    base.update(overrides)
    return SMTPSettings(**base)


class _FakeSettings:
    """Doble simple de Settings: get_smtp_config solo lee estos atributos."""

    def __init__(self, *, host="", user="", password="", from_email="", tls=True, port=587):
        self.SMTP_HOST = host
        self.SMTP_USER = user
        self.SMTP_PASSWORD = password
        self.SMTP_FROM = from_email
        self.SMTP_TLS = tls
        self.SMTP_PORT = port


class TestGetSmtpConfig:
    async def test_returns_settings_when_fully_configured(self, monkeypatch):
        fake = _FakeSettings(
            host="smtp.real.org",
            user="user@real.org",
            password="pw",
            from_email="noreply@real.org",
            tls=True,
            port=465,
        )
        monkeypatch.setattr(
            "app.core.config.get_settings", lambda: fake
        )

        cfg = await get_smtp_config()

        assert cfg is not None
        assert cfg.host == "smtp.real.org"
        assert cfg.user == "user@real.org"
        assert cfg.password == "pw"
        assert cfg.from_email == "noreply@real.org"
        assert cfg.port == 465
        assert cfg.tls is True

    async def test_from_email_falls_back_to_user_when_smtp_from_unset(self, monkeypatch):
        fake = _FakeSettings(
            host="smtp.real.org", user="user@real.org", password="pw", from_email=""
        )
        monkeypatch.setattr(
            "app.core.config.get_settings", lambda: fake
        )

        cfg = await get_smtp_config()

        assert cfg is not None
        assert cfg.from_email == "user@real.org"

    @pytest.mark.parametrize(
        "missing_var",
        ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"],
    )
    async def test_returns_none_when_required_var_missing(self, monkeypatch, missing_var):
        values = {
            "SMTP_HOST": "smtp.real.org",
            "SMTP_USER": "user@real.org",
            "SMTP_PASSWORD": "pw",
        }
        values[missing_var] = ""
        fake = _FakeSettings(
            host=values["SMTP_HOST"], user=values["SMTP_USER"], password=values["SMTP_PASSWORD"]
        )
        monkeypatch.setattr(
            "app.core.config.get_settings", lambda: fake
        )

        cfg = await get_smtp_config()

        assert cfg is None


class TestSendEmailNotConfigured:
    async def test_returns_false_without_raising_when_no_config(self, monkeypatch):
        async def _no_config(db=None):
            return None

        monkeypatch.setattr(
            "app.services.notifications.smtp.get_smtp_config", _no_config
        )

        ok = await send_email(to="dest@example.org", subject="s", body_html="<p>x</p>")

        assert ok is False


class TestSendEmailMessageConstruction:
    async def test_builds_multipart_message_with_headers_and_sends(self, monkeypatch):
        captured = {}

        async def _fake_send(msg, **kwargs):
            captured["msg"] = msg
            captured["kwargs"] = kwargs

        monkeypatch.setattr(aiosmtplib, "send", AsyncMock(side_effect=_fake_send))

        ok = await send_email(
            to="dest@example.org",
            subject="Asunto de prueba",
            body_html="<p>hola</p>",
            body_text="hola",
            _config=_cfg(),
        )

        assert ok is True
        msg = captured["msg"]
        assert msg["Subject"] == "Asunto de prueba"
        assert msg["From"] == "bot@example.org"
        assert msg["To"] == "dest@example.org"
        assert msg["Message-ID"] is not None
        assert "@example.org" in msg["Message-ID"]
        assert msg["Date"] is not None
        assert msg.is_multipart()

        parts = msg.get_payload()
        content_types = {p.get_content_type() for p in parts}
        assert "text/plain" in content_types
        assert "text/html" in content_types

        kwargs = captured["kwargs"]
        assert kwargs["hostname"] == "smtp.example.org"
        assert kwargs["port"] == 587
        assert kwargs["username"] == "bot@example.org"
        assert kwargs["password"] == "s3cr3t"
        assert kwargs["start_tls"] is True

    async def test_omits_plain_text_part_when_body_text_not_given(self, monkeypatch):
        captured = {}

        async def _fake_send(msg, **kwargs):
            captured["msg"] = msg

        monkeypatch.setattr(aiosmtplib, "send", AsyncMock(side_effect=_fake_send))

        ok = await send_email(
            to="dest@example.org",
            subject="s",
            body_html="<p>solo html</p>",
            _config=_cfg(),
        )

        assert ok is True
        parts = captured["msg"].get_payload()
        content_types = [p.get_content_type() for p in parts]
        assert content_types == ["text/html"]

    async def test_message_id_domain_falls_back_to_localhost_without_at_sign(self, monkeypatch):
        captured = {}

        async def _fake_send(msg, **kwargs):
            captured["msg"] = msg

        monkeypatch.setattr(aiosmtplib, "send", AsyncMock(side_effect=_fake_send))

        ok = await send_email(
            to="dest@example.org",
            subject="s",
            body_html="<p>x</p>",
            _config=_cfg(from_email="bot-sin-arroba"),
        )

        assert ok is True
        assert "@localhost" in captured["msg"]["Message-ID"]


class TestSendEmailErrorHandling:
    """Fuerza cada rama de excepción de aiosmtplib.send (líneas 96-127)."""

    async def test_authentication_error_returns_false(self, monkeypatch):
        monkeypatch.setattr(
            aiosmtplib,
            "send",
            AsyncMock(side_effect=aiosmtplib.SMTPAuthenticationError(535, "bad credentials")),
        )

        ok = await send_email(
            to="dest@example.org", subject="s", body_html="<p>x</p>", _config=_cfg()
        )

        assert ok is False

    async def test_connect_error_returns_false(self, monkeypatch):
        monkeypatch.setattr(
            aiosmtplib,
            "send",
            AsyncMock(side_effect=aiosmtplib.SMTPConnectError("connection refused")),
        )

        ok = await send_email(
            to="dest@example.org", subject="s", body_html="<p>x</p>", _config=_cfg()
        )

        assert ok is False

    async def test_timeout_error_returns_false(self, monkeypatch):
        monkeypatch.setattr(
            aiosmtplib,
            "send",
            AsyncMock(side_effect=aiosmtplib.SMTPTimeoutError("timed out")),
        )

        ok = await send_email(
            to="dest@example.org", subject="s", body_html="<p>x</p>", _config=_cfg()
        )

        assert ok is False

    async def test_tls_not_supported_returns_false(self, monkeypatch):
        monkeypatch.setattr(
            aiosmtplib,
            "send",
            AsyncMock(side_effect=aiosmtplib.SMTPNotSupported("STARTTLS not supported")),
        )

        ok = await send_email(
            to="dest@example.org", subject="s", body_html="<p>x</p>", _config=_cfg(tls=True)
        )

        assert ok is False

    async def test_generic_smtp_exception_returns_false(self, monkeypatch):
        monkeypatch.setattr(
            aiosmtplib,
            "send",
            AsyncMock(side_effect=aiosmtplib.SMTPException("protocolo roto")),
        )

        ok = await send_email(
            to="dest@example.org", subject="s", body_html="<p>x</p>", _config=_cfg()
        )

        assert ok is False

    async def test_recipients_refused_is_handled_as_smtp_exception(self, monkeypatch):
        refused = aiosmtplib.SMTPRecipientsRefused(
            [aiosmtplib.SMTPRecipientRefused("dest@example.org", 550, "mailbox unavailable")]
        )
        monkeypatch.setattr(aiosmtplib, "send", AsyncMock(side_effect=refused))

        ok = await send_email(
            to="dest@example.org", subject="s", body_html="<p>x</p>", _config=_cfg()
        )

        assert ok is False

    async def test_os_error_network_unreachable_returns_false(self, monkeypatch):
        monkeypatch.setattr(
            aiosmtplib,
            "send",
            AsyncMock(side_effect=OSError("Network is unreachable")),
        )

        ok = await send_email(
            to="dest@example.org", subject="s", body_html="<p>x</p>", _config=_cfg()
        )

        assert ok is False

    async def test_unexpected_exception_is_caught_and_returns_false(self, monkeypatch):
        monkeypatch.setattr(
            aiosmtplib,
            "send",
            AsyncMock(side_effect=RuntimeError("algo totalmente inesperado")),
        )

        ok = await send_email(
            to="dest@example.org", subject="s", body_html="<p>x</p>", _config=_cfg()
        )

        assert ok is False


async def test_port_465_uses_direct_ssl(monkeypatch):
    from app.services.notifications import smtp

    captured = {}

    async def _fake_send(msg, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(smtp.aiosmtplib, "send", _fake_send)
    cfg = smtp.SMTPSettings(host="smtp.x", port=465, user="u", password="p", from_email="a@x.org", tls=True)

    assert await smtp.send_email(to="b@x.org", subject="s", body_html="<p>h</p>", _config=cfg) is True
    assert captured["use_tls"] is True and captured["start_tls"] is False

