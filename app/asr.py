"""ASR — распознавание аудио через MiniMax Whisper API.

Видео подаётся напрямую в M3 через LangChain-агента (без отдельного ASR).
"""
import logging
import httpx

from .config import settings

logger = logging.getLogger(__name__)


async def transcribe_audio(file_path: str, language: str = "ru") -> str:
    """
    Отправляет аудиофайл в MiniMax Whisper API и возвращает транскрипт.

    Args:
        file_path: путь к локальному аудиофайлу
        language: ISO-639-1 код языка (по умолчанию ru)

    Returns:
        строка с транскриптом

    Raises:
        RuntimeError: при ошибке API
    """
    if not settings.minimax_api_key:
        raise RuntimeError("MINIMAX_API_KEY не задан в .env")

    url = f"{settings.minimax_base_url}/audio/transcriptions"

    headers = {"Authorization": f"Bearer {settings.minimax_api_key}"}

    with open(file_path, "rb") as f:
        files = {"file": (file_path.split("/")[-1], f, "application/octet-stream")}
        data = {
            "model": settings.minimax_whisper_model,
            "response_format": "json",
            "language": language,
        }
        logger.info(f"ASR: отправляю {file_path} в {url}")
        async with httpx.AsyncClient(timeout=settings.asr_timeout_sec) as client:
            resp = await client.post(url, headers=headers, files=files, data=data)

    if resp.status_code != 200:
        raise RuntimeError(f"ASR API error {resp.status_code}: {resp.text[:500]}")

    result = resp.json()
    text = result.get("text") or result.get("transcript", "")
    logger.info(f"ASR: получено {len(text)} символов")
    return text
