"""Smoke-тесты основного API."""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import BASE_DIR
from app.main import app


def _load_api_key_from_env_file() -> str:
    """Читает API_KEY из .env (без pydantic — чтобы не ломать monkeypatch в test_transcribe_with_auth_disabled)."""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


@pytest.fixture
def auth_headers():
    """Заголовок Authorization с API_KEY из .env. Если ключ пуст — заголовок не передаётся (dev-mode)."""
    key = os.environ.get("API_KEY") or _load_api_key_from_env_file()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
def auth_disabled_env(monkeypatch):
    """Временно отключает API_KEY, чтобы приложение работало в dev-mode (без auth)."""
    import app.config as cfg
    import app.auth as auth_mod
    import app.mcp_server as mcp_mod
    import app.api as api_mod

    monkeypatch.delenv("API_KEY", raising=False)
    new_settings = cfg.Settings(_env_file=None)
    # Подменяем settings во всех модулях, которые импортировали его в виде объекта
    cfg.settings = new_settings
    auth_mod.settings = new_settings
    mcp_mod.settings = new_settings
    api_mod.settings = new_settings
    yield
    monkeypatch.undo()
    cfg.settings = cfg.Settings()
    auth_mod.settings = cfg.settings
    mcp_mod.settings = cfg.settings
    api_mod.settings = cfg.settings


client = TestClient(app)


def test_health(auth_headers):
    r = client.get("/api/v1/health", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_root_serves_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "Meeting Protocol" in r.text


def test_mcp_info(auth_headers):
    r = client.get("/mcp/info", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "meeting-protocol"
    names = {t["name"] for t in data["tools"]}
    assert names == {"transcribe_meeting", "get_protocol", "list_protocols"}


def test_mcp_initialize(auth_headers):
    r = client.post(
        "/mcp/rpc",
        headers=auth_headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["result"]["serverInfo"]["name"] == "meeting-protocol"


def test_mcp_tools_list(auth_headers):
    r = client.post(
        "/mcp/rpc",
        headers=auth_headers,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        },
    )
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    for t in tools:
        if t["name"] == "transcribe_meeting":
            props = t["inputSchema"]["properties"]
            assert "model" not in props


def test_transcribe_no_file(auth_headers):
    """Без файла — ошибка 422 (validation)."""
    r = client.post("/api/v1/transcribe", headers=auth_headers, data={})
    assert r.status_code == 422


def test_transcribe_with_auth_disabled(auth_disabled_env):
    """Без API_KEY — запрос проходит (dev mode), но без MiniMax ключа упадёт на API."""
    r = client.post(
        "/api/v1/transcribe",
        files={"file": ("a.mp3", b"fake", "audio/mpeg")},
    )
    assert r.status_code in (200, 400, 415, 500)


def test_info_endpoint(auth_headers):
    """GET /api/v1/info — показывает провайдера, без секретов."""
    r = client.get("/api/v1/info", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert "asr_provider" in data
    assert "llm_provider" in data
    assert "autoai_use" in data
    assert "autoai_model" in data
    # Убедимся, что ключи НЕ утекли в ответ
    body_text = r.text.lower()
    for needle in ["sk-cp", "sk-aut", "bearer", "api_key="]:
        assert needle not in body_text, f"Leaked '{needle}' in info response!"


def test_prompts_list(auth_headers):
    """GET /api/v1/prompts — список промптов."""
    r = client.get("/api/v1/prompts", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    names = [p["name"] for p in data["prompts"]]
    assert names == ["audio", "video"]


def test_prompts_get_audio(auth_headers):
    """GET /api/v1/prompts/audio — текст audio-промпта."""
    r = client.get("/api/v1/prompts/audio", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "audio"
    assert "json" in data["text"].lower()
    assert data["length"] > 100


def test_prompts_get_unknown_404(auth_headers):
    r = client.get("/api/v1/prompts/unknown", headers=auth_headers)
    assert r.status_code == 404


def test_prompts_update_and_reset(auth_headers):
    """PUT → проверить изменение → POST /reset → вернуть дефолт."""
    # Запомнить оригинал
    r = client.get("/api/v1/prompts/video", headers=auth_headers)
    original = r.json()["text"]
    try:
        # Обновить
        new_text = "TEST PROMPT " + str(len(original))
        r = client.put(
            "/api/v1/prompts/video",
            headers=auth_headers,
            json={"text": new_text},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "updated"
        # Проверить
        r = client.get("/api/v1/prompts/video", headers=auth_headers)
        assert r.json()["text"] == new_text
    finally:
        # Восстановить
        r = client.post("/api/v1/prompts/video/reset", headers=auth_headers)
        assert r.status_code == 200
        # Убедиться что вернулся дефолт
        r = client.get("/api/v1/prompts/video", headers=auth_headers)
        assert r.json()["text"] == original
