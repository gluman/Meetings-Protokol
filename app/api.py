"""REST API роутеры.

Все эндпоинты публичные (без require_bearer) — для удобства web-интерфейса.
Если в .env задан API_KEY — клиент МОЖЕТ передать Authorization: Bearer *** (валидируется),
если не передан — пускаем (для локальной доверенной сети).
MCP-сервер и prompts_api остаются защищёнными (требуют Bearer).
"""
import base64
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse

from . import storage
from . import storage_templates
from .asr import transcribe_audio
from .config import settings
from .docx import render_protocol_docx
from .llm import generate_protocol
from .models import JobStatus

logger = logging.getLogger(__name__)
# Без глобального require_bearer — web-интерфейс работает без ключа.
# Внешние клиенты могут передавать Authorization: Bearer *** (проверяется опционально).
router = APIRouter(prefix="/api/v1")


# Путь к шаблону протокола (DOCX) — публичный, отдаётся без авторизации
TEMPLATE_PATH = Path(__file__).parent / "static" / "templates" / "protocol_template.docx"


def _detect_kind(mime: str) -> str:
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    return "unknown"


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/info")
async def info():
    """Показывает активный провайдер (autoai/minimax-direct + whisper-server). Без секретов в ответе."""
    from .asr import _provider_status as asr_status
    from .llm import _provider_status as llm_status

    llm_provider, llm_url = llm_status()
    return {
        "asr_provider": asr_status(),
        "llm_provider": llm_provider,
        "llm_url": llm_url,
        "autoai_use": settings.autoai_use,
        "autoai_model": settings.autoai_model,
        "whisper_server_url": settings.whisper_server_url,
        "whisper_use": settings.whisper_use,
        "minimax_whisper_model": settings.minimax_whisper_model,
    }


@router.get("/jobs")
async def list_jobs(limit: int = 50):
    return [j.model_dump(mode="json") for j in storage.list_jobs(limit)]


def _safe_stem(filename: str) -> str:
    """Безопасное имя файла без расширения (для имён DOCX)."""
    from pathlib import PurePosixPath
    stem = PurePosixPath(filename or "protocol").stem
    # убрать опасные символы, оставить unicode (русский и т.п.)
    stem = "".join(c for c in stem if c.isalnum() or c in " _-")
    stem = stem.strip().strip("._-") or "protocol"
    return stem[:80]  # ограничение длины


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = storage.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    data = job.model_dump(mode="json")
    # добавим в ответ docx_url и download_name для удобства фронта
    original = data.get("file_name") or ""
    stem = _safe_stem(original)
    data["docx_url"] = f"/api/v1/download/{job_id}.docx"
    data["download_name"] = f"{stem}.docx"
    return data


@router.get("/download/{filename}")
async def download_file(filename: str):
    """Скачать DOCX.

    Поддерживает два варианта filename:
    1. `{job_id}.docx`     — ищет по job_id, ищет в БД оригинальное имя файла,
                             отдаёт DOCX с Content-Disposition: {stem}.docx
    2. `{stem}.docx`       — прямой путь к файлу в storage/protocols/ (для legacy)
    """
    if "/" in filename or ".." in filename:
        raise HTTPException(400, "invalid filename")

    # Вариант 1: {job_id}.docx
    if filename.startswith("mp-") and filename.endswith(".docx"):
        job_id = filename[:-5]  # strip .docx
        job = storage.get_job(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        original = job.file_name or ""
        stem = _safe_stem(original)
        path = settings.storage_dir / "protocols" / f"{stem}.docx"
        if not path.exists():
            # fallback на job_id-based путь
            path = settings.storage_dir / "protocols" / f"{job_id}.docx"
            if not path.exists():
                raise HTTPException(404, "docx not found")
            return FileResponse(
                path,
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                filename=f"{job_id}.docx",
            )
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=f"{stem}.docx",
        )

    # Вариант 2: legacy прямой путь
    path = settings.storage_dir / "protocols" / filename
    if not path.exists():
        raise HTTPException(404, "file not found")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )


@router.post("/transcribe")
async def transcribe(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    prompt: str = Form(""),
    template_id: str = Form(""),
):
    """Принимает аудио или видео, возвращает job_id, обрабатывает в фоне. Всегда M3.

    template_id: если задан — использовать промпт этого шаблона (приоритет над prompt).
                  если пуст — берётся default template (если есть), иначе fallback на prompt.
    """
    job_id = f"mp-{uuid.uuid4().hex[:12]}"
    mime = (file.content_type or "").lower()
    kind = _detect_kind(mime)
    if kind == "unknown":
        raise HTTPException(
            400, f"Поддерживаются только audio/* и video/*. Получен: {mime}"
        )

    # Сохраняем файл (с прогресс-логом для больших файлов)
    file_path = settings.storage_dir / "audio" / f"{job_id}_{file.filename}"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(
        f"upload start: job={job_id} name={file.filename!r} "
        f"max_mb={settings.max_file_size_mb} timeout_asr={settings.asr_timeout_sec}s"
    )
    chunks = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)  # 1 MB
        if not chunk:
            break
        total += len(chunk)
        chunks.append(chunk)
        if total % (10 * 1024 * 1024) < 1024 * 1024:
            logger.info(f"upload progress: job={job_id} {total // (1024*1024)} MB")
        if total > settings.max_file_size_mb * 1024 * 1024:
            raise HTTPException(413, f"Файл больше {settings.max_file_size_mb} МБ")
    content = b"".join(chunks)
    file_path.write_bytes(content)
    logger.info(f"upload done: job={job_id} size={total // (1024*1024)} MB")

    # === Выбор шаблона и промпта ===
    # Приоритет: явный template_id > default template > встроенный DEFAULT_AUDIO
    effective_template_id = template_id.strip()
    template_prompt = ""
    if not effective_template_id:
        default_t = storage_templates.get_default_template()
        if default_t:
            effective_template_id = default_t["id"]
            template_prompt = default_t.get("prompt", "")
            logger.info(f"transcribe: using default template {effective_template_id}")
    else:
        t = storage_templates.get_template(effective_template_id)
        if not t:
            raise HTTPException(400, f"template {effective_template_id} not found")
        template_prompt = t.get("prompt", "")
        logger.info(f"transcribe: using template {effective_template_id}")

    # Финальный промпт: если есть template — берём его, иначе user-prompt
    # (template — основной, prompt — дополнение/заметки к встрече)
    final_prompt = template_prompt or prompt

    original_name = file.filename or "audio"
    storage.create_job(
        job_id=job_id,
        model_used="m3",
        is_video=(kind == "video"),
        file_name=original_name,
        file_path=str(file_path),
    )
    output_stem = _safe_stem(original_name)
    background_tasks.add_task(
        _process_job, job_id, file_path, final_prompt, kind, output_stem
    )
    return {
        "job_id": job_id,
        "status": "pending",
        "message": "Задача поставлена в очередь. Опрос: GET /api/v1/jobs/{job_id}",
    }


async def _process_job(
    job_id: str,
    file_path: Path,
    prompt: str,
    kind: str,
    output_stem: str,
) -> None:
    """Фоновый пайплайн: ASR → LLM (M3) → DOCX → SQLite."""
    try:
        storage.update_status(job_id, "transcribing")
        is_video = kind == "video"

        video_b64 = None
        transcript = ""
        if is_video:
            # для видео отдаём base64 в M3 vision
            video_b64 = base64.b64encode(file_path.read_bytes()).decode("ascii")
        else:
            transcript = await transcribe_audio(str(file_path), language="ru")
        storage.update_status(job_id, "analyzing")

        protocol, used_model = await generate_protocol(
            transcript=transcript,
            prompt=prompt,
            is_video=is_video,
            video_base64=video_b64,
        )
        storage.save_protocol(job_id, protocol)
        storage.update_status(job_id, "rendering")

        await render_protocol_docx(protocol, job_id, output_name=output_stem)
        # обновим model_used на фактически использованную
        with storage._conn() as c:
            c.execute(
                "UPDATE jobs SET model_used=? WHERE job_id=?",
                (used_model, job_id),
            )
        storage.update_status(job_id, "completed")
        logger.info(f"Job {job_id} done. model={used_model} docx={output_stem}.docx")
    except Exception as e:
        logger.exception(f"Job {job_id} failed")
        storage.update_status(job_id, "failed", error=str(e)[:1000])
    finally:
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass
