"""
Tests for extended jobs-view endpoints (Шаги 3-8):
  - PATCH /jobs-view/{id}/template
  - POST  /jobs-view/{id}/copy
  - POST  /jobs-view/{id}/regenerate
  - POST  /jobs-view/{id}/extract-candidates
  - GET   /jobs-view/{id}/candidates
  - POST  /jobs-view/candidates/{cid}/review
  - DELETE /jobs-view/{id}
  - storage_jobs helpers: update_job_template, mark_candidates_extracted,
    increment_regenerate, set_parent_job, list_job_candidates, review_candidate
"""
import os
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


@pytest.fixture
def auth_client(client):
    """Client with admin logged in (для endpoints с auth)."""
    from app import storage_users
    storage_users.create_user("testadmin", "testpass1", "admin")
    r = client.post("/web/login", json={"username": "testadmin", "password": "testpass1"})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture
def job_with_meta(auth_client):
    """Создаёт job + глоссарий + template и привязывает."""
    from app import storage, storage_templates, storage_jobs
    from app import glossaries as gl_mod

    # Создаём job
    jid = "mp-test-001"
    storage.create_job(
        job_id=jid,
        model_used="minimax-m3",
        is_video=False,
        file_name="meeting.mp3",
        file_path="/tmp/meeting.mp3",
    )
    # Создаём глоссарий
    gid = gl_mod.create_glossary(owner_id=1, name="Test Glossary", is_shared=False)
    gl_mod.add_entry(
        glossary_id=gid,
        term="API",
        definition="Application Programming Interface",
        abbreviation="API",
        pronunciation="а-пи-ай",
        comment="общий термин",
        needs_review=False,
    )
    storage_jobs.attach_glossary_to_job(jid, gid)

    # Создаём template
    import uuid as _u
    tmpl_id = storage_templates.create_template(
        template_id=f"tpl-{_u.uuid4().hex[:8]}",
        name="Custom",
        source_filename="custom.docx",
        source_format="docx",
        sections=[{"title": "Section 1", "fields": ["date", "participants"]}],
        prompt="Generate protocol.",
    )["id"]

    return {
        "job_id": jid,
        "glossary_id": gid,
        "template_id": tmpl_id,
    }


# ---------------------------------------------------------------------------
# Storage layer
# ---------------------------------------------------------------------------
class TestStorageHelpers:
    def test_init_extended_creates_new_columns(self):
        """Проверяет, что init_extended добавил новые колонки."""
        from app import storage_jobs
        schema = storage_jobs.get_schema()
        jobs_cols = {c["name"] for c in schema["jobs"]}
        for col in (
            "description", "template_id", "template_name",
            "candidates_extracted", "regenerate_count", "parent_job_id",
        ):
            assert col in jobs_cols, f"missing column: {col}"

    def test_update_job_template(self):
        from app import storage, storage_jobs
        storage.create_job("mp-t1", "minimax-m3", False, "f.mp3", "/tmp/f.mp3")
        ok = storage_jobs.update_job_template("mp-t1", 5, "My Custom")
        assert ok is True
        meta = storage_jobs.get_job_meta("mp-t1")
        assert meta["template_id"] == 5
        assert meta["template_name"] == "My Custom"
        # Сброс на None
        storage_jobs.update_job_template("mp-t1", None, None)
        meta = storage_jobs.get_job_meta("mp-t1")
        assert meta["template_id"] is None

    def test_increment_regenerate(self):
        from app import storage, storage_jobs
        storage.create_job("mp-r1", "minimax-m3", False, "f.mp3", "/tmp/f.mp3")
        n1 = storage_jobs.increment_regenerate("mp-r1")
        n2 = storage_jobs.increment_regenerate("mp-r1")
        n3 = storage_jobs.increment_regenerate("mp-r1")
        assert (n1, n2, n3) == (1, 2, 3)

    def test_mark_candidates_extracted(self):
        from app import storage, storage_jobs
        storage.create_job("mp-c1", "minimax-m3", False, "f.mp3", "/tmp/f.mp3")
        ok = storage_jobs.mark_candidates_extracted("mp-c1")
        assert ok is True

    def test_set_parent_job(self):
        from app import storage, storage_jobs
        storage.create_job("mp-p1", "minimax-m3", False, "f.mp3", "/tmp/f.mp3")
        storage.create_job("mp-p2", "minimax-m3", False, "f.mp3", "/tmp/f.mp3")
        ok = storage_jobs.set_parent_job("mp-p2", "mp-p1")
        assert ok is True
        meta = storage_jobs.get_job_meta("mp-p2")
        assert meta["parent_job_id"] == "mp-p1"

    def test_list_jobs_with_meta_includes_new_fields(self):
        from app import storage, storage_jobs
        storage.create_job("mp-l1", "minimax-m3", False, "f.mp3", "/tmp/f.mp3")
        rows = storage_jobs.list_jobs_with_meta()
        assert len(rows) >= 1
        j = next(r for r in rows if r["job_id"] == "mp-l1")
        # Новые поля
        for f in ("template_id", "template_name", "candidates_count",
                  "candidates_extracted", "regenerate_count", "parent_job_id"):
            assert f in j, f"missing field in list_jobs_with_meta: {f}"


# ---------------------------------------------------------------------------
# Template endpoint
# ---------------------------------------------------------------------------
class TestTemplateEndpoint:
    def test_set_template(self, auth_client, job_with_meta):
        r = auth_client.patch(
            f"/api/v1/jobs-view/{job_with_meta['job_id']}/template",
            json={"template_id": job_with_meta["template_id"]},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["template_id"] == job_with_meta["template_id"]
        assert data["template_name"] == "Custom"

    def test_reset_template_to_default(self, auth_client, job_with_meta):
        # Set
        auth_client.patch(
            f"/api/v1/jobs-view/{job_with_meta['job_id']}/template",
            json={"template_id": job_with_meta["template_id"]},
        )
        # Reset
        r = auth_client.patch(
            f"/api/v1/jobs-view/{job_with_meta['job_id']}/template",
            json={"template_id": None},
        )
        assert r.status_code == 200
        assert r.json()["template_id"] is None

    def test_template_not_found(self, auth_client, job_with_meta):
        r = auth_client.patch(
            f"/api/v1/jobs-view/{job_with_meta['job_id']}/template",
            json={"template_id": 9999},
        )
        assert r.status_code == 404

    def test_job_not_found(self, auth_client):
        r = auth_client.patch(
            "/api/v1/jobs-view/mp-nonexistent/template",
            json={"template_id": 1},
        )
        assert r.status_code == 404

    def test_unauth_no_cookie(self, client, job_with_meta):
        """Без cookie — middleware должен вернуть 401/403 или 404 (job нет в этом scope)."""
        r = client.patch(
            f"/api/v1/jobs-view/{job_with_meta['job_id']}/template",
            json={"template_id": 1},
        )
        # 401 (cookie required) / 403 (forbidden) / 404 (job not found в другом scope)
        # / 200 (middleware → login.html) — все ОК, главное что не 500
        assert r.status_code in (200, 401, 403, 404)
        assert r.status_code < 500


# ---------------------------------------------------------------------------
# Copy endpoint
# ---------------------------------------------------------------------------
class TestCopyEndpoint:
    def test_copy_creates_new_job(self, auth_client, job_with_meta):
        r = auth_client.post(f"/api/v1/jobs-view/{job_with_meta['job_id']}/copy")
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["parent_job_id"] == job_with_meta["job_id"]
        assert data["new_job_id"] != job_with_meta["job_id"]
        assert data["new_job_id"].startswith("mp-")

    def test_copy_copies_template_and_glossaries(self, auth_client, job_with_meta):
        # Сначала привязываем template
        auth_client.patch(
            f"/api/v1/jobs-view/{job_with_meta['job_id']}/template",
            json={"template_id": job_with_meta["template_id"]},
        )
        # Описание
        auth_client.patch(
            f"/api/v1/jobs-view/{job_with_meta['job_id']}/description",
            json={"description": "my meeting"},
        )
        # Copy
        r = auth_client.post(f"/api/v1/jobs-view/{job_with_meta['job_id']}/copy")
        new_id = r.json()["new_job_id"]

        # Проверяем meta
        from app import storage_jobs
        meta = storage_jobs.get_job_meta(new_id)
        assert meta["template_id"] == job_with_meta["template_id"]
        assert meta["parent_job_id"] == job_with_meta["job_id"]
        assert meta["description"] == "my meeting"
        # Глоссарии скопированы
        gloss = storage_jobs.list_job_glossaries(new_id)
        assert len(gloss) == 1
        assert gloss[0]["id"] == job_with_meta["glossary_id"]

    def test_copy_nonexistent_job(self, auth_client):
        r = auth_client.post("/api/v1/jobs-view/mp-nope/copy")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Regenerate endpoint
# ---------------------------------------------------------------------------
class TestRegenerateEndpoint:
    def test_regenerate_completed_job(self, auth_client, job_with_meta):
        from app import storage
        storage.update_status(job_with_meta["job_id"], "completed")
        r = auth_client.post(f"/api/v1/jobs-view/{job_with_meta['job_id']}/regenerate")
        assert r.status_code == 200
        data = r.json()
        assert data["regenerate_count"] == 1

    def test_regenerate_increments_count(self, auth_client, job_with_meta):
        from app import storage
        for i in range(3):
            storage.update_status(job_with_meta["job_id"], "completed")
            r = auth_client.post(f"/api/v1/jobs-view/{job_with_meta['job_id']}/regenerate")
            assert r.json()["regenerate_count"] == i + 1

    def test_regenerate_queued_409(self, auth_client, job_with_meta):
        from app import storage
        storage.update_status(job_with_meta["job_id"], "queued")
        r = auth_client.post(f"/api/v1/jobs-view/{job_with_meta['job_id']}/regenerate")
        assert r.status_code == 409

    def test_regenerate_nonexistent(self, auth_client):
        r = auth_client.post("/api/v1/jobs-view/mp-nope/regenerate")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Candidates endpoints
# ---------------------------------------------------------------------------
class TestCandidatesEndpoints:
    def _create_pending_candidate(self, job_id, term="API"):
        from app import storage_jobs
        from datetime import datetime
        with storage_jobs._conn() as c:  # type: ignore[attr-defined]
            cur = c.execute(
                """INSERT INTO glossary_candidates
                   (job_id, term, context, suggested_definition, status, created_at)
                   VALUES (?, ?, ?, ?, 'pending', ?)""",
                (job_id, term, "context here", "suggested def", datetime.utcnow().isoformat()),
            )
            return cur.lastrowid

    def test_list_candidates_empty(self, auth_client, job_with_meta):
        r = auth_client.get(f"/api/v1/jobs-view/{job_with_meta['job_id']}/candidates")
        assert r.status_code == 200
        assert r.json()["candidates"] == []

    def test_list_candidates_with_filter(self, auth_client, job_with_meta):
        cid = self._create_pending_candidate(job_with_meta["job_id"], "API")
        r = auth_client.get(
            f"/api/v1/jobs-view/{job_with_meta['job_id']}/candidates?status=pending"
        )
        assert r.status_code == 200
        cands = r.json()["candidates"]
        assert len(cands) == 1
        assert cands[0]["id"] == cid
        assert cands[0]["term"] == "API"

    def test_review_candidate_accept(self, auth_client, job_with_meta):
        cid = self._create_pending_candidate(job_with_meta["job_id"], "TLS")
        r = auth_client.post(
            f"/api/v1/jobs-view/candidates/{cid}/review",
            json={"status": "accepted"},
        )
        assert r.status_code == 200
        # Проверяем в БД
        r2 = auth_client.get(
            f"/api/v1/jobs-view/{job_with_meta['job_id']}/candidates"
        )
        cands = r2.json()["candidates"]
        assert cands[0]["status"] == "accepted"
        assert cands[0]["reviewed_at"] is not None

    def test_review_candidate_reject(self, auth_client, job_with_meta):
        cid = self._create_pending_candidate(job_with_meta["job_id"], "K8s")
        r = auth_client.post(
            f"/api/v1/jobs-view/candidates/{cid}/review",
            json={"status": "rejected"},
        )
        assert r.status_code == 200
        r2 = auth_client.get(
            f"/api/v1/jobs-view/{job_with_meta['job_id']}/candidates"
        )
        assert r2.json()["candidates"][0]["status"] == "rejected"

    def test_review_invalid_status(self, auth_client, job_with_meta):
        cid = self._create_pending_candidate(job_with_meta["job_id"])
        r = auth_client.post(
            f"/api/v1/jobs-view/candidates/{cid}/review",
            json={"status": "maybe"},
        )
        assert r.status_code == 400

    def test_review_nonexistent(self, auth_client):
        r = auth_client.post(
            "/api/v1/jobs-view/candidates/9999/review",
            json={"status": "accepted"},
        )
        assert r.status_code == 404

    def test_extract_candidates_no_protocol_409(self, auth_client, job_with_meta):
        from app import storage
        storage.update_status(job_with_meta["job_id"], "completed")
        r = auth_client.post(
            f"/api/v1/jobs-view/{job_with_meta['job_id']}/extract-candidates"
        )
        assert r.status_code == 409  # no protocol_json

    def test_extract_candidates_not_completed_409(self, auth_client, job_with_meta):
        r = auth_client.post(
            f"/api/v1/jobs-view/{job_with_meta['job_id']}/extract-candidates"
        )
        assert r.status_code == 409  # status != completed

    def test_extract_candidates_nonexistent(self, auth_client):
        r = auth_client.post("/api/v1/jobs-view/mp-nope/extract-candidates")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Delete endpoint
# ---------------------------------------------------------------------------
class TestDeleteEndpoint:
    def test_delete_job(self, auth_client, job_with_meta):
        r = auth_client.delete(f"/api/v1/jobs-view/{job_with_meta['job_id']}")
        assert r.status_code == 200
        # GET → 404
        r2 = auth_client.get(f"/api/v1/jobs-view/{job_with_meta['job_id']}")
        assert r2.status_code == 404

    def test_delete_nonexistent(self, auth_client):
        r = auth_client.delete("/api/v1/jobs-view/mp-nope")
        assert r.status_code == 404

    def test_delete_cascades_to_candidates(self, auth_client, job_with_meta):
        # Создаём candidate
        from app import storage_jobs
        from datetime import datetime
        with storage_jobs._conn() as c:  # type: ignore[attr-defined]
            c.execute(
                """INSERT INTO glossary_candidates
                   (job_id, term, status, created_at) VALUES (?, ?, 'pending', ?)""",
                (job_with_meta["job_id"], "test", datetime.utcnow().isoformat()),
            )
        # Удаляем job
        auth_client.delete(f"/api/v1/jobs-view/{job_with_meta['job_id']}")
        # Проверяем — candidate тоже удалён (CASCADE)
        with storage_jobs._conn() as c:  # type: ignore[attr-defined]
            rows = c.execute(
                "SELECT COUNT(*) AS c FROM glossary_candidates WHERE job_id = ?",
                (job_with_meta["job_id"],),
            ).fetchone()
        assert rows["c"] == 0


# ---------------------------------------------------------------------------
# Integration: list_jobs_with_meta + new fields visible
# ---------------------------------------------------------------------------
class TestListJobsViewIntegration:
    def test_list_includes_template_and_meta(self, auth_client, job_with_meta):
        auth_client.patch(
            f"/api/v1/jobs-view/{job_with_meta['job_id']}/template",
            json={"template_id": job_with_meta["template_id"]},
        )
        r = auth_client.get("/api/v1/jobs-view/")
        assert r.status_code == 200
        data = r.json()
        jobs = data["jobs"]
        j = next(j for j in jobs if j["job_id"] == job_with_meta["job_id"])
        assert j["template_id"] == job_with_meta["template_id"]
        assert j["template_name"] == "Custom"
        assert j["glossary_count"] == 1
        assert j["candidates_count"] == 0
        # regenerate_count/candidates_extracted/parent_job_id — None или 0
        assert j.get("regenerate_count") in (None, 0)
        assert j.get("candidates_extracted") in (None, 0)
        assert j["parent_job_id"] is None

    def test_get_job_meta_includes_new_fields(self, auth_client, job_with_meta):
        r = auth_client.get(f"/api/v1/jobs-view/{job_with_meta['job_id']}")
        assert r.status_code == 200
        data = r.json()
        for f in ("template_id", "template_name", "candidates_count",
                  "candidates_extracted", "regenerate_count", "parent_job_id"):
            assert f in data, f"missing {f}"
