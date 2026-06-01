# API Examples

## Web UI
Откройте в браузере `http://HOST:8765/` и следуйте интерфейсу.

## REST API

### 1. Загрузить файл и запустить обработку
```bash
curl -X POST http://localhost:8765/api/v1/transcribe \
  -F "file=@meeting.mp4" \
  -F "prompt=Встреча команды разработки" \
  -F "model=minimax"
```

Ответ:
```json
{
  "job_id": "mp-abc123def456",
  "status": "pending",
  "message": "Задача поставлена в очередь. Опрос: GET /api/v1/jobs/{job_id}"
}
```

### 2. Опрос статуса
```bash
curl http://localhost:8765/api/v1/jobs/mp-abc123def456
```

Когда `status: "completed"`, в ответе появится `docx_url`.

### 3. Скачать DOCX
```bash
curl -OJ http://localhost:8765/api/v1/download/mp-abc123def456.docx
```

## MCP (Model Context Protocol)

### Discovery
```bash
curl http://localhost:8765/mcp/info
```

### JSON-RPC 2.0
```bash
# initialize
curl -X POST http://localhost:8765/mcp/rpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'

# tools/list
curl -X POST http://localhost:8765/mcp/rpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# tools/call
curl -X POST http://localhost:8765/mcp/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0",
    "id":3,
    "method":"tools/call",
    "params":{
      "name":"transcribe_meeting",
      "arguments":{
        "file_url":"https://example.com/meeting.mp4",
        "prompt":"Встреча 01.06",
        "model":"m3"
      }
    }
  }'
```

### SSE-транспорт (для n8n, Claude Desktop и т.д.)
```
GET /mcp/sse
→ event: endpoint
   data: /mcp/rpc
```

## CLI

```bash
# Обработать файл
python -m app.cli transcribe meeting.mp4 --model m3

# Список
python -m app.cli list
```
