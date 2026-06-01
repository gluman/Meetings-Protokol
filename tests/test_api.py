"""Smoke-тесты основного API."""
import pytest
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health():
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_root_serves_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "Meeting Protocol" in r.text


def test_mcp_info():
    r = client.get("/mcp/info")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "meeting-protocol"
    # Только transcribe_meeting, get_protocol, list_protocols
    names = {t["name"] for t in data["tools"]}
    assert names == {"transcribe_meeting", "get_protocol", "list_protocols"}


def test_mcp_initialize():
    r = client.post(
        "/mcp/rpc",
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


def test_mcp_tools_list():
    r = client.post(
        "/mcp/rpc",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        },
    )
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    # Убираем выбор модели из схемы
    for t in tools:
        if t["name"] == "transcribe_meeting":
            props = t["inputSchema"]["properties"]
            assert "model" not in props  # модель больше не выбирается


def test_transcribe_no_file():
    """Без файла — ошибка 422 (validation)."""
    r = client.post("/api/v1/transcribe", data={})
    assert r.status_code == 422


def test_transcribe_with_auth_disabled():
    """Без API_KEY в .env — запрос проходит (dev mode), но без MiniMax ключа упадёт на API."""
    r = client.post(
        "/api/v1/transcribe",
        files={"file": ("a.mp3", b"fake", "audio/mpeg")},
    )
    # Без MINIMAX_API_KEY получим 500 (RuntimeError в фоне), с ключом — 400 (битый файл)
    assert r.status_code in (200, 400, 415, 500)
