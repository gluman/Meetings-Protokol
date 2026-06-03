"""Хранилище шаблонов протоколов на SQLite."""
import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .config import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
DB_PATH = settings.storage_dir / "jobs.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_templates_table() -> None:
    with _lock, _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                source_filename TEXT,
                source_format TEXT,
                sections_json TEXT NOT NULL,
                prompt TEXT NOT NULL,
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def create_template(
    template_id: str,
    name: str,
    source_filename: str,
    source_format: str,
    sections: list[dict],
    prompt: str,
) -> dict:
    """Создаёт шаблон. Если шаблонов ещё нет — делает его default."""
    now = datetime.utcnow().isoformat()
    with _lock, _conn() as c:
        # Проверяем, есть ли уже шаблоны
        n = c.execute("SELECT COUNT(*) FROM templates").fetchone()[0]
        is_default = 1 if n == 0 else 0

        c.execute(
            """INSERT INTO templates
               (id, name, source_filename, source_format, sections_json,
                prompt, is_default, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                template_id,
                name,
                source_filename,
                source_format,
                json.dumps(sections, ensure_ascii=False),
                prompt,
                is_default,
                now,
                now,
            ),
        )
    return get_template(template_id)  # type: ignore


def get_template(template_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM templates WHERE id=?", (template_id,)
        ).fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def list_templates() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM templates ORDER BY is_default DESC, created_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_default_template() -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM templates WHERE is_default=1 LIMIT 1"
        ).fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def update_template_prompt(template_id: str, prompt: str) -> dict | None:
    now = datetime.utcnow().isoformat()
    with _lock, _conn() as c:
        c.execute(
            "UPDATE templates SET prompt=?, updated_at=? WHERE id=?",
            (prompt, now, template_id),
        )
    return get_template(template_id)


def set_default_template(template_id: str) -> dict | None:
    now = datetime.utcnow().isoformat()
    with _lock, _conn() as c:
        c.execute("UPDATE templates SET is_default=0, updated_at=?", (now,))
        c.execute(
            "UPDATE templates SET is_default=1, updated_at=? WHERE id=?",
            (now, template_id),
        )
    return get_template(template_id)


def delete_template(template_id: str) -> bool:
    with _lock, _conn() as c:
        cur = c.execute("DELETE FROM templates WHERE id=?", (template_id,))
    return cur.rowcount > 0


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "source_filename": row["source_filename"] or "",
        "source_format": row["source_format"] or "",
        "sections": json.loads(row["sections_json"] or "[]"),
        "prompt": row["prompt"] or "",
        "is_default": bool(row["is_default"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
