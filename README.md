# Meeting Protocol Service
Сервис транскрибации аудио/видео встреч и генерации протокола в DOCX.

## Возможности
- **Web-интерфейс** с авторизацией: чат с загрузкой медиафайла → DOCX
- **REST API** с Bearer-авторизацией: `/api/v1/transcribe`, `/api/v1/protocols/{id}`, `/api/v1/download/{id}`
- **MCP-сервер** (JSON-RPC + SSE): инструменты `transcribe_meeting`, `get_protocol`, `list_protocols`
- **CLI**: `python -m app.cli transcribe meeting.mp3`

## Модель
Используется **только MiniMax-M3** — единственная модель, поддерживающая и аудио, и видео.

## Стек
- Python 3.12, FastAPI, Uvicorn
- ASR: MiniMax Whisper API (только для аудио)
- LLM: MiniMax-M3 (vision + text)
- DOCX: HTML → LibreOffice (`soffice --headless --convert-to docx`)
- Auth: Bearer-token (настраивается в .env)

## Установка

```bash
pip3 install --user --break-system-packages -r requirements.txt
cp .env.example .env
# заполнить MINIMAX_API_KEY и API_KEY
```

## Запуск

```bash
# Прямой запуск
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8765

# или через systemd (автозапуск)
systemctl --user enable --now meeting-protocol
```

## Авторизация

После запуска в `.env`:
- `API_KEY=your_secret` — все API и MCP-запросы требуют `Authorization: Bearer your_secret`
- Если `API_KEY` пустой — авторизация отключена (только dev-режим)

## Доступ из интернета

Сервис слушает на `0.0.0.0:8765`. Проброс порта на роутере:
- Внешний 443/8765 → 192.168.0.114:8765
- (или поставить Caddy/nginx для HTTPS)

## API

### POST /api/v1/transcribe
```bash
curl -X POST http://HOST:8765/api/v1/transcribe \
  -H "Authorization: Bearer your_key" \
  -F "file=@meeting.mp4" \
  -F "prompt=Встреча команды"
```

Ответ:
```json
{
  "job_id": "mp-abc123",
  "status": "pending",
  "message": "..."
}
```

### GET /api/v1/jobs/{id}
```json
{
  "job_id": "mp-abc123",
  "status": "completed",
  "model_used": "MiniMax-M3",
  "is_video": true,
  "protocol": {
    "date": "01.06.2026",
    "time_start": "14:00",
    "participants": "...",
    "questions": [...],
    "decisions": [...],
    "open_questions": [...]
  },
  "docx_url": "/api/v1/download/mp-abc123.docx"
}
```

## MCP

```bash
# Discovery
curl http://HOST:8765/mcp/info

# JSON-RPC
curl -X POST http://HOST:8765/mcp/rpc \
  -H "Authorization: Bearer your_key" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'

curl -X POST http://HOST:8765/mcp/rpc \
  -H "Authorization: Bearer your_key" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0","id":2,"method":"tools/call",
    "params":{
      "name":"transcribe_meeting",
      "arguments":{
        "file_url":"https://example.com/meeting.mp4",
        "prompt":"Встреча 01.06"
      }
    }
  }'
```

## CLI

```bash
python -m app.cli transcribe meeting.mp4
python -m app.cli list
```

## Структура
```
app/
  main.py          — FastAPI entrypoint
  config.py        — настройки из .env
  auth.py          — Bearer-аутентификация
  asr.py           — MiniMax Whisper
  llm.py           — MiniMax-M3
  docx.py          — HTML → DOCX
  api.py           — REST API
  mcp_server.py    — MCP (JSON-RPC + SSE)
  cli.py           — CLI
  models.py        — Pydantic
  storage.py       — SQLite история
  static/          — web UI
storage/           — DOCX, аудио, БД
```
