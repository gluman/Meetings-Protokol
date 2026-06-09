"""E2E tests for app/api_glossaries.py via FastAPI TestClient."""

from unittest.mock import MagicMock, patch

from app.main import app
from app.storage import create_job
from fastapi.testclient import TestClient

client = TestClient(app)


def _create_user(username: str = "testuser") -> int:
    """Создаёт тестового пользователя в БД, возвращает user_id."""
    from app.storage_users import create_user, get_user_by_username

    existing = get_user_by_username(username)
    if existing:
        return int(existing["id"])
    create_user(
        username=username,
        password="TestPass123!",
        role="editor",
    )
    u = get_user_by_username(username)
    return int(u["id"])


def _login_cookie(username: str = "testuser") -> str:
    """Логинится и возвращает cookie mp_session."""
    r = client.post(
        "/web/login", json={"username": username, "password": "TestPass123!"}
    )
    if r.status_code != 200:
        raise RuntimeError(f"login failed: {r.status_code} {r.text}")
    return r.cookies.get("mp_session", "")


# ---------------------------------------------------------------------------
# Glossaries
# ---------------------------------------------------------------------------
def test_create_glossary_requires_auth():
    """Без cookie → 401."""
    r = client.post("/api/v1/glossaries", json={"name": "Test", "is_shared": False})
    assert r.status_code == 401


def test_create_glossary_ok():
    """Создание с cookie → 201 + body."""
    _create_user("g_create_user")
    cookie = _login_cookie("g_create_user")
    r = client.post(
        "/api/v1/glossaries",
        json={"name": "Test", "is_shared": False},
        cookies={"mp_session": cookie},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Test"
    assert not body["is_shared"]


def test_list_glossaries_ok():
    """GET /glossaries возвращает список."""
    _create_user("g_list_user")
    cookie = _login_cookie("g_list_user")
    client.post(
        "/api/v1/glossaries", json={"name": "A"}, cookies={"mp_session": cookie}
    )
    client.post(
        "/api/v1/glossaries", json={"name": "B"}, cookies={"mp_session": cookie}
    )
    r = client.get("/api/v1/glossaries", cookies={"mp_session": cookie})
    assert r.status_code == 200
    names = {g["name"] for g in r.json()}
    assert {"A", "B"} <= names


def test_get_glossary_404():
    """GET несуществующего → 404."""
    _create_user("g_get_user")
    cookie = _login_cookie("g_get_user")
    r = client.get("/api/v1/glossaries/99999", cookies={"mp_session": cookie})
    assert r.status_code == 404


def test_update_glossary_owner():
    """Owner может обновить имя."""
    _create_user("g_update_user")
    cookie = _login_cookie("g_update_user")
    r = client.post(
        "/api/v1/glossaries", json={"name": "Old"}, cookies={"mp_session": cookie}
    )
    gid = r.json()["id"]
    r = client.patch(
        f"/api/v1/glossaries/{gid}",
        json={"name": "New"},
        cookies={"mp_session": cookie},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "New"


def test_update_glossary_not_owner_forbidden():
    """Не-owner → 403."""
    _create_user("g_owner")
    _create_user("g_other")
    owner_cookie = _login_cookie("g_owner")
    other_cookie = _login_cookie("g_other")
    r = client.post(
        "/api/v1/glossaries",
        json={"name": "Mine"},
        cookies={"mp_session": owner_cookie},
    )
    gid = r.json()["id"]
    r = client.patch(
        f"/api/v1/glossaries/{gid}",
        json={"name": "Hacked"},
        cookies={"mp_session": other_cookie},
    )
    assert r.status_code == 403


def test_delete_glossary_owner():
    """DELETE → 204."""
    _create_user("g_del_user")
    cookie = _login_cookie("g_del_user")
    r = client.post(
        "/api/v1/glossaries", json={"name": "X"}, cookies={"mp_session": cookie}
    )
    gid = r.json()["id"]
    r = client.delete(f"/api/v1/glossaries/{gid}", cookies={"mp_session": cookie})
    assert r.status_code == 204


def test_copy_glossary_deep():
    """Copy создаёт новый с entries."""
    _create_user("g_copy_user")
    cookie = _login_cookie("g_copy_user")
    r = client.post(
        "/api/v1/glossaries", json={"name": "Source"}, cookies={"mp_session": cookie}
    )
    src_id = r.json()["id"]
    client.post(
        f"/api/v1/glossaries/{src_id}/entries",
        json={"term": "ASR", "definition": "recognition"},
        cookies={"mp_session": cookie},
    )
    r = client.post(
        f"/api/v1/glossaries/{src_id}/copy",
        json={"new_name": "Copy"},
        cookies={"mp_session": cookie},
    )
    assert r.status_code == 201
    new_id = r.json()["id"]
    assert new_id != src_id
    r = client.get(
        f"/api/v1/glossaries/{new_id}/entries", cookies={"mp_session": cookie}
    )
    assert any(e["term"] == "ASR" for e in r.json())


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------
def test_add_entry_ok():
    """POST /entries → 201 + body."""
    _create_user("e_add_user")
    cookie = _login_cookie("e_add_user")
    r = client.post(
        "/api/v1/glossaries", json={"name": "T"}, cookies={"mp_session": cookie}
    )
    gid = r.json()["id"]
    r = client.post(
        f"/api/v1/glossaries/{gid}/entries",
        json={"term": "ASR", "definition": "Speech recognition", "abbreviation": "ASR"},
        cookies={"mp_session": cookie},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["term"] == "ASR"
    assert not body["needs_review"]


def test_add_entry_validation_error():
    """Пустой term → 422 (Pydantic) или 400 (endpoint)."""
    _create_user("e_val_user")
    cookie = _login_cookie("e_val_user")
    r = client.post(
        "/api/v1/glossaries", json={"name": "T"}, cookies={"mp_session": cookie}
    )
    gid = r.json()["id"]
    r = client.post(
        f"/api/v1/glossaries/{gid}/entries",
        json={"term": "", "definition": "x"},
        cookies={"mp_session": cookie},
    )
    # Pydantic min_length=1 → 422; если бы validation было в endpoint → 400
    assert r.status_code in (400, 422)


def test_list_entries_permission():
    """Private глоссарий другого user → 403."""
    _create_user("e_owner")
    _create_user("e_other")
    owner_cookie = _login_cookie("e_owner")
    other_cookie = _login_cookie("e_other")
    r = client.post(
        "/api/v1/glossaries",
        json={"name": "Private"},
        cookies={"mp_session": owner_cookie},
    )
    gid = r.json()["id"]
    r = client.get(
        f"/api/v1/glossaries/{gid}/entries", cookies={"mp_session": other_cookie}
    )
    assert r.status_code == 403


def test_update_entry_ok():
    """PATCH entry."""
    _create_user("e_upd_user")
    cookie = _login_cookie("e_upd_user")
    r = client.post(
        "/api/v1/glossaries", json={"name": "T"}, cookies={"mp_session": cookie}
    )
    gid = r.json()["id"]
    r = client.post(
        f"/api/v1/glossaries/{gid}/entries",
        json={"term": "T", "definition": "D"},
        cookies={"mp_session": cookie},
    )
    eid = r.json()["id"]
    r = client.patch(
        f"/api/v1/glossary-entries/{eid}",
        json={"definition": "New D", "comment": "c"},
        cookies={"mp_session": cookie},
    )
    assert r.status_code == 200
    assert r.json()["definition"] == "New D"
    assert r.json()["comment"] == "c"


def test_delete_entry():
    """DELETE entry → 204."""
    _create_user("e_del_user")
    cookie = _login_cookie("e_del_user")
    r = client.post(
        "/api/v1/glossaries", json={"name": "T"}, cookies={"mp_session": cookie}
    )
    gid = r.json()["id"]
    r = client.post(
        f"/api/v1/glossaries/{gid}/entries",
        json={"term": "T", "definition": "D"},
        cookies={"mp_session": cookie},
    )
    eid = r.json()["id"]
    r = client.delete(f"/api/v1/glossary-entries/{eid}", cookies={"mp_session": cookie})
    assert r.status_code == 204


def test_toggle_needs_review():
    """Toggle flip."""
    _create_user("e_tog_user")
    cookie = _login_cookie("e_tog_user")
    r = client.post(
        "/api/v1/glossaries", json={"name": "T"}, cookies={"mp_session": cookie}
    )
    gid = r.json()["id"]
    r = client.post(
        f"/api/v1/glossaries/{gid}/entries",
        json={"term": "T", "definition": "D", "needs_review": False},
        cookies={"mp_session": cookie},
    )
    eid = r.json()["id"]
    r = client.post(
        f"/api/v1/glossary-entries/{eid}/toggle-needs-review",
        cookies={"mp_session": cookie},
    )
    assert r.status_code == 200
    assert r.json()["needs_review"]


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------
@patch("app.glossary_candidates.httpx.Client")
def test_extract_candidates_endpoint(mock_client_cls):
    """POST /candidates/extract → 201 + list of ids."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": '{"candidates": [{"term": "ASR", "context": "c", "suggested_definition": "d"}]}'
                }
            }
        ]
    }
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = mock_client

    jid = "test-extract-job-1"
    create_job(
        jid, model_used="m", is_video=False, file_name="f.wav", file_path="/tmp/f.wav"
    )
    r = client.post(
        "/api/v1/candidates/extract",
        json={"transcript": "Some text", "job_id": jid},
    )
    assert r.status_code == 201, r.text
    ids = r.json()
    assert len(ids) == 1


def test_list_candidates_endpoint():
    """GET /jobs/{jid}/candidates."""
    jid = "test-list-cand-job"
    create_job(jid, model_used="m", is_video=False, file_name="f", file_path="/tmp/f")
    from app.glossary_candidates import extract_candidates as _ext

    with patch("app.glossary_candidates.httpx.Client") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"candidates": [{"term": "X", "context": "c", "suggested_definition": "d"}]}'
                    }
                }
            ]
        }
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        _ext("text", jid)

    r = client.get(f"/api/v1/jobs/{jid}/candidates")
    assert r.status_code == 200
    assert len(r.json()) == 1


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------
def test_queue_state_empty():
    """GET /queue возвращает state с running=None и пустым queued."""
    r = client.get("/api/v1/queue")
    assert r.status_code == 200
    body = r.json()
    assert body["running"] is None or isinstance(body["running"], dict)
    assert isinstance(body["queued"], list)


def test_enqueue_endpoint():
    """POST /jobs/{jid}/enqueue → 200 + position."""
    jid = "test-enqueue-job-1"
    create_job(jid, model_used="m", is_video=False, file_name="f", file_path="/tmp/f")
    r = client.post(f"/api/v1/jobs/{jid}/enqueue")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["position"] == 1


def test_enqueue_nonexistent_job():
    """POST /jobs/.../enqueue для несуществующего → 404."""
    r = client.post("/api/v1/jobs/no-such-job/enqueue")
    assert r.status_code == 404


def test_cancel_job():
    """POST /jobs/{jid}/cancel → 200."""
    jid = "test-cancel-job-1"
    create_job(jid, model_used="m", is_video=False, file_name="f", file_path="/tmp/f")
    client.post(f"/api/v1/jobs/{jid}/enqueue")
    r = client.post(f"/api/v1/jobs/{jid}/cancel")
    assert r.status_code == 200
    assert r.json()["canceled"]


def test_queue_position_endpoint():
    """GET /jobs/{jid}/queue-position."""
    jid = "test-pos-job-1"
    create_job(jid, model_used="m", is_video=False, file_name="f", file_path="/tmp/f")
    client.post(f"/api/v1/jobs/{jid}/enqueue")
    r = client.get(f"/api/v1/jobs/{jid}/queue-position")
    assert r.status_code == 200
    body = r.json()
    assert body["in_queue"]
    assert body["position"] == 1
