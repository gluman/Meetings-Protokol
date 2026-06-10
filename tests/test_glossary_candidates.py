"""Tests for app/glossary_candidates.py — LLM extraction + accept/reject/edit.

Тесты LLM call (extract_candidates) замоканы через monkeypatch httpx,
чтобы не делать реальный HTTP-запрос.
"""

from unittest.mock import MagicMock, patch

import pytest
from app.glossary_candidates import (
    accept_candidate,
    edit_and_accept,
    extract_candidates,
    get_candidate,
    list_candidates,
    reject_candidate,
)
from app.glossaries import create_glossary
from app.storage import create_job


@pytest.fixture
def job_id() -> str:
    """Создаёт тестовый job в БД."""
    jid = "test-job-123"
    create_job(
        jid,
        model_used="test",
        is_video=False,
        file_name="test.wav",
        file_path="/tmp/test.wav",
    )
    return jid


def _mock_llm_response(candidates: list[dict]) -> dict:
    """Создаёт мок ответа LLM в формате OpenAI chat completion."""
    return {
        "choices": [
            {
                "message": {
                    "content": '{"candidates": '
                    + str(candidates).replace("'", '"')
                    + "}"
                }
            }
        ]
    }


@patch("app.glossary_candidates.httpx.Client")
def test_extract_candidates_success(mock_client_cls, job_id):
    """Успешное извлечение: 3 кандидата от LLM → 3 записи в БД."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_llm_response(
        [
            {
                "term": "ASR",
                "context": "ASR для транскрибации",
                "suggested_definition": "распознавание речи",
            },
            {
                "term": "LLM",
                "context": "использовали LLM",
                "suggested_definition": "большая языковая модель",
            },
            {
                "term": "RAG",
                "context": "применили RAG",
                "suggested_definition": "генерация с поиском",
            },
        ]
    )
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = mock_client

    ids = extract_candidates(
        "Это тестовая транскрибация с упоминанием ASR, LLM, RAG.", job_id
    )
    assert len(ids) == 3
    # Проверяю что все 3 в БД
    candidates = list_candidates(job_id, status="pending")
    assert len(candidates) == 3
    terms = {c["term"] for c in candidates}
    assert terms == {"ASR", "LLM", "RAG"}


@patch("app.glossary_candidates.httpx.Client")
def test_extract_candidates_empty(mock_client_cls, job_id):
    """LLM вернула пустой список → 0 кандидатов."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_llm_response([])
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = mock_client

    ids = extract_candidates("Любой текст", job_id)
    assert ids == []
    assert list_candidates(job_id) == []


@patch("app.glossary_candidates.httpx.Client")
def test_extract_candidates_bad_json(mock_client_cls, job_id):
    """LLM вернула невалидный JSON → 0 кандидатов, не падает."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": "not a json"}}]}
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = mock_client

    ids = extract_candidates("Текст", job_id)
    assert ids == []


def test_extract_candidates_empty_transcript(job_id):
    """Пустой транскрипт → 0 кандидатов, без вызова LLM."""
    ids = extract_candidates("", job_id)
    assert ids == []
    ids = extract_candidates("   ", job_id)
    assert ids == []


def test_extract_candidates_job_not_found():
    """Несуществующий job → ValueError."""
    with pytest.raises(ValueError):
        extract_candidates("text", "non-existent-job-id")


@patch("app.glossary_candidates.httpx.Client")
def test_extract_candidates_llm_filters_invalid(mock_client_cls, job_id):
    """LLM вернула мусор вперемешку с валидными — фильтруем невалидные."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": '{"candidates": ['
                    '{"term": "OK"}, '
                    '{"term": ""}, '
                    '{"no_term": "x"}, '
                    '{"term": "Also OK"}'
                    "]}"
                }
            }
        ]
    }
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = mock_client

    ids = extract_candidates("text", job_id)
    # Только 2 валидных (с непустым term)
    assert len(ids) == 2


@patch("app.glossary_candidates.httpx.Client")
def test_extract_candidates_caps_at_15(mock_client_cls, job_id):
    """LLM вернула 20 → сохраняем только 15."""
    many = [
        {"term": f"T{i}", "context": "c", "suggested_definition": "d"}
        for i in range(20)
    ]
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_llm_response(many)
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = mock_client

    ids = extract_candidates("text", job_id)
    assert len(ids) == 15


@patch("app.glossary_candidates.httpx.Client")
def test_extract_candidates_truncates_long_term(mock_client_cls, job_id):
    """Очень длинный term обрезается до 200 символов."""
    long_term = "X" * 500
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_llm_response(
        [{"term": long_term, "context": "c", "suggested_definition": "d"}]
    )
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = mock_client

    ids = extract_candidates("text", job_id)
    cand = get_candidate(ids[0])
    assert len(cand["term"]) == 200


@patch("app.glossary_candidates.httpx.Client")
def test_accept_candidate_creates_entry(mock_client_cls, job_id):
    """accept создаёт entry в глоссарии + помечает accepted."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_llm_response(
        [{"term": "ASR", "context": "c", "suggested_definition": "распознавание речи"}]
    )
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = mock_client

    [cid] = extract_candidates("text", job_id)
    gid = create_glossary("Test", owner_id=1)
    entry_id = accept_candidate(cid, reviewed_by=1, glossary_id=gid)
    assert entry_id > 0
    cand = get_candidate(cid)
    assert cand["status"] == "accepted"
    assert cand["reviewed_by"] == 1
    # Entry должен быть в глоссарии
    from app.glossaries import list_entries

    entries = list_entries(gid)
    assert any(e["term"] == "ASR" for e in entries)


@patch("app.glossary_candidates.httpx.Client")
def test_accept_candidate_without_glossary(mock_client_cls, job_id):
    """accept без glossary_id — только помечает, без entry."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_llm_response(
        [{"term": "X", "context": "c", "suggested_definition": "d"}]
    )
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = mock_client

    [cid] = extract_candidates("text", job_id)
    entry_id = accept_candidate(cid, reviewed_by=1, glossary_id=None)
    assert entry_id == 0
    cand = get_candidate(cid)
    assert cand["status"] == "accepted"


def test_accept_candidate_not_found():
    """accept несуществующего → ValueError."""
    with pytest.raises(ValueError):
        accept_candidate(99999, reviewed_by=1)


@patch("app.glossary_candidates.httpx.Client")
def test_accept_candidate_already_reviewed(mock_client_cls, job_id):
    """accept уже принятого → ValueError."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_llm_response(
        [{"term": "X", "context": "c", "suggested_definition": "d"}]
    )
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = mock_client

    [cid] = extract_candidates("text", job_id)
    accept_candidate(cid, reviewed_by=1, glossary_id=None)
    with pytest.raises(ValueError):
        accept_candidate(cid, reviewed_by=1, glossary_id=None)


@patch("app.glossary_candidates.httpx.Client")
def test_reject_candidate(mock_client_cls, job_id):
    """reject помечает status='rejected'."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_llm_response(
        [{"term": "X", "context": "c", "suggested_definition": "d"}]
    )
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = mock_client

    [cid] = extract_candidates("text", job_id)
    assert reject_candidate(cid, reviewed_by=1)
    cand = get_candidate(cid)
    assert cand["status"] == "rejected"


def test_reject_candidate_not_found():
    """reject несуществующего → False."""
    assert reject_candidate(99999, reviewed_by=1) is False


@patch("app.glossary_candidates.httpx.Client")
def test_edit_and_accept(mock_client_cls, job_id):
    """edit_and_accept с правками создаёт entry с новыми term/definition."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_llm_response(
        [{"term": "ORIG", "context": "c", "suggested_definition": "old def"}]
    )
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = mock_client

    [cid] = extract_candidates("text", job_id)
    gid = create_glossary("Test", owner_id=1)
    entry_id = edit_and_accept(
        cid, reviewed_by=1, new_term="FIXED", new_definition="new def", glossary_id=gid
    )
    assert entry_id > 0
    from app.glossaries import list_entries

    entries = list_entries(gid)
    assert any(e["term"] == "FIXED" and e["definition"] == "new def" for e in entries)
    cand = get_candidate(cid)
    assert cand["status"] == "accepted"


@patch("app.glossary_candidates.httpx.Client")
def test_edit_and_accept_empty_fields(mock_client_cls, job_id):
    """edit_and_accept с пустыми полями → ValueError."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_llm_response(
        [{"term": "X", "context": "c", "suggested_definition": "d"}]
    )
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = mock_client

    [cid] = extract_candidates("text", job_id)
    gid = create_glossary("Test", owner_id=1)
    with pytest.raises(ValueError):
        edit_and_accept(
            cid, reviewed_by=1, new_term="", new_definition="x", glossary_id=gid
        )
    with pytest.raises(ValueError):
        edit_and_accept(
            cid, reviewed_by=1, new_term="x", new_definition="", glossary_id=gid
        )


@patch("app.glossary_candidates.httpx.Client")
def test_list_candidates_filters_by_status(mock_client_cls, job_id):
    """list_candidates фильтрует по статусу."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_llm_response(
        [
            {"term": "A", "context": "c", "suggested_definition": "d"},
            {"term": "B", "context": "c", "suggested_definition": "d"},
        ]
    )
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = mock_client

    [c1, c2] = extract_candidates("text", job_id)
    accept_candidate(c1, reviewed_by=1, glossary_id=None)
    pending = list_candidates(job_id, status="pending")
    accepted = list_candidates(job_id, status="accepted")
    assert len(pending) == 1
    assert pending[0]["term"] == "B"
    assert len(accepted) == 1
    assert accepted[0]["term"] == "A"
