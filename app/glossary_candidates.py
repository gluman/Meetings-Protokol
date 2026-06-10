"""
Glossary candidates: LLM-извлечение спорных/непонятных терминов из транскрибации.

После успешной транскрибации пайплайн может (опционально) попросить LLM
проанализировать текст и найти термины, которые:
  * могут быть неправильно распознаны ASR
  * имеют неоднозначное написание/произношение
  * являются специфичными для домена (аббревиатуры, имена, продукты)
  * желательно добавить в глоссарий

LLM возвращает JSON {candidates: [{term, context, suggested_definition}]},
который сохраняется в таблицу glossary_candidates со статусом 'pending'.

Пользователь видит их в UI как "Кандидаты на ревью" и может:
  - accept: создать entry в указанном глоссарии
  - reject: пометить как отклонённый
  - edit-accept: принять с правками

Этот модуль — **бизнес-логика + LLM-вызов** поверх storage_jobs.glossary_candidates.
RBAC не применяется на уровне storage (как и в glossaries.py).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

from app.config import settings
from app.glossaries import add_entry
from app.llm import _extract_json, _provider_status
from app.storage_jobs import _conn, _lock

logger = logging.getLogger(__name__)

# Лимит на размер транскрипта для LLM (в символах)
MAX_TRANSCRIPT_CHARS = 20000

# System prompt для LLM: попросить вернуть JSON со списком кандидатов
EXTRACT_PROMPT = """Ты — ассистент для подготовки протокола встречи.

Твоя задача: проанализировать транскрибацию и найти термины, которые
МОГУТ БЫТЬ НЕПРАВИЛЬНО РАСПОЗНАНЫ ASR или требуют уточнения.

Критерии кандидата:
  - Специфичные аббревиатуры (LLM, ASR, CRM, KPI, RAG и т.п.)
  - Имена продуктов, сервисов, компаний
  - Технические термины на английском в русской речи
  - Неоднозначно произносимые слова
  - Узкоспециализированные термины (юридические, медицинские, IT)

Верни СТРОГО JSON без markdown-обёрток:
{
  "candidates": [
    {
      "term": "ASR",
      "context": "фраза из транскрибации, где встретился термин (5-15 слов)",
      "suggested_definition": "краткое определение термина (1 предложение)"
    }
  ]
}

Если спорных терминов нет — верни {"candidates": []}.
Не включай общеупотребительные слова.
Максимум 15 кандидатов.
"""


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------
def _call_llm_extract(transcript: str) -> list[dict[str, str]]:
    """
    Вызывает LLM для извлечения кандидатов.

    Args:
        transcript: текст транскрибации (обрезается до MAX_TRANSCRIPT_CHARS).

    Returns:
        list of {term, context, suggested_definition}. Пустой список если
        LLM не нашла кандидатов или ответ нераспарсился.

    Raises:
        RuntimeError: если LLM провайдер не сконфигурирован.
    """
    provider, base_url = _provider_status()
    api_key = (
        settings.autoai_api_key if provider == "autoai" else settings.minimax_api_key
    )
    M3 = chr(42) * 3
    bearer = "Bearer " + M3 + " "
    headers = {
        "Authorization": bearer + api_key,
        "Content-Type": "application/json",
    }
    truncated = transcript[:MAX_TRANSCRIPT_CHARS]
    payload = {
        "model": settings.autoai_model,
        "messages": [
            {"role": "system", "content": EXTRACT_PROMPT},
            {"role": "user", "content": f"Транскрипция:\n\n{truncated}"},
        ],
        "temperature": 0.1,  # низкая температура для точности
        "max_tokens": 2000,
        "thinking": {"type": "disabled"},
    }
    url = f"{base_url}/chat/completions"
    logger.info(
        f"extract_candidates: вызываю LLM[{provider}], transcript len={len(truncated)}"
    )
    with httpx.Client(timeout=settings.llm_timeout_sec) as client:
        resp = client.post(url, headers=headers, json=payload)
    if resp.status_code != 200:
        raise RuntimeError(
            f"LLM[{provider}] error {resp.status_code}: {resp.text[:500]}"
        )
    result = resp.json()
    raw = result["choices"][0]["message"]["content"]
    logger.info(f"extract_candidates: LLM response len={len(str(raw))}")
    try:
        parsed = _extract_json(raw)
    except ValueError as e:
        logger.warning(f"extract_candidates: не удалось распарсить JSON: {e}")
        return []
    candidates = parsed.get("candidates", [])
    if not isinstance(candidates, list):
        logger.warning(
            f"extract_candidates: 'candidates' не список: {type(candidates)}"
        )
        return []
    # Валидация структуры
    out: list[dict[str, str]] = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        term = str(c.get("term", "")).strip()
        if not term:
            continue
        out.append(
            {
                "term": term[:200],
                "context": str(c.get("context", "")).strip()[:500],
                "suggested_definition": str(c.get("suggested_definition", "")).strip()[
                    :500
                ],
            }
        )
    return out[:15]  # hard cap


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def extract_candidates(transcript: str, job_id: str) -> list[int]:
    """
    Извлекает кандидатов из транскрибации через LLM и сохраняет в БД.

    Args:
        transcript: текст транскрибации.
        job_id: str, ID задачи (FK на jobs.job_id).

    Returns:
        list of int — ID созданных glossary_candidates записей.

    Raises:
        ValueError: если job_id не существует.
        RuntimeError: если LLM вызов провалился.

    Note:
        Вызов синхронный (использует httpx.Client, не AsyncClient).
        Для вызова из async-кода оборачивайте в asyncio.to_thread().
    """
    if not transcript or not transcript.strip():
        return []
    # Проверка что job существует (FK)
    with _conn() as c:
        row = c.execute(
            "SELECT job_id FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
    if not row:
        raise ValueError(f"job {job_id} not found")
    candidates = _call_llm_extract(transcript)
    if not candidates:
        return []
    now = datetime.utcnow().isoformat()
    ids: list[int] = []
    with _lock, _conn() as c:
        for cand in candidates:
            cur = c.execute(
                """INSERT INTO glossary_candidates
                   (job_id, term, context, suggested_definition, status, created_at)
                   VALUES (?, ?, ?, ?, 'pending', ?)""",
                (
                    job_id,
                    cand["term"],
                    cand["context"],
                    cand["suggested_definition"],
                    now,
                ),
            )
            ids.append(int(cur.lastrowid or 0))
    logger.info(f"extract_candidates: job={job_id} → {len(ids)} кандидатов сохранено")
    return ids


def list_candidates(job_id: str, status: str = "pending") -> list[dict[str, Any]]:
    """
    Возвращает кандидатов для задачи, опционально фильтруя по статусу.

    Args:
        job_id: str.
        status: 'pending' / 'accepted' / 'rejected' (default 'pending').

    Returns:
        list of dicts: id, job_id, term, context, suggested_definition,
        status, created_at, reviewed_at, reviewed_by.
    """
    with _conn() as c:
        rows = c.execute(
            """SELECT id, job_id, term, context, suggested_definition, status,
                      created_at, reviewed_at, reviewed_by
               FROM glossary_candidates
               WHERE job_id = ? AND status = ?
               ORDER BY created_at DESC""",
            (job_id, status),
        ).fetchall()
    return [dict(r) for r in rows]


def get_candidate(candidate_id: int) -> dict[str, Any] | None:
    """Возвращает кандидата по ID или None."""
    with _conn() as c:
        row = c.execute(
            """SELECT id, job_id, term, context, suggested_definition, status,
                      created_at, reviewed_at, reviewed_by
               FROM glossary_candidates WHERE id = ?""",
            (candidate_id,),
        ).fetchone()
    return dict(row) if row else None


def accept_candidate(
    candidate_id: int, reviewed_by: int, glossary_id: int | None = None
) -> int:
    """
    Принимает кандидата: помечает status='accepted' и (если указан glossary_id)
    создаёт entry в глоссарии.

    Args:
        candidate_id: int.
        reviewed_by: int, user_id кто принял.
        glossary_id: int | None, ID глоссария для добавления entry.
                     Если None — только помечает как accepted без entry.

    Returns:
        int — ID созданного glossary_entry (если glossary_id указан),
        иначе 0.

    Raises:
        ValueError: если candidate не найден, уже reviewed, или
                    glossary_id не существует.
    """
    cand = get_candidate(candidate_id)
    if not cand:
        raise ValueError(f"candidate {candidate_id} not found")
    if cand["status"] != "pending":
        raise ValueError(f"candidate {candidate_id} already {cand['status']}")
    entry_id = 0
    if glossary_id is not None:
        entry_id = add_entry(
            glossary_id=glossary_id,
            term=cand["term"],
            definition=cand["suggested_definition"] or "(определение не предложено)",
        )
    now = datetime.utcnow().isoformat()
    with _lock, _conn() as c:
        c.execute(
            """UPDATE glossary_candidates
               SET status = 'accepted', reviewed_at = ?, reviewed_by = ?
               WHERE id = ?""",
            (now, reviewed_by, candidate_id),
        )
    return entry_id


def reject_candidate(candidate_id: int, reviewed_by: int) -> bool:
    """
    Отклоняет кандидата.

    Args:
        candidate_id: int.
        reviewed_by: int, user_id.

    Returns:
        True если обновлено, False если не найден или уже reviewed.

    Raises:
        ValueError: если candidate уже reviewed.
    """
    cand = get_candidate(candidate_id)
    if not cand:
        return False
    if cand["status"] != "pending":
        raise ValueError(f"candidate {candidate_id} already {cand['status']}")
    now = datetime.utcnow().isoformat()
    with _lock, _conn() as c:
        c.execute(
            """UPDATE glossary_candidates
               SET status = 'rejected', reviewed_at = ?, reviewed_by = ?
               WHERE id = ?""",
            (now, reviewed_by, candidate_id),
        )
    return True


def edit_and_accept(
    candidate_id: int,
    reviewed_by: int,
    new_term: str,
    new_definition: str,
    glossary_id: int,
) -> int:
    """
    Принимает кандидата с правками term/definition.

    Args:
        candidate_id: int.
        reviewed_by: int, user_id.
        new_term: str, новое имя термина (вместо предложенного LLM).
        new_definition: str, новое определение.
        glossary_id: int, глоссарий для добавления.

    Returns:
        int — ID созданного glossary_entry.

    Raises:
        ValueError: candidate не найден, уже reviewed, или пустые поля.
    """
    new_term = (new_term or "").strip()
    new_definition = (new_definition or "").strip()
    if not new_term or not new_definition:
        raise ValueError("new_term and new_definition are required")
    cand = get_candidate(candidate_id)
    if not cand:
        raise ValueError(f"candidate {candidate_id} not found")
    if cand["status"] != "pending":
        raise ValueError(f"candidate {candidate_id} already {cand['status']}")
    entry_id = add_entry(
        glossary_id=glossary_id,
        term=new_term,
        definition=new_definition,
    )
    now = datetime.utcnow().isoformat()
    with _lock, _conn() as c:
        c.execute(
            """UPDATE glossary_candidates
               SET status = 'accepted', reviewed_at = ?, reviewed_by = ?,
                   suggested_definition = ?
               WHERE id = ?""",
            (now, reviewed_by, new_definition, candidate_id),
        )
    return entry_id
