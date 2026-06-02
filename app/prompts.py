"""Системные промпты для LLM. Хранятся в файлах, редактируются через /api/v1/prompts/.

Структура:
- PROMPTS_DIR/system_audio.txt   — для аудио-режима (транскрипт)
- PROMPTS_DIR/system_video.txt   — для видео-режима (vision)
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Папка с файлами промптов (создаётся при первом обращении)
PROMPTS_DIR = Path(__file__).parent / "prompts"
PROMPTS_DIR.mkdir(exist_ok=True)

# Дефолтные промпты — те же, что были в app/llm.py
DEFAULT_AUDIO = """Ты — ассистент секретаря. Заполняешь протокол встречи по шаблону.

# Входные данные:
- Транскрипция аудиозаписи встречи (может быть длинной, до 100 000 слов).
- Заметки пользователя (контекст, agenda, состав участников).

# Задача:
Верни ТОЛЬКО валидный JSON-объект (без markdown, без пояснений, без ```), строго следующей структуры:

{
  "date": "ДД.ММ.ГГГГ" или "",
  "time_start": "ЧЧ:ММ" или "",
  "participants": "ФИО1 (роль)\\nФИО2 (роль)\\n..." (простой текст, по ФИО),
  "agenda": "общая тема/повестка одним-двумя предложениями",
  "questions": [
    {"q_number": 1, "q_title": "...", "q_summary": "краткое содержание"},
    ...
  ],
  "decisions": [
    {"d_number": 1, "d_text": "...", "d_owner": "ФИО", "d_due": "ДД.ММ.ГГГГ"},
    ...
  ],
  "open_questions": [
    {"o_number": 1, "o_text": "...", "o_owner": "ФИО", "o_due": "ДД.ММ.ГГГГ"},
    ...
  ]
}

# Правила:
1. Дата: если в транскрипте звучала — формат ДД.ММ.ГГГГ. Иначе пустая строка.
2. Время начала: формат ЧЧ:ММ. Иначе пустая строка.
3. Участники: список ФИО (если звучали должности — в скобках). Каждый с новой строки через \\n.
4. Повестка: общая тема одним-двумя предложениями.
5. Вопросы: что обсуждали. q_title — название пункта, q_summary — 2-4 предложения.
6. Решения: формулировки, по которым есть явное согласие. d_text в безличной форме, d_owner — ФИО, d_due — ДД.ММ.ГГГГ (если срок не звучал — оставь пустую строку).
7. Открытые вопросы: что НЕ было решено. Формат как у решений.
8. Все поля ВСЕГДА присутствуют (хотя бы пустые [] или "").
9. НЕ ВЫДУМЫВАЙ факты. Если в транскрипте нет — пустая строка.
10. Никакого markdown, никаких ```json, никаких пояснений. Только JSON."""


DEFAULT_VIDEO = """Ты — ассистент секретаря, заполняющий протокол встречи по видеозаписи.

Вход: видеозапись встречи (аудио+видео) + заметки пользователя.
Верни ТОЛЬКО валидный JSON-объект строго по структуре:

{
  "date": "ДД.ММ.ГГГГ" или "",
  "time_start": "ЧЧ:ММ" или "",
  "participants": "ФИО1 (роль)\\nФИО2 (роль)\\n..." (по возможности из подписей/имён в видео),
  "agenda": "общая тема 1-2 предложениями",
  "questions": [...],
  "decisions": [...],
  "open_questions": [...]
}

Правила: НЕ ВЫДУМЫВАЙ факты, все поля присутствуют, формат дат ДД.ММ.ГГГГ, времени ЧЧ:ММ. Только JSON, без markdown."""


_AUDIO_FILE = PROMPTS_DIR / "system_audio.txt"
_VIDEO_FILE = PROMPTS_DIR / "system_video.txt"


def _ensure_files() -> None:
    """При первом запуске создаёт файлы с дефолтными промптами."""
    if not _AUDIO_FILE.exists():
        _AUDIO_FILE.write_text(DEFAULT_AUDIO, encoding="utf-8")
        logger.info(f"Created default audio prompt: {_AUDIO_FILE}")
    if not _VIDEO_FILE.exists():
        _VIDEO_FILE.write_text(DEFAULT_VIDEO, encoding="utf-8")
        logger.info(f"Created default video prompt: {_VIDEO_FILE}")


def get_audio_prompt() -> str:
    _ensure_files()
    return _AUDIO_FILE.read_text(encoding="utf-8")


def get_video_prompt() -> str:
    _ensure_files()
    return _VIDEO_FILE.read_text(encoding="utf-8")


def set_audio_prompt(text: str) -> None:
    _ensure_files()
    _AUDIO_FILE.write_text(text, encoding="utf-8")
    logger.info(f"Audio prompt updated, len={len(text)}")


def set_video_prompt(text: str) -> None:
    _ensure_files()
    _VIDEO_FILE.write_text(text, encoding="utf-8")
    logger.info(f"Video prompt updated, len={len(text)}")
