"""
API endpoints для глоссариев, кандидатов и очереди.

Подключается в app/main.py через app.include_router(api_glossaries_router).
Все endpoints возвращают JSON.

Эндпойнты (префикс из include_router prefix="/api/v1"):
  Glossaries:
    POST   /glossaries                  — создать
    GET    /glossaries                  — список (свои + shared)
    GET    /glossaries/{gid}            — детали
    PATCH  /glossaries/{gid}            — обновить имя/is_shared
    DELETE /glossaries/{gid}            — удалить
    POST   /glossaries/{gid}/copy       — deep copy
  Entries:
    POST   /glossaries/{gid}/entries    — добавить entry
    GET    /glossaries/{gid}/entries    — список entries
    PATCH  /glossary-entries/{eid}      — обновить entry
    DELETE /glossary-entries/{eid}      — удалить
    POST   /glossary-entries/{eid}/toggle-needs-review  — toggle
  Candidates:
    GET    /jobs/{jid}/candidates       — список (фильтр ?status=)
    POST   /candidates/{cid}/accept     — accept (+ опц. в глоссарий)
    POST   /candidates/{cid}/reject     — reject
    POST   /candidates/{cid}/edit-accept — accept с правками
  Queue:
    GET    /queue                       — состояние (running + queued)
    POST   /jobs/{jid}/enqueue          — добавить в очередь
    POST   /jobs/{jid}/cancel           — cooperative cancel
    GET    /jobs/{jid}/queue-position   — позиция в очереди

RBAC на уровне storage (app.glossaries/app.job_queue),
auth на уровне Depends(get_current_user) из app.web_auth.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.glossaries import (
    add_entry as gloss_add_entry,
    copy_glossary as gloss_copy,
    create_glossary as gloss_create,
    delete_entry as gloss_delete_entry,
    delete_glossary as gloss_delete,
    get_entry as gloss_get_entry,
    get_glossary as gloss_get,
    list_entries as gloss_list_entries,
    list_glossaries_for_user as gloss_list,
    toggle_needs_review as gloss_toggle_nr,
    update_entry as gloss_update_entry,
    update_glossary as gloss_update,
)
from app.glossary_candidates import (
    accept_candidate as cand_accept,
    edit_and_accept as cand_edit_accept,
    extract_candidates as cand_extract,
    get_candidate as cand_get,
    list_candidates as cand_list,
    reject_candidate as cand_reject,
)
from app.job_queue import (
    cancel as queue_cancel,
    enqueue as queue_enqueue,
    get_queue_entry,
    is_cancel_requested as queue_is_canceled,
    list_queue_state as queue_state,
    queue_position as queue_pos,
)
from app.web_auth import get_current_user_id_optional

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["glossaries"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class GlossaryCreate(BaseModel):
    """Запрос на создание глоссария."""

    name: str = Field(..., min_length=1, max_length=200)
    is_shared: bool = False


class GlossaryUpdate(BaseModel):
    """Запрос на обновление глоссария (любое поле опционально)."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_shared: bool | None = None


class GlossaryCopy(BaseModel):
    """Запрос на deep copy глоссария."""

    new_name: str = Field(..., min_length=1, max_length=200)


class EntryCreate(BaseModel):
    """Запрос на создание entry в глоссарии."""

    term: str = Field(..., min_length=1, max_length=200)
    definition: str = Field(..., min_length=1, max_length=2000)
    abbreviation: str | None = Field(default=None, max_length=100)
    pronunciation: str | None = Field(default=None, max_length=200)
    comment: str | None = Field(default=None, max_length=1000)
    needs_review: bool = False


class EntryUpdate(BaseModel):
    """Запрос на обновление entry."""

    term: str | None = Field(default=None, min_length=1, max_length=200)
    definition: str | None = Field(default=None, min_length=1, max_length=2000)
    abbreviation: str | None = Field(default=None, max_length=100)
    pronunciation: str | None = Field(default=None, max_length=200)
    comment: str | None = Field(default=None, max_length=1000)
    needs_review: bool | None = None


class CandidateAccept(BaseModel):
    """Запрос на accept кандидата (опц. в глоссарий)."""

    glossary_id: int | None = None


class CandidateEditAccept(BaseModel):
    """Запрос на accept с правками."""

    new_term: str = Field(..., min_length=1, max_length=200)
    new_definition: str = Field(..., min_length=1, max_length=2000)
    glossary_id: int


class ExtractRequest(BaseModel):
    """Запрос на извлечение кандидатов из транскрипта."""

    transcript: str = Field(..., min_length=1)
    job_id: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Helper: current user_id (для RBAC)
# ---------------------------------------------------------------------------
def _uid(user_id: int | None) -> int:
    """
    Возвращает user_id или 401 если не авторизован.
    """
    if not user_id:
        raise HTTPException(status_code=401, detail="authentication required")
    return int(user_id)


# ---------------------------------------------------------------------------
# Glossary endpoints
# ---------------------------------------------------------------------------
@router.post("/glossaries", status_code=201)
async def create_glossary_endpoint(
    body: GlossaryCreate,
    user_id: int | None = Depends(get_current_user_id_optional),
) -> dict[str, Any]:
    """Создаёт новый глоссарий.

    Body: {name, is_shared?}
    Returns: {id, name, owner_id, is_shared, created_at, updated_at}
    """
    uid = _uid(user_id)
    gid = gloss_create(name=body.name, owner_id=uid, is_shared=body.is_shared)
    return gloss_get(gid) or {}


@router.get("/glossaries")
async def list_glossaries_endpoint(
    include_shared: bool = Query(default=True),
    user_id: int | None = Depends(get_current_user_id_optional),
) -> list[dict[str, Any]]:
    """Список глоссариев пользователя (свои + опц. shared)."""
    uid = _uid(user_id)
    return gloss_list(uid, include_shared=include_shared)


@router.get("/glossaries/{glossary_id}")
async def get_glossary_endpoint(
    glossary_id: int,
    user_id: int | None = Depends(get_current_user_id_optional),
) -> dict[str, Any]:
    """Детали глоссария по ID."""
    g = gloss_get(glossary_id)
    if not g:
        raise HTTPException(status_code=404, detail="glossary not found")
    return g


@router.patch("/glossaries/{glossary_id}")
async def update_glossary_endpoint(
    glossary_id: int,
    body: GlossaryUpdate,
    user_id: int | None = Depends(get_current_user_id_optional),
) -> dict[str, Any]:
    """Обновляет имя и/или is_shared (owner/admin only)."""
    uid = _uid(user_id)
    ok = gloss_update(
        glossary_id,
        user_id=uid,
        name=body.name,
        is_shared=body.is_shared,
    )
    if not ok:
        raise HTTPException(status_code=403, detail="forbidden or not found")
    return gloss_get(glossary_id) or {}


@router.delete("/glossaries/{glossary_id}", status_code=204)
async def delete_glossary_endpoint(
    glossary_id: int,
    user_id: int | None = Depends(get_current_user_id_optional),
) -> None:
    """Удаляет глоссарий (owner/admin only)."""
    uid = _uid(user_id)
    if not gloss_delete(glossary_id, user_id=uid):
        raise HTTPException(status_code=403, detail="forbidden or not found")


@router.post("/glossaries/{glossary_id}/copy", status_code=201)
async def copy_glossary_endpoint(
    glossary_id: int,
    body: GlossaryCopy,
    user_id: int | None = Depends(get_current_user_id_optional),
) -> dict[str, Any]:
    """Deep copy глоссария (создаёт новый с копией entries)."""
    uid = _uid(user_id)
    try:
        new_id = gloss_copy(glossary_id, new_name=body.new_name, owner_id=uid)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return gloss_get(new_id) or {}


# ---------------------------------------------------------------------------
# Entries endpoints
# ---------------------------------------------------------------------------
@router.post("/glossaries/{glossary_id}/entries", status_code=201)
async def add_entry_endpoint(
    glossary_id: int,
    body: EntryCreate,
    user_id: int | None = Depends(get_current_user_id_optional),
) -> dict[str, Any]:
    """Добавляет entry в глоссарий."""
    _uid(user_id)  # auth check
    try:
        eid = gloss_add_entry(
            glossary_id=glossary_id,
            term=body.term,
            definition=body.definition,
            abbreviation=body.abbreviation,
            pronunciation=body.pronunciation,
            comment=body.comment,
            needs_review=body.needs_review,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return gloss_get_entry(eid) or {}


@router.get("/glossaries/{glossary_id}/entries")
async def list_entries_endpoint(
    glossary_id: int,
    user_id: int | None = Depends(get_current_user_id_optional),
) -> list[dict[str, Any]]:
    """Список entries глоссария (нужен доступ — owner/shared/admin)."""
    uid = _uid(user_id)
    try:
        return gloss_list_entries(glossary_id, user_id=uid)
    except PermissionError:
        raise HTTPException(status_code=403, detail="no access to this glossary")


@router.patch("/glossary-entries/{entry_id}")
async def update_entry_endpoint(
    entry_id: int,
    body: EntryUpdate,
    user_id: int | None = Depends(get_current_user_id_optional),
) -> dict[str, Any]:
    """Обновляет entry."""
    uid = _uid(user_id)
    try:
        ok = gloss_update_entry(
            entry_id,
            user_id=uid,
            term=body.term,
            definition=body.definition,
            abbreviation=body.abbreviation,
            pronunciation=body.pronunciation,
            comment=body.comment,
            needs_review=body.needs_review,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=403, detail="forbidden or not found")
    return gloss_get_entry(entry_id) or {}


@router.delete("/glossary-entries/{entry_id}", status_code=204)
async def delete_entry_endpoint(
    entry_id: int,
    user_id: int | None = Depends(get_current_user_id_optional),
) -> None:
    """Удаляет entry."""
    uid = _uid(user_id)
    if not gloss_delete_entry(entry_id, user_id=uid):
        raise HTTPException(status_code=403, detail="forbidden or not found")


@router.post("/glossary-entries/{entry_id}/toggle-needs-review", status_code=200)
async def toggle_needs_review_endpoint(
    entry_id: int,
    user_id: int | None = Depends(get_current_user_id_optional),
) -> dict[str, Any]:
    """Toggle needs_review флага."""
    uid = _uid(user_id)
    if not gloss_toggle_nr(entry_id, user_id=uid):
        raise HTTPException(status_code=403, detail="forbidden or not found")
    return gloss_get_entry(entry_id) or {}


# ---------------------------------------------------------------------------
# Candidates endpoints
# ---------------------------------------------------------------------------
@router.get("/jobs/{job_id}/candidates")
async def list_candidates_endpoint(
    job_id: str,
    status: str = Query(default="pending", pattern="^(pending|accepted|rejected)$"),
) -> list[dict[str, Any]]:
    """Список кандидатов для job (фильтр по статусу)."""
    return cand_list(job_id, status=status)


@router.get("/candidates/{candidate_id}")
async def get_candidate_endpoint(candidate_id: int) -> dict[str, Any]:
    """Детали кандидата."""
    c = cand_get(candidate_id)
    if not c:
        raise HTTPException(status_code=404, detail="candidate not found")
    return c


@router.post("/candidates/extract", status_code=201)
async def extract_candidates_endpoint(body: ExtractRequest) -> list[int]:
    """Извлечь кандидатов из транскрипта через LLM.

    Body: {transcript, job_id}
    Returns: list of created candidate IDs.
    """
    try:
        return cand_extract(body.transcript, body.job_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")


@router.post("/candidates/{candidate_id}/accept")
async def accept_candidate_endpoint(
    candidate_id: int,
    body: CandidateAccept,
    user_id: int | None = Depends(get_current_user_id_optional),
) -> dict[str, Any]:
    """Accept кандидата (опц. добавляет entry в глоссарий).

    Returns: {entry_id: int, candidate: dict}
    """
    uid = _uid(user_id)
    try:
        entry_id = cand_accept(
            candidate_id, reviewed_by=uid, glossary_id=body.glossary_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"entry_id": entry_id, "candidate": cand_get(candidate_id)}


@router.post("/candidates/{candidate_id}/reject")
async def reject_candidate_endpoint(
    candidate_id: int,
    user_id: int | None = Depends(get_current_user_id_optional),
) -> dict[str, Any]:
    """Reject кандидата."""
    uid = _uid(user_id)
    try:
        ok = cand_reject(candidate_id, reviewed_by=uid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="candidate not found")
    return cand_get(candidate_id) or {}


@router.post("/candidates/{candidate_id}/edit-accept")
async def edit_and_accept_endpoint(
    candidate_id: int,
    body: CandidateEditAccept,
    user_id: int | None = Depends(get_current_user_id_optional),
) -> dict[str, Any]:
    """Accept с правками term/definition."""
    uid = _uid(user_id)
    try:
        entry_id = cand_edit_accept(
            candidate_id,
            reviewed_by=uid,
            new_term=body.new_term,
            new_definition=body.new_definition,
            glossary_id=body.glossary_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"entry_id": entry_id, "candidate": cand_get(candidate_id)}


# ---------------------------------------------------------------------------
# Queue endpoints
# ---------------------------------------------------------------------------
@router.get("/queue")
async def queue_state_endpoint() -> dict[str, Any]:
    """Состояние очереди: running + queued list + total."""
    return queue_state()


@router.post("/jobs/{job_id}/enqueue", status_code=200)
async def enqueue_job_endpoint(job_id: str) -> dict[str, Any]:
    """Добавляет job в очередь.

    Returns: {position, queue_entry}
    """
    try:
        pos = queue_enqueue(job_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"position": pos, "queue_entry": get_queue_entry(job_id)}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job_endpoint(job_id: str) -> dict[str, Any]:
    """Cooperative cancel (помечает canceled, воркер увидит)."""
    ok = queue_cancel(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not found or already finished")
    return {"canceled": True, "queue_entry": get_queue_entry(job_id)}


@router.get("/jobs/{job_id}/queue-position")
async def queue_position_endpoint(job_id: str) -> dict[str, Any]:
    """Позиция job в очереди или статус (running/done/etc)."""
    entry = get_queue_entry(job_id)
    if not entry:
        return {"in_queue": False, "status": "not_in_queue"}
    pos = queue_pos(job_id)
    return {
        "in_queue": pos is not None,
        "position": pos,
        "status": entry["status"],
        "is_canceled": queue_is_canceled(job_id),
    }
