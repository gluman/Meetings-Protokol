"""Конфигурация сервиса из .env файла."""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).parent.parent


class Settings(BaseSettings):
    # MiniMax
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimax.io/v1"
    minimax_model_default: str = "MiniMax-M2.7"
    minimax_whisper_model: str = "MiniMax-Whisper"

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
    api_key: str = ""  # если задан — требуется заголовок Authorization: Bearer <api_key>
    # Если api_key пустой — авторизация отключена (только для dev!)
    # Если api_token пустой — авторизация отключена (только для dev!)

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
