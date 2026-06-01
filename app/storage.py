"""Хранилище статусов задач на SQLite."""
import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .config import settings
from .models import JobStatus, Protocol

logger = logging.getLogger(__name__)

_lock = threading.Lock()
DB_PATH = settings.storage_dir / "jobs.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _lock, _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                model_used TEXT,
                is_video INTEGER NOT NULL DEFAULT 0,
                file_name TEXT,
                file_path TEXT,
                created_at TEXT NOT NULL,
                finished_at TEXT,
                error TEXT,
                protocol_json TEXT
            )
            """
        )


def create_job(
    job_id: str,
    model_used: str,
    is_video: bool,
    file_name: str,
    file_path: str,
) -> None:
    with _lock, _conn() as c:
        c.execute(
            """INSERT INTO jobs
               (job_id, status, model_used, is_video, file_name, file_path, created_at)
               VALUES (?, 'pending', ?, ?, ?, ?, ?)""",
            (
                job_id,
                model_used,
                int(is_video),
                file_name,
                file_path,
                datetime.utcnow().isoformat(),
            ),
        )


def update_status(job_id: str, status: str, error: str | None = None) -> None:
    finished = (
        datetime.utcnow().isoformat()
        if status in ("completed", "failed")
        else None
    )
    with _lock, _conn() as c:
        if finished:
            c.execute(
                "UPDATE jobs SET status=?, error=?, finished_at=? WHERE job_id=?",
                (status, error, finished, job_id),
            )
        else:
            c.execute(
                "UPDATE jobs SET status=?, error=? WHERE job_id=?",
                (status, error, job_id),
            )


def save_protocol(job_id: str, protocol: Protocol) -> None:
    with _lock, _conn() as c:
        c.execute(
            "UPDATE jobs SET protocol_json=? WHERE job_id=?",
            (protocol.model_dump_json(), job_id),
        )


def get_job(job_id: str) -> JobStatus | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM jobs WHERE job_id=?", (job_id,)
        ).fetchone()
    if not row:
        return None
    proto = None
    if row["protocol_json"]:
        try:
            proto = Protocol.model_validate_json(row["protocol_json"])
        except Exception as e:
            logger.warning(f"Failed to parse protocol for {job_id}: {e}")
    return JobStatus(
        job_id=row["job_id"],
        status=row["status"],
        model_used=row["model_used"] or "",
        is_video=bool(row["is_video"]),
        file_name=row["file_name"] or "",
        created_at=datetime.fromisoformat(row["created_at"]),
        finished_at=(
            datetime.fromisoformat(row["finished_at"])
            if row["finished_at"]
            else None
        ),
        error=row["error"],
        protocol=proto,
        docx_url=f"/api/v1/download/{row['job_id']}.docx"
        if row["status"] == "completed"
        else None,
    )


def list_jobs(limit: int = 50) -> list[JobStatus]:
    with _conn() as c:
        rows = c.execute(
            "SELECT job_id FROM jobs WHERE status='completed' ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    jobs: list[JobStatus] = []
    for r in rows:
        j = get_job(r["job_id"])
        if j:
            jobs.append(j)
    return jobs
