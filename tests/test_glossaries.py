"""Tests for app/glossaries.py — CRUD + RBAC + copy.

Storage инициализируется в conftest.py (autouse fixture).
"""

import pytest
from app.glossaries import (
    add_entry,
    copy_glossary,
    create_glossary,
    delete_entry,
    delete_glossary,
    get_entry,
    get_glossary,
    is_admin_user,
    list_entries,
    list_glossaries_for_user,
    toggle_needs_review,
    update_entry,
    update_glossary,
)


def test_create_glossary():
    """Базовое создание глоссария."""
    gid = create_glossary("Test", owner_id=1)
    g = get_glossary(gid)
    assert g is not None
    assert g["name"] == "Test"
    assert g["owner_id"] == 1
    assert g["is_shared"] == 0


def test_create_glossary_shared():
    """Создание сразу shared."""
    gid = create_glossary("Public", owner_id=1, is_shared=True)
    g = get_glossary(gid)
    assert g["is_shared"] == 1


def test_create_glossary_empty_name_raises():
    """Пустое имя → ValueError."""
    with pytest.raises(ValueError):
        create_glossary("", owner_id=1)
    with pytest.raises(ValueError):
        create_glossary("   ", owner_id=1)


def test_list_glossaries_for_user_own():
    """Пользователь видит только свои (если include_shared=False)."""
    create_glossary("Mine1", owner_id=1)
    create_glossary("Mine2", owner_id=1)
    create_glossary("Other", owner_id=2)
    res = list_glossaries_for_user(1, include_shared=False)
    assert len(res) == 2
    names = {g["name"] for g in res}
    assert names == {"Mine1", "Mine2"}


def test_list_glossaries_for_user_with_shared():
    """С include_shared=True — видит и чужие shared."""
    create_glossary("Mine", owner_id=1)
    create_glossary("OtherShared", owner_id=2, is_shared=True)
    create_glossary("OtherPrivate", owner_id=2, is_shared=False)
    res = list_glossaries_for_user(1, include_shared=True)
    names = {g["name"] for g in res}
    assert "Mine" in names
    assert "OtherShared" in names
    assert "OtherPrivate" not in names


def test_update_glossary_owner():
    """Owner может обновить имя и share."""
    gid = create_glossary("Old", owner_id=1)
    assert update_glossary(gid, user_id=1, name="New", is_shared=True)
    g = get_glossary(gid)
    assert g["name"] == "New"
    assert g["is_shared"] == 1


def test_update_glossary_not_owner():
    """Не-owner не может обновить."""
    gid = create_glossary("Mine", owner_id=1)
    assert not update_glossary(gid, user_id=2, name="Hacked")


def test_update_glossary_not_found():
    """Несуществующий → False."""
    assert not update_glossary(9999, user_id=1, name="X")


def test_delete_glossary_owner():
    """Owner может удалить."""
    gid = create_glossary("Test", owner_id=1)
    assert delete_glossary(gid, user_id=1)
    assert get_glossary(gid) is None


def test_delete_glossary_not_owner():
    """Не-owner не может удалить."""
    gid = create_glossary("Mine", owner_id=1)
    assert not delete_glossary(gid, user_id=2)
    assert get_glossary(gid) is not None


def test_copy_glossary_deep():
    """Copy создаёт новый глоссарий с теми же entries."""
    gid = create_glossary("Source", owner_id=1)
    add_entry(gid, "TERM1", "def1", abbreviation="T1")
    add_entry(gid, "TERM2", "def2", needs_review=True)
    new_id = copy_glossary(gid, "Copy", owner_id=2)
    assert new_id != gid
    src_entries = list_entries(gid)
    new_entries = list_entries(new_id)
    assert len(src_entries) == len(new_entries) == 2
    src_terms = {e["term"] for e in src_entries}
    new_terms = {e["term"] for e in new_entries}
    assert src_terms == new_terms == {"TERM1", "TERM2"}


def test_copy_glossary_source_not_found():
    """Copy несуществующего → ValueError."""
    with pytest.raises(ValueError):
        copy_glossary(9999, "X", owner_id=1)


def test_add_entry_basic():
    """add_entry создаёт запись."""
    gid = create_glossary("Test", owner_id=1)
    eid = add_entry(gid, "TERM", "definition")
    entry = get_entry(eid)
    assert entry is not None
    assert entry["term"] == "TERM"
    assert entry["definition"] == "definition"
    assert entry["needs_review"] == 0


def test_add_entry_with_extras():
    """add_entry с abbreviation/pronunciation/comment/needs_review."""
    gid = create_glossary("Test", owner_id=1)
    eid = add_entry(
        gid,
        "ASR",
        "Automatic Speech Recognition",
        abbreviation="ASR",
        pronunciation="a-s-r",
        comment="common",
        needs_review=True,
    )
    entry = get_entry(eid)
    assert entry["abbreviation"] == "ASR"
    assert entry["pronunciation"] == "a-s-r"
    assert entry["comment"] == "common"
    assert entry["needs_review"] == 1


def test_add_entry_invalid():
    """Пустые term/definition → ValueError."""
    gid = create_glossary("Test", owner_id=1)
    with pytest.raises(ValueError):
        add_entry(gid, "", "def")
    with pytest.raises(ValueError):
        add_entry(gid, "term", "")


def test_add_entry_glossary_not_found():
    """Глоссарий не существует → ValueError."""
    with pytest.raises(ValueError):
        add_entry(9999, "t", "d")


def test_list_entries_permission():
    """Private глоссарий другого user → PermissionError."""
    gid = create_glossary("Private", owner_id=1, is_shared=False)
    add_entry(gid, "T", "D")
    with pytest.raises(PermissionError):
        list_entries(gid, user_id=2)
    # Owner видит
    entries = list_entries(gid, user_id=1)
    assert len(entries) == 1


def test_list_entries_shared_access():
    """Shared глоссарий — другие могут читать."""
    gid = create_glossary("Shared", owner_id=1, is_shared=True)
    add_entry(gid, "T", "D")
    entries = list_entries(gid, user_id=2)
    assert len(entries) == 1


def test_update_entry_owner():
    """Owner может обновить entry."""
    gid = create_glossary("Test", owner_id=1)
    eid = add_entry(gid, "T", "D")
    assert update_entry(eid, user_id=1, definition="New", comment="c")
    e = get_entry(eid)
    assert e["definition"] == "New"
    assert e["comment"] == "c"


def test_update_entry_not_owner():
    """Не-owner не может обновить."""
    gid = create_glossary("Mine", owner_id=1)
    eid = add_entry(gid, "T", "D")
    assert not update_entry(eid, user_id=2, definition="Hacked")
    e = get_entry(eid)
    assert e["definition"] == "D"  # unchanged


def test_delete_entry_owner():
    """Owner может удалить entry."""
    gid = create_glossary("Test", owner_id=1)
    eid = add_entry(gid, "T", "D")
    assert delete_entry(eid, user_id=1)
    assert get_entry(eid) is None


def test_toggle_needs_review():
    """Toggle переключает needs_review."""
    gid = create_glossary("Test", owner_id=1)
    eid = add_entry(gid, "T", "D", needs_review=False)
    assert toggle_needs_review(eid, user_id=1)
    e = get_entry(eid)
    assert e["needs_review"] == 1
    toggle_needs_review(eid, user_id=1)
    e = get_entry(eid)
    assert e["needs_review"] == 0


def test_cascade_delete():
    """Удаление глоссария каскадно удаляет entries (FK ON DELETE CASCADE)."""
    gid = create_glossary("Test", owner_id=1)
    eid1 = add_entry(gid, "T1", "D1")
    eid2 = add_entry(gid, "T2", "D2")
    assert delete_glossary(gid, user_id=1)
    assert get_entry(eid1) is None
    assert get_entry(eid2) is None


def test_is_admin_user_no_users():
    """Если user_id не существует — False (не admin)."""
    assert is_admin_user(9999) is False
