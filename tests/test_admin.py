"""Tests for admin panel: storage_users, rbac, admin_api.

Запускать: pytest tests/test_admin.py -v
"""
import os
import tempfile
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Подменяем storage_dir на временную папку ПЕРЕД импортом app
TMPDIR = tempfile.mkdtemp(prefix="mp_test_admin_")
os.environ["STORAGE_DIR"] = TMPDIR
os.environ["WEB_SESSION_SECRET"] = "test-secret-for-jwt-only-not-real"
# ВАЖНО: очищаем .env creds, чтобы auth шёл через БД
# (pydantic_settings читает .env при init, но env vars приоритетнее)
os.environ["WEB_USERNAME"] = ""
os.environ["WEB_PASSWORD"] = ""

from app import storage_users  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.rbac import get_current_user, require_role  # noqa: E402
from app.web_auth import is_web_auth_enabled, login  # noqa: E402

# Force storage_dir to TMPDIR
settings.storage_dir = Path(TMPDIR)
(storage_users.DB_PATH).parent.mkdir(parents=True, exist_ok=True)

# Lock для thread-safety
_test_lock = threading.Lock()


@pytest.fixture(autouse=True)
def reset_db():
    """Drop+recreate users DB перед каждым тестом."""
    with _test_lock:
        if Path(storage_users.DB_PATH).exists():
            Path(storage_users.DB_PATH).unlink()
    storage_users.init_users_table()
    yield
    if Path(storage_users.DB_PATH).exists():
        Path(storage_users.DB_PATH).unlink()


@pytest.fixture
def client():
    return TestClient(app)


# ===========================================================================
# 1. storage_users unit tests
# ===========================================================================

def test_init_users_table_creates_tables():
    storage_users.init_users_table()
    assert storage_users.count_users() == 0


def test_create_user_minimal():
    u = storage_users.create_user("alice", "secret123", "viewer")
    assert u["username"] == "alice"
    assert u["role"] == "viewer"
    assert u["is_active"] == 1
    assert u["password_hash"]  # не пусто
    assert u["password_salt"]


def test_create_user_duplicate_fails():
    storage_users.create_user("bob", "secret123", "viewer")
    with pytest.raises(Exception):  # sqlite3.IntegrityError
        storage_users.create_user("bob", "secret456", "viewer")


def test_create_user_short_password_fails():
    with pytest.raises(ValueError, match="at least 6"):
        storage_users.create_user("eve", "abc", "viewer")


def test_create_user_invalid_role_fails():
    with pytest.raises(ValueError, match="must be one of"):
        storage_users.create_user("eve", "secret123", "superuser")  # type: ignore


def test_verify_credentials_success():
    storage_users.create_user("alice", "secret123", "viewer")
    u = storage_users.verify_credentials("alice", "secret123")
    assert u is not None
    assert u["username"] == "alice"
    assert u["last_login_at"] is not None  # обновилось


def test_verify_credentials_wrong_password():
    storage_users.create_user("alice", "secret123", "viewer")
    u = storage_users.verify_credentials("alice", "wrongpass")
    assert u is None


def test_verify_credentials_unknown_user():
    assert storage_users.verify_credentials("ghost", "any") is None


def test_verify_credentials_inactive_user():
    storage_users.create_user("alice", "secret123", "viewer")
    storage_users.update_user(1, is_active=False)
    u = storage_users.verify_credentials("alice", "secret123")
    assert u is None


def test_update_user_role_and_password():
    storage_users.create_user("alice", "secret123", "viewer")
    u = storage_users.update_user(1, role="editor", password="newpass456")
    assert u["role"] == "editor"
    # Новый пароль работает
    assert storage_users.verify_credentials("alice", "newpass456") is not None
    # Старый — нет
    assert storage_users.verify_credentials("alice", "secret123") is None


def test_count_admins():
    storage_users.create_user("a1", "secret1", "admin")
    storage_users.create_user("a2", "secret2", "admin")
    storage_users.create_user("e1", "secret3", "editor")
    assert storage_users.count_admins() == 2
    # деактивируем a2
    storage_users.update_user(2, is_active=False)
    assert storage_users.count_admins() == 1


def test_delete_user_last_admin_blocked():
    storage_users.create_user("solo", "secret1", "admin")
    with pytest.raises(ValueError, match="last active admin"):
        storage_users.delete_user(1)


def test_delete_user_non_admin_ok():
    storage_users.create_user("admin1", "secret1", "admin")
    storage_users.create_user("editor1", "secret2", "editor")
    assert storage_users.delete_user(2) is True
    assert storage_users.count_users() == 1


def test_bootstrap_creates_admin():
    storage_users.bootstrap_admin()
    assert storage_users.count_users() == 1
    u = storage_users.list_users()[0]
    assert u["username"] == "admin"
    assert u["role"] == "admin"
    # Файл с паролем
    master = settings.storage_dir / "webauth_master.txt"
    assert master.exists()
    content = master.read_text()
    assert "admin" in content
    assert "Password:" in content


def test_bootstrap_idempotent():
    storage_users.bootstrap_admin()
    storage_users.bootstrap_admin()  # повторно
    assert storage_users.count_users() == 1


# ===========================================================================
# 2. Settings
# ===========================================================================

def test_settings_default():
    storage_users.init_users_table()
    items = storage_users.list_settings()
    assert len(items) > 0
    # Каждый item имеет обязательные поля
    for it in items:
        assert "key" in it
        assert "label" in it
        assert "secret" in it
        assert "effective_value" in it
        assert "is_overridden" in it


def test_setting_set_get_effective():
    storage_users.set_setting("autoai_model", "test-model-1")
    assert storage_users.get_setting("autoai_model") == "test-model-1"
    assert storage_users.get_effective("autoai_model") == "test-model-1"


def test_setting_set_unknown_key_rejected():
    with pytest.raises(ValueError, match="not editable"):
        storage_users.set_setting("not_a_real_key", "x")


def test_setting_delete_reverts():
    storage_users.set_setting("autoai_model", "test-model-1")
    storage_users.delete_setting("autoai_model")
    assert storage_users.get_setting("autoai_model") is None
    # effective теперь = .env default
    assert storage_users.get_effective("autoai_model") == settings.autoai_model


# ===========================================================================
# 3. /me endpoint (auth not required when env creds missing)
# ===========================================================================

def test_me_no_auth_disabled(client):
    r = client.get("/web/api/v1/admin/me")
    assert r.status_code == 200
    data = r.json()
    assert data["auth_enabled"] is False
    assert data["is_admin"] is False
    assert data["user"] is None


# ===========================================================================
# 4. Admin endpoints with auth
# ===========================================================================

@pytest.fixture
def admin_client(client):
    """Client with admin user in DB."""
    storage_users.create_user("admin1", "adminpass1", "admin")
    storage_users.create_user("editor1", "editorpass1", "editor")
    # Login as admin
    r = client.post("/web/login", json={"username": "admin1", "password": "adminpass1"})
    assert r.status_code == 200, r.text
    return client


def test_admin_list_users(admin_client):
    r = admin_client.get("/web/api/v1/admin/users")
    assert r.status_code == 200
    users = r.json()
    assert len(users) == 2
    assert {u["username"] for u in users} == {"admin1", "editor1"}


def test_admin_create_user(admin_client):
    r = admin_client.post(
        "/web/api/v1/admin/users",
        json={"username": "newviewer", "password": "newpass123", "role": "viewer"},
    )
    assert r.status_code == 201
    u = r.json()
    assert u["username"] == "newviewer"
    assert u["role"] == "viewer"
    # В БД тоже
    assert storage_users.get_user_by_username("newviewer") is not None


def test_admin_create_duplicate_409(admin_client):
    r = admin_client.post(
        "/web/api/v1/admin/users",
        json={"username": "admin1", "password": "newpass123", "role": "viewer"},
    )
    assert r.status_code == 409


def test_admin_update_user_role(admin_client):
    r = admin_client.put(
        "/web/api/v1/admin/users/2",
        json={"role": "admin"},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


def test_admin_demote_last_admin_blocked(admin_client):
    # Сейчас admin1 = единственный admin. Пытаемся понизить.
    r = admin_client.put(
        "/web/api/v1/admin/users/1",
        json={"role": "viewer"},
    )
    assert r.status_code == 400
    assert "last active admin" in r.json()["detail"]


def test_admin_delete_self_blocked(admin_client):
    r = admin_client.delete("/web/api/v1/admin/users/1")  # admin1
    assert r.status_code == 400
    assert "yourself" in r.json()["detail"]


def test_admin_delete_other_user(admin_client):
    r = admin_client.delete("/web/api/v1/admin/users/2")  # editor1
    assert r.status_code == 200


def test_admin_reset_password(admin_client):
    r = admin_client.post("/web/api/v1/admin/users/2/reset-password")
    assert r.status_code == 200
    data = r.json()
    assert data["username"] == "editor1"
    assert "new_password" in data
    assert len(data["new_password"]) >= 12
    # Новый пароль работает
    new_client = TestClient(app)
    r2 = new_client.post("/web/login", json={"username": "editor1", "password": data["new_password"]})
    assert r2.status_code == 200


# ===========================================================================
# 5. RBAC: editor не может управлять users
# ===========================================================================

@pytest.fixture
def editor_client(client):
    storage_users.create_user("admin1", "adminpass1", "admin")
    storage_users.create_user("editor1", "editorpass1", "editor")
    r = client.post("/web/login", json={"username": "editor1", "password": "editorpass1"})
    assert r.status_code == 200
    return client


def test_editor_cannot_list_users(editor_client):
    r = editor_client.get("/web/api/v1/admin/users")
    assert r.status_code == 403


def test_editor_cannot_create_user(editor_client):
    r = editor_client.post(
        "/web/api/v1/admin/users",
        json={"username": "hacker", "password": "hackpass", "role": "admin"},
    )
    assert r.status_code == 403


def test_editor_me_role(editor_client):
    r = editor_client.get("/web/api/v1/admin/me")
    assert r.status_code == 200
    data = r.json()
    assert data["role"] == "editor"
    assert data["is_admin"] is False


def test_unauth_cannot_access_admin(client):
    # Auth disabled → admin endpoints открыты (dev-режим)
    # Но в этом тесте мы специально проверяем поведение с активным auth
    storage_users.create_user("admin1", "adminpass1", "admin")
    # logout / нет сессии
    r = client.get("/web/api/v1/admin/users")
    assert r.status_code == 401


# ===========================================================================
# 6. Settings API
# ===========================================================================

def test_settings_list_with_override(admin_client):
    storage_users.set_setting("autoai_model", "custom-model")
    r = admin_client.get("/web/api/v1/admin/settings")
    assert r.status_code == 200
    items = r.json()
    model = next(i for i in items if i["key"] == "autoai_model")
    assert model["is_overridden"] is True
    assert model["override_value"] == "custom-model"


def test_settings_update(admin_client):
    r = admin_client.put(
        "/web/api/v1/admin/settings/autoai_model",
        json={"value": "new-model-123"},
    )
    assert r.status_code == 200
    assert r.json()["override_value"] == "new-model-123"


def test_settings_update_int_validation(admin_client):
    r = admin_client.put(
        "/web/api/v1/admin/settings/max_file_size_mb",
        json={"value": "not-an-int"},
    )
    assert r.status_code == 400


def test_settings_update_bool_validation(admin_client):
    r = admin_client.put(
        "/web/api/v1/admin/settings/autoai_use",
        json={"value": "maybe"},
    )
    assert r.status_code == 400


def test_settings_revert(admin_client):
    storage_users.set_setting("autoai_model", "custom")
    r = admin_client.delete("/web/api/v1/admin/settings/autoai_model")
    assert r.status_code == 200
    assert r.json()["is_overridden"] is False


def test_settings_update_unknown_key_404(admin_client):
    r = admin_client.put(
        "/web/api/v1/admin/settings/not_a_real_key",
        json={"value": "x"},
    )
    assert r.status_code == 404
