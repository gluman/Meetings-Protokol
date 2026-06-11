"""MCP-сервер (Model Context Protocol).

Предоставляет инструменты:
- transcribe_meeting(file_url, prompt) — только M3
- get_protocol(job_id)
- list_protocols()
"""
import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from . import storage
from .api import _process_job
from .auth import require_bearer
from .config import settings

logger = logging.getLogger(__name__)

# Auth НЕ ставим на уровне роутера (чтобы /mcp/info и /mcp/sse были публичными для discovery),
# но tools/call в RPC проверяется вручную
mcp_router = APIRouter(prefix="/mcp")

SERVER_INFO = {
    "name": "meeting-protocol",
    "version": "1.0.0",
}

TOOLS = [
    {
        "name": "transcribe_meeting",
        "description": (
            "Принимает аудио- или видеофайл встречи, возвращает структурированный "
            "JSON-протокол и DOCX. Используется модель MiniMax-M3 "
            "(единственная поддерживаемая — для аудио и видео)."
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


def _check_auth_or_401(authorization: str | None) -> None:
    """Проверка авторизации для MCP tools (если api_key задан)."""
    if not settings.api_key:
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization[7:].strip()
    if token != settings.api_key:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key"
        )


async def _tool_transcribe_meeting(arguments: dict) -> dict:
    """Инструмент: скачать файл, поставить в очередь."""
    import httpx
    import base64 as b64

    file_url = arguments.get("file_url")
    file_b64 = arguments.get("file_base64")
    file_name = arguments.get("file_name", "media.mp4")
    prompt = arguments.get("prompt", "")

    if not file_url and not file_b64:
        return {"error": "file_url or file_base64 required"}

    if file_url:
        if file_url.startswith("http://") or file_url.startswith("https://"):
            async with httpx.AsyncClient(timeout=300) as client:
                r = await client.get(file_url)
            data = r.content
        else:
            data = Path(file_url).read_bytes()
    else:
        data = b64.b64decode(file_b64 or "")

    job_id = f"mp-{uuid.uuid4().hex[:12]}"
    file_path = settings.storage_dir / "audio" / f"{job_id}_{file_name}"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(data)

    mime = "video/mp4" if file_name.lower().endswith((".mp4", ".mov", ".webm", ".mkv")) else "audio/mpeg"
    if file_name.lower().endswith(".wav"):
        mime = "audio/wav"
    elif file_name.lower().endswith((".m4a", ".ogg", ".flac")):
        mime = "audio/" + file_name.split(".")[-1]

    kind = "video" if mime.startswith("video/") else "audio"
    storage.create_job(
        job_id=job_id,
        model_used="m3",
        is_video=(kind == "video"),
        file_name=file_name,
        file_path=str(file_path),
    )
    # Glossary injection: _process_job сам подтянет entries через job_glossaries
    asyncio.create_task(_process_job(job_id, file_path, prompt, kind))

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
    # Auth (если api_key задан)
    auth_header = request.headers.get("authorization")
    _check_auth_or_401(auth_header)

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
            {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
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
    """SSE-транспорт для MCP."""

    async def event_gen() -> AsyncIterator[dict]:
        yield {"event": "endpoint", "data": "/mcp/rpc"}
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(15)
            yield {"event": "ping", "data": ""}

    return EventSourceResponse(event_gen())


@mcp_router.get("/info")
async def mcp_info():
    """Discovery endpoint."""
    return {
        "name": SERVER_INFO["name"],
        "version": SERVER_INFO["version"],
        "transport": ["sse", "http-jsonrpc"],
        "sse_url": "/mcp/sse",
        "rpc_url": "/mcp/rpc",
        "auth": "required" if settings.api_key else "disabled",
        "tools": TOOLS,
    }
