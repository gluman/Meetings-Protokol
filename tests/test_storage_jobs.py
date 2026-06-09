"""Tests for app/storage_jobs.py — migration + introspection.

Storage инициализируется в conftest.py (autouse fixture).
"""

from app.storage_jobs import (
    _add_column,
    _column_exists,
    get_schema,
    init_extended,
    list_tables,
)


def test_tables_created():
    """5 новых таблиц должны быть созданы."""
    tables = list_tables()
    for t in [
        "glossaries",
        "glossary_entries",
        "glossary_candidates",
        "job_queue",
        "job_glossaries",
    ]:
        assert t in tables, f"Missing table: {t}"


def test_jobs_description_column():
    """ALTER TABLE jobs ADD COLUMN description TEXT."""
    assert _column_exists("jobs", "description") is True


def test_idempotency():
    """Повторный вызов init_extended() не падает."""
    init_extended()
    init_extended()
    # Если упал — тест провалится с исключением


def test_add_column_idempotent():
    """Повторный _add_column не падает и возвращает False."""
    result1 = _add_column("jobs", "description", "TEXT")
    result2 = _add_column("jobs", "description", "TEXT")
    assert result1 is False  # уже был добавлен в fixture
    assert result2 is False  # и второй раз тоже False


def test_glossaries_schema():
    """glossaries содержит все нужные колонки."""
    schema = get_schema()
    cols = {c["name"] for c in schema["glossaries"]}
    assert {"id", "name", "owner_id", "is_shared", "created_at", "updated_at"} <= cols


def test_glossary_entries_schema():
    """glossary_entries содержит comment + needs_review."""
    schema = get_schema()
    cols = {c["name"] for c in schema["glossary_entries"]}
    assert {
        "term",
        "definition",
        "abbreviation",
        "pronunciation",
        "comment",
        "needs_review",
    } <= cols


def test_job_queue_schema():
    """job_queue содержит status, position, worker_pid."""
    schema = get_schema()
    cols = {c["name"] for c in schema["job_queue"]}
    assert {
        "job_id",
        "position",
        "status",
        "worker_pid",
        "started_at",
        "finished_at",
        "error",
    } <= cols


def test_glossary_candidates_schema():
    """glossary_candidates имеет status, reviewed_at, reviewed_by."""
    schema = get_schema()
    cols = {c["name"] for c in schema["glossary_candidates"]}
    assert {
        "term",
        "context",
        "suggested_definition",
        "status",
        "reviewed_at",
        "reviewed_by",
    } <= cols
