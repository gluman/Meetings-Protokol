"""FastAPI entrypoint."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .api import router as api_router
from .config import settings
from .mcp_server import mcp_router
from .prompts_api import router as prompts_router
from . import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init_db()
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

app.include_router(api_router)
app.include_router(mcp_router)
app.include_router(prompts_router)

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
    return FileResponse(STATIC_DIR / "favicon.ico", media_type="image/x-icon")
