"""Tests for app/job_queue.py — DB-backed FIFO queue + cancel + reap."""

from datetime import datetime, timedelta

import pytest
from app.job_queue import (
    STALE_THRESHOLD_SEC,
    _reindex_positions,
    cancel,
    dequeue,
    enqueue,
    get_queue_entry,
    is_cancel_requested,
    list_queue_state,
    mark_done,
    mark_failed,
    queue_position,
    queue_size,
    reap_stale,
    running_job_id,
)
from app.storage import create_job


@pytest.fixture
def job_ids() -> list[str]:
    """Создаёт 3 тестовых job в БД."""
    ids = []
    for i in range(3):
        jid = f"test-job-{i}"
        create_job(
            jid,
            model_used="test",
            is_video=False,
            file_name=f"f{i}.wav",
            file_path=f"/tmp/f{i}.wav",
        )
        ids.append(jid)
    return ids


def test_enqueue_returns_position(job_ids):
    """enqueue возвращает 1-based position."""
    p1 = enqueue(job_ids[0])
    p2 = enqueue(job_ids[1])
    p3 = enqueue(job_ids[2])
    assert p1 == 1
    assert p2 == 2
    assert p3 == 3


def test_enqueue_duplicate_raises(job_ids):
    """Повторный enqueue → IntegrityError."""
    enqueue(job_ids[0])
    with pytest.raises(Exception):  # sqlite3.IntegrityError
        enqueue(job_ids[0])


def test_enqueue_nonexistent_job():
    """enqueue несуществующего job → ValueError."""
    with pytest.raises(ValueError):
        enqueue("non-existent-job-xyz")


def test_dequeue_fifo(job_ids):
    """FIFO: dequeue берёт в порядке enqueue."""
    enqueue(job_ids[0])
    enqueue(job_ids[1])
    enqueue(job_ids[2])
    d1 = dequeue()
    d2 = dequeue()
    d3 = dequeue()
    assert d1["job_id"] == job_ids[0]
    assert d2["job_id"] == job_ids[1]
    assert d3["job_id"] == job_ids[2]
    assert d3 is None or d3["job_id"] == job_ids[2]


def test_dequeue_empty():
    """Пустая очередь → None."""
    assert dequeue() is None


def test_dequeue_marks_running(job_ids):
    """После dequeue status='running'."""
    enqueue(job_ids[0])
    d = dequeue()
    assert d is not None
    entry = get_queue_entry(job_ids[0])
    assert entry["status"] == "running"
    assert entry["started_at"] is not None


def test_dequeue_reindexes(job_ids):
    """После dequeue остальные позиции сдвигаются 1..N-1."""
    enqueue(job_ids[0])
    enqueue(job_ids[1])
    enqueue(job_ids[2])
    dequeue()
    assert queue_position(job_ids[0]) is None  # running
    assert queue_position(job_ids[1]) == 1
    assert queue_position(job_ids[2]) == 2


def test_mark_done(job_ids):
    """mark_done переводит running → done."""
    enqueue(job_ids[0])
    dequeue()
    assert mark_done(job_ids[0])
    entry = get_queue_entry(job_ids[0])
    assert entry["status"] == "done"


def test_mark_done_not_running(job_ids):
    """mark_done не-running → False."""
    enqueue(job_ids[0])
    # Не вызываем dequeue
    assert not mark_done(job_ids[0])


def test_mark_failed(job_ids):
    """mark_failed пишет error и ставит finished_at."""
    enqueue(job_ids[0])
    dequeue()
    assert mark_failed(job_ids[0], "test error")
    entry = get_queue_entry(job_ids[0])
    assert entry["status"] == "failed"
    assert entry["error"] == "test error"
    assert entry["finished_at"] is not None


def test_mark_failed_queued(job_ids):
    """mark_failed работает и на queued (не только running)."""
    enqueue(job_ids[0])
    assert mark_failed(job_ids[0], "fail before start")
    entry = get_queue_entry(job_ids[0])
    assert entry["status"] == "failed"


def test_cancel_queued(job_ids):
    """cancel queued job → canceled."""
    enqueue(job_ids[0])
    assert cancel(job_ids[0])
    entry = get_queue_entry(job_ids[0])
    assert entry["status"] == "canceled"
    assert entry["finished_at"] is not None


def test_cancel_running(job_ids):
    """cancel running job → canceled."""
    enqueue(job_ids[0])
    dequeue()
    assert cancel(job_ids[0])
    entry = get_queue_entry(job_ids[0])
    assert entry["status"] == "canceled"


def test_cancel_done_returns_false(job_ids):
    """cancel завершённого → False."""
    enqueue(job_ids[0])
    dequeue()
    mark_done(job_ids[0])
    assert not cancel(job_ids[0])


def test_is_cancel_requested(job_ids):
    """is_cancel_requested() возвращает True после cancel."""
    enqueue(job_ids[0])
    dequeue()
    assert not is_cancel_requested(job_ids[0])
    cancel(job_ids[0])
    assert is_cancel_requested(job_ids[0])


def test_reap_stale_marks_old_running_as_failed(job_ids):
    """reap_stale переводит старые running в failed."""
    enqueue(job_ids[0])
    dequeue()
    # Имитируем старую дату started_at
    with pytest.MonkeyPatch.context():
        from app.storage_jobs import _conn

        old_iso = (
            datetime.utcnow() - timedelta(seconds=STALE_THRESHOLD_SEC + 100)
        ).isoformat()
        with _conn() as c:
            c.execute(
                "UPDATE job_queue SET started_at = ? WHERE job_id = ?",
                (old_iso, job_ids[0]),
            )
    reaped = reap_stale()
    assert job_ids[0] in reaped
    entry = get_queue_entry(job_ids[0])
    assert entry["status"] == "failed"


def test_reap_stale_skips_fresh_running(job_ids):
    """reap_stale НЕ трогает свежие running."""
    enqueue(job_ids[0])
    dequeue()
    reaped = reap_stale()
    assert job_ids[0] not in reaped
    entry = get_queue_entry(job_ids[0])
    assert entry["status"] == "running"


def test_queue_position(job_ids):
    """queue_position возвращает 1-based позицию queued."""
    enqueue(job_ids[0])
    enqueue(job_ids[1])
    assert queue_position(job_ids[0]) == 1
    assert queue_position(job_ids[1]) == 2
    dequeue()
    assert queue_position(job_ids[0]) is None
    assert queue_position(job_ids[1]) == 1


def test_queue_size(job_ids):
    """queue_size считает только queued."""
    enqueue(job_ids[0])
    enqueue(job_ids[1])
    dequeue()
    assert queue_size() == 1


def test_running_job_id(job_ids):
    """running_job_id возвращает текущий running."""
    enqueue(job_ids[0])
    dequeue()
    assert running_job_id() == job_ids[0]
    mark_done(job_ids[0])
    assert running_job_id() is None


def test_list_queue_state(job_ids):
    """list_queue_state возвращает running + queued."""
    enqueue(job_ids[0])
    enqueue(job_ids[1])
    dequeue()  # job_ids[0] → running
    state = list_queue_state()
    assert state["running"]["job_id"] == job_ids[0]
    assert len(state["queued"]) == 1
    assert state["queued"][0]["job_id"] == job_ids[1]
    assert state["total_queued"] == 1


def test_reindex_positions_compacts(job_ids):
    """_reindex_positions пересчитывает 1..N без дыр."""
    enqueue(job_ids[0])
    enqueue(job_ids[1])
    enqueue(job_ids[2])
    # Искусственно делаем дыру
    from app.storage_jobs import _conn

    with _conn() as c:
        c.execute("UPDATE job_queue SET position = 99 WHERE job_id = ?", (job_ids[1],))
    _reindex_positions()
    assert queue_position(job_ids[0]) == 1
    assert queue_position(job_ids[1]) == 2
    assert queue_position(job_ids[2]) == 3


def test_get_queue_entry_nonexistent():
    """get_queue_entry для несуществующего → None."""
    assert get_queue_entry("nope") is None
