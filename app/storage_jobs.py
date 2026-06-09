"""
Storage layer для расширенной работы с jobs: описание, очередь, глоссарии, кандидаты.

Этот модуль добавляет поверх существующего app/storage.py:
  * 5 новых таблиц: glossaries, glossary_entries, glossary_candidates, job_queue, job_glossaries
  * Колонку jobs.description (ALTER TABLE)
  * Утилиты миграции: _column_exists, _add_column (idempotent, безопасно для повторного запуска)
  * Контекстный менеджер _conn с row_factory=sqlite3.Row

Идемпотентность:
    Все CREATE TABLE используют IF NOT EXISTS, все ALTER через _add_column
    (проверяет PRAGMA table_info, добавляет только если колонки нет).
    Это позволяет запускать init_extended() на каждом старте сервиса.

RBAC:
    На уровне storage НЕТ проверки прав — это делают вызывающие модули
    (app/glossaries.py, app/job_queue.py, etc.) на основе user_id.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import settings

# ---------------------------------------------------------------------------
# Lock + connection
# ---------------------------------------------------------------------------
_lock = threading.RLock()

# Кэшируем path, но не коннект (для multi-thread FastAPI каждый вызов открывает
# новую коннекцию — sqlite3 безопасен для этого при check_same_thread=False)
_DB_PATH: Path | None = None


def _db_path() -> Path:
    """Возвращает путь к jobs.db (используя settings.storage_dir)."""
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = settings.storage_dir / "jobs.db"
    return _DB_PATH


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    """
    Контекстный менеджер для sqlite3.Connection.

    Returns:
        sqlite3.Connection с row_factory=sqlite3.Row (чтобы можно было
        обращаться к колонкам по имени, например row['job_id']).

    Использование:
        with _conn() as c:
            row = c.execute("SELECT * FROM jobs WHERE job_id=?", (jid,)).fetchone()
            print(row['status'])
    """
    p = _db_path()
    c = sqlite3.connect(str(p), check_same_thread=False, timeout=30.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()  # default isolation_level="" (deferred) requires explicit commit
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Migration helpers
# ---------------------------------------------------------------------------
def _column_exists(table: str, column: str) -> bool:
    """
    Проверяет, существует ли колонка `column` в таблице `table`.

    Args:
        table: имя таблицы (например 'jobs').
        column: имя колонки (например 'description').

    Returns:
        True если колонка существует, False иначе.
    """
    with _conn() as c:
        rows = c.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _add_column(table: str, column: str, ddl: str) -> bool:
    """
    Добавляет колонку в таблицу, если её ещё нет.

    Args:
        table: имя таблицы.
        column: имя колонки (для проверки существования).
        ddl: полный DDL после имени колонки (например 'TEXT NULL').

    Returns:
        True если колонка была добавлена, False если уже существовала.

    Raises:
        sqlite3.OperationalError: если ALTER TABLE падает по другой причине
            (например, неверный синтаксис DDL).
    """
    if _column_exists(table, column):
        return False
    with _lock, _conn() as c:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    return True


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------
def init_extended() -> None:
    """
    Инициализирует расширенную схему jobs.db.

    Создаёт 5 новых таблиц и добавляет колонку jobs.description.
    Идемпотентно — можно вызывать на каждом старте.

    Таблицы:
        glossaries:
            id INTEGER PK, name TEXT, owner_id INTEGER, is_shared INTEGER (0/1),
            created_at TEXT, updated_at TEXT.
        glossary_entries:
            id INTEGER PK, glossary_id INTEGER (FK→glossaries.id ON DELETE CASCADE),
            term TEXT, definition TEXT, abbreviation TEXT NULL, pronunciation TEXT NULL,
            comment TEXT NULL, needs_review INTEGER (0/1), created_at TEXT.
        glossary_candidates:
            id INTEGER PK, job_id TEXT (FK→jobs.job_id ON DELETE CASCADE),
            term TEXT, context TEXT NULL, suggested_definition TEXT NULL,
            status TEXT (pending/accepted/rejected), created_at TEXT,
            reviewed_at TEXT NULL, reviewed_by INTEGER NULL.
        job_queue:
            id INTEGER PK, job_id TEXT (FK→jobs.job_id ON DELETE CASCADE, UNIQUE),
            position INTEGER, status TEXT (queued/running/done/failed/canceled),
            worker_pid INTEGER NULL, started_at TEXT NULL, finished_at TEXT NULL,
            error TEXT NULL.
        job_glossaries:
            M:N между jobs и glossaries.
            job_id TEXT (FK→jobs.job_id), glossary_id INTEGER (FK→glossaries.id),
            PRIMARY KEY (job_id, glossary_id).

    Колонка:
        jobs.description: TEXT NULL — короткий комментарий пользователя.
    """
    with _lock, _conn() as c:
        # ----- glossaries -----
        c.execute("""
            CREATE TABLE IF NOT EXISTS glossaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                owner_id INTEGER NOT NULL,
                is_shared INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_glossaries_owner
                ON glossaries (owner_id)
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_glossaries_shared
                ON glossaries (is_shared)
        """)

        # ----- glossary_entries -----
        c.execute("""
            CREATE TABLE IF NOT EXISTS glossary_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                glossary_id INTEGER NOT NULL,
                term TEXT NOT NULL,
                definition TEXT NOT NULL,
                abbreviation TEXT,
                pronunciation TEXT,
                comment TEXT,
                needs_review INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (glossary_id) REFERENCES glossaries(id) ON DELETE CASCADE
            )
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_glossary_entries_glossary
                ON glossary_entries (glossary_id)
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_glossary_entries_needs_review
                ON glossary_entries (needs_review)
        """)

        # ----- glossary_candidates -----
        c.execute("""
            CREATE TABLE IF NOT EXISTS glossary_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                term TEXT NOT NULL,
                context TEXT,
                suggested_definition TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewed_by INTEGER,
                FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
            )
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_glossary_candidates_job
                ON glossary_candidates (job_id)
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_glossary_candidates_status
                ON glossary_candidates (status)
        """)

        # ----- job_queue -----
        c.execute("""
            CREATE TABLE IF NOT EXISTS job_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL UNIQUE,
                position INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                worker_pid INTEGER,
                started_at TEXT,
                finished_at TEXT,
                error TEXT,
                FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
            )
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_queue_position
                ON job_queue (position, status)
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_queue_status
                ON job_queue (status)
        """)

        # ----- job_glossaries (M:N) -----
        c.execute("""
            CREATE TABLE IF NOT EXISTS job_glossaries (
                job_id TEXT NOT NULL,
                glossary_id INTEGER NOT NULL,
                PRIMARY KEY (job_id, glossary_id),
                FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE,
                FOREIGN KEY (glossary_id) REFERENCES glossaries(id) ON DELETE CASCADE
            )
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_glossaries_job
                ON job_glossaries (job_id)
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_glossaries_glossary
                ON job_glossaries (glossary_id)
        """)

    # ----- ALTER jobs.description (вне транзакции с CREATE) -----
    _add_column("jobs", "description", "TEXT")


# ---------------------------------------------------------------------------
# Read-only introspection (для отладки и тестов)
# ---------------------------------------------------------------------------
def list_tables() -> list[str]:
    """Возвращает список всех таблиц в jobs.db (для диагностики)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    return [r["name"] for r in rows]


def get_schema() -> dict[str, list[dict]]:
    """
    Возвращает схему jobs.db в виде {table: [{name, type, notnull, default, pk}, ...]}.

    Используется в e2e тестах для проверки миграции.
    """
    schema: dict[str, list[dict]] = {}
    for tbl in list_tables():
        with _conn() as c:
            rows = c.execute(f"PRAGMA table_info({tbl})").fetchall()
        schema[tbl] = [dict(r) for r in rows]
    return schema


# ---------------------------------------------------------------------------
# Jobs view: список заданий с joined data (description, queue position, glossaries)
# ---------------------------------------------------------------------------
def list_jobs_with_meta(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """
    Возвращает список jobs с дополнительными полями:
      - description: TEXT (из ALTER TABLE jobs ADD COLUMN description)
      - queue_position: INT | None — позиция в очереди (1-based) если job в 'queued'
      - queue_status: TEXT | None — 'running' | 'queued' | 'canceled' | None
      - glossary_count: INT — кол-во привязанных глоссариев
      - template_id: TEXT | None — пока не хранится в jobs (NULL), резерв для Шага 3
      - prompt_id: TEXT | None — пока не хранится (NULL), резерв

    Args:
        status: фильтр по status ('completed' | 'running' | 'queued' | 'failed' | 'canceled' | 'draft' | None)
        limit: max кол-во записей
        offset: пропустить первые N (для пагинации)

    Returns:
        list[dict]: каждая запись — один job, плюс мета-поля.
                    None-поля опущены чтобы не раздувать JSON.
    """
    where = ""
    params: list = []
    if status:
        where = "WHERE j.status = ?"
        params.append(status)
    params.extend([limit, offset])

    with _conn() as c:
        rows = c.execute(
            f"""
            SELECT
                j.job_id,
                j.status,
                j.model_used,
                j.is_video,
                j.file_name,
                j.file_path,
                j.created_at,
                j.finished_at,
                j.error,
                j.description,
                jq.position AS queue_position,
                jq.status AS queue_status,
                (
                    SELECT COUNT(*)
                    FROM job_glossaries jg
                    WHERE jg.job_id = j.job_id
                ) AS glossary_count
            FROM jobs j
            LEFT JOIN job_queue jq ON jq.job_id = j.job_id
            {where}
            ORDER BY j.created_at DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params),
        ).fetchall()
    return [dict(r) for r in rows]


def get_job_meta(job_id: str) -> dict | None:
    """
    Возвращает job с joined метаданными (description, queue, glossaries, candidates_count).

    Args:
        job_id: UUID

    Returns:
        dict | None: {job_id, status, ..., description, queue_position, queue_status,
                      glossaries: [{id, name, is_shared}], candidates_count: int}
        None если job не найден.
    """
    with _conn() as c:
        row = c.execute(
            """
            SELECT
                j.job_id,
                j.status,
                j.model_used,
                j.is_video,
                j.file_name,
                j.file_path,
                j.created_at,
                j.finished_at,
                j.error,
                j.protocol_json,
                j.description,
                jq.position AS queue_position,
                jq.status AS queue_status
            FROM jobs j
            LEFT JOIN job_queue jq ON jq.job_id = j.job_id
            WHERE j.job_id = ?
            """,
            (job_id,),
        ).fetchone()
    if not row:
        return None
    out = dict(row)

    # Прикреплённые глоссарии (только id, name, is_shared — для UI)
    # NOTE: открываем новое соединение — `with _conn() as c` уже вышел из scope.
    with _conn() as c2:
        glossaries = c2.execute(
            """
            SELECT g.id, g.name, g.is_shared
            FROM glossaries g
            JOIN job_glossaries jg ON jg.glossary_id = g.id
            WHERE jg.job_id = ?
            ORDER BY g.name
            """,
            (job_id,),
        ).fetchall()
        cand_count = c2.execute(
            "SELECT COUNT(*) AS cnt FROM glossary_candidates WHERE job_id = ?",
            (job_id,),
        ).fetchone()["cnt"]
    out["glossaries"] = [dict(g) for g in glossaries]
    out["candidates_count"] = cand_count
    return out


def update_job_description(job_id: str, description: str) -> bool:
    """
    Обновляет поле description (autosave для примечания). Максимум 2000 символов.

    Returns:
        bool: True если job существует и обновлён, False если job не найден.
    """
    if len(description) > 2000:
        raise ValueError("description too long (max 2000 chars)")
    with _conn() as c:
        cur = c.execute(
            "UPDATE jobs SET description = ? WHERE job_id = ?",
            (description, job_id),
        )
        c.commit()
        return cur.rowcount > 0


def attach_glossary_to_job(job_id: str, glossary_id: int) -> bool:
    """
    Привязывает глоссарий к job (many-to-many через job_glossaries).
    Идемпотентно: повторный attach не дублирует (PRIMARY KEY (job_id, glossary_id)).
    """
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO job_glossaries (job_id, glossary_id) VALUES (?, ?)",
            (job_id, glossary_id),
        )
        c.commit()
    return True


def detach_glossary_from_job(job_id: str, glossary_id: int) -> bool:
    """Отвязывает глоссарий от job."""
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM job_glossaries WHERE job_id = ? AND glossary_id = ?",
            (job_id, glossary_id),
        )
        c.commit()
        return cur.rowcount > 0


def list_job_glossaries(job_id: str) -> list[dict]:
    """Возвращает список глоссариев, привязанных к job."""
    with _conn() as c:
        rows = c.execute(
            """
            SELECT g.id, g.name, g.is_shared
            FROM glossaries g
            JOIN job_glossaries jg ON jg.glossary_id = g.id
            WHERE jg.job_id = ?
            ORDER BY g.name
            """,
            (job_id,),
        ).fetchall()
    return [dict(r) for r in rows]
