"""Тесты storage_templates."""
import uuid

import pytest

from app import storage, storage_templates


@pytest.fixture(autouse=True)
def clean_db():
    """Перед каждым тестом — инициализируем схему и чистим templates."""
    import sqlite3
    from app.config import settings
    storage_templates.init_templates_table()
    db = settings.storage_dir / "jobs.db"
    con = sqlite3.connect(str(db))
    con.execute("DELETE FROM templates")
    con.commit()
    con.close()
    yield


def test_create_first_is_default():
    tid = "tpl-" + uuid.uuid4().hex[:10]
    t = storage_templates.create_template(
        template_id=tid, name="First", source_filename="a.md", source_format="md",
        sections=[{"name": "Участники"}], prompt="test prompt",
    )
    assert t["is_default"] is True
    assert t["name"] == "First"


def test_create_second_not_default():
    t1 = storage_templates.create_template(
        template_id="tpl-a", name="A", source_filename="a", source_format="md",
        sections=[], prompt="p",
    )
    t2 = storage_templates.create_template(
        template_id="tpl-b", name="B", source_filename="b", source_format="md",
        sections=[], prompt="p",
    )
    assert t1["is_default"] is True
    assert t2["is_default"] is False


def test_list_orders_default_first():
    storage_templates.create_template(
        template_id="tpl-a", name="A", source_filename="", source_format="md",
        sections=[], prompt="",
    )
    storage_templates.create_template(
        template_id="tpl-b", name="B", source_filename="", source_format="md",
        sections=[], prompt="",
    )
    all_t = storage_templates.list_templates()
    assert all_t[0]["id"] == "tpl-a"  # default first
    assert all_t[0]["is_default"] is True


def test_set_default():
    storage_templates.create_template(
        template_id="tpl-a", name="A", source_filename="", source_format="md",
        sections=[], prompt="",
    )
    storage_templates.create_template(
        template_id="tpl-b", name="B", source_filename="", source_format="md",
        sections=[], prompt="",
    )
    storage_templates.set_default_template("tpl-b")
    default = storage_templates.get_default_template()
    assert default is not None
    assert default["id"] == "tpl-b"
    a = storage_templates.get_template("tpl-a")
    assert a is not None and a["is_default"] is False


def test_update_prompt():
    tid = storage_templates.create_template(
        template_id="tpl-a", name="A", source_filename="", source_format="md",
        sections=[], prompt="old",
    )["id"]
    updated = storage_templates.update_template_prompt(tid, "new prompt")
    assert updated is not None
    assert updated["prompt"] == "new prompt"


def test_delete():
    tid = storage_templates.create_template(
        template_id="tpl-a", name="A", source_filename="", source_format="md",
        sections=[], prompt="",
    )["id"]
    assert storage_templates.delete_template(tid) is True
    assert storage_templates.get_template(tid) is None


def test_delete_nonexistent():
    assert storage_templates.delete_template("tpl-doesnt-exist") is False
