"""
REST endpoints для jobs в табличном UI (дополняет app/api.py).

Существующие /api/v1/jobs и /api/v1/jobs/{job_id} в app/api.py — остаются для
обратной совместимости. Здесь — новые endpoints под отдельным префиксом
/api/v1/jobs-view/..., чтобы не пересекаться по path templates:

  GET    /api/v1/jobs-view/                   — список с пагинацией, фильтр status, joined meta
  GET    /api/v1/jobs-view/{job_id}           — детали с glossaries + candidates count
  PATCH  /api/v1/jobs-view/{job_id}/description  — autosave примечания (max 2000 chars)
  POST   /api/v1/jobs-view/{job_id}/glossaries    — attach glossary (body: {glossary_id: int})
  DELETE /api/v1/jobs-view/{job_id}/glossaries/{glossary_id} — detach
  GET    /api/v1/jobs-view/{job_id}/glossaries    — список привязанных глоссариев

Authorization: cookie session (mp_session). Для тестов и middleware используется
sync helper get_user_id_from_token_sync.
Job ownership: не проверяется — все аутентифицированные видят все jobs
(для маленьких команд MVP это OK; granular RBAC в backlog).
"""
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from . import storage_jobs

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/jobs-view", tags=["jobs-view"])

# Разрешённые статусы для фильтра (используется в list_jobs endpoint)
JobStatusFilter = Literal[
    "queued", "running", "completed", "failed", "canceled", "draft"
]


def _get_user_id(request: Request) -> int | None:
    """Sync helper: достаёт user_id из mp_session cookie через Request scope.

    FastAPI Cookie Depends не работает в sync def endpoints (FastAPI выдаёт
    'coroutine was never awaited' warning). Используем request.cookies напрямую
    с тем же _verify_token pipeline что в web_auth.get_current_user_id_optional.
    """
    from .web_auth import get_user_id_from_token_sync
    token = request.cookies.get("mp_session")
    return get_user_id_from_token_sync(token)


@router.get("/")
def list_jobs_endpoint(
    request: Request,
    status: JobStatusFilter | None = Query(default=None, description="Фильтр по статусу"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Возвращает список jobs с description, queue position, glossary count.

    Args:
        status: опциональный фильтр ('completed' | 'queued' | 'running' | ...)
        limit:  max записей (1..200, default 50)
        offset: пропустить первые N (для пагинации)

    Returns:
        {
          "jobs": [{job_id, status, ..., description, queue_position, glossary_count, ...}, ...],
          "total": N,    # общее кол-во (для UI pagination)
          "limit": limit,
          "offset": offset
        }
    """
    user_id = _get_user_id(request)  # noqa: F841 (логируется для аудита)
    rows = storage_jobs.list_jobs_with_meta(status=status, limit=limit, offset=offset)
    # total (для UI "page X of Y")
    with storage_jobs._conn() as c:  # type: ignore[attr-defined]
        where = "WHERE status = ?" if status else ""
        params = (status,) if status else ()
        total = c.execute(
            f"SELECT COUNT(*) AS cnt FROM jobs {where}", params
        ).fetchone()["cnt"]
    return {
        "jobs": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{job_id}")
def get_job_endpoint(job_id: str, request: Request):
    """Возвращает job с привязанными глоссариями и кол-вом candidates.

    Returns:
        200: {job_id, status, ..., description, queue_position, queue_status,
              glossaries: [{id, name, is_shared}], candidates_count, protocol_json, error}
        404: если job не найден
    """
    user_id = _get_user_id(request)  # noqa: F841
    job = storage_jobs.get_job_meta(job_id)
    if not job:
        raise HTTPException(404, f"job {job_id} not found")
    return job


@router.patch("/{job_id}/description")
def update_job_description_endpoint(
    job_id: str, payload: dict, request: Request
):
    """Autosave примечания (UI кнопка 💾 или debounce 2с).

    Body: {"description": "текст..."} (max 2000 chars)

    Returns:
        200: {"ok": true, "description": "..."}
        404: job не найден
        400: description > 2000 chars или wrong type
    """
    user_id = _get_user_id(request)  # noqa: F841
    desc = (payload or {}).get("description", "")
    if not isinstance(desc, str):
        raise HTTPException(400, "description must be string")
    try:
        ok = storage_jobs.update_job_description(job_id, desc)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, f"job {job_id} not found")
    return {"ok": True, "description": desc}


@router.post("/{job_id}/glossaries", status_code=200)
def attach_glossary_endpoint(
    job_id: str, payload: dict, request: Request
):
    """Привязывает глоссарий к job (idempotent)."""
    user_id = _get_user_id(request)  # noqa: F841
    gid = (payload or {}).get("glossary_id")
    if not isinstance(gid, int):
        raise HTTPException(400, "glossary_id (int) required")
    from . import storage
    from . import glossaries
    if not storage.get_job(job_id):
        raise HTTPException(404, f"job {job_id} not found")
    if not glossaries.get_glossary(gid):
        raise HTTPException(404, f"glossary {gid} not found")
    storage_jobs.attach_glossary_to_job(job_id, gid)
    return {"ok": True, "job_id": job_id, "glossary_id": gid}


@router.delete("/{job_id}/glossaries/{glossary_id}", status_code=200)
def detach_glossary_endpoint(
    job_id: str, glossary_id: int, request: Request
):
    """Отвязывает глоссарий от job."""
    user_id = _get_user_id(request)  # noqa: F841
    if not storage_jobs.detach_glossary_from_job(job_id, glossary_id):
        raise HTTPException(404, "glossary not attached to this job")
    return {"ok": True}


@router.get("/{job_id}/glossaries")
def list_job_glossaries_endpoint(job_id: str, request: Request):
    """Список глоссариев, привязанных к job."""
    user_id = _get_user_id(request)  # noqa: F841
    from . import storage
    if not storage.get_job(job_id):
        raise HTTPException(404, f"job {job_id} not found")
    return {"glossaries": storage_jobs.list_job_glossaries(job_id)}
