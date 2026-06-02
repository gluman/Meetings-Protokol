"""LLM — генерация структурированного JSON-протокола через AutoAI Router (или прямой MiniMax).

Только одна модель — MiniMax-M3. Поддерживает и аудио (через vision с транскриптом),
и видео (напрямую).
"""
import json
import logging
import re

import httpx

from .config import settings
from .models import Protocol
from .prompts import get_audio_prompt, get_video_prompt

logger = logging.getLogger(__name__)


def _provider_status() -> tuple[str, str]:
    """Возвращает (provider_name, base_url) — какой провайдер сейчас активен.

    Ключ НЕ возвращается — он остаётся в settings.
    """
    if settings.autoai_use and settings.autoai_api_key:
        return "autoai", settings.autoai_base_url
    if settings.minimax_api_key:
        return "minimax-direct", settings.minimax_base_url
    raise RuntimeError(
        "LLM: нет ни AUTOAI_API_KEY, ни MINIMAX_API_KEY. Задайте хотя бы один в .env"
    )


def _extract_json(raw) -> dict:
    """Извлекает первый валидный JSON-объект из ответа LLM.

    Стратегия:
    1. Если ответ уже dict — вернуть как есть.
    2. Убрать markdown-обёртки ```json ... ``` если есть.
    3. Найти первый top-level {...} через balanced-brace scanning
       (с учётом строк и escape) и вернуть его.
    4. Если первый кандидат не парсится, попробовать обрезать по
       правильным границам (для случая, когда LLM вставила {...} внутри строки).
    """
    if isinstance(raw, dict):
        return raw
    s = str(raw).strip()

    # 1) Strip markdown code fences
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)

    # 2) Find FIRST balanced {...} candidate (with string/escape awareness)
    depth = 0
    start = -1
    in_str = False
    esc = False
    end = -1
    for i, ch in enumerate(s):
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    end = i
                    break

    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in LLM response: {s[:300]}")

    candidate = s[start : end + 1]
    # 3) Попробовать распарсить первый кандидат
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e1:
        # 4) Если первый кандидат битый (LLM засунула { в строку),
        # пробуем найти другие top-level блоки тем же сканером
        candidates = []
        depth = 0
        start = -1
        in_str = False
        esc = False
        for i, ch in enumerate(s):
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start != -1:
                        candidates.append(s[start : i + 1])
                        start = -1

        last_err = e1
        for cand in candidates:
            try:
                return json.loads(cand)
            except json.JSONDecodeError as e:
                last_err = e
                continue
        # 5) Last resort: голый json.loads всей строки
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
        raise ValueError(
            f"No valid JSON in LLM response. last_err={last_err}. "
            f"first_candidate={candidates[0][:200] if candidates else candidate[:200]}"
        )


async def generate_protocol(
    transcript: str = "",
    prompt: str = "",
    *,
    is_video: bool = False,
    video_base64: str | None = None,
) -> tuple[Protocol, str]:
    """Генерация протокола через MiniMax-M3 (через AutoAI Router или прямой MiniMax).

    Args:
        transcript: транскрипция аудио (для audio-режима)
        prompt: заметки пользователя
        is_video: если True, передаём видео в vision
        video_base64: base64 видеофайла (только для is_video=True)

    Returns:
        (Protocol, model_used_name)
    """
    provider, base_url = _provider_status()
    api_key = settings.autoai_api_key if provider == "autoai" else settings.minimax_api_key

    # Берём промпт из файла (можно редактировать через /api/v1/prompts)
    sys_prompt = get_video_prompt() if is_video else get_audio_prompt()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    if is_video and video_base64:
        user_content = [
            {
                "type": "text",
                "text": (
                    f"Заметки пользователя: {prompt or '(не предоставлены)'}\n\n"
                    "Транскрибируй речь участников и заполни структуру протокола."
                ),
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
        "model": settings.autoai_model,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
        "max_tokens": 16000 if is_video else 8000,
        "thinking": {"type": "disabled"},
    }

    url = f"{base_url}/chat/completions"
    logger.info(f"LLM[{provider}]: отправляю запрос, is_video={is_video}, model={settings.autoai_model}")
    async with httpx.AsyncClient(timeout=settings.llm_timeout_sec) as client:
        resp = await client.post(url, headers=headers, json=payload)

    if resp.status_code != 200:
        raise RuntimeError(f"LLM[{provider}] error {resp.status_code}: {resp.text[:500]}")

    result = resp.json()
    raw = result["choices"][0]["message"]["content"]
    logger.info(f"LLM[raw len={len(str(raw))}]: {str(raw)[:1000]!r}")
    parsed = _extract_json(raw)
    return Protocol.model_validate(parsed), settings.autoai_model
