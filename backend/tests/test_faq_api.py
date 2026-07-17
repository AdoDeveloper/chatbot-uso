"""Integration tests for the FAQ API.

Exercises the full HTTP → router → service → DB pipeline against an in-memory
SQLite database. Each test gets a fresh DB and a fresh authenticated user.
"""
from __future__ import annotations

import pytest

from app.models.enums import UserRole


@pytest.fixture
async def admin_user(make_user):
    return await make_user(role=UserRole.admin)


@pytest.fixture
async def viewer_user(make_user):
    return await make_user(role=UserRole.viewer)


class TestFAQList:
    async def test_empty_list_returns_array(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/faq", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json() == []

    async def test_unauthenticated_request_rejected(self, client):
        r = await client.get("/api/v1/faq")
        assert r.status_code in (401, 403)


class TestFAQCreate:
    async def test_admin_can_create_faq(self, client, admin_user, auth_headers):
        payload = {
            "question": "¿Cuándo abren las inscripciones?",
            "answer": "Las inscripciones abren en febrero de cada año.",
            "tags": ["inscripciones", "fechas"],
            "is_active": True,
        }
        r = await client.post("/api/v1/faq", json=payload, headers=auth_headers(admin_user))
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["question"] == payload["question"]
        assert body["tags"] == payload["tags"]
        assert body["is_active"] is True
        assert "id" in body
        assert "created_at" in body

    async def test_viewer_cannot_create_faq(self, client, viewer_user, auth_headers):
        # Editors+ are the only roles allowed to mutate the FAQ catalog.
        r = await client.post(
            "/api/v1/faq",
            json={"question": "¿Pregunta?", "answer": "Respuesta de ejemplo."},
            headers=auth_headers(viewer_user),
        )
        assert r.status_code == 403

    async def test_too_short_question_rejected(self, client, admin_user, auth_headers):
        # Schema enforces min_length=5
        r = await client.post(
            "/api/v1/faq",
            json={"question": "hi", "answer": "respuesta válida"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422

    async def test_too_short_answer_rejected(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/faq",
            json={"question": "¿pregunta válida?", "answer": "ok"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422

    async def test_create_then_list_round_trips(self, client, admin_user, auth_headers):
        await client.post(
            "/api/v1/faq",
            json={"question": "¿Pregunta uno?", "answer": "Respuesta uno extendida."},
            headers=auth_headers(admin_user),
        )
        await client.post(
            "/api/v1/faq",
            json={"question": "¿Pregunta dos?", "answer": "Respuesta dos extendida."},
            headers=auth_headers(admin_user),
        )
        r = await client.get("/api/v1/faq", headers=auth_headers(admin_user))
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 2
        questions = {item["question"] for item in items}
        assert questions == {"¿Pregunta uno?", "¿Pregunta dos?"}


class TestFAQUpdate:
    async def test_patch_changes_fields(self, client, admin_user, auth_headers):
        create = await client.post(
            "/api/v1/faq",
            json={"question": "¿Original?", "answer": "Texto original aquí."},
            headers=auth_headers(admin_user),
        )
        faq_id = create.json()["id"]

        r = await client.patch(
            f"/api/v1/faq/{faq_id}",
            json={"answer": "Texto actualizado del FAQ.", "is_active": False},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["answer"] == "Texto actualizado del FAQ."
        assert body["is_active"] is False
        assert body["question"] == "¿Original?"  # untouched

    async def test_patch_unknown_id_returns_404(self, client, admin_user, auth_headers):
        r = await client.patch(
            "/api/v1/faq/00000000-0000-0000-0000-000000000000",
            json={"answer": "lo que sea de longitud suficiente"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 404


class TestFAQDelete:
    async def test_delete_removes_entry(self, client, admin_user, auth_headers):
        create = await client.post(
            "/api/v1/faq",
            json={"question": "¿Borrable?", "answer": "Esta entrada se va a borrar."},
            headers=auth_headers(admin_user),
        )
        faq_id = create.json()["id"]

        r = await client.delete(f"/api/v1/faq/{faq_id}", headers=auth_headers(admin_user))
        assert r.status_code == 204

        # Confirm the item is gone from the list.
        r2 = await client.get("/api/v1/faq", headers=auth_headers(admin_user))
        assert all(item["id"] != faq_id for item in r2.json())

    async def test_viewer_cannot_delete(self, client, viewer_user, admin_user, auth_headers):
        # Create as admin, then try to delete as viewer.
        create = await client.post(
            "/api/v1/faq",
            json={"question": "¿Solo lectura?", "answer": "Texto que sólo se puede leer."},
            headers=auth_headers(admin_user),
        )
        faq_id = create.json()["id"]

        r = await client.delete(f"/api/v1/faq/{faq_id}", headers=auth_headers(viewer_user))
        assert r.status_code == 403
