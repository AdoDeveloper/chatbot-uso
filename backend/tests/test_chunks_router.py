"""Tests de caracterización para app/api/v1/chunks/router.py.

Estos tests fijan el comportamiento ACTUAL de los endpoints de chunks
(no cubiertos por ningún otro archivo de test) antes de mover su lógica
a una capa de servicio, para poder confirmar que la migración no cambia
nada observable. Qdrant y el modelo de embeddings se sustituyen por
monkeypatch — no hay Qdrant real en el entorno de test.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.enums import ReviewStatus, SourceStatus, SourceType
from app.models.source import Source


FAKE_EMBEDDING = {"dense": [0.1, 0.2, 0.3], "sparse_indices": [1, 2], "sparse_values": [0.5, 0.5]}


@pytest.fixture
async def seeded_source(db_session):
    s = Source(
        id=uuid.uuid4(),
        name="Reglamento académico",
        type=SourceType.pdf,
        status=SourceStatus.ready,
        review_status=ReviewStatus.pendiente_revision,
        chunk_count=1,
    )
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)
    return s


def _fake_chunk(source: Source, point_id: str, *, text="Texto original del chunk", is_discarded=False, warnings=None):
    return {
        "id": point_id,
        "text": text,
        "source_id": str(source.id),
        "source_name": source.name,
        "chunk_index": 0,
        "section": "Capítulo 1",
        "parent_id": None,
        "parent_text": None,
        "environment": "production",
        "warnings": warnings or [],
        "is_discarded": is_discarded,
    }


@pytest.fixture
def patch_vector_store(monkeypatch):
    """Sustituye las funciones de app.services.ingestion.vector_store usadas
    por el router de chunks. Devuelve un dict mutable {point_id: chunk_dict}
    que los tests pueblan directamente, más un stub de cliente Qdrant con
    upsert/set_payload espiables."""
    from app.services.ingestion import vector_store as vs

    store: dict[str, dict] = {}
    upsert_calls: list[dict] = []
    set_payload_calls: list[dict] = []

    async def _get_chunk(point_id: str):
        return store.get(point_id)

    async def _list_all_chunks(source_id: str):
        return [c for c in store.values() if c.get("source_id") == source_id]

    class _FakeClient:
        async def upsert(self, *, collection_name, points, wait=True):
            for p in points:
                upsert_calls.append({"id": p.id, "payload": p.payload})
                if p.id in store:
                    store[p.id] = {**store[p.id], **p.payload, "id": p.id}

        async def set_payload(self, *, collection_name, payload, points):
            for pid in points:
                set_payload_calls.append({"id": pid, "payload": payload})
                if pid in store:
                    store[pid].update(payload)

    fake_client = _FakeClient()

    monkeypatch.setattr(vs, "get_chunk", _get_chunk)
    monkeypatch.setattr(vs, "list_all_chunks", _list_all_chunks)
    monkeypatch.setattr(vs, "_get_client", lambda: fake_client)

    async def _embed_texts_async(texts, prefix=""):
        return [FAKE_EMBEDDING for _ in texts]

    import app.services.knowledge.chunk_editing as chunk_editing
    monkeypatch.setattr(chunk_editing, "embed_texts_async", _embed_texts_async)

    async def _invalidate_by_source(source_id):
        return None
    monkeypatch.setattr(chunk_editing.cache_svc, "invalidate_by_source", _invalidate_by_source)

    return {"store": store, "upsert_calls": upsert_calls, "set_payload_calls": set_payload_calls}


class TestGetChunk:
    async def test_get_chunk_not_found_returns_404(self, client, admin_user, auth_headers, patch_vector_store):
        r = await client.get("/api/v1/chunks/does-not-exist", headers=auth_headers(admin_user))
        assert r.status_code == 404

    async def test_get_chunk_returns_data(self, client, admin_user, auth_headers, patch_vector_store, seeded_source):
        point_id = str(uuid.uuid4())
        patch_vector_store["store"][point_id] = _fake_chunk(seeded_source, point_id)

        r = await client.get(f"/api/v1/chunks/{point_id}", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == point_id
        assert body["text"] == "Texto original del chunk"
        assert body["was_edited"] is False


class TestListSourceChunks:
    async def test_list_chunks_paginates_and_counts_warnings(
        self, client, admin_user, auth_headers, patch_vector_store, seeded_source
    ):
        for i in range(3):
            pid = str(uuid.uuid4())
            patch_vector_store["store"][pid] = _fake_chunk(
                seeded_source, pid, text=f"chunk {i}", warnings=["short"] if i == 0 else []
            )

        r = await client.get(
            f"/api/v1/chunks/source/{seeded_source.id}?page=1&page_size=2",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 3
        assert len(body["chunks"]) == 2
        assert body["warning_counts"] == {"short": 1}

    async def test_list_chunks_filters_by_warning(
        self, client, admin_user, auth_headers, patch_vector_store, seeded_source
    ):
        pid_a, pid_b = str(uuid.uuid4()), str(uuid.uuid4())
        patch_vector_store["store"][pid_a] = _fake_chunk(seeded_source, pid_a, warnings=["pii"])
        patch_vector_store["store"][pid_b] = _fake_chunk(seeded_source, pid_b, warnings=[])

        r = await client.get(
            f"/api/v1/chunks/source/{seeded_source.id}?warning=pii",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["chunks"][0]["id"] == pid_a


class TestEditChunk:
    async def test_edit_chunk_not_found_returns_404(self, client, admin_user, auth_headers, patch_vector_store):
        r = await client.patch(
            "/api/v1/chunks/does-not-exist/content",
            json={"text": "nuevo texto"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 404

    async def test_edit_chunk_noop_when_text_unchanged(
        self, client, admin_user, auth_headers, patch_vector_store, seeded_source
    ):
        point_id = str(uuid.uuid4())
        patch_vector_store["store"][point_id] = _fake_chunk(seeded_source, point_id, text="mismo texto")

        r = await client.patch(
            f"/api/v1/chunks/{point_id}/content",
            json={"text": "mismo texto"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["was_edited"] is False
        # No debe haber tocado Qdrant si el texto es idéntico.
        assert len(patch_vector_store["upsert_calls"]) == 0

    async def test_edit_chunk_updates_text_and_writes_audit(
        self, client, admin_user, auth_headers, patch_vector_store, seeded_source, db_session
    ):
        point_id = str(uuid.uuid4())
        patch_vector_store["store"][point_id] = _fake_chunk(seeded_source, point_id, text="texto viejo")

        r = await client.patch(
            f"/api/v1/chunks/{point_id}/content",
            json={"text": "texto nuevo", "reason": "corrección ortográfica"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["text"] == "texto nuevo"
        assert body["was_edited"] is True
        assert len(patch_vector_store["upsert_calls"]) == 1

        from sqlalchemy import select
        from app.models.chunk_edit import ChunkEdit
        res = await db_session.execute(select(ChunkEdit).where(ChunkEdit.chunk_point_id == point_id))
        edit = res.scalar_one()
        assert edit.previous_content == "texto viejo"
        assert edit.new_content == "texto nuevo"
        assert edit.reason == "corrección ortográfica"
        assert edit.edited_by_id == admin_user.id

    async def test_edit_chunk_source_missing_returns_404(
        self, client, admin_user, auth_headers, patch_vector_store
    ):
        point_id = str(uuid.uuid4())
        ghost_source_id = str(uuid.uuid4())
        patch_vector_store["store"][point_id] = {
            "id": point_id,
            "text": "texto",
            "source_id": ghost_source_id,
            "source_name": "fuente eliminada",
            "chunk_index": 0,
            "warnings": [],
            "is_discarded": False,
        }
        r = await client.patch(
            f"/api/v1/chunks/{point_id}/content",
            json={"text": "otro texto"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 404


class TestDiscardRestore:
    async def test_discard_then_restore_chunk(
        self, client, admin_user, auth_headers, patch_vector_store, seeded_source
    ):
        point_id = str(uuid.uuid4())
        patch_vector_store["store"][point_id] = _fake_chunk(seeded_source, point_id)

        r1 = await client.post(f"/api/v1/chunks/{point_id}/discard", headers=auth_headers(admin_user))
        assert r1.status_code == 200
        assert r1.json()["is_discarded"] is True

        r2 = await client.post(f"/api/v1/chunks/{point_id}/restore", headers=auth_headers(admin_user))
        assert r2.status_code == 200
        assert r2.json()["is_discarded"] is False

        assert len(patch_vector_store["set_payload_calls"]) == 2

    async def test_discard_not_found_returns_404(self, client, admin_user, auth_headers, patch_vector_store):
        r = await client.post("/api/v1/chunks/does-not-exist/discard", headers=auth_headers(admin_user))
        assert r.status_code == 404


class TestChunkHistory:
    async def test_history_empty_when_no_edits(self, client, admin_user, auth_headers, patch_vector_store):
        r = await client.get("/api/v1/chunks/some-point-id/history", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json() == []

    async def test_history_lists_edits_newest_first(
        self, client, admin_user, auth_headers, patch_vector_store, seeded_source, db_session
    ):
        """Dos ediciones consecutivas pueden caer en el mismo instante bajo
        SQLite (resolución de timestamp insuficiente para distinguir orden),
        así que forzamos edited_at distintos tras la segunda edición en vez
        de depender del reloj real — lo que importa es que el endpoint
        efectivamente ordena DESC por edited_at, no la precisión del reloj."""
        import datetime as dt
        from sqlalchemy import select
        from app.models.chunk_edit import ChunkEdit

        point_id = str(uuid.uuid4())
        patch_vector_store["store"][point_id] = _fake_chunk(seeded_source, point_id, text="v1")

        await client.patch(
            f"/api/v1/chunks/{point_id}/content", json={"text": "v2"}, headers=auth_headers(admin_user)
        )
        await client.patch(
            f"/api/v1/chunks/{point_id}/content", json={"text": "v3"}, headers=auth_headers(admin_user)
        )

        res = await db_session.execute(
            select(ChunkEdit).where(ChunkEdit.chunk_point_id == point_id).order_by(ChunkEdit.edited_at)
        )
        edits = res.scalars().all()
        assert len(edits) == 2
        edits[0].edited_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=10)
        await db_session.commit()

        r = await client.get(f"/api/v1/chunks/{point_id}/history", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 2
        assert body[0]["new_content"] == "v3"
        assert body[1]["new_content"] == "v2"
