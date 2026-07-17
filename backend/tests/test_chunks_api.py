from __future__ import annotations

import uuid



class TestListSources:
    async def test_list_requires_auth(self, client):
        r = await client.get("/api/v1/sources")
        assert r.status_code == 401

    async def test_list_returns_sources(self, client, admin_user, auth_headers, db_session):
        from app.models.enums import ReviewStatus, SourceStatus, SourceType
        from app.models.source import Source
        s = Source(
            id=uuid.uuid4(),
            name="Test doc",
            type=SourceType.pdf,
            status=SourceStatus.ready,
            review_status=ReviewStatus.pendiente_revision,
            chunk_count=5,
        )
        db_session.add(s)
        await db_session.commit()
        r = await client.get(
            "/api/v1/sources",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1
        names = [s["name"] for s in data]
        assert "Test doc" in names


class TestSourceCRUD:
    async def test_get_source_by_id(self, client, admin_user, auth_headers, db_session):
        from app.models.enums import ReviewStatus, SourceStatus, SourceType
        from app.models.source import Source
        s = Source(
            id=uuid.uuid4(),
            name="Doc único",
            type=SourceType.pdf,
            status=SourceStatus.ready,
            review_status=ReviewStatus.aprobada,
        )
        db_session.add(s)
        await db_session.commit()
        sid = str(s.id)
        r = await client.get(
            f"/api/v1/sources/{sid}",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["name"] == "Doc único"

    async def test_delete_source_requires_perm(self, client, admin_user, auth_headers, db_session):
        from app.models.enums import ReviewStatus, SourceStatus, SourceType
        from app.models.source import Source
        s = Source(
            id=uuid.uuid4(),
            name="A borrar",
            type=SourceType.pdf,
            status=SourceStatus.ready,
            review_status=ReviewStatus.pendiente_revision,
        )
        db_session.add(s)
        await db_session.commit()
        sid = str(s.id)
        r = await client.delete(
            f"/api/v1/sources/{sid}",
            headers=auth_headers(admin_user),
        )
        assert r.status_code in (200, 204)


class TestSourceTags:
    async def test_bulk_tag_requires_auth(self, client):
        r = await client.post(
            "/api/v1/sources/bulk/tag",
            json={"source_ids": [str(uuid.uuid4())], "tags": ["tag1"]},
        )
        assert r.status_code == 401

    async def test_bulk_tag_adds_and_removes(self, client, admin_user, auth_headers, db_session):
        from app.models.enums import ReviewStatus, SourceStatus, SourceType
        from app.models.source import Source
        s = Source(
            id=uuid.uuid4(),
            name="Doc etiquetado",
            type=SourceType.pdf,
            status=SourceStatus.ready,
            review_status=ReviewStatus.aprobada,
        )
        db_session.add(s)
        await db_session.commit()
        sid = str(s.id)

        r = await client.post(
            "/api/v1/sources/bulk/tag",
            json={"source_ids": [sid], "tags": ["beca", "admisión"], "action": "add"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200

        r = await client.post(
            "/api/v1/sources/bulk/tag",
            json={"source_ids": [sid], "tags": ["beca"], "action": "remove"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200

        r = await client.get(f"/api/v1/sources/{sid}", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["tags"] == ["admisión"]
