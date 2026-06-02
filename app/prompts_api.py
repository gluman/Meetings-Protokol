"""REST API: просмотр и редактирование системных промптов.

GET  /api/v1/prompts           — список промптов + длины
GET  /api/v1/prompts/audio     — текст audio-промпта
GET  /api/v1/prompts/video     — текст video-промпта
PUT  /api/v1/prompts/audio     — заменить audio-промпт (body: {"text": "..."})
PUT  /api/v1/prompts/video     — заменить video-промпт (body: {"text": "..."})
POST /api/v1/prompts/audio/reset — сбросить на дефолт
POST /api/v1/prompts/video/reset — сбросить на дефолт
"""
import logging

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from . import prompts as prompts_lib

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])


class PromptUpdate(BaseModel):
    text: str = Field(..., min_length=1, max_length=50000, description="Текст системного промпта")


@router.get("")
async def list_prompts():
    """Список всех промптов с метаданными."""
    audio = prompts_lib.get_audio_prompt()
    video = prompts_lib.get_video_prompt()
    return {
        "prompts": [
            {
                "name": "audio",
                "description": "Системный промпт для audio-режима (транскрипт → JSON)",
                "length": len(audio),
                "lines": audio.count("\n") + 1,
                "url": "/api/v1/prompts/audio",
            },
            {
                "name": "video",
                "description": "Системный промпт для video-режима (vision → JSON)",
                "length": len(video),
                "lines": video.count("\n") + 1,
                "url": "/api/v1/prompts/video",
            },
        ]
    }


def _get(name: str):
    if name == "audio":
        return prompts_lib.get_audio_prompt()
    if name == "video":
        return prompts_lib.get_video_prompt()
    raise HTTPException(404, f"Unknown prompt: {name}")


def _set(name: str, text: str):
    if name == "audio":
        prompts_lib.set_audio_prompt(text)
    elif name == "video":
        prompts_lib.set_video_prompt(text)
    else:
        raise HTTPException(404, f"Unknown prompt: {name}")


def _reset(name: str):
    if name == "audio":
        prompts_lib.set_audio_prompt(prompts_lib.DEFAULT_AUDIO)
    elif name == "video":
        prompts_lib.set_video_prompt(prompts_lib.DEFAULT_VIDEO)
    else:
        raise HTTPException(404, f"Unknown prompt: {name}")


@router.get("/{name}")
async def get_prompt(name: str):
    """Получить текст промпта по имени (audio | video)."""
    text = _get(name)
    return {"name": name, "text": text, "length": len(text)}


@router.put("/{name}")
async def update_prompt(name: str, body: PromptUpdate):
    """Заменить промпт. Эффект с следующего вызова LLM (текущие job не пересчитываются)."""
    _set(name, body.text)
    logger.info(f"Prompt '{name}' updated, len={len(body.text)}")
    return {"name": name, "length": len(body.text), "status": "updated"}


@router.post("/{name}/reset")
async def reset_prompt(name: str):
    """Сбросить промпт на дефолтный."""
    _reset(name)
    text = _get(name)
    return {"name": name, "length": len(text), "status": "reset to default"}
