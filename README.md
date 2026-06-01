# Meeting Protocol Service
Сервис транскрибации аудио/видео встреч и генерации протокола в DOCX.

## Возможности
- **Web-интерфейс**: чат с загрузкой медиафайла → ответ с DOCX
- **REST API**: `/api/v1/transcribe`, `/api/v1/protocols/{id}`, `/api/v1/download/{id}`
- **MCP-сервер**: `/mcp/sse` — инструменты `transcribe_meeting`, `get_protocol`
- **CLI**: `python -m app.cli transcribe meeting.mp3`

## Стек
- Python 3.12, FastAPI, Uvicorn
- ASR: MiniMax Whisper API (`/v1/audio/transcriptions`)
- LLM: MiniMax (M2.7/M3) через OpenAI-совместимый API
- DOCX: HTML → LibreOffice (`soffice --headless --convert-to docx`)
- MCP: SSE-транспорт

## Запуск
```bash
# 1. установить зависимости
pip3 install --user --break-system-packages -r requirements.txt

# 2. .env
cp .env.example .env
# заполнить MINIMAX_API_KEY

# 3. запустить
python -m app.main
# → http://0.0.0.0:8765
```

## API

### POST /api/v1/transcribe
multipart/form-data: `file` (audio/video), `prompt` (опц.), `model` (опц.: m3/minimax/ollama)

Ответ:
```json
{
  "job_id": "mp-...",
  "status": "completed",
  "model_used": "m3",
  "protocol": { "date": "...", "time_start": "...", "participants": "...", ... },
  "docx_url": "/api/v1/download/mp-...docx"
}
```

### GET /api/v1/download/{filename}
Возвращает .docx файл.

## MCP

Endpoint: `GET /mcp/sse` (Server-Sent Events).
Инструменты:
- `transcribe_meeting(file_url, prompt, model)` — запуск пайплайна
- `get_protocol(job_id)` — получить результат
- `list_protocols()` — список завершённых

## Структура
```
app/
  main.py          — FastAPI + MCP entrypoint
  config.py        — настройки из .env
  asr.py           — ASR (MiniMax Whisper / Ollama Whisper)
  llm.py           — генерация JSON протокола
  docx.py          — HTML → DOCX через soffice
  mcp_server.py    — MCP-сервер (SSE)
  api.py           — REST API роутеры
  models.py        — Pydantic-схемы
  cli.py           — CLI интерфейс
  static/
    index.html     — web-интерфейс
    app.js
    styles.css
storage/
  protocols/       — готовые DOCX
  audio/           — загруженные медиа (временные)
  jobs.db          — SQLite с историей
```
