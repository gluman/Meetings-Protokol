"""Хранилище пользователей и настроек (overrides поверх .env).

Users:
  - SQLite таблица users (id, username, password_hash, role, is_active, created_at)
  - пароли: pbkdf2_hmac(sha256, 200k итераций, 32 байт) — NIST SP 800-132
  - роли: 'admin' | 'editor' | 'viewer'
  - bootstrap: при первом запуске создаётся admin, пароль в webauth_master.txt

Settings (overrides):
  - SQLite таблица settings (key TEXT PRIMARY KEY, value TEXT)
  - читается поверх .env: get_setting(key) → value или None
  - для чувствительных полей (API keys) — маскирование при чтении
"""
import json
import logging
import os
import secrets
import sqlite3
import threading
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime
from hashlib import pbkdf2_hmac
from pathlib import Path
from typing import Literal

from .config import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
DB_PATH = settings.storage_dir / "users.db"

# Используем ту же БД, что и jobs/templates (storage_dir), но отдельный файл.
# Альтернатива: всё в одной БД через ATTACH. Оставим отдельный файл для простоты миграций.

Role = Literal["admin", "editor", "viewer"]
ROLES: tuple[Role, ...] = ("admin", "editor", "viewer")

# Итерации pbkdf2 (200_000 — NIST рекомендация 2023+)
PBKDF2_ITERATIONS = 200_000
PBKDF2_SALT_BYTES = 16
PBKDF2_DKLEN = 32


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_users_table() -> None:
    with _lock, _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin','editor','viewer')),
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
    logger.info("users + settings tables initialised")


# ---------------------------------------------------------------------------
# Password hashing (pbkdf2_hmac, NIST SP 800-132)
# ---------------------------------------------------------------------------

def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """Возвращает (hash_b64, salt_b64)."""
    if salt is None:
        salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    dk = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS, dklen=PBKDF2_DKLEN)
    return (
        urlsafe_b64encode(dk).decode("ascii"),
        urlsafe_b64encode(salt).decode("ascii"),
    )


def _verify_password(password: str, hash_b64: str, salt_b64: str) -> bool:
    try:
        salt = urlsafe_b64decode(salt_b64.encode("ascii"))
        expected = urlsafe_b64decode(hash_b64.encode("ascii"))
    except Exception:
        return False
    dk = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS, dklen=PBKDF2_DKLEN)
    # constant-time
    return secrets.compare_digest(dk, expected)


# ---------------------------------------------------------------------------
# Users CRUD
# ---------------------------------------------------------------------------

def get_user_by_username(username: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def list_users() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, username, role, is_active, created_at, last_login_at FROM users ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def count_users() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def count_admins() -> int:
    with _conn() as c:
        return c.execute(
            "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
        ).fetchone()[0]


def create_user(username: str, password: str, role: Role) -> dict:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if not username or len(username) < 2:
        raise ValueError("username must be at least 2 chars")
    if not password or len(password) < 6:
        raise ValueError("password must be at least 6 chars")
    hash_b64, salt_b64 = _hash_password(password)
    with _lock, _conn() as c:
        cur = c.execute(
            """INSERT INTO users (username, password_hash, password_salt, role, is_active, created_at)
               VALUES (?, ?, ?, ?, 1, ?)""",
            (username, hash_b64, salt_b64, role, datetime.utcnow().isoformat()),
        )
        new_id = cur.lastrowid
    logger.info(f"user '{username}' created (role={role})")
    return get_user_by_id(new_id)


def update_user(user_id: int, *, role: Role | None = None, is_active: bool | None = None,
                password: str | None = None) -> dict | None:
    sets: list[str] = []
    vals: list = []
    if role is not None:
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        sets.append("role=?")
        vals.append(role)
    if is_active is not None:
        sets.append("is_active=?")
        vals.append(int(is_active))
    if password is not None:
        if len(password) < 6:
            raise ValueError("password must be at least 6 chars")
        hash_b64, salt_b64 = _hash_password(password)
        sets.append("password_hash=?")
        vals.append(hash_b64)
        sets.append("password_salt=?")
        vals.append(salt_b64)
    if not sets:
        return get_user_by_id(user_id)
    vals.append(user_id)
    with _lock, _conn() as c:
        c.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", vals)
    return get_user_by_id(user_id)


def delete_user(user_id: int) -> bool:
    # Запрет удаления последнего активного админа
    target = get_user_by_id(user_id)
    if not target:
        return False
    if target["role"] == "admin" and target["is_active"]:
        if count_admins() <= 1:
            raise ValueError("cannot delete the last active admin")
    with _lock, _conn() as c:
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
    logger.info(f"user id={user_id} ('{target['username']}') deleted")
    return True


def verify_credentials(username: str, password: str) -> dict | None:
    """Возвращает user dict при успехе, None при ошибке. Обновляет last_login_at."""
    u = get_user_by_username(username)
    if not u or not u["is_active"]:
        return None
    if not _verify_password(password, u["password_hash"], u["password_salt"]):
        return None
    with _lock, _conn() as c:
        c.execute(
            "UPDATE users SET last_login_at=? WHERE id=?",
            (datetime.utcnow().isoformat(), u["id"]),
        )
    return get_user_by_id(u["id"])


# ---------------------------------------------------------------------------
# Settings (overrides)
# ---------------------------------------------------------------------------

# Whitelist: какие ключи можно override-ить через админку
EDITABLE_SETTINGS = {
    "minimax_api_key":         {"label": "MiniMax API Key",        "secret": True},
    "autoai_api_key":          {"label": "AutoAI Router API Key",  "secret": True},
    "autoai_base_url":         {"label": "AutoAI Base URL",        "secret": False},
    "autoai_model":            {"label": "AutoAI Model",           "secret": False},
    "autoai_use":              {"label": "Use AutoAI Router",      "secret": False, "type": "bool"},
    "whisper_server_url":      {"label": "Whisper Server URL",     "secret": False},
    "whisper_use":             {"label": "Use Whisper ASR",        "secret": False, "type": "bool"},
    "web_session_ttl_hours":   {"label": "Web Session TTL (hours)","secret": False, "type": "int"},
    "max_file_size_mb":        {"label": "Max File Size (MB)",     "secret": False, "type": "int"},
    "asr_timeout_sec":         {"label": "ASR Timeout (sec)",      "secret": False, "type": "int"},
    "llm_timeout_sec":         {"label": "LLM Timeout (sec)",      "secret": False, "type": "int"},
    "minimax_base_url":        {"label": "MiniMax Base URL",       "secret": False},
    "minimax_model_default":   {"label": "MiniMax Default Model",  "secret": False},
}


def get_setting(key: str) -> str | None:
    with _conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    if key not in EDITABLE_SETTINGS:
        raise ValueError(f"setting '{key}' is not editable via admin")
    with _lock, _conn() as c:
        c.execute(
            """INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, value, datetime.utcnow().isoformat()),
        )
    logger.info(f"setting '{key}' updated")


def delete_setting(key: str) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM settings WHERE key=?", (key,))
    logger.info(f"setting '{key}' deleted (reverted to .env default)")


def list_settings() -> list[dict]:
    """Возвращает ВСЕ настройки (из .env + overrides) с пометкой override/secret."""
    out = []
    for key, meta in EDITABLE_SETTINGS.items():
        env_val = str(getattr(settings, key, "") or "")
        override = get_setting(key)
        effective = override if override is not None else env_val
        out.append({
            "key": key,
            "label": meta["label"],
            "secret": meta.get("secret", False),
            "type": meta.get("type", "str"),
            "env_value": env_val,
            "override_value": override,
            "effective_value": effective,
            "is_overridden": override is not None,
        })
    return out


def get_effective(key: str) -> str:
    """Читает override, иначе .env значение. Для использования в коде."""
    ov = get_setting(key)
    if ov is not None:
        return ov
    return str(getattr(settings, key, "") or "")


# ---------------------------------------------------------------------------
# Bootstrap: первый запуск → создать admin, пароль в webauth_master.txt
# ---------------------------------------------------------------------------

def bootstrap_admin() -> None:
    """Если users пуст — создаём admin, печатаем пароль в лог + файл webauth_master.txt.

    Безопасно вызывать много раз: идемпотентно (только при пустой таблице).
    """
    init_users_table()
    if count_users() > 0:
        return

    # Генерируем пароль: 16 символов, easy-to-type
    password = secrets.token_urlsafe(12)  # ~16 chars
    username = "admin"
    create_user(username, password, role="admin")

    master_path = settings.storage_dir / "webauth_master.txt"
    try:
        os.chmod(settings.storage_dir, 0o700)
    except Exception:
        pass

    content = (
        f"Meeting-Protocol master admin credentials\n"
        f"==========================================\n"
        f"Username: {username}\n"
        f"Password: {password}\n"
        f"==========================================\n"
        f"Generated: {datetime.utcnow().isoformat()}Z\n"
        f"CHANGE THIS PASSWORD IMMEDIATELY via admin panel.\n"
        f"Delete this file after you memorised the password.\n"
    )
    master_path.write_text(content, encoding="utf-8")
    try:
        os.chmod(master_path, 0o600)
    except Exception:
        pass

    logger.warning("=" * 60)
    logger.warning(f"BOOTSTRAP: created admin user '{username}'")
    logger.warning(f"BOOTSTRAP: password saved to {master_path}")
    logger.warning(f"BOOTSTRAP: please change password via admin panel and delete the file")
    logger.warning("=" * 60)


# ---------------------------------------------------------------------------
# Migration: импорт .env WEB_USERNAME/WEB_PASSWORD в БД (если ещё нет)
# ---------------------------------------------------------------------------

def migrate_from_env() -> None:
    """Если в .env заданы WEB_USERNAME/WEB_PASSWORD, создаём в БД пользователя
    с этими кредами и role=admin (если его ещё нет по username).

    Раньше early-exit'ил при count_users() > 0, что ломало аутентификацию,
    когда в БД уже были user'ы (test/admin1), а env-юзера (gluman) не было:
    login через env-fallback давал JWT, но /web/check → get_user_by_username(env_user)
    → None → 401 → бесконечный редирект на /.

    Теперь мигрируем только если в БД нет пользователя с таким username
    (не трогаем существующих — даже если их много)."""
    env_user = getattr(settings, "web_username", "") or ""
    env_pass = getattr(settings, "web_password", "") or ""
    if not env_user or not env_pass:
        return
    # Уже есть в БД? — ничего не делаем (мог быть создан вручную или мигрирован ранее)
    if get_user_by_username(env_user):
        return
    try:
        create_user(env_user, env_pass, role="admin")
        logger.info(f"migrated WEB_USERNAME='{env_user}' from .env into users DB")
    except ValueError:
        # admin уже есть, ничего
        pass
