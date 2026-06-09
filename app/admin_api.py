"""Admin REST API: управление пользователями, ролями и настройками.

Prefix: /web/api/v1/admin

Endpoints:
  GET    /users                       [admin]   — список пользователей
  POST   /users                       [admin]   — создать пользователя
  PUT    /users/{id}                  [admin]   — изменить роль/пароль/active
  DELETE /users/{id}                  [admin]   — удалить
  GET    /settings                    [admin]   — все настройки (.env + override)
  PUT    /settings/{key}              [admin]   — установить override
  DELETE /settings/{key}              [admin]   — удалить override (вернуть .env)
  GET    /me                          [any]     — текущий пользователь + роль
  POST   /users/{id}/reset-password   [admin]   — сброс пароля
"""
# pyright: reportOptionalSubscript=false
# pyright: reportOptionalMemberAccess=false
# В декораторе @require_role(...) параметр `user` уже отфильтрован от None,
# но сигнатура требует Optional[dict] для совместимости с dev-режимом.
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .rbac import require_role, get_current_user
from .storage_users import (
    list_users, create_user, update_user, delete_user,
    get_user_by_username, get_user_by_id, count_admins, count_users,
    list_settings, set_setting, delete_setting,
    EDITABLE_SETTINGS, Role,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/web/api/v1/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    role: Role = "viewer"


class UserUpdate(BaseModel):
    role: Optional[Role] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    role: Role
    is_active: bool
    created_at: str
    last_login_at: Optional[str]


class SettingsUpdate(BaseModel):
    value: str


class SettingOut(BaseModel):
    key: str
    label: str
    secret: bool
    type: str
    env_value: str
    override_value: Optional[str]
    effective_value: str
    is_overridden: bool


class MeOut(BaseModel):
    user: Optional[str]
    role: Optional[Role]
    auth_enabled: bool
    is_admin: bool


# ---------------------------------------------------------------------------
# /me
# ---------------------------------------------------------------------------

@router.get("/me", response_model=MeOut)
@require_role("any")
async def get_me(user: Optional[dict] = None) -> MeOut:
    from .web_auth import is_web_auth_enabled
    return MeOut(
        user=user["username"] if user else None,
        role=user["role"] if user else None,
        auth_enabled=is_web_auth_enabled(),
        is_admin=bool(user and user["role"] == "admin"),
    )


# ---------------------------------------------------------------------------
# Users CRUD
# ---------------------------------------------------------------------------

@router.get("/users", response_model=list[UserOut])
@require_role("admin")
async def list_all_users(user: Optional[dict] = None):
    return list_users()


@router.post("/users", response_model=UserOut, status_code=201)
@require_role("admin")
async def create_new_user(body: UserCreate, user: Optional[dict] = None):
    if get_user_by_username(body.username):
        raise HTTPException(409, f"user '{body.username}' already exists")
    try:
        new = create_user(body.username, body.password, body.role)
    except ValueError as e:
        raise HTTPException(400, str(e))
    # Не возвращаем password_hash
    return UserOut(
        id=new["id"],
        username=new["username"],
        role=new["role"],
        is_active=bool(new["is_active"]),
        created_at=new["created_at"],
        last_login_at=new.get("last_login_at"),
    )


@router.put("/users/{user_id}", response_model=UserOut)
@require_role("admin")
async def update_user_endpoint(user_id: int, body: UserUpdate, user: Optional[dict] = None):
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "user not found")
    # Запрет: нельзя деактивировать/понизить последнего активного админа
    if (target["role"] == "admin" and target["is_active"]
            and (body.role and body.role != "admin" or body.is_active is False)):
        if count_admins() <= 1:
            raise HTTPException(400, "cannot demote/deactivate the last active admin")
    try:
        updated = update_user(user_id, role=body.role, is_active=body.is_active, password=body.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return UserOut(
        id=updated["id"],
        username=updated["username"],
        role=updated["role"],
        is_active=bool(updated["is_active"]),
        created_at=updated["created_at"],
        last_login_at=updated.get("last_login_at"),
    )


@router.delete("/users/{user_id}")
@require_role("admin")
async def delete_user_endpoint(user_id: int, user: Optional[dict] = None):
    # Запрет удаления самого себя
    if user and user["id"] == user_id:
        raise HTTPException(400, "cannot delete yourself")
    try:
        ok = delete_user(user_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, "user not found")
    return {"ok": True, "deleted_id": user_id}


@router.post("/users/{user_id}/reset-password")
@require_role("admin")
async def reset_password(user_id: int, user: Optional[dict] = None):
    """Генерирует новый случайный пароль, возвращает его ОДИН РАЗ."""
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "user not found")
    assert user is not None  # гарантировано require_role("admin")
    new_password = secrets.token_urlsafe(12)
    update_user(user_id, password=new_password)
    logger.info(f"admin '{user['username']}' reset password for user '{target['username']}'")
    return {
        "ok": True,
        "username": target["username"],
        "new_password": new_password,
        "message": "save this password now — it will not be shown again",
    }


# ---------------------------------------------------------------------------
# Settings CRUD
# ---------------------------------------------------------------------------

@router.get("/settings", response_model=list[SettingOut])
@require_role("admin")
async def list_all_settings(user: Optional[dict] = None):
    return list_settings()


@router.put("/settings/{key}", response_model=SettingOut)
@require_role("admin")
async def update_setting_endpoint(key: str, body: SettingsUpdate, user: Optional[dict] = None):
    if key not in EDITABLE_SETTINGS:
        raise HTTPException(404, f"setting '{key}' is not editable")
    spec = EDITABLE_SETTINGS[key]
    # Валидация по типу
    val_type = spec.get("type", "str")
    if val_type == "int":
        try:
            int(body.value)
        except ValueError:
            raise HTTPException(400, f"value must be int for '{key}'")
    elif val_type == "bool":
        if body.value.lower() not in ("true", "false", "1", "0", "yes", "no"):
            raise HTTPException(400, f"value must be bool for '{key}'")
        # нормализуем
        body.value = "true" if body.value.lower() in ("true", "1", "yes") else "false"
    set_setting(key, body.value)
    logger.info(f"admin '{user['username']}' set '{key}'")
    # Вернуть обновлённую запись
    items = {s["key"]: s for s in list_settings()}
    return items[key]


@router.delete("/settings/{key}", response_model=SettingOut)
@require_role("admin")
async def delete_setting_endpoint(key: str, user: Optional[dict] = None):
    if key not in EDITABLE_SETTINGS:
        raise HTTPException(404, f"setting '{key}' is not editable")
    delete_setting(key)
    logger.info(f"admin '{user['username']}' reverted '{key}' to .env default")
    items = {s["key"]: s for s in list_settings()}
    return items[key]
