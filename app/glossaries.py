"""
Glossaries: CRUD + share/unshare + copy + entries с comment/needs_review.

Этот модуль — **бизнес-логика** над storage_jobs.py. Хранит глоссарии и их entries.

RBAC:
  editor: может создать свой, делиться, удалить свой. Не может редактировать/удалить
          чужие (даже shared). Не может удалить shared glossary, если он не его.
  admin:  может всё (см. is_admin_user()).

Ключевые функции:
  create_glossary(name, owner_id, is_shared=False) -> int
  list_glossaries_for_user(user_id, include_shared=True) -> list[dict]
  get_glossary(glossary_id) -> dict | None
  update_glossary(glossary_id, user_id, name=None, is_shared=None) -> bool
  delete_glossary(glossary_id, user_id) -> bool  # RBAC
  copy_glossary(src_id, new_name, owner_id) -> int  # deep copy entries
  add_entry(glossary_id, term, definition, ...) -> int
  list_entries(glossary_id, user_id) -> list[dict]
  update_entry(entry_id, user_id, ...) -> bool
  delete_entry(entry_id, user_id) -> bool
  toggle_needs_review(entry_id, user_id) -> bool
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.storage_jobs import _conn, _lock


# ---------------------------------------------------------------------------
# RBAC helpers
# ---------------------------------------------------------------------------
def is_admin_user(user_id: int) -> bool:
    """
    Проверяет, является ли пользователь администратором.

    Args:
        user_id: int ID пользователя.

    Returns:
        True если admin, False иначе.

    Note:
        Реализация через app.storage_users (которая уже есть в проекте).
        Импортируется лениво, чтобы избежать циклических импортов.
    """
    try:
        from app.storage_users import get_user_by_id

        u = get_user_by_id(user_id)
        return bool(u and u.get("role") == "admin")
    except Exception:
        return False


def can_modify_glossary(glossary: dict, user_id: int) -> bool:
    """
    Может ли пользователь редактировать/удалить глоссарий.

    Args:
        glossary: dict с полями 'owner_id', 'is_shared'.
        user_id: int.

    Returns:
        True если:
          - пользователь — owner ИЛИ
          - пользователь — admin
    """
    if not glossary:
        return False
    return glossary["owner_id"] == user_id or is_admin_user(user_id)


# ---------------------------------------------------------------------------
# Glossary CRUD
# ---------------------------------------------------------------------------
def create_glossary(name: str, owner_id: int, is_shared: bool = False) -> int:
    """
    Создаёт новый глоссарий.

    Args:
        name: имя глоссария (NOT NULL, любой непустой).
        owner_id: int, ID владельца.
        is_shared: bool, виден ли другим пользователям (default False).

    Returns:
        int — ID созданного глоссария.

    Raises:
        ValueError: если name пустой.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")
    now = datetime.utcnow().isoformat()
    with _lock, _conn() as c:
        cur = c.execute(
            """INSERT INTO glossaries (name, owner_id, is_shared, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (name, owner_id, int(is_shared), now, now),
        )
    return int(cur.lastrowid or 0)


def list_glossaries_for_user(
    user_id: int, include_shared: bool = True
) -> list[dict[str, Any]]:
    """
    Возвращает список глоссариев: свои + (опционально) shared.

    Args:
        user_id: int.
        include_shared: bool, если True добавляет глоссарии с is_shared=1.

    Returns:
        list of dicts с полями id, name, owner_id, is_shared, created_at, updated_at,
        entry_count (через подзапрос).
    """
    with _conn() as c:
        if include_shared:
            rows = c.execute(
                """SELECT g.id, g.name, g.owner_id, g.is_shared, g.created_at, g.updated_at,
                          (SELECT COUNT(*) FROM glossary_entries e WHERE e.glossary_id = g.id) AS entry_count
                   FROM glossaries g
                   WHERE g.owner_id = ? OR g.is_shared = 1
                   ORDER BY g.is_shared DESC, g.updated_at DESC""",
                (user_id,),
            ).fetchall()
        else:
            rows = c.execute(
                """SELECT g.id, g.name, g.owner_id, g.is_shared, g.created_at, g.updated_at,
                          (SELECT COUNT(*) FROM glossary_entries e WHERE e.glossary_id = g.id) AS entry_count
                   FROM glossaries g
                   WHERE g.owner_id = ?
                   ORDER BY g.updated_at DESC""",
                (user_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_glossary(glossary_id: int) -> dict[str, Any] | None:
    """
    Возвращает глоссарий по ID.

    Args:
        glossary_id: int.

    Returns:
        dict или None если не найден.
    """
    with _conn() as c:
        row = c.execute(
            "SELECT id, name, owner_id, is_shared, created_at, updated_at FROM glossaries WHERE id = ?",
            (glossary_id,),
        ).fetchone()
    return dict(row) if row else None


def update_glossary(
    glossary_id: int,
    user_id: int,
    name: str | None = None,
    is_shared: bool | None = None,
) -> bool:
    """
    Обновляет имя и/или is_shared. RBAC: только owner или admin.

    Args:
        glossary_id: int.
        user_id: int (для RBAC).
        name: новое имя или None (не менять).
        is_shared: новое значение или None (не менять).

    Returns:
        True если обновлено, False если не найдено или нет прав.
    """
    g = get_glossary(glossary_id)
    if not g or not can_modify_glossary(g, user_id):
        return False
    updates: list[str] = []
    params: list[Any] = []
    if name is not None:
        name = name.strip()
        if not name:
            raise ValueError("name cannot be empty")
        updates.append("name = ?")
        params.append(name)
    if is_shared is not None:
        updates.append("is_shared = ?")
        params.append(int(is_shared))
    if not updates:
        return True
    updates.append("updated_at = ?")
    params.append(datetime.utcnow().isoformat())
    params.append(glossary_id)
    with _lock, _conn() as c:
        c.execute(f"UPDATE glossaries SET {', '.join(updates)} WHERE id = ?", params)
    return True


def delete_glossary(glossary_id: int, user_id: int) -> bool:
    """
    Удаляет глоссарий (и все entries через CASCADE).

    Args:
        glossary_id: int.
        user_id: int (для RBAC).

    Returns:
        True если удалено, False если не найдено или нет прав.
    """
    g = get_glossary(glossary_id)
    if not g or not can_modify_glossary(g, user_id):
        return False
    with _lock, _conn() as c:
        c.execute("DELETE FROM glossaries WHERE id = ?", (glossary_id,))
    return True


def copy_glossary(src_id: int, new_name: str, owner_id: int) -> int:
    """
    Deep copy глоссария: создаёт новый глоссарий и копирует все entries.

    Args:
        src_id: int, ID исходного глоссария.
        new_name: str, имя нового (для нового владельца).
        owner_id: int, ID нового владельца.

    Returns:
        int — ID нового глоссария.

    Raises:
        ValueError: если src не найден или new_name пустой.
    """
    src = get_glossary(src_id)
    if not src:
        raise ValueError(f"glossary {src_id} not found")
    new_id = create_glossary(new_name, owner_id=owner_id, is_shared=False)
    with _lock, _conn() as c:
        c.execute(
            """INSERT INTO glossary_entries
               (glossary_id, term, definition, abbreviation, pronunciation, comment, needs_review, created_at)
               SELECT ?, term, definition, abbreviation, pronunciation, comment, needs_review, ?
               FROM glossary_entries WHERE glossary_id = ?""",
            (new_id, datetime.utcnow().isoformat(), src_id),
        )
    return new_id


# ---------------------------------------------------------------------------
# Entries CRUD
# ---------------------------------------------------------------------------
def add_entry(
    glossary_id: int,
    term: str,
    definition: str,
    abbreviation: str | None = None,
    pronunciation: str | None = None,
    comment: str | None = None,
    needs_review: bool = False,
) -> int:
    """
    Добавляет entry в глоссарий.

    Args:
        glossary_id: int.
        term: str (NOT NULL).
        definition: str (NOT NULL).
        abbreviation: str | None.
        pronunciation: str | None.
        comment: str | None.
        needs_review: bool, требует ли ревью.

    Returns:
        int — ID entry.

    Raises:
        ValueError: term/definition пустые или glossary не существует.
    """
    term = (term or "").strip()
    definition = (definition or "").strip()
    if not term or not definition:
        raise ValueError("term and definition are required")
    if not get_glossary(glossary_id):
        raise ValueError(f"glossary {glossary_id} not found")
    now = datetime.utcnow().isoformat()
    with _lock, _conn() as c:
        cur = c.execute(
            """INSERT INTO glossary_entries
               (glossary_id, term, definition, abbreviation, pronunciation, comment, needs_review, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                glossary_id,
                term,
                definition,
                abbreviation,
                pronunciation,
                comment,
                int(needs_review),
                now,
            ),
        )
        # Bump updated_at
        c.execute(
            "UPDATE glossaries SET updated_at = ? WHERE id = ?", (now, glossary_id)
        )
    return int(cur.lastrowid or 0)


def list_entries(glossary_id: int, user_id: int | None = None) -> list[dict[str, Any]]:
    """
    Возвращает entries глоссария.

    Args:
        glossary_id: int.
        user_id: int | None (для RBAC, опционально).

    Returns:
        list of dicts: id, term, definition, abbreviation, pronunciation,
        comment, needs_review, created_at.

    Raises:
        PermissionError: если user_id указан и не имеет доступа к глоссарию.
    """
    g = get_glossary(glossary_id)
    if not g:
        return []
    if (
        user_id is not None
        and g["owner_id"] != user_id
        and not g["is_shared"]
        and not is_admin_user(user_id)
    ):
        raise PermissionError("no access to this glossary")
    with _conn() as c:
        rows = c.execute(
            """SELECT id, glossary_id, term, definition, abbreviation, pronunciation,
                      comment, needs_review, created_at
               FROM glossary_entries WHERE glossary_id = ?
               ORDER BY needs_review DESC, created_at DESC""",
            (glossary_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_entry(entry_id: int) -> dict[str, Any] | None:
    """Возвращает entry по ID или None."""
    with _conn() as c:
        row = c.execute(
            "SELECT id, glossary_id, term, definition, abbreviation, pronunciation, comment, needs_review, created_at FROM glossary_entries WHERE id = ?",
            (entry_id,),
        ).fetchone()
    return dict(row) if row else None


def update_entry(
    entry_id: int,
    user_id: int,
    term: str | None = None,
    definition: str | None = None,
    abbreviation: str | None = None,
    pronunciation: str | None = None,
    comment: str | None = None,
    needs_review: bool | None = None,
) -> bool:
    """
    Обновляет entry. RBAC: только owner глоссария или admin.

    Args:
        entry_id: int.
        user_id: int (для RBAC).
        term/definition/abbreviation/pronunciation/comment/needs_review:
            новое значение или None (не менять).

    Returns:
        True если обновлено, False если не найдено или нет прав.
    """
    entry = get_entry(entry_id)
    if not entry:
        return False
    g = get_glossary(entry["glossary_id"])
    if not g or not can_modify_glossary(g, user_id):
        return False
    updates: list[str] = []
    params: list[Any] = []
    for field, value in [
        ("term", term),
        ("definition", definition),
        ("abbreviation", abbreviation),
        ("pronunciation", pronunciation),
        ("comment", comment),
    ]:
        if value is not None:
            v = value.strip() if isinstance(value, str) else value
            if field in ("term", "definition") and not v:
                raise ValueError(f"{field} cannot be empty")
            updates.append(f"{field} = ?")
            params.append(v)
    if needs_review is not None:
        updates.append("needs_review = ?")
        params.append(int(needs_review))
    if not updates:
        return True
    params.append(entry_id)
    with _lock, _conn() as c:
        c.execute(
            f"UPDATE glossary_entries SET {', '.join(updates)} WHERE id = ?", params
        )
    return True


def delete_entry(entry_id: int, user_id: int) -> bool:
    """
    Удаляет entry. RBAC: только owner глоссария или admin.

    Args:
        entry_id: int.
        user_id: int.

    Returns:
        True если удалено, False если не найдено или нет прав.
    """
    entry = get_entry(entry_id)
    if not entry:
        return False
    g = get_glossary(entry["glossary_id"])
    if not g or not can_modify_glossary(g, user_id):
        return False
    with _lock, _conn() as c:
        c.execute("DELETE FROM glossary_entries WHERE id = ?", (entry_id,))
    return True


def toggle_needs_review(entry_id: int, user_id: int) -> bool:
    """
    Переключает флаг needs_review у entry.

    Args:
        entry_id: int.
        user_id: int.

    Returns:
        True если обновлено, False если не найдено или нет прав.
    """
    entry = get_entry(entry_id)
    if not entry:
        return False
    g = get_glossary(entry["glossary_id"])
    if not g or not can_modify_glossary(g, user_id):
        return False
    new_val = 0 if entry["needs_review"] else 1
    with _lock, _conn() as c:
        c.execute(
            "UPDATE glossary_entries SET needs_review = ? WHERE id = ?",
            (new_val, entry_id),
        )
    return True
