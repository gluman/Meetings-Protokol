"""Role-Based Access Control декоратор.

Использование:
    from .rbac import require_role, get_current_user

    @router.get("/admin/users")
    @require_role("admin")
    async def list_users_endpoint(): ...   # НЕ указывать user вручную — RBAC инжектит

    @router.get("/me")
    @require_role("any")
    async def get_me(user: dict = ...): ...   # можно указать, но default = Depends(get_current_user)

RBAC сам инжектит параметр `user: dict | None` через Depends(get_current_user).
Правила:
  - auth disabled (dev) → user=None, пускает всех
  - role не подходит → 403
  - нет сессии → 401
"""
# pyright: reportOptionalSubscript=false
import inspect
import logging
from typing import Literal

from fastapi import Cookie, Depends, HTTPException, params

from .web_auth import COOKIE_NAME, _verify_token, is_web_auth_enabled
from .storage_users import get_user_by_username, Role

logger = logging.getLogger(__name__)

RoleSpec = Role | tuple[Role, ...] | Literal["any"]


def get_current_user(
    mp_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> dict | None:
    """FastAPI dependency: возвращает user dict или None (dev-режим).

    - None если web auth disabled
    - 401 если auth enabled и сессия невалидна
    """
    if not is_web_auth_enabled():
        return None
    if not mp_session:
        raise HTTPException(401, "no session")
    payload = _verify_token(mp_session)
    if not payload:
        raise HTTPException(401, "invalid or expired session")
    user = get_user_by_username(payload.get("sub", ""))
    if not user or not user["is_active"]:
        raise HTTPException(401, "user not found or disabled")
    return user


def require_role(*allowed: Role | Literal["any"]):
    """Декоратор. Использовать ПОВЕРХ @router.*:
        @router.get(...)
        @require_role("admin")
        async def f(): ...   # user инжектится автоматически

    Или, если нужен user в теле:
        @router.get(...)
        @require_role("admin")
        async def f(user: dict = ...): ...   # default подменится на Depends
    """
    if not allowed:
        raise ValueError("require_role: at least one role required")
    spec: set[str] = set(allowed)

    def decorator(func):
        sig = inspect.signature(func)
        params_list = list(sig.parameters.values())

        # Всегда заменяем/добавляем параметр `user` с Depends(get_current_user)
        new_params = []
        user_replaced = False
        for p in params_list:
            if p.name == "user":
                # Заменяем default на Depends(get_current_user), аннотация остаётся
                new_params.append(
                    p.replace(default=Depends(get_current_user))
                )
                user_replaced = True
            else:
                new_params.append(p)
        if not user_replaced:
            new_params.append(
                inspect.Parameter(
                    "user",
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=Depends(get_current_user),
                    annotation="dict | None",
                )
            )
        func.__signature__ = sig.replace(parameters=new_params)

        async def wrapper(*args, **kwargs):
            user = kwargs.get("user")
            if not is_web_auth_enabled():
                # dev-режим — пускаем всех
                return await func(*args, **kwargs)
            if user is None:
                raise HTTPException(401, "authentication required")
            if "any" not in spec and user["role"] not in spec:
                logger.warning(
                    f"RBAC: user '{user['username']}' (role={user['role']}) "
                    f"denied access to {func.__name__} (allowed: {spec})"
                )
                raise HTTPException(403, f"role '{user['role']}' not allowed")
            return await func(*args, **kwargs)

        # Wrapper имеет ту же сигнатуру, что и func с подменённым user
        wrapper.__signature__ = func.__signature__
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper
    return decorator
