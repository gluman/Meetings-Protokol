"""ASR — распознавание аудио через локальный whisper.cpp сервер на srv-ai1 (GPU).

Whisper-server принимает multipart upload на /inference, поддерживает ТОЛЬКО WAV.
Поэтому:
1. Если файл не WAV — конвертируем в WAV через ffmpeg (16kHz mono).
2. Если файл длиннее ~90 сек (audio-ctx 1500 * stride) — режем на чанки по 60 сек
   и склеиваем результаты (whisper base имеет лимит ~30 сек на один pass, чанки
   длиннее деградируют).

При недоступности whisper-server (timeout, connection refused) — падаем с RuntimeError.
"""
import asyncio
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

from .config import settings

logger = logging.getLogger(__name__)


def _provider_status() -> str:
    """Какой провайдер активен для ASR."""
    if settings.whisper_use and settings.whisper_server_url:
        return f"whisper-server[{settings.whisper_server_url}]"
    return "<none — задайте whisper_use=True в .env>"


def _is_wav(path: str) -> bool:
    return Path(path).suffix.lower() in (".wav", ".wave")


def _to_wav(src: str) -> str:
    """Конвертирует любой аудиоформат в 16kHz mono WAV через ffmpeg.
    Возвращает путь к временному .wav файлу.
    """
    if _is_wav(src):
        return src
    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "ASR: ffmpeg не установлен, а файл не WAV. "
            "Установите ffmpeg: sudo apt install -y ffmpeg"
        )
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-ar", "16000",   # sample rate 16kHz
        "-ac", "1",        # mono
        "-f", "wav",
        tmp,
    ]
    logger.info(f"ASR: конвертирую {src} → {tmp} через ffmpeg")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ASR: ffmpeg failed ({proc.returncode}): {proc.stderr[:500]}"
        )
    return tmp


def _get_duration_sec(wav_path: str) -> float:
    """Длительность WAV файла в секундах (через wave stdlib, ffmpeg-независимо)."""
    import wave
    with wave.open(wav_path, "rb") as w:
        return w.getnframes() / w.getframerate()


def _split_wav(wav_path: str, chunk_sec: int = 60) -> list[str]:
    """Режет WAV на чанки по chunk_sec секунд через ffmpeg. Возвращает список путей."""
    if not shutil.which("ffmpeg"):
        return [wav_path]  # без ffmpeg не можем резать
    duration = _get_duration_sec(wav_path)
    if duration <= chunk_sec + 5:  # +5 сек запас
        return [wav_path]
    tmpdir = tempfile.mkdtemp(prefix="asr_chunks_")
    # Используем ffmpeg segmenter
    pattern = str(Path(tmpdir) / "chunk_%03d.wav")
    cmd = [
        "ffmpeg", "-y", "-i", wav_path,
        "-f", "segment",
        "-segment_time", str(chunk_sec),
        "-ar", "16000", "-ac", "1",
        "-reset_timestamps", "1",
        pattern,
    ]
    logger.info(f"ASR: режу {wav_path} ({duration:.1f}s) на чанки по {chunk_sec}s")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        logger.warning(f"ASR: ffmpeg segmenter failed: {proc.stderr[:200]}")
        return [wav_path]
    chunks = sorted(Path(tmpdir).glob("chunk_*.wav"))
    return [str(c) for c in chunks]


async def _transcribe_one(wav_path: str, language: str) -> str:
    """Отправляет один WAV в whisper-server."""
    url = f"{settings.whisper_server_url}/inference"
    with open(wav_path, "rb") as f:
        files = {"file": (Path(wav_path).name, f, "audio/wav")}
        data = {
            "language": language,
            "response_format": "json",
            "task": "transcribe",
            "temperature": "0.0",
            "temperature_inc": "0.2",
        }
        logger.info(f"ASR[whisper-server]: POST {url} ({Path(wav_path).name})")
        try:
            async with httpx.AsyncClient(timeout=settings.asr_timeout_sec) as client:
                resp = await client.post(url, files=files, data=data)
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise RuntimeError(
                f"ASR: не удалось подключиться к {url}: {e}. "
                f"Проверьте что whisper-server запущен."
            ) from e

    if resp.status_code != 200:
        raise RuntimeError(f"ASR error {resp.status_code}: {resp.text[:500]}")
    return resp.json().get("text", "").strip()


async def transcribe_audio(file_path: str, language: str = "ru") -> str:
    """Отправляет аудиофайл в whisper-server и возвращает транскрипт.

    Поддерживает любые форматы (mp3, m4a, ogg, flac, wav) — конвертирует в WAV.
    Длинные файлы (>60 сек) режет на чанки.
    """
    if not settings.whisper_server_url:
        raise RuntimeError("ASR: WHISPER_SERVER_URL не задан в .env")

    # 1. Конвертация в WAV если нужно
    wav_path = await asyncio.get_event_loop().run_in_executor(
        None, _to_wav, file_path
    )
    cleanup_wav = [] if wav_path == file_path else [wav_path]

    try:
        # 2. Чанкинг если длинный
        chunks = await asyncio.get_event_loop().run_in_executor(
            None, _split_wav, wav_path, 60
        )
        if len(chunks) > 1:
            cleanup_wav.extend(chunks)
            logger.info(f"ASR: {len(chunks)} чанков")

        # 3. Распознавание каждого чанка
        parts = []
        for i, chunk in enumerate(chunks):
            logger.info(f"ASR: чанк {i+1}/{len(chunks)} — {Path(chunk).name}")
            text = await _transcribe_one(chunk, language)
            if text:
                parts.append(text)
            else:
                logger.warning(f"ASR: чанк {i+1} вернул пусто")

        full = " ".join(parts).strip()
        logger.info(f"ASR: итог {len(full)} символов из {len(chunks)} чанков")
        return full
    finally:
        # Чистим временные файлы
        for p in cleanup_wav:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass
