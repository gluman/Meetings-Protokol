"""Шаблоны протоколов: парсинг примера → JSON-структура + авто-промпт.

Поддерживает:
- DOCX (через python-docx): извлекает заголовки (стили Heading 1/2) и параграфы.
- txt/md: делит на секции по эвристике (заглавные строки, ключевые слова).

Возвращает Template с:
- sections: [{name, description, example_text}]
- prompt: автогенерированный system prompt для LLM
- source_format: docx | txt | md
- source_filename: оригинальное имя
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


# Канонические разделы протокола (имена, которые мы ожидаем найти)
CANONICAL_SECTIONS = [
    "Участники",
    "Повестка",
    "Вопросы",
    "Решения",
    "Открытые вопросы",
]

# Эвристика: что считать заголовком раздела в произвольном тексте
SECTION_PATTERNS = [
    r"^\s*(участники|присутствовали|состав)\s*[:.]?\s*$",
    r"^\s*(повестка|тема|общая тема)\s*[:.]?\s*$",
    r"^\s*(вопросы|обсуждение|обсуждённые вопросы|обсудили)\s*[:.]?\s*$",
    r"^\s*(решения|принятые решения|итоги|принято)\s*[:.]?\s*$",
    r"^\s*(открытые вопросы|нерешённые|требуют решения)\s*[:.]?\s*$",
]


@dataclass
class TemplateSection:
    """Секция шаблона."""
    name: str
    description: str = ""
    example_text: str = ""


@dataclass
class Template:
    """Шаблон протокола."""
    name: str
    source_filename: str
    source_format: Literal["docx", "txt", "md"]
    sections: list[TemplateSection] = field(default_factory=list)
    prompt: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# === Парсинг ===

def parse_docx(path: Path) -> list[TemplateSection]:
    """Парсит DOCX, выделяет секции по стилям заголовков и эвристике."""
    import docx  # python-docx
    doc = docx.Document(str(path))
    sections: list[TemplateSection] = []
    current_name: str | None = None
    current_text: list[str] = []

    def flush():
        nonlocal current_name, current_text
        if current_name is not None:
            sections.append(TemplateSection(
                name=current_name,
                description="",
                example_text="\n".join(current_text).strip()[:1000],
            ))
        current_name = None
        current_text = []

    for para in doc.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue
        style = (getattr(para.style, "name", "") or "").lower()
        is_heading = "heading" in style or "title" in style
        # Дополнительно — короткие строки БЕЗ точки в конце в верхнем регистре
        is_short_header = (
            len(text) < 60
            and not text.endswith(".")
            and not text.endswith(":")
            and (text.isupper() or text.istitle())
        )
        if is_heading or (is_short_header and _matches_section_keyword(text)):
            flush()
            current_name = _normalize_section_name(text) or text
        else:
            current_text.append(text)
    flush()
    return sections


def parse_text(path: Path) -> list[TemplateSection]:
    """Парсит txt/md, выделяет секции по эвристике заголовков."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    sections: list[TemplateSection] = []
    current_name: str | None = None
    current_text: list[str] = []

    def flush():
        nonlocal current_name, current_text
        if current_name is not None:
            sections.append(TemplateSection(
                name=current_name,
                description="",
                example_text="\n".join(current_text).strip()[:1000],
            ))
        current_name = None
        current_text = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Markdown heading: # / ## / ###
        md_heading = re.match(r"^#{1,3}\s+(.+)$", stripped)
        # Pattern match по ключевым словам
        matched = bool(md_heading) or any(
            re.match(pat, stripped, re.IGNORECASE) for pat in SECTION_PATTERNS
        )
        if matched:
            flush()
            name = md_heading.group(1).strip() if md_heading else stripped
            current_name = _normalize_section_name(name) or name
        else:
            current_text.append(stripped)
    flush()
    return sections


def _matches_section_keyword(text: str) -> bool:
    return any(re.match(pat, text, re.IGNORECASE) for pat in SECTION_PATTERNS)


def _normalize_section_name(text: str) -> str | None:
    """Приводит к каноническому имени раздела, если узнаёт."""
    t = text.lower().strip().rstrip(":.")
    for canonical in CANONICAL_SECTIONS:
        if t == canonical.lower() or t.startswith(canonical.lower()[:6]):
            return canonical
    return None


def parse_file(path: Path, original_filename: str = "") -> Template:
    """Главная точка входа: парсит файл и возвращает Template."""
    name = original_filename or path.name
    ext = path.suffix.lower().lstrip(".")
    if ext == "docx":
        sections = parse_docx(path)
        fmt = "docx"
    elif ext in ("txt", "md", "markdown"):
        sections = parse_text(path)
        fmt = "txt" if ext == "txt" else "md"
    else:
        # fallback: txt
        sections = parse_text(path)
        fmt = "txt"

    # Если секций не нашли — добавляем дефолтные, без example
    if not sections:
        sections = [TemplateSection(name=s) for s in CANONICAL_SECTIONS]

    template = Template(
        name=path.stem[:80],
        source_filename=name,
        source_format=fmt,
        sections=sections,
    )
    template.prompt = generate_prompt(template)
    return template


# === Генерация промпта ===

def generate_prompt(template: Template) -> str:
    """Генерирует system prompt для LLM на основе шаблона.

    Промпт описывает:
    - роль (аналитик протоколов)
    - формат ответа (JSON)
    - обязательные разделы (из шаблона)
    - примеры из source-файла (если есть)
    """
    parts: list[str] = []

    parts.append("Ты — аналитик встреч. Составь протокол встречи на основе расшифровки.")
    parts.append("")
    parts.append("## Формат ответа")
    parts.append("Верни ТОЛЬКО валидный JSON без пояснений до/после:")
    parts.append("{")
    parts.append('  "date": "ДД.ММ.ГГГГ (если упомянута, иначе пусто)",')
    parts.append('  "time_start": "ЧЧ:ММ (если упомянуто)",')
    parts.append('  "participants": ["Список участников"],')
    parts.append('  "agenda": "Общая тема / повестка встречи",')
    parts.append('  "questions": [{"q_number": 1, "q_title": "...", "q_summary": "..."}],')
    parts.append('  "decisions": [{"d_number": 1, "d_text": "...", "d_owner": "ФИО", "d_due": "срок"}],')
    parts.append('  "open_questions": [{"o_number": 1, "o_text": "...", "o_owner": "ФИО", "o_due": "срок"}]')
    parts.append("}")
    parts.append("")

    parts.append("## Разделы протокола")
    parts.append("Структура должна включать следующие разделы (в этом порядке):")
    for i, sec in enumerate(template.sections, 1):
        parts.append(f"{i}. **{sec.name}**" + (f" — {sec.description}" if sec.description else ""))
    parts.append("")

    # Если в шаблоне есть примеры — даём как референс
    examples = [s for s in template.sections if s.example_text]
    if examples:
        parts.append("## Примеры из исходного документа")
        for sec in examples:
            parts.append(f"### {sec.name}")
            parts.append(sec.example_text[:400])
            parts.append("")

    parts.append("## Правила заполнения")
    parts.append("- Каждый вопрос — отдельный объект с q_number (по порядку).")
    parts.append("- Каждое решение — отдельный объект с d_number и обязательными d_owner/d_due.")
    parts.append("- Если срок в расшифровке указан словами (\"до пятницы\", \"на следующей неделе\") — запиши текстом как есть, не выдумывай ДД.ММ.ГГГГ.")
    parts.append("- Если ответственный не назван явно — оставь пустую строку.")
    parts.append("- q_summary — 1 предложение, констатация факта. Без подробностей.")
    parts.append("- Не выдумывай факты: чего нет в расшифровке — не пиши.")
    parts.append("")
    parts.append("Источник шаблона: " + template.source_filename)

    return "\n".join(parts).strip()
