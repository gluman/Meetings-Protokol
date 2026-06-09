"""
REST endpoints для jobs в табличном UI (дополняет app/api.py).

Существующие /api/v1/jobs и /api/v1/jobs/{job_id} в app/api.py — остаются для
обратной совместимости. Здесь — новые endpoints под отдельным префиксом
/api/v1/jobs-view/..., чтобы не пересекаться по path templates:

  GET    /api/v1/jobs-view/                          — список с пагинацией, фильтр status, joined meta
  GET    /api/v1/jobs-view/{job_id}                  — детали с glossaries + candidates count
  PATCH  /api/v1/jobs-view/{job_id}/description      — autosave примечания (max 2000 chars)
  POST   /api/v1/jobs-view/{job_id}/glossaries       — attach glossary (body: {glossary_id: int})
  DELETE /api/v1/jobs-view/{job_id}/glossaries/{glossary_id} — detach
  GET    /api/v1/jobs-view/{job_id}/glossaries       — список привязанных глоссариев
  PATCH  /api/v1/jobs-view/{job_id}/template         — выбор/смена шаблона (id)
  POST   /api/v1/jobs-view/{job_id}/copy             — копия существующего (новый job, parent_job_id)
  POST   /api/v1/jobs-view/{job_id}/regenerate       — пересоздать документ (increment count)
  POST   /api/v1/jobs-view/{job_id}/extract-candidates — запуск LLM-extract терминов
  GET    /api/v1/jobs-view/{job_id}/candidates       — список candidates
  POST   /api/v1/jobs-view/candidates/{cid}/review   — accept/reject candidate

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


# ---------------------------------------------------------------------------
# Template selection (требование: выбор шаблона при создании/восстановлении)
# ---------------------------------------------------------------------------
@router.patch("/{job_id}/template")
def update_job_template_endpoint(
    job_id: str, payload: dict, request: Request
):
    """Выбор/смена шаблона для job.
    Body: {"template_id": int | null}
    Если template_id is null — сбрасывает на дефолт (default.docx).

    Returns:
        200: {"ok": true, "template_id": ..., "template_name": ...}
        404: job или template не найден
    """
    _get_user_id(request)  # noqa: F841
    from . import storage
    from . import storage_templates

    if not storage.get_job(job_id):
        raise HTTPException(404, f"job {job_id} not found")

    tid = (payload or {}).get("template_id", None)
    if tid is None:
        # Сброс на дефолт
        storage_jobs.update_job_template(job_id, None, None)
        return {"ok": True, "template_id": None, "template_name": None}

    # template_id может быть int (legacy templates) или str (новые tpl-...)
    if not isinstance(tid, (int, str)):
        raise HTTPException(400, "template_id must be int or str or null")
    tmpl = storage_templates.get_template(str(tid))
    if not tmpl:
        raise HTTPException(404, f"template {tid} not found")
    # В БД jobs.template_id храним int если int, иначе str (всегда строка для совместимости)
    storage_jobs.update_job_template(job_id, tid, tmpl.get("name"))
    return {"ok": True, "template_id": tid, "template_name": tmpl.get("name")}


# ---------------------------------------------------------------------------
# Copy / Regenerate
# ---------------------------------------------------------------------------
@router.post("/{job_id}/copy", status_code=201)
def copy_job_endpoint(job_id: str, request: Request):
    """
    Создаёт копию существующего job (тот же файл, prompt, template, glossaries).
    Новый job_id, status='draft', parent_job_id=source.

    Используется в UI: кнопка "📋 Скопировать строку".
    """
    _get_user_id(request)  # noqa: F841
    import uuid
    from . import storage

    src = storage_jobs.get_job_meta(job_id)
    if not src:
        raise HTTPException(404, f"job {job_id} not found")

    new_id = f"mp-{uuid.uuid4().hex[:12]}"
    # create_job копирует file_name/file_path/model_used/is_video
    storage.create_job(
        job_id=new_id,
        model_used=src.get("model_used") or "minimax-m3",
        is_video=bool(src.get("is_video")),
        file_name=src.get("file_name") or "",
        file_path=src.get("file_path") or "",
    )
    # копируем meta
    storage_jobs.update_job_template(
        new_id,
        src.get("template_id"),
        src.get("template_name"),
    )
    if src.get("description"):
        storage_jobs.update_job_description(new_id, src["description"])
    storage_jobs.set_parent_job(new_id, job_id)
    # копируем привязки глоссариев
    for g in storage_jobs.list_job_glossaries(job_id):
        storage_jobs.attach_glossary_to_job(new_id, g["id"])

    return {
        "ok": True,
        "new_job_id": new_id,
        "parent_job_id": job_id,
    }


@router.post("/{job_id}/regenerate", status_code=200)
def regenerate_job_endpoint(job_id: str, request: Request):
    """
    Регенерирует документ (с уточнённым глоссарием).
    - НЕ создаёт новый job (тот же job_id).
    - increment regenerate_count.
    - status → 'queued' если был completed/failed (если не queued/running).
    - file_path остаётся (новый DOCX перезапишется).

    Используется в UI: после того как пользователь дополнил глоссарий
    на основе candidates, кнопка "🔄 Пересоздать документ".
    """
    _get_user_id(request)  # noqa: F841
    from . import storage
    from . import job_queue as jq

    job_meta = storage_jobs.get_job_meta(job_id)
    if not job_meta:
        raise HTTPException(404, f"job {job_id} not found")
    status_now = job_meta.get("status")
    if status_now in ("queued", "running"):
        raise HTTPException(409, f"job is {status_now}, cannot regenerate")

    # Сбросить status → pending (worker dequeue → running), increment count
    storage.update_status(job_id, "pending")
    n = storage_jobs.increment_regenerate(job_id)
    try:
        jq.enqueue(job_id)
    except Exception as e:
        # если уже в очереди — игнорируем
        logger.warning(f"regenerate: enqueue failed (may be already in queue): {e}")
    return {"ok": True, "job_id": job_id, "regenerate_count": n}


# ---------------------------------------------------------------------------
# Candidates (LLM-извлечение спорных терминов)
# ---------------------------------------------------------------------------
@router.post("/{job_id}/extract-candidates", status_code=200)
def extract_candidates_endpoint(job_id: str, request: Request):
    """
    Запускает LLM-извлечение спорных/незнакомых терминов из протокола.
    Сохраняет в glossary_candidates со статусом 'pending'.

    Используется:
    - автоматически при завершении job (если candidates_extracted=0)
    - вручную из UI после уточнения глоссария
    """
    _get_user_id(request)  # noqa: F841
    from . import glossary_candidates as cand_mod

    job_meta = storage_jobs.get_job_meta(job_id)
    if not job_meta:
        raise HTTPException(404, f"job {job_id} not found")
    if job_meta.get("status") != "completed":
        raise HTTPException(409, f"job is {job_meta.get('status')}, candidates can only be extracted from completed jobs")

    # Берём protocol_json для extract
    proto = job_meta.get("protocol_json") or ""
    if not proto:
        raise HTTPException(409, "job has no protocol_json to extract from")

    try:
        new_ids = cand_mod.extract_candidates(
            transcript=proto,
            job_id=job_id,
        )
    except Exception as e:
        logger.exception(f"extract_candidates: failed: {e}")
        raise HTTPException(500, f"LLM extract failed: {e}")

    storage_jobs.mark_candidates_extracted(job_id)
    return {"ok": True, "extracted": len(new_ids), "candidate_ids": new_ids}


@router.get("/{job_id}/candidates")
def list_candidates_endpoint(
    job_id: str,
    request: Request,
    status: str | None = Query(default=None, description="pending|accepted|rejected"),
):
    """Список candidates для job."""
    _get_user_id(request)  # noqa: F841
    from . import storage
    if not storage.get_job(job_id):
        raise HTTPException(404, f"job {job_id} not found")
    return {"candidates": storage_jobs.list_job_candidates(job_id, status=status)}


@router.post("/candidates/{candidate_id}/review", status_code=200)
def review_candidate_endpoint(candidate_id: int, payload: dict, request: Request):
    """
    Принять или отклонить candidate.
    Body: {"status": "accepted" | "rejected"}
    """
    _get_user_id(request)  # noqa: F841
    status = (payload or {}).get("status")
    if status not in ("accepted", "rejected"):
        raise HTTPException(400, "status must be 'accepted' or 'rejected'")
    try:
        ok = storage_jobs.review_candidate(candidate_id, status, reviewed_by=_get_user_id(request))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, f"candidate {candidate_id} not found")
    return {"ok": True, "candidate_id": candidate_id, "status": status}


# ---------------------------------------------------------------------------
# Delete job
# ---------------------------------------------------------------------------
@router.delete("/{job_id}", status_code=200)
def delete_job_endpoint(job_id: str, request: Request):
    """Удаляет job (и связанные glossary_candidates, queue, glossaries).

    Используется в UI: кнопка "🗑 Удалить строку".
    """
    _get_user_id(request)  # noqa: F841
    from . import storage
    if not storage.get_job(job_id):
        raise HTTPException(404, f"job {job_id} not found")
    storage.delete_job(job_id)
    return {"ok": True, "job_id": job_id}
