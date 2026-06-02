"""LLM — генерация структурированного JSON-протокола через AutoAI Router (или прямой MiniMax).

Только одна модель — MiniMax-M3. Поддерживает и аудио (через vision с транскриптом),
и видео (напрямую).
"""
import json
import logging

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
    parsed = _extract_json(raw)
    return Protocol.model_validate(parsed), settings.autoai_model
