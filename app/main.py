"""FastAPI entrypoint."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import router as api_router
from .config import settings
from .mcp_server import mcp_router
from .prompts_api import router as prompts_router
from .templates_api import router as templates_router
from .web_auth import (
    COOKIE_NAME,
    is_session_valid,
    is_web_auth_enabled,
    router as web_auth_router,
)
from .admin_api import router as admin_router
from .api_glossaries import router as api_glossaries_router
from .api_jobs import router as api_jobs_router
from . import storage
from . import storage_templates

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init_db()
    storage_templates.init_templates_table()
    # Bootstrap admin + миграция .env → БД (idempotent)
    from .storage_users import bootstrap_admin, migrate_from_env

    bootstrap_admin()
    migrate_from_env()
    logger.info(f"Service started. Storage: {settings.storage_dir}")
    yield


app = FastAPI(
    title="Meeting Protocol Service",
    description="Транскрибация встреч + генерация DOCX-протокола. Web, REST API, MCP.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def web_auth_middleware(request, call_next):
    """Если web-auth включён, проверяет JWT-куку для web-маршрутов (/, /static, /web/check и т.д.).
    API эндпоинты (/api/v1/*) проходят — у них свой Bearer-ключ, или открытый режим.
    """
    path = request.url.path
    # Защищаем: корень, статику, и /web/check (нужна авторизация)
    # Открытые: /web/login, /web/logout, /api/v1/*, /mcp/*
    needs_auth = path == "/" or path.startswith("/static") or path == "/web/check"
    if is_web_auth_enabled() and needs_auth:
        token = request.cookies.get(COOKIE_NAME)
        if not is_session_valid(token):
            # Для web-страниц — редирект на /web/login (отдаст HTML)
            if path.startswith("/web"):
                return JSONResponse(
                    {"ok": False, "error": "no session"},
                    status_code=401,
                )
            # HTML-страницы и static — отдаём login.html
            login_page = STATIC_DIR / "login.html"
            if login_page.exists():
                return FileResponse(login_page, status_code=200)
            # fallback
            return JSONResponse(
                {"detail": "Unauthorized: see /web/login"},
                status_code=401,
            )
    return await call_next(request)


app.include_router(api_router)
app.include_router(mcp_router)
app.include_router(prompts_router)
app.include_router(templates_router)
app.include_router(web_auth_router)
app.include_router(admin_router)
app.include_router(api_glossaries_router)
app.include_router(api_jobs_router)

# Статические файлы (web UI)
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/v1/template")
async def download_template():
    """Публичная раздача шаблона протокола (DOCX) — без авторизации."""
    template_path = STATIC_DIR / "templates" / "protocol_template.docx"
    if not template_path.exists():
        raise HTTPException(404, "Template not found")
    return FileResponse(
        template_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="protocol_template.docx",
    )


@app.get("/favicon.ico")
async def favicon():
    favicon_path = STATIC_DIR / "favicon.ico"
    if not favicon_path.exists():
        # Без файла — отдать 204 (браузер перестанет повторно запрашивать)
        from fastapi.responses import Response

        return Response(status_code=204)
    return FileResponse(favicon_path, media_type="image/x-icon")
