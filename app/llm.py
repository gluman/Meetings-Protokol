"""LLM — генерация структурированного JSON-протокола через MiniMax или Ollama."""
import json
import logging
import re
from typing import Literal

import httpx

from .config import settings
from .models import Protocol

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """Ты — ассистент секретаря. Заполняешь протокол встречи по шаблону.

# Входные данные:
- Транскрипция аудиозаписи встречи (может быть длинной, до 100 000 слов).
- Заметки пользователя (контекст, agenda, состав участников).

# Задача:
Верни ТОЛЬКО валидный JSON-объект (без markdown, без пояснений, без ```), строго следующей структуры:

{
  "date": "ДД.ММ.ГГГГ" или "",
  "time_start": "ЧЧ:ММ" или "",
  "participants": "ФИО1 (роль)\\nФИО2 (роль)\\n..." (простой текст, по ФИО),
  "agenda": "общая тема/повестка одним-двумя предложениями",
  "questions": [
    {"q_number": 1, "q_title": "...", "q_summary": "краткое содержание"},
    ...
  ],
  "decisions": [
    {"d_number": 1, "d_text": "...", "d_owner": "ФИО", "d_due": "ДД.ММ.ГГГГ"},
    ...
  ],
  "open_questions": [
    {"o_number": 1, "o_text": "...", "o_owner": "ФИО", "o_due": "ДД.ММ.ГГГГ"},
    ...
  ]
}

# Правила:
1. Дата: если в транскрипте звучала — формат ДД.ММ.ГГГГ. Иначе пустая строка.
2. Время начала: формат ЧЧ:ММ. Иначе пустая строка.
3. Участники: список ФИО (если звучали должности — в скобках). Каждый с новой строки через \\n.
4. Повестка: общая тема одним-двумя предложениями.
5. Вопросы: что обсуждали. q_title — название пункта, q_summary — 2-4 предложения.
6. Решения: формулировки, по которым есть явное согласие. d_text в безличной форме, d_owner — ФИО, d_due — ДД.ММ.ГГГГ (если срок не звучал — оставь пустую строку).
7. Открытые вопросы: что НЕ было решено. Формат как у решений.
8. Все поля ВСЕГДА присутствуют (хотя бы пустые [] или "").
9. НЕ ВЫДУМЫВАЙ факты. Если в транскрипте нет — пустая строка.
10. Никакого markdown, никаких ```json, никаких пояснений. Только JSON."""


VIDEO_SYSTEM_PROMPT = """Ты — ассистент секретаря, заполняющий протокол встречи по видеозаписи.

Вход: видеозапись встречи (аудио+видео) + заметки пользователя.
Верни ТОЛЬКО валидный JSON-объект строго по структуре:

{
  "date": "ДД.ММ.ГГГГ" или "",
  "time_start": "ЧЧ:ММ" или "",
  "participants": "ФИО1 (роль)\\nФИО2 (роль)\\n..." (по возможности из подписей/имён в видео),
  "agenda": "общая тема 1-2 предложениями",
  "questions": [...],
  "decisions": [...],
  "open_questions": [...]
}

Правила: НЕ ВЫДУМЫВАЙ факты, все поля присутствуют, формат дат ДД.ММ.ГГГГ, времени ЧЧ:ММ. Только JSON, без markdown."""


def _extract_json(raw: str) -> dict:
    """Извлекает первый валидный JSON-объект из ответа LLM."""
    if isinstance(raw, dict):
        return raw
    s = str(raw)
    i = s.find("{")
    j = s.rfind("}")
    if i == -1 or j == -1:
        raise ValueError(f"No JSON object found in LLM response: {s[:200]}")
    clean = s[i:j+1]
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        fixed = clean.replace("\\n", " ").replace('\\"', '"')
        return json.loads(fixed)


async def generate_protocol_minimax(
    transcript: str,
    prompt: str,
    *,
    model: str | None = None,
    is_video: bool = False,
    video_base64: str | None = None,
) -> Protocol:
    """Генерация протокола через MiniMax (text-only или vision)."""
    if not settings.minimax_api_key:
        raise RuntimeError("MINIMAX_API_KEY не задан")
    use_model = model or settings.minimax_model_default
    sys_prompt = VIDEO_SYSTEM_PROMPT if is_video else SYSTEM_PROMPT
    headers = {
        "Authorization": f"Bearer {settings.minimax_api_key}",
        "Content-Type": "application/json",
    }

    # Формируем content
    if is_video and video_base64:
        # Vision-формат: текст + изображение/видео (M3 принимает image_url с video)
        user_content = [
            {
                "type": "text",
                "text": f"Заметки пользователя: {prompt or '(не предоставлены)'}\n\nТранскрибируй речь участников и заполни структуру протокола.",
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:video/mp4;base64,{video_base64}"},
            },
        ]
    else:
        user_content = (
            f"Заметки пользователя: {prompt or '(не предоставлены)'}\n\n"
            f"Транскрипция встречи:\n\n{transcript[:80000]}"
        )

    payload = {
        "model": use_model,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
        "max_tokens": 16000 if is_video else 8000,
    }
    if is_video:
        payload["thinking"] = {"type": "disabled"}

    url = f"{settings.minimax_base_url}/chat/completions"
    logger.info(f"LLM (MiniMax {use_model}): отправляю запрос")
    async with httpx.AsyncClient(timeout=settings.llm_timeout_sec) as client:
        resp = await client.post(url, headers=headers, json=payload)

    if resp.status_code != 200:
        raise RuntimeError(f"LLM API error {resp.status_code}: {resp.text[:500]}")

    result = resp.json()
    raw = result["choices"][0]["message"]["content"]
    parsed = _extract_json(raw)
    return Protocol.model_validate(parsed)


async def generate_protocol_ollama(
    transcript: str,
    prompt: str,
) -> Protocol:
    """Генерация протокола через локальную Ollama (OpenAI-совместимый endpoint)."""
    url = f"{settings.ollama_base_url}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Заметки пользователя: {prompt or '(не предоставлены)'}\n\n"
                    f"Транскрипция:\n\n{transcript[:60000]}"
                ),
            },
        ],
        "temperature": 0.2,
        "stream": False,
    }
    logger.info(f"LLM (Ollama {settings.ollama_model}): отправляю запрос")
    async with httpx.AsyncClient(timeout=settings.llm_timeout_sec) as client:
        resp = await client.post(url, headers=headers, json=payload)

    if resp.status_code != 200:
        raise RuntimeError(f"Ollama API error {resp.status_code}: {resp.text[:500]}")

    result = resp.json()
    raw = result["choices"][0]["message"]["content"]
    parsed = _extract_json(raw)
    return Protocol.model_validate(parsed)


async def generate_protocol(
    transcript: str,
    prompt: str,
    *,
    model: Literal["m3", "minimax", "ollama"] = "minimax",
    is_video: bool = False,
    video_base64: str | None = None,
) -> tuple[Protocol, str]:
    """Универсальный диспетчер: выбирает провайдера по `model`."""
    if model == "ollama":
        protocol = await generate_protocol_ollama(transcript, prompt)
        return protocol, "ollama"
    if model == "m3":
        protocol = await generate_protocol_minimax(
            transcript, prompt, model="MiniMax-M3",
            is_video=is_video, video_base64=video_base64,
        )
        return protocol, "MiniMax-M3"
    # default: minimax
    protocol = await generate_protocol_minimax(
        transcript, prompt, model=settings.minimax_model_default,
        is_video=is_video, video_base64=video_base64,
    )
    return protocol, settings.minimax_model_default
