"""Тесты для инъекции глоссария в system prompt.

Проверяет:
- _format_glossary_block корректно собирает блок
- entries с needs_review=1 игнорируются
- пустой/None → пустой блок
- _process_job подтягивает entries из job_glossaries M:N
"""
from __future__ import annotations

import pytest

from app.llm import _format_glossary_block


# ---------------------------------------------------------------------------
# Pure: _format_glossary_block
# ---------------------------------------------------------------------------
class TestFormatGlossaryBlock:
    """Форматтер блока глоссария для system prompt."""

    def test_empty_entries_returns_empty_string(self):
        assert _format_glossary_block([]) == ""
        assert _format_glossary_block(None) == ""

    def test_all_needs_review_returns_empty_string(self):
        entries = [
            {"term": "ASR", "definition": "x", "needs_review": 1},
            {"term": "LLM", "definition": "y", "needs_review": 1},
        ]
        assert _format_glossary_block(entries) == ""

    def test_basic_entry_appears_in_block(self):
        entries = [
            {"term": "ASR", "definition": "Automatic Speech Recognition",
             "abbreviation": None, "pronunciation": None, "comment": None,
             "needs_review": 0},
        ]
        block = _format_glossary_block(entries)
        assert "## Глоссарий встречи" in block
        assert "**ASR**" in block
        assert "Automatic Speech Recognition" in block

    def test_abbreviation_rendered(self):
        entries = [
            {"term": "Метрика", "definition": "показатель", "abbreviation": "KPI",
             "pronunciation": None, "comment": None, "needs_review": 0},
        ]
        block = _format_glossary_block(entries)
        assert "KPI" in block
        assert "сокр." in block

    def test_pronunciation_rendered(self):
        entries = [
            {"term": "Шрёдингер", "definition": "физик", "abbreviation": None,
             "pronunciation": "Шрёдингер", "comment": None, "needs_review": 0},
        ]
        block = _format_glossary_block(entries)
        assert "произн." in block
        assert "Шрёдингер" in block

    def test_comment_rendered(self):
        entries = [
            {"term": "ASR", "definition": "x", "abbreviation": None,
             "pronunciation": None, "comment": "Использовать английскую аббревиатуру",
             "needs_review": 0},
        ]
        block = _format_glossary_block(entries)
        assert "примечание:" in block
        assert "Использовать английскую аббревиатуру" in block

    def test_needs_review_entry_skipped_but_others_included(self):
        entries = [
            {"term": "ASR", "definition": "ok", "needs_review": 0,
             "abbreviation": None, "pronunciation": None, "comment": None},
            {"term": "СПОРНО", "definition": "непонятно", "needs_review": 1,
             "abbreviation": None, "pronunciation": None, "comment": None},
            {"term": "LLM", "definition": "Large Language Model", "needs_review": 0,
             "abbreviation": None, "pronunciation": None, "comment": None},
        ]
        block = _format_glossary_block(entries)
        assert "ASR" in block
        assert "LLM" in block
        assert "СПОРНО" not in block
        assert "непонятно" not in block

    def test_empty_term_skipped(self):
        entries = [
            {"term": "", "definition": "мусор", "needs_review": 0,
             "abbreviation": None, "pronunciation": None, "comment": None},
            {"term": "KPI", "definition": "ok", "needs_review": 0,
             "abbreviation": None, "pronunciation": None, "comment": None},
        ]
        block = _format_glossary_block(entries)
        assert "мусор" not in block
        assert "KPI" in block

    def test_multiple_entries_all_in_block(self):
        entries = [
            {"term": f"T{i}", "definition": f"d{i}", "needs_review": 0,
             "abbreviation": None, "pronunciation": None, "comment": None}
            for i in range(5)
        ]
        block = _format_glossary_block(entries)
        for i in range(5):
            assert f"T{i}" in block
            assert f"d{i}" in block


# ---------------------------------------------------------------------------
# Integration: _process_job подтягивает entries
# ---------------------------------------------------------------------------
class TestProcessJobGlossaryInjection:
    """Интеграция: _process_job вызывает list_job_entries_with_glossary и
    передаёт в generate_protocol. Проверяем через мок."""

    def test_process_job_passes_glossary_entries_to_llm(self, monkeypatch):
        """Когда job имеет привязанные глоссарии, _process_job подтягивает их
        и передаёт в generate_protocol как glossary_entries."""
        import asyncio
        from pathlib import Path

        from app import api as api_mod

        captured = {"glossary_entries": None}

        async def fake_generate_protocol(*args, **kwargs):
            captured["glossary_entries"] = kwargs.get("glossary_entries")
            # Возвращаем минимальный валидный Protocol
            from app.models import Protocol
            return (Protocol(date="", time_start="", participants="", agenda="",
                             questions=[], decisions=[], open_questions=[]),
                    "fake-model")

        # Подменяем generate_protocol и list_job_entries_with_glossary.
        # list_job_entries_with_glossary импортируется лениво внутри _process_job,
        # поэтому подменяем в исходном модуле storage_jobs.
        monkeypatch.setattr(api_mod, "generate_protocol", fake_generate_protocol)
        async def fake_transcribe(*a, **kw):
            return "fake transcript"
        monkeypatch.setattr(api_mod, "transcribe_audio", fake_transcribe)

        # Прямой вызов list_job_entries_with_glossary через storage_jobs
        # (для проверки, что загрузка работает в принципе)
        # (если переопределение не подхватится — упадёт на AttributeError)
        # Запускаем _process_job с подменой render_protocol_docx и save_protocol
        async def fake_render(*a, **kw):
            return None
        monkeypatch.setattr(api_mod, "render_protocol_docx", fake_render)
        monkeypatch.setattr(api_mod.storage, "save_protocol", lambda *a, **kw: None)
        monkeypatch.setattr(api_mod.storage, "update_status", lambda *a, **kw: None)        # Создаём job и привязываем глоссарий
        from app import storage
        from app import storage_jobs
        from app import storage_templates
        from app import glossaries as gloss_mod
        storage.init_db()
        storage_templates.init_templates_table()
        storage_jobs.init_extended()

        job_id = "mp-test-injection-1"
        storage.create_job(
            job_id=job_id, model_used="m3", is_video=False,
            file_name="test.mp3", file_path="/tmp/test.mp3",
        )
        # Создаём глоссарий + 2 entries
        gloss_id = gloss_mod.create_glossary(name="g1", owner_id=1, is_shared=False)
        gloss_mod.add_entry(gloss_id, "ASR", "x")
        gloss_mod.add_entry(gloss_id, "KPI", "y")
        # Привязываем к job
        storage_jobs.attach_glossary_to_job(job_id, gloss_id)

        # Запускаем
        import tempfile, os
        # Создаём фиктивный файл чтобы _process_job не упал на unlink
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"\x00")
            tmp_path = Path(f.name)

        try:
            asyncio.run(api_mod._process_job(
                job_id=job_id, file_path=tmp_path, prompt="", kind="audio"
            ))
        finally:
            # _process_job в своём finally сам делает file_path.unlink(missing_ok=True)
            if tmp_path.exists():
                os.unlink(tmp_path)

        # Проверяем, что в generate_protocol попали entries
        assert captured["glossary_entries"] is not None
        assert len(captured["glossary_entries"]) == 2
        terms = {e["term"] for e in captured["glossary_entries"]}
        assert terms == {"ASR", "KPI"}
