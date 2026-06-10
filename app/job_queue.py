"""
Job queue: DB-backed FIFO очередь с serial worker.

Архитектура:
    - Одна очередь на сервис (не per-user).
    - Только ОДИН job выполняется одновременно (serial).
    - Worker — asyncio task, polling БД каждые 0.5с.
    - Cooperative cancel: между шагами пайплайна проверяется is_cancel_requested().
    - Reap stale: jobs в статусе 'running' > 1 час переводятся в 'failed'.

Статусы job_queue:
    queued:     ждёт своей очереди
    running:    сейчас обрабатывается
    done:       успешно завершён
    failed:     ошибка
    canceled:   отменён пользователем или воркером

Таблица: job_queue (id, job_id UNIQUE, position, status, worker_pid,
                   started_at, finished_at, error)
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

from app.storage_jobs import _conn, _lock

logger = logging.getLogger(__name__)

# Порог для reap_stale (секунды)
STALE_THRESHOLD_SEC = 3600  # 1 час

# Интервал polling worker loop
WORKER_POLL_INTERVAL_SEC = 0.5


# ---------------------------------------------------------------------------
# Position management
# ---------------------------------------------------------------------------
def _next_position() -> int:
    """Возвращает следующую позицию в очереди (max + 1, минимум 1)."""
    with _conn() as c:
        row = c.execute(
            "SELECT COALESCE(MAX(position), 0) AS mx FROM job_queue"
        ).fetchone()
    return int(row["mx"]) + 1


def _reindex_positions() -> None:
    """
    Переиндексирует позиции в очереди (1..N) для queued jobs.
    Сортирует по id ASC (auto-increment = порядок enqueue), не по position,
    чтобы не было дыр при ручных правках.
    Вызывается после dequeue чтобы не было дыр.
    """
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT id FROM job_queue WHERE status='queued' ORDER BY id ASC"
        ).fetchall()
        for i, row in enumerate(rows, start=1):
            c.execute("UPDATE job_queue SET position = ? WHERE id = ?", (i, row["id"]))


# ---------------------------------------------------------------------------
# Queue operations
# ---------------------------------------------------------------------------
def enqueue(job_id: str) -> int:
    """
    Добавляет job в очередь.

    Args:
        job_id: str, ID задачи (FK на jobs.job_id).

    Returns:
        int — position в очереди (1 = первый на выполнение).

    Raises:
        ValueError: если job_id не существует в jobs.
        sqlite3.IntegrityError: если job_id уже в очереди.
    """
    with _conn() as c:
        if not c.execute("SELECT 1 FROM jobs WHERE job_id = ?", (job_id,)).fetchone():
            raise ValueError(f"job {job_id} not found")
    pos = _next_position()
    with _lock, _conn() as c:
        c.execute(
            """INSERT INTO job_queue (job_id, position, status)
               VALUES (?, ?, 'queued')""",
            (job_id, pos),
        )
    logger.info(f"queue: enqueued {job_id} at position {pos}")
    return pos


def dequeue() -> dict[str, Any] | None:
    """
    Забирает следующий queued job, переводит в 'running'.

    Returns:
        dict с полями job_id, queue_id, position, started_at (ISO).
        None если очередь пуста.

    Note:
        Вызывается ТОЛЬКО воркером. Если нужно проверить состояние —
        используй list_queue_state().
    """
    with _lock, _conn() as c:
        row = c.execute(
            """SELECT id, job_id, position FROM job_queue
               WHERE status = 'queued'
               ORDER BY position ASC LIMIT 1"""
        ).fetchone()
        if not row:
            return None
        now = datetime.utcnow().isoformat()
        c.execute(
            """UPDATE job_queue
               SET status = 'running', worker_pid = ?, started_at = ?
               WHERE id = ?""",
            (os.getpid(), now, row["id"]),
        )
    _reindex_positions()
    return {
        "job_id": row["job_id"],
        "queue_id": int(row["id"]),
        "position": int(row["position"]),
        "started_at": now,
    }


def mark_done(job_id: str) -> bool:
    """
    Помечает job как успешно завершённый.

    Args:
        job_id: str.

    Returns:
        True если обновлено, False если job не в running.
    """
    now = datetime.utcnow().isoformat()
    with _lock, _conn() as c:
        cur = c.execute(
            """UPDATE job_queue SET status = 'done', finished_at = ?
               WHERE job_id = ? AND status = 'running'""",
            (now, job_id),
        )
    return cur.rowcount > 0


def mark_failed(job_id: str, error: str) -> bool:
    """
    Помечает job как failed с сообщением об ошибке.

    Args:
        job_id: str.
        error: str, описание ошибки.

    Returns:
        True если обновлено.
    """
    now = datetime.utcnow().isoformat()
    with _lock, _conn() as c:
        cur = c.execute(
            """UPDATE job_queue SET status = 'failed', finished_at = ?, error = ?
               WHERE job_id = ? AND status IN ('running', 'queued')""",
            (now, error[:2000], job_id),
        )
    return cur.rowcount > 0


def cancel(job_id: str) -> bool:
    """
    Cooperative cancel: помечает job как 'canceled'.
    Воркер проверяет is_cancel_requested() между шагами пайплайна.

    Args:
        job_id: str.

    Returns:
        True если найден и помечен, False если уже завершён.
    """
    now = datetime.utcnow().isoformat()
    with _lock, _conn() as c:
        cur = c.execute(
            """UPDATE job_queue SET status = 'canceled', finished_at = ?
               WHERE job_id = ? AND status IN ('queued', 'running')""",
            (now, job_id),
        )
    return cur.rowcount > 0


def is_cancel_requested(job_id: str) -> bool:
    """
    Проверяет, был ли job отменён. Вызывается воркером между шагами.

    Args:
        job_id: str.

    Returns:
        True если status='canceled'.
    """
    with _conn() as c:
        row = c.execute(
            "SELECT status FROM job_queue WHERE job_id = ?", (job_id,)
        ).fetchone()
    return bool(row and row["status"] == "canceled")


def reap_stale(threshold_sec: int = STALE_THRESHOLD_SEC) -> list[str]:
    """
    Находит jobs в 'running' > threshold_sec секунд, переводит в 'failed'.

    Args:
        threshold_sec: int, секунд (default 3600 = 1 час).

    Returns:
        list of job_id которые были переведены в failed.
    """
    # Получаем все running и проверяем started_at
    with _conn() as c:
        rows = c.execute(
            """SELECT job_id, started_at FROM job_queue
               WHERE status = 'running' AND started_at IS NOT NULL"""
        ).fetchall()
    reaped: list[str] = []
    for row in rows:
        try:
            started = datetime.fromisoformat(row["started_at"])
            age = (datetime.utcnow() - started).total_seconds()
            if age > threshold_sec:
                if mark_failed(row["job_id"], f"reaped stale job (age={int(age)}s)"):
                    reaped.append(row["job_id"])
                    logger.warning(
                        f"queue: reaped stale job {row['job_id']} (age={int(age)}s)"
                    )
        except (ValueError, TypeError):
            continue
    return reaped


# ---------------------------------------------------------------------------
# Read-only state
# ---------------------------------------------------------------------------
def queue_position(job_id: str) -> int | None:
    """
    Возвращает позицию job в очереди (1 = первый).

    Args:
        job_id: str.

    Returns:
        int — позиция (1-based) или None если job не в очереди или уже done.
    """
    with _conn() as c:
        row = c.execute(
            "SELECT position, status FROM job_queue WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    if not row or row["status"] != "queued":
        return None
    return int(row["position"])


def queue_size() -> int:
    """Возвращает количество jobs в статусе 'queued'."""
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS cnt FROM job_queue WHERE status = 'queued'"
        ).fetchone()
    return int(row["cnt"])


def running_job_id() -> str | None:
    """Возвращает job_id текущего running job или None."""
    with _conn() as c:
        row = c.execute(
            "SELECT job_id FROM job_queue WHERE status = 'running' LIMIT 1"
        ).fetchone()
    return row["job_id"] if row else None


def list_queue_state(limit: int = 50) -> dict[str, Any]:
    """
    Возвращает полное состояние очереди для UI.

    Args:
        limit: int, максимум queued jobs в списке.

    Returns:
        dict {running: {job_id, started_at} | None,
              queued: [{job_id, position, created_at}, ...],
              total_queued: int}
    """
    with _conn() as c:
        running_row = c.execute(
            """SELECT job_id, started_at FROM job_queue
               WHERE status = 'running' LIMIT 1"""
        ).fetchone()
        queued_rows = c.execute(
            """SELECT job_id, position FROM job_queue
               WHERE status = 'queued' ORDER BY position ASC LIMIT ?""",
            (limit,),
        ).fetchall()
        total = c.execute(
            "SELECT COUNT(*) AS cnt FROM job_queue WHERE status = 'queued'"
        ).fetchone()
    return {
        "running": (
            {"job_id": running_row["job_id"], "started_at": running_row["started_at"]}
            if running_row
            else None
        ),
        "queued": [
            {"job_id": r["job_id"], "position": int(r["position"])} for r in queued_rows
        ],
        "total_queued": int(total["cnt"]),
    }


def get_queue_entry(job_id: str) -> dict[str, Any] | None:
    """Возвращает запись из job_queue для job_id или None."""
    with _conn() as c:
        row = c.execute(
            """SELECT job_id, position, status, worker_pid, started_at,
                      finished_at, error
               FROM job_queue WHERE job_id = ?""",
            (job_id,),
        ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------
async def worker_loop(sleep_sec: float = WORKER_POLL_INTERVAL_SEC) -> None:
    """
    Бесконечный asyncio loop, polling БД и запуск jobs.

    Args:
        sleep_sec: интервал между проверками (default 0.5s).

    Note:
        Импортирует _process_job лениво, чтобы избежать циклических импортов
        (main.py импортирует job_queue, job_queue не должен импортировать main).

        _process_job — это существующая функция из app.api (или app.main),
        которая принимает job_id и делает всю обработку (ASR + LLM + DOCX).

        Чтобы этот loop не превратился в busy-wait, reap_stale() вызывается
        каждые 60 секунд.
    """
    try:
        from app.api import _process_job  # type: ignore  # noqa: F401

        _ = _process_job  # imported for worker use; suppress F401
    except ImportError:
        logger.error("worker_loop: cannot import _process_job — worker disabled")
        return

    last_reap = datetime.utcnow()
    logger.info("worker_loop: started, polling every %.1fs", sleep_sec)
    while True:
        try:
            # Периодический reap (каждые 60с)
            now = datetime.utcnow()
            if (now - last_reap).total_seconds() > 60:
                try:
                    reaped = reap_stale()
                    if reaped:
                        logger.info(f"worker_loop: reaped {len(reaped)} stale jobs")
                except Exception as e:
                    logger.warning(f"worker_loop: reap error: {e}")
                last_reap = now

            # Если уже что-то running — ждём
            if running_job_id():
                await asyncio.sleep(sleep_sec)
                continue

            # Берём следующий
            deq = dequeue()
            if not deq:
                await asyncio.sleep(sleep_sec)
                continue

            jid = deq["job_id"]
            logger.info(f"worker_loop: processing {jid}")

            # Запускаем обработку в thread pool, чтобы не блокировать loop
            try:
                await asyncio.to_thread(_process_job_sync_wrapper, jid)
                if not is_cancel_requested(jid):
                    mark_done(jid)
                    logger.info(f"worker_loop: {jid} done")
            except Exception as e:
                logger.exception(f"worker_loop: {jid} failed: {e}")
                if not is_cancel_requested(jid):
                    mark_failed(jid, str(e)[:2000])

        except asyncio.CancelledError:
            logger.info("worker_loop: cancelled, exiting")
            raise
        except Exception as e:
            logger.exception(f"worker_loop: unexpected error: {e}")
            await asyncio.sleep(sleep_sec * 2)


def _process_job_sync_wrapper(job_id: str) -> None:
    """
    Синхронная обёртка вокруг _process_job.
    _process_job в app/api.py — async, поэтому запускаем через asyncio.run.
    Но проще держать sync — воркер вызывает транскрибацию + LLM напрямую.
    """
    import asyncio
    from app.api import _process_job  # type: ignore

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_process_job(job_id))
        finally:
            loop.close()
    except Exception as e:
        logger.exception(f"_process_job_sync_wrapper({job_id}) failed: {e}")
        raise
