"""MCP-сервер (Model Context Protocol) поверх SSE.

Предоставляет инструменты:
- transcribe_meeting(file_url, prompt, model)
- get_protocol(job_id)
- list_protocols()
"""
import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from . import storage
from .api import _process_job
from .config import settings

logger = logging.getLogger(__name__)

mcp_router = APIRouter(prefix="/mcp")

# MCP-протокол: JSON-RPC 2.0
SERVER_INFO = {
    "name": "meeting-protocol",
    "version": "1.0.0",
}

TOOLS = [
    {
        "name": "transcribe_meeting",
        "description": (
            "Принимает аудио- или видеофайл встречи, возвращает структурированный "
            "JSON-протокол и DOCX. Поддерживает модели: m3 (MiniMax-M3, "
            "единственная для видео), minimax (MiniMax-M2.7, по умолчанию), ollama (локально)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_url": {
                    "type": "string",
                    "description": "URL файла (http/https) или локальный путь",
                },
                "file_base64": {
                    "type": "string",
                    "description": "Файл в base64 (альтернатива file_url)",
                },
                "file_name": {
                    "type": "string",
                    "description": "Имя файла с расширением (например, meeting.mp4)",
                },
                "prompt": {
                    "type": "string",
                    "description": "Дополнительные заметки к встрече",
                },
                "model": {
                    "type": "string",
                    "enum": ["m3", "minimax", "ollama"],
                    "description": "Модель LLM (по умолчанию minimax)",
                },
            },
        },
    },
    {
        "name": "get_protocol",
        "description": "Получить статус и JSON-протокол по job_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "list_protocols",
        "description": "Список завершённых протоколов (последние 50).",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


async def _tool_transcribe_meeting(arguments: dict) -> dict:
    """Инструмент: скачать файл, поставить в очередь."""
    import httpx
    import base64 as b64

    file_url = arguments.get("file_url")
    file_b64 = arguments.get("file_base64")
    file_name = arguments.get("file_name", "media.mp4")
    prompt = arguments.get("prompt", "")
    model = arguments.get("model", "minimax")

    if not file_url and not file_b64:
        return {"error": "file_url or file_base64 required"}

    # Скачиваем / декодируем
    if file_url:
        if file_url.startswith("http://") or file_url.startswith("https://"):
            async with httpx.AsyncClient(timeout=300) as client:
                r = await client.get(file_url)
            data = r.content
        else:
            # локальный путь
            data = Path(file_url).read_bytes()
    else:
        data = b64.b64decode(file_b64 or "")

    job_id = f"mp-{uuid.uuid4().hex[:12]}"
    file_path = settings.storage_dir / "audio" / f"{job_id}_{file_name}"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(data)

    mime = "video/mp4" if file_name.lower().endswith((".mp4", ".mov", ".webm", ".mkv")) else "audio/mpeg"
    if file_name.lower().endswith((".wav",)):
        mime = "audio/wav"
    elif file_name.lower().endswith((".m4a", ".ogg", ".flac")):
        mime = "audio/" + file_name.split(".")[-1]

    kind = "video" if mime.startswith("video/") else "audio"
    storage.create_job(
        job_id=job_id,
        model_used=model,
        is_video=(kind == "video"),
        file_name=file_name,
        file_path=str(file_path),
    )

    # Запускаем в фоне (не блокируем MCP-вызов)
    asyncio.create_task(_process_job(job_id, file_path, prompt, model, kind))

    return {
        "job_id": job_id,
        "status": "pending",
        "docx_url": f"/api/v1/download/{job_id}.docx",
        "status_url": f"/api/v1/jobs/{job_id}",
        "message": "Обработка запущена. Опросите status_url через несколько секунд.",
    }


async def _tool_get_protocol(arguments: dict) -> dict:
    job = storage.get_job(arguments["job_id"])
    if not job:
        return {"error": "job not found"}
    return job.model_dump(mode="json")


async def _tool_list_protocols(arguments: dict) -> dict:
    return {"protocols": [j.model_dump(mode="json") for j in storage.list_jobs()]}


TOOL_DISPATCH = {
    "transcribe_meeting": _tool_transcribe_meeting,
    "get_protocol": _tool_get_protocol,
    "list_protocols": _tool_list_protocols,
}


@mcp_router.post("/rpc")
async def mcp_rpc(request: Request):
    """JSON-RPC 2.0 endpoint для MCP."""
    body = await request.json()
    method = body.get("method")
    req_id = body.get("id")
    params = body.get("params", {})

    if method == "initialize":
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": SERVER_INFO,
                    "capabilities": {"tools": {}},
                },
            }
        )

    if method == "tools/list":
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": TOOLS},
            }
        )

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        handler = TOOL_DISPATCH.get(tool_name)
        if not handler:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                }
            )
        try:
            result = await handler(arguments)
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                        "isError": False,
                    },
                }
            )
        except Exception as e:
            logger.exception("tool error")
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: {e}"}],
                        "isError": True,
                    },
                }
            )

    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"},
        }
    )


@mcp_router.get("/sse")
async def mcp_sse(request: Request):
    """SSE-транспорт для MCP (для клиентов, которые его поддерживают)."""

    async def event_gen() -> AsyncIterator[dict]:
        # initial endpoint event
        yield {
            "event": "endpoint",
            "data": "/mcp/rpc",
        }
        # keep-alive
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(15)
            yield {"event": "ping", "data": ""}

    return EventSourceResponse(event_gen())


@mcp_router.get("/info")
async def mcp_info():
    """Discovery endpoint: описание MCP-сервера."""
    return {
        "name": SERVER_INFO["name"],
        "version": SERVER_INFO["version"],
        "transport": ["sse", "http-jsonrpc"],
        "sse_url": "/mcp/sse",
        "rpc_url": "/mcp/rpc",
        "tools": TOOLS,
    }
