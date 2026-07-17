"""Tests de caracterización para app/api/v1/guardrails/router.py.

test_guardrails.py cubre el motor de guardrails (validate_input) como
función pura, pero ningún endpoint HTTP de este router — en particular
el CRUD de patrones custom (_load_custom_list/_save_custom_list) no
tenía ninguna prueba. Se fijan aquí antes de mover ese CRUD a servicio.
"""
from __future__ import annotations

import pytest


class TestPatternsCrud:
    async def test_list_patterns_includes_builtins(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/guardrails/patterns", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert len(body) > 0
        assert all(p["source"] == "builtin" for p in body)

    async def test_create_pattern_appears_in_list(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/guardrails/patterns",
            json={"regex": r"\bignora\b", "label": "Ignora instrucciones", "category": "Custom", "example": "ignora todo"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 201
        created = r.json()
        assert created["source"] == "custom"
        assert created["label"] == "Ignora instrucciones"

        r2 = await client.get("/api/v1/guardrails/patterns", headers=auth_headers(admin_user))
        labels = [p["label"] for p in r2.json()]
        assert "Ignora instrucciones" in labels

    async def test_create_pattern_invalid_regex_rejected(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/guardrails/patterns",
            json={"regex": "(unclosed", "label": "Malo", "category": "Custom", "example": ""},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 400

    async def test_update_pattern(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/guardrails/patterns",
            json={"regex": r"\btest\b", "label": "Original", "category": "Custom", "example": ""},
            headers=auth_headers(admin_user),
        )
        pattern_id = r.json()["id"]

        r2 = await client.patch(
            f"/api/v1/guardrails/patterns/{pattern_id}",
            json={"label": "Actualizado"},
            headers=auth_headers(admin_user),
        )
        assert r2.status_code == 200
        assert r2.json()["label"] == "Actualizado"

    async def test_update_pattern_invalid_regex_rejected(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/guardrails/patterns",
            json={"regex": r"\btest\b", "label": "Original", "category": "Custom", "example": ""},
            headers=auth_headers(admin_user),
        )
        pattern_id = r.json()["id"]

        r2 = await client.patch(
            f"/api/v1/guardrails/patterns/{pattern_id}",
            json={"regex": "(unclosed"},
            headers=auth_headers(admin_user),
        )
        assert r2.status_code == 400

    async def test_update_pattern_not_found(self, client, admin_user, auth_headers):
        r = await client.patch(
            "/api/v1/guardrails/patterns/does-not-exist",
            json={"label": "X"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 404

    async def test_delete_pattern(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/guardrails/patterns",
            json={"regex": r"\bborrar\b", "label": "A borrar", "category": "Custom", "example": ""},
            headers=auth_headers(admin_user),
        )
        pattern_id = r.json()["id"]

        r2 = await client.delete(f"/api/v1/guardrails/patterns/{pattern_id}", headers=auth_headers(admin_user))
        assert r2.status_code == 200

        r3 = await client.get("/api/v1/guardrails/patterns", headers=auth_headers(admin_user))
        assert pattern_id not in [p["id"] for p in r3.json()]

    async def test_delete_pattern_not_found(self, client, admin_user, auth_headers):
        r = await client.delete("/api/v1/guardrails/patterns/does-not-exist", headers=auth_headers(admin_user))
        assert r.status_code == 404


class TestPatternImpact:
    async def test_pattern_impact_not_found(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/guardrails/patterns/does-not-exist/impact", headers=auth_headers(admin_user)
        )
        assert r.status_code == 404

    @pytest.mark.skip(
        reason="pattern_impact usa func.json_unquote(), especifico de MySQL; "
        "el entorno de test corre sobre SQLite (ver conftest.py DATABASE_URL) "
        "y no soporta esa funcion. No cubre el 200 real contra MySQL/produccion."
    )
    async def test_pattern_impact_zero_blocks(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/guardrails/patterns",
            json={"regex": r"\bimpacto\b", "label": "Impacto test", "category": "Custom", "example": ""},
            headers=auth_headers(admin_user),
        )
        pattern_id = r.json()["id"]

        r2 = await client.get(
            f"/api/v1/guardrails/patterns/{pattern_id}/impact?days=7", headers=auth_headers(admin_user)
        )
        assert r2.status_code == 200
        body = r2.json()
        assert body["blocks"] == 0
        assert body["days"] == 7


class TestConfigAndTest:
    async def test_get_config(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/guardrails/config", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert "enabled" in body
        assert "injection_patterns_count" in body

    async def test_guardrails_test_endpoint(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/guardrails/test",
            json={"text": "Hola, ¿cuál es el horario de la biblioteca?"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["passed"] is True


class TestInjectionLog:
    async def test_injection_log_empty(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/guardrails/injection-log", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json() == []
