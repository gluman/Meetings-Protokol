"""ASR — распознавание аудио через AutoAI Router (предпочтительно) или прямой MiniMax.

Видео подаётся напрямую в M3 через vision API (без отдельного ASR).
"""
import logging

import httpx

from .config import settings

logger = logging.getLogger(__name__)


def _provider_status() -> str:
    """Какой провайдер активен для ASR. ASR всегда идёт через прямой MiniMax (autoai не поддерживает /audio/transcriptions)."""
    if settings.minimax_api_key:
        return f"minimax-direct[{settings.minimax_base_url}]"
    return "<none — задайте MINIMAX_API_KEY в .env>"


async def transcribe_audio(file_path: str, language: str = "ru") -> str:
    """Отправляет аудиофайл в Whisper-совместимый endpoint и возвращает транскрипт.

    AutoAI роутер (srv-proxy :8080) НЕ поддерживает /audio/transcriptions,
    поэтому ASR всегда идёт через прямой MiniMax API (если задан MINIMAX_API_KEY).

    Args:
        file_path: путь к локальному аудиофайлу
        language: ISO-639-1 код языка (по умолчанию ru)

    Returns:
        строка с транскриптом

    Raises:
        RuntimeError: при ошибке API или отсутствии ключа
    """
    if not settings.minimax_api_key:
        raise RuntimeError(
            "ASR: MINIMAX_API_KEY не задан. AutoAI роутер не поддерживает /audio/transcriptions, "
            "поэтому для ASR обязателен прямой MiniMax ключ. Задайте MINIMAX_API_KEY в .env."
        )

    base_url = settings.minimax_base_url
    api_key = settings.minimax_api_key
    whisper_model = settings.minimax_whisper_model
    provider = "minimax-direct"

    url = f"{base_url}/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}

    with open(file_path, "rb") as f:
        files = {"file": (file_path.split("/")[-1], f, "application/octet-stream")}
        data = {
            "model": whisper_model,
            "response_format": "json",
            "language": language,
        }
        logger.info(f"ASR[{provider}]: отправляю {file_path} в {url}")
        async with httpx.AsyncClient(timeout=settings.asr_timeout_sec) as client:
            resp = await client.post(url, headers=headers, files=files, data=data)

    if resp.status_code != 200:
        raise RuntimeError(f"ASR[{provider}] error {resp.status_code}: {resp.text[:500]}")

    result = resp.json()
    text = result.get("text") or result.get("transcript", "")
    logger.info(f"ASR[{provider}]: получено {len(text)} символов")
    return text
