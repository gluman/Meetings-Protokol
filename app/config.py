"""Конфигурация сервиса из .env файла."""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).parent.parent


class Settings(BaseSettings):
    # MiniMax (прямой API — fallback, если AUTOAI_USE=false)
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimax.io/v1"
    minimax_model_default: str = "MiniMax-M2.7"
    minimax_whisper_model: str = "MiniMax-Whisper"

    # AutoAI Router (OpenAI-совместимый, идёт через srv-proxy 192.168.0.125:8080)
    autoai_base_url: str = "http://192.168.0.125:8080/v1"
    autoai_api_key: str = ""
    autoai_use: bool = True  # если True и autoai_api_key задан — ходим через роутер
    autoai_model: str = "MiniMax-M3"  # единственная модель

    # ASR: локальный whisper.cpp сервер на srv-ai1 (GPU)
    whisper_server_url: str = "http://192.168.0.94:9000"  # whisper-server endpoint
    whisper_use: bool = True  # если True — ASR через whisper-server, иначе прямой MiniMax (если бы был ASR)

    # Ollama
# (не используется — оставлен только MiniMax-M3)
# ollama_base_url: str = "http://192.168.0.94:11434"
# ollama_model: str = "qwen2.5:14b-16k"

    # Система
    soffice_path: str = "/usr/bin/soffice"
    storage_dir: Path = BASE_DIR / "storage"
    host: str = "0.0.0.0"
    port: int = 8765

    # Авторизация
    api_key: str = ""  # если задан — требуется заголовок Authorization: Bearer ***
    # Если api_key пустой — авторизация отключена (только для dev!)
    # Если api_token пустой — авторизация отключена (только для dev!)

    # Web-интерфейс: логин/пароль (cookie-сессия через JWT).
    # Если оба пустые — web-интерфейс открыт без авторизации (dev-режим).
    # В PRODUCTION ОБЯЗАТЕЛЬНО задать WEB_USERNAME и WEB_PASSWORD.
    web_username: str = ""
    web_password: str = ""
    web_session_secret: str = "change-me-in-env"  # для подписи JWT (заменить!)
    web_session_ttl_hours: int = 24  # сколько живёт cookie

    # Таймауты/лимиты
    max_file_size_mb: int = 500
    asr_timeout_sec: int = 600
    llm_timeout_sec: int = 300

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
(settings.storage_dir / "protocols").mkdir(exist_ok=True)
(settings.storage_dir / "audio").mkdir(exist_ok=True)
