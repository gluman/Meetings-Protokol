# Meeting-Protocol — Windows Installation Guide

> Полностью автоматическая установка всех зависимостей на Windows 10/11 / Server 2019+ за один запуск `install.bat`.
> Никаких ручных скачиваний, никаких команд вручную.

---

## Что устанавливается

| # | Компонент | Назначение | Источник |
|---|---|---|---|
| 1 | **Python 3.11+** | Backend runtime | winget: `Python.Python.3.12` |
| 2 | **Виртуальное окружение `.venv`** | Изолированные зависимости | `python -m venv` |
| 3 | **Зависимости из `requirements.txt`** | FastAPI, uvicorn, aiosqlite, ... | PyPI |
| 4 | **FFmpeg** | Декодирование mp4/m4a | winget: `Gyan.FFmpeg` |
| 5 | **Ollama** + модель `MiniMax-M3` | Локальный LLM | winget: `Ollama.Ollama` |
| 6 | **whisper.cpp** (CUDA или CPU) — **бинарь, без модели** | Локальный ASR | winget: `ggml-org.whisper.cpp.CUDA` |
| 6a | **Модель ggml-*.bin** — `scripts\download_models.bat` | ASR | [huggingface.co/ggerganov/whisper.cpp](https://huggingface.co/ggerganov/whisper.cpp) |
| 7 | **Caddy** + self-signed cert | HTTPS reverse proxy | winget: `CaddyServer.Caddy` |
| 8 | **NSSM** | Управление Windows-сервисами | winget: `nssm.nssm` |
| 9 | **.env** (с свежим `WEB_SESSION_SECRET`) | Конфиг приложения | из `.env.example` |
| 10 | **Start Menu shortcuts** (5 шт) | Быстрый доступ | `%APPDATA%\...\Start Menu\Programs\Meeting-Protocol` |
| 11 | **Windows Service `MeetingProtocol-Whisper`** | ASR стартует автоматически | NSSM |

---

## Системные требования

| | Минимум | Рекомендуется |
|---|---|---|
| **ОС** | Windows 10 21H2 / Server 2019 | Windows 11 / Server 2022 |
| **RAM** | 8 ГБ | 16 ГБ (для whisper large-v3) |
| **Диск** | 10 ГБ свободно | 15 ГБ (модель large-v3 весит 3.1 ГБ) |
| **GPU** | Не обязательно | NVIDIA с 6+ ГБ VRAM (CUDA-сборка whisper + Ollama) |
| **.NET** | Уже стоит на Win10+ | — |
| **PowerShell** | 5.1 (встроен) | — |
| **Права** | **Администратор** (UAC) | — |
| **Сеть** | Доступ к GitHub, winget, PyPI, huggingface.co | — |

> ⚠️ Если у вас **корпоративный firewall** — возможно, придётся добавить исключения для winget и huggingface.

---

## Запуск установки

### 1. Клонируйте репозиторий

Откройте **cmd от администратора** (Пуск → `cmd` → правой кнопкой → «Запуск от имени администратора»):

```cmd
cd C:\Projects
git clone https://github.com/gluman/Meetings-Protokol.git
cd Meetings-Protokol
```

### 2. Запустите установщик

```cmd
install.bat
```

Скрипт **сам запросит elevation** через UAC, если вы забыли запустить cmd от админа.

### 3. Следите за выводом

```
===============================================================
 Meeting-Protocol — Windows MAX installer
===============================================================

[detect] Checking for NVIDIA GPU...
        GPU: NVIDIA GeForce RTX 3060
Package manager: winget

[1/9] Python 3.11+...
[2/9] Virtual environment .venv ...
[3/9] Python packages from requirements.txt ...
[4/9] FFmpeg (for mp4/m4a input) ...
[5/9] Ollama + MiniMax-M3 model ...
[6/9] whisper.cpp server + ggml-large-v3 model ...
[7/9] Caddy (HTTPS reverse proxy with self-signed fallback) ...
[8/9] NSSM (Windows Service helper) ...
[9/9] .env configuration, Start Menu shortcuts, optional service...

===============================================================
 INSTALL COMPLETE
===============================================================
```

### 4. Заполните `.env`

Скрипт создал `.env` из `.env.example` **со случайным `WEB_SESSION_SECRET`**, но ключи API вам нужно вписать самим:

```cmd
notepad .env
```

Заполните **обязательно**:

```ini
MINIMAX_API_KEY=sk-cp-...your-key
AUTOAI_API_KEY=sk-aut...your-key
WEB_USERNAME=gluman
WEB_PASSWORD=your-strong-password
```

Опционально (если хотите локальный LLM):
```ini
# .env.example уже содержит рабочие URL для Ollama на этой же машине
```

### 5. Запустите

**Dev-режим** (консоль, с hot-reload):
```cmd
scripts\run.bat
```
или Start Menu → Meeting-Protocol → **Start Meeting-Protocol (dev)**.

**Как Windows Service** (фоновый режим, автостарт):
```cmd
scripts\service_install.bat
```
или Start Menu → Meeting-Protocol → **Install as Windows Service**.

Откройте: <http://127.0.0.1:8765/>

### 6. Скачайте модель whisper

`install.bat` **не** качает модели (3.1 ГБ для large-v3 — слишком много для дефолтной установки). Скачайте отдельно:

```cmd
REM Базовая (142 МБ) — для большинства случаев
scripts\download_models.bat

REM Или конкретная
scripts\download_models.bat base
scripts\download_models.bat medium
scripts\download_models.bat large-v3
```

Подробности и SHA256: см. **[README_MODELS.md](README_MODELS.md)**.

> Если `MeetingProtocol-Whisper` Windows Service не запустился — значит модели нет. Скачайте и переустановите.

---

## Управление сервисами

| Действие | Команда |
|---|---|
| Стартовать ASR вручную | `sc start MeetingProtocol-Whisper` |
| Остановить ASR | `sc stop MeetingProtocol-Whisper` |
| Стартовать web | `sc start MeetingProtocol` |
| Удалить web-сервис | `scripts\service_uninstall.bat` |
| Логи ASR | `type logs\whisper.log` |
| Логи web | `type logs\service.log` |
| Перезапустить ASR | `sc stop MeetingProtocol-Whisper && sc start MeetingProtocol-Whisper` |

---

## HTTPS через Caddy

После установки в `caddy/Caddyfile` лежит базовый конфиг:

```
:8443 {
    tls ./certs/localhost.crt ./certs/localhost.key
    reverse_proxy 127.0.0.1:8765
}
```

Запуск:
```cmd
caddy run --config caddy\Caddyfile
```

Откройте: <https://localhost:8443/>

> ⚠️ Self-signed сертификат — браузер выдаст предупреждение. Для продакшна замените на Let's Encrypt через реальный домен.

---

## Troubleshooting

### `winget` не найден

Скрипт сам поставит Chocolatey. Но если winget отсутствует и chocolatey заблокирован — установите вручную:
- winget: <https://aka.ms/getwinget>
- choco: <https://chocolatey.org/install>

### Ollama: модель не скачивается

Проверьте вручную:
```cmd
ollama list
ollama pull MiniMax-M3
```

### Whisper: `whisper-server.exe` не найден

winget-пакет `ggml-org.whisper.cpp.CUDA` может быть недоступен. Проверьте:
```cmd
winget search whisper
```

Альтернатива — собрать вручную:
```cmd
git clone https://github.com/ggml-org/whisper.cpp
cd whisper.cpp
cmake -B build -DGGML_CUDA=1
cmake --build build --config Release --target whisper-server
```

### `.env` создан с пустыми ключами

Это нормально — `.env.example` содержит заглушки `***-here`. Откройте `.env` в блокноте и впишите реальные ключи.

### Уже был установлен Python 3.10

Скрипт проверит версию и попробует обновить. Если winget не обновляет — скачайте 3.12 с <https://python.org/downloads/>.

### GPU не видится

Скрипт ставит `whisper.cpp.CUDA` только если `nvidia-smi` находит GPU. Иначе — CPU-вариант (медленнее в ~10×, но работает).

Проверить:
```cmd
nvidia-smi
```

### Удаление

Удаление сервисов:
```cmd
scripts\service_uninstall.bat
sc stop MeetingProtocol-Whisper
sc delete MeetingProtocol-Whisper
```

Удаление пакетов:
```cmd
winget uninstall Python.Python.3.12
winget uninstall Ollama.Ollama
winget uninstall ggml-org.whisper.cpp.CUDA
winget uninstall CaddyServer.Caddy
winget uninstall nssm.nssm
winget uninstall Gyan.FFmpeg
```

Удалить папку проекта:
```cmd
rmdir /s /q C:\Projects\Meetings-Protokol
```

---

## Что НЕ делает установщик

- ❌ Не открывает порты на роутере
- ❌ Не настраивает DDNS
- ❌ Не выпускает Let's Encrypt сертификаты
- ❌ Не отправляет ничего в интернет
- ❌ Не модифицирует системные файлы вне `winget`/`choco`

Всё, что касается публичного доступа, — настраивается вручную (см. раздел "HTTPS через Caddy").

---

## Архитектура после установки

```
┌──────────────────────────────────────────────────────────────┐
│  Browser                                                     │
│   ↓ http(s)://127.0.0.1:8765 (или :8443 через Caddy)        │
├──────────────────────────────────────────────────────────────┤
│  Windows Service "MeetingProtocol"  (NSSM → uvicorn)         │
│   → app.main:app  (FastAPI)                                  │
├──────────────────────────────────────────────────────────────┤
│  Whisper ASR                  Ollama LLM       External LLM  │
│  (Windows Service,            (port 11434)     (MiniMax API) │
│   port 9000)                                                  │
│  whisper-server.exe                                          │
│  + ggml-large-v3.bin                                         │
└──────────────────────────────────────────────────────────────┘
```
