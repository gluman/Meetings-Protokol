"""REST API для шаблонов протоколов.

Эндпоинты:
- GET  /api/v1/templates                — список всех шаблонов
- GET  /api/v1/templates/default        — дефолтный шаблон (или 404)
- POST /api/v1/templates/from-example   — multipart: file, name? → создать шаблон из файла
- GET  /api/v1/templates/{id}           — детали шаблона
- PUT  /api/v1/templates/{id}/prompt    — обновить промпт
- POST /api/v1/templates/{id}/default   — сделать дефолтным
- DELETE /api/v1/templates/{id}         — удалить
"""
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from . import storage_templates
from .config import settings
from .templates import parse_file, generate_prompt

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/templates", tags=["templates"])


class PromptUpdate(BaseModel):
    prompt: str


@router.get("")
async def list_all():
    return {"templates": storage_templates.list_templates()}


@router.get("/default")
async def get_default():
    t = storage_templates.get_default_template()
    if not t:
        raise HTTPException(404, "no default template")
    return t


@router.post("/from-example")
async def create_from_example(
    file: UploadFile = File(...),
    name: str = Form(""),
):
    """Парсит загруженный файл (DOCX/txt/md), генерирует шаблон + промпт."""
    original = file.filename or "example"
    # path traversal
    if "/" in original or ".." in original or "\\" in original:
        raise HTTPException(400, "invalid filename")

    ext = Path(original).suffix.lower()
    if ext not in (".docx", ".txt", ".md", ".markdown"):
        raise HTTPException(400, f"Поддерживаются: .docx, .txt, .md. Получен: {ext}")

    # Сохраняем во временный файл
    tmp_dir = settings.storage_dir / "templates" / "examples"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{uuid.uuid4().hex[:12]}_{original}"
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10 MB max для примера
        raise HTTPException(413, "Файл примера больше 10 МБ")
    tmp_path.write_bytes(content)

    try:
        template = parse_file(tmp_path, original_filename=original)
    except Exception as e:
        logger.exception("parse_file failed")
        raise HTTPException(400, f"Не удалось распарсить: {e}")
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass

    # Если задано имя — переопределяем
    if name.strip():
        template.name = name.strip()[:80]

    template_id = f"tpl-{uuid.uuid4().hex[:10]}"
    result = storage_templates.create_template(
        template_id=template_id,
        name=template.name,
        source_filename=template.source_filename,
        source_format=template.source_format,
        sections=[s if isinstance(s, dict) else s.__dict__ for s in template.sections],
        prompt=template.prompt,
    )
    return result


@router.get("/{template_id}")
async def get_one(template_id: str):
    t = storage_templates.get_template(template_id)
    if not t:
        raise HTTPException(404, "template not found")
    return t


@router.put("/{template_id}/prompt")
async def update_prompt(template_id: str, body: PromptUpdate):
    t = storage_templates.update_template_prompt(template_id, body.prompt)
    if not t:
        raise HTTPException(404, "template not found")
    return t


@router.post("/{template_id}/default")
async def set_default(template_id: str):
    t = storage_templates.set_default_template(template_id)
    if not t:
        raise HTTPException(404, "template not found")
    return t


@router.delete("/{template_id}")
async def delete(template_id: str):
    ok = storage_templates.delete_template(template_id)
    if not ok:
        raise HTTPException(404, "template not found")
    return {"ok": True}
