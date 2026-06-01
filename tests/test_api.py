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
    assert any(t["name"] == "transcribe_meeting" for t in data["tools"])


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
    names = {t["name"] for t in tools}
    assert {"transcribe_meeting", "get_protocol", "list_protocols"} <= names


def test_transcribe_no_file():
    r = client.post("/api/v1/transcribe", data={})
    assert r.status_code == 422  # validation error
