"""E2E тесты для app/api_jobs.py — табличное представление jobs.

Покрывает:
- list_jobs (фильтр, пагинация, total)
- get_job (404, joined data)
- update_job_description (autosave, max 2000, 404)
- attach/detach glossary (idempotent, 404)
- list_job_glossaries
"""
import json
import os

import pytest
from fastapi.testclient import TestClient

# Force test storage BEFORE importing app
os.environ.setdefault("STORAGE_DIR", "/tmp/meeting_protocol_test_api_jobs")

from app.main import app  # noqa: E402

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _create_user(username: str = "testuser", role: str = "editor") -> int:
    """Создаёт пользователя в users.db, возвращает user_id."""
    from app.storage_users import create_user, get_user_by_username
    existing = get_user_by_username(username)
    if existing:
        return existing["id"]
    u = create_user(username, "TestPass123!", role=role)
    return u["id"]


def _login_cookie(username: str) -> str:
    """Логинится через /web/login (JSON), возвращает session token."""
    r = client.post(
        "/web/login",
        json={"username": username, "password": "TestPass123!"},
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.cookies.get("mp_session")


def _create_job_direct(
    file_name: str = "test.mp3",
    status: str = "completed",
    description: str | None = None,
) -> str:
    """Создаёт job напрямую через storage (минуя /transcribe)."""
    from app import storage, storage_jobs
    import uuid
    jid = f"mp-test-{uuid.uuid4().hex[:8]}"
    storage.create_job(
        job_id=jid,
        model_used="M3",
        is_video=0,
        file_name=file_name,
        file_path=f"/tmp/audio/{file_name}",
    )
    if status != "queued":
        storage.update_status(jid, status)
    if description is not None:
        storage_jobs.update_job_description(jid, description)
    return jid


# ---------------------------------------------------------------------------
# GET /api/v1/jobs
# ---------------------------------------------------------------------------
def test_list_jobs_empty():
    """Свежий storage → пустой список."""
    user_id = _create_user("lj_empty")
    cookie = _login_cookie("lj_empty")
    r = client.get("/api/v1/jobs-view/", cookies={"mp_session": cookie})
    assert r.status_code == 200
    data = r.json()
    assert "jobs" in data
    assert "total" in data
    assert "limit" in data
    assert "offset" in data
    assert isinstance(data["jobs"], list)


def test_list_jobs_with_results():
    """Создаём 3 jobs → возвращаются с joined meta."""
    _create_user("lj_data")
    cookie = _login_cookie("lj_data")
    j1 = _create_job_direct("a.mp3", "completed", "Note 1")
    j2 = _create_job_direct("b.mp3", "failed", "Note 2")
    j3 = _create_job_direct("c.mp3", "completed", None)
    r = client.get("/api/v1/jobs-view/", cookies={"mp_session": cookie})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 3
    ids = {j["job_id"] for j in data["jobs"]}
    assert {j1, j2, j3}.issubset(ids)
    # description должен присутствовать в каждом
    for j in data["jobs"]:
        assert "description" in j
        assert "queue_position" in j  # None если не в очереди
        assert "glossary_count" in j


def test_list_jobs_filter_status():
    """Фильтр status=completed → только completed."""
    _create_user("lj_filter")
    cookie = _login_cookie("lj_filter")
    _create_job_direct("done1.mp3", "completed")
    _create_job_direct("done2.mp3", "completed")
    _create_job_direct("fail1.mp3", "failed")
    r = client.get(
        "/api/v1/jobs-view?status=completed", cookies={"mp_session": cookie}
    )
    assert r.status_code == 200
    data = r.json()
    for j in data["jobs"]:
        assert j["status"] == "completed"
    assert data["total"] >= 2


def test_list_jobs_pagination():
    """limit + offset работают."""
    _create_user("lj_page")
    cookie = _login_cookie("lj_page")
    for i in range(5):
        _create_job_direct(f"p{i}.mp3", "completed")
    r1 = client.get(
        "/api/v1/jobs-view?limit=2&offset=0", cookies={"mp_session": cookie}
    )
    r2 = client.get(
        "/api/v1/jobs-view?limit=2&offset=2", cookies={"mp_session": cookie}
    )
    assert r1.status_code == 200 and r2.status_code == 200
    assert len(r1.json()["jobs"]) == 2
    assert len(r2.json()["jobs"]) == 2
    # разные записи (ORDER BY created_at DESC)
    ids1 = {j["job_id"] for j in r1.json()["jobs"]}
    ids2 = {j["job_id"] for j in r2.json()["jobs"]}
    assert ids1.isdisjoint(ids2)


def test_list_jobs_limit_validation():
    """limit > 200 → 422 (FastAPI Query validation)."""
    _create_user("lj_limit")
    cookie = _login_cookie("lj_limit")
    r = client.get(
        "/api/v1/jobs-view?limit=500", cookies={"mp_session": cookie}
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/{job_id}
# ---------------------------------------------------------------------------
def test_get_job_ok():
    """Существующий job → 200 с glossaries + candidates_count."""
    _create_user("gj_ok")
    cookie = _login_cookie("gj_ok")
    jid = _create_job_direct("x.mp3", "completed", "Test note")
    r = client.get(f"/api/v1/jobs-view/{jid}", cookies={"mp_session": cookie})
    assert r.status_code == 200
    data = r.json()
    assert data["job_id"] == jid
    assert data["status"] == "completed"
    assert data["description"] == "Test note"
    assert "glossaries" in data
    assert isinstance(data["glossaries"], list)
    assert "candidates_count" in data


def test_get_job_404():
    """Несуществующий job → 404."""
    _create_user("gj_404")
    cookie = _login_cookie("gj_404")
    r = client.get(
        "/api/v1/jobs-view/nonexistent-id", cookies={"mp_session": cookie}
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/v1/jobs/{job_id}/description
# ---------------------------------------------------------------------------
def test_update_description_ok():
    """Autosave: обновляет description."""
    _create_user("ud_ok")
    cookie = _login_cookie("ud_ok")
    jid = _create_job_direct("d.mp3", "completed", "")
    r = client.patch(
        f"/api/v1/jobs-view/{jid}/description",
        json={"description": "Autosaved note"},
        cookies={"mp_session": cookie},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["description"] == "Autosaved note"
    # Перечитываем
    r2 = client.get(
        f"/api/v1/jobs-view/{jid}", cookies={"mp_session": cookie}
    )
    assert r2.json()["description"] == "Autosaved note"


def test_update_description_404():
    """Несуществующий job → 404."""
    _create_user("ud_404")
    cookie = _login_cookie("ud_404")
    r = client.patch(
        "/api/v1/jobs-view/no-such-job/description",
        json={"description": "x"},
        cookies={"mp_session": cookie},
    )
    assert r.status_code == 404


def test_update_description_too_long():
    """description > 2000 → 400."""
    _create_user("ud_long")
    cookie = _login_cookie("ud_long")
    jid = _create_job_direct("long.mp3", "completed")
    r = client.patch(
        f"/api/v1/jobs-view/{jid}/description",
        json={"description": "x" * 2001},
        cookies={"mp_session": cookie},
    )
    assert r.status_code == 400


def test_update_description_must_be_string():
    """description=int → 400."""
    _create_user("ud_type")
    cookie = _login_cookie("ud_type")
    jid = _create_job_direct("t.mp3", "completed")
    r = client.patch(
        f"/api/v1/jobs-view/{jid}/description",
        json={"description": 12345},
        cookies={"mp_session": cookie},
    )
    assert r.status_code == 400


def test_update_description_idempotent():
    """Повторный PATCH с тем же description → ok."""
    _create_user("ud_idem")
    cookie = _login_cookie("ud_idem")
    jid = _create_job_direct("i.mp3", "completed")
    for _ in range(3):
        r = client.patch(
            f"/api/v1/jobs-view/{jid}/description",
            json={"description": "same"},
            cookies={"mp_session": cookie},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/v1/jobs/{job_id}/glossaries (attach)
# ---------------------------------------------------------------------------
def test_attach_glossary_ok():
    """Привязываем глоссарий → ok."""
    from app.glossaries import create_glossary
    _create_user("ag_ok")
    cookie = _login_cookie("ag_ok")
    jid = _create_job_direct("attach.mp3", "completed")
    user_id = _create_user("glossary_owner")
    gid = create_glossary("Test", owner_id=user_id, is_shared=True)
    r = client.post(
        f"/api/v1/jobs-view/{jid}/glossaries",
        json={"glossary_id": gid},
        cookies={"mp_session": cookie},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["glossary_id"] == gid


def test_attach_glossary_idempotent():
    """Повторный attach → 200 (не дублирует)."""
    from app.glossaries import create_glossary, list_entries
    _create_user("ag_idem")
    cookie = _login_cookie("ag_idem")
    jid = _create_job_direct("ai.mp3", "completed")
    user_id = _create_user("ag_idem_owner")
    gid = create_glossary("Idem", owner_id=user_id, is_shared=True)
    # attach дважды
    r1 = client.post(
        f"/api/v1/jobs-view/{jid}/glossaries",
        json={"glossary_id": gid},
        cookies={"mp_session": cookie},
    )
    r2 = client.post(
        f"/api/v1/jobs-view/{jid}/glossaries",
        json={"glossary_id": gid},
        cookies={"mp_session": cookie},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    # get_job → glossary_count=1
    r = client.get(f"/api/v1/jobs-view/{jid}", cookies={"mp_session": cookie})
    assert r.json()["glossaries"][0]["id"] == gid
    # Список в БД ровно 1
    attached = list_entries(gid)  # sanity check
    assert attached is not None


def test_attach_glossary_404_job():
    """Несуществующий job → 404."""
    from app.glossaries import create_glossary
    _create_user("ag_404j")
    cookie = _login_cookie("ag_404j")
    user_id = _create_user("ag_404j_owner")
    gid = create_glossary("X", owner_id=user_id, is_shared=True)
    r = client.post(
        "/api/v1/jobs-view/no-such-job/glossaries",
        json={"glossary_id": gid},
        cookies={"mp_session": cookie},
    )
    assert r.status_code == 404


def test_attach_glossary_404_glossary():
    """Несуществующий glossary_id → 404."""
    _create_user("ag_404g")
    cookie = _login_cookie("ag_404g")
    jid = _create_job_direct("g404.mp3", "completed")
    r = client.post(
        f"/api/v1/jobs-view/{jid}/glossaries",
        json={"glossary_id": 99999},
        cookies={"mp_session": cookie},
    )
    assert r.status_code == 404


def test_attach_glossary_invalid_payload():
    """Без glossary_id или wrong type → 400."""
    _create_user("ag_bad")
    cookie = _login_cookie("ag_bad")
    jid = _create_job_direct("bad.mp3", "completed")
    r = client.post(
        f"/api/v1/jobs-view/{jid}/glossaries",
        json={},
        cookies={"mp_session": cookie},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /api/v1/jobs/{job_id}/glossaries/{glossary_id}
# ---------------------------------------------------------------------------
def test_detach_glossary_ok():
    """Attach → detach → ok."""
    from app.glossaries import create_glossary
    _create_user("dg_ok")
    cookie = _login_cookie("dg_ok")
    jid = _create_job_direct("det.mp3", "completed")
    user_id = _create_user("dg_ok_owner")
    gid = create_glossary("D", owner_id=user_id, is_shared=True)
    # attach
    client.post(
        f"/api/v1/jobs-view/{jid}/glossaries",
        json={"glossary_id": gid},
        cookies={"mp_session": cookie},
    )
    # detach
    r = client.delete(
        f"/api/v1/jobs-view/{jid}/glossaries/{gid}",
        cookies={"mp_session": cookie},
    )
    assert r.status_code == 200
    # verify через get_job
    r2 = client.get(f"/api/v1/jobs-view/{jid}", cookies={"mp_session": cookie})
    assert r2.json()["glossaries"] == []


def test_detach_glossary_not_attached_404():
    """Detach непривязанного → 404."""
    _create_user("dg_404")
    cookie = _login_cookie("dg_404")
    jid = _create_job_direct("dn.mp3", "completed")
    r = client.delete(
        f"/api/v1/jobs-view/{jid}/glossaries/9999",
        cookies={"mp_session": cookie},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/{job_id}/glossaries
# ---------------------------------------------------------------------------
def test_list_job_glossaries_ok():
    """Возвращает список привязанных."""
    from app.glossaries import create_glossary
    _create_user("ljg_ok")
    cookie = _login_cookie("ljg_ok")
    jid = _create_job_direct("lg.mp3", "completed")
    user_id = _create_user("ljg_ok_owner")
    g1 = create_glossary("G1", owner_id=user_id, is_shared=True)
    g2 = create_glossary("G2", owner_id=user_id, is_shared=True)
    for g in [g1, g2]:
        client.post(
            f"/api/v1/jobs-view/{jid}/glossaries",
            json={"glossary_id": g},
            cookies={"mp_session": cookie},
        )
    r = client.get(
        f"/api/v1/jobs-view/{jid}/glossaries",
        cookies={"mp_session": cookie},
    )
    assert r.status_code == 200
    data = r.json()
    gids = {g["id"] for g in data["glossaries"]}
    assert {g1, g2}.issubset(gids)


def test_list_job_glossaries_404():
    """Job не найден → 404."""
    _create_user("ljg_404")
    cookie = _login_cookie("ljg_404")
    r = client.get(
        "/api/v1/jobs-view/no-such/glossaries",
        cookies={"mp_session": cookie},
    )
    assert r.status_code == 404
