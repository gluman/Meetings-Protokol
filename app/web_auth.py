"""Web-авторизация по логину/паролю через JWT в cookie.

Порядок проверки credentials:
  1) Сначала ищем user в БД (storage_users.verify_credentials) — основной путь
  2) Если auth disabled (БД пуста и .env тоже пуст) — пускаем всех (dev)
  3) Fallback: если в .env заданы WEB_USERNAME/WEB_PASSWORD и БД пуста,
     verify_credentials сам замигрирует env-юзера при первом логине
     (через migrate_from_env) — но в этом модуле мы делаем простой fallback.

JWT payload:
  - sub: username
  - role: 'admin' | 'editor' | 'viewer'
  - iat, exp

Endpoints:
  - POST /web/login    — {username, password} → JWT cookie
  - POST /web/logout
  - GET  /web/check    — {ok, user, role, auth_disabled}
"""
import hashlib
import hmac
import json
import logging
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode

from fastapi import APIRouter, Cookie, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .config import settings
from .storage_users import verify_credentials, get_user_by_username

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/web", tags=["web-auth"])

COOKIE_NAME = "mp_session"


class LoginRequest(BaseModel):
    username: str
    password: str


def _b64url(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    return urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _make_token(username: str, role: str, ttl_hours: int) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": username,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl_hours * 3600,
    }
    h_b = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p_b = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    msg = f"{h_b}.{p_b}".encode()
    sig = hmac.new(
        settings.web_session_secret.encode(), msg, hashlib.sha256
    ).digest()
    return f"{h_b}.{p_b}.{_b64url(sig)}"


def _verify_token(token: str) -> dict | None:
    try:
        h_b, p_b, s_b = token.split(".")
    except ValueError:
        return None
    msg = f"{h_b}.{p_b}".encode()
    expected = hmac.new(
        settings.web_session_secret.encode(), msg, hashlib.sha256
    ).digest()
    if not hmac.compare_digest(_b64url(expected), s_b):
        return None
    try:
        payload = json.loads(_b64url_decode(p_b))
    except Exception:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload


# ---------------------------------------------------------------------------
# Auth-mode detection: БД / .env / disabled
# ---------------------------------------------------------------------------

def is_web_auth_enabled() -> bool:
    """True если есть хоть один из источников: .env creds или users в БД."""
    if settings.web_username and settings.web_password:
        return True
    # Если в БД есть хотя бы один активный юзер — auth enabled
    from .storage_users import list_users
    try:
        return any(u["is_active"] for u in list_users())
    except Exception:
        return False


def _try_env_login(username: str, password: str) -> bool:
    """Fallback на .env creds (если БД пуста)."""
    if not (settings.web_username and settings.web_password):
        return False
    # Константное время
    u_ok = hmac.compare_digest(
        hashlib.sha256(username.encode()).digest(),
        hashlib.sha256(settings.web_username.encode()).digest(),
    )
    p_ok = hmac.compare_digest(
        hashlib.sha256(password.encode()).digest(),
        hashlib.sha256(settings.web_password.encode()).digest(),
    )
    return u_ok and p_ok


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/login")
async def login(body: LoginRequest, response: Response):
    """Проверяет логин/пароль, выдаёт JWT в httpOnly cookie.

    Порядок:
      1) БД (storage_users)
      2) Fallback на .env (если БД пуста)

    Возвращает JSON {ok, user, role, ttl_hours, _redirect} — JS-клиент (login.html)
    сам делает window.location.href на _redirect. Не делаем 303-redirect потому,
    что TestClient (и часть браузеров) теряет Set-Cookie в redirect-цепочке.
    """
    if not is_web_auth_enabled():
        return JSONResponse(
            {"ok": False, "error": "web auth disabled (set WEB_USERNAME/WEB_PASSWORD in .env)"},
            status_code=503,
        )

    # 1) БД
    user = verify_credentials(body.username, body.password)
    role = None
    if user:
        role = user["role"]
    else:
        # 2) Fallback .env
        if _try_env_login(body.username, body.password):
            role = "admin"  # .env-юзер = супер-админ (legacy)
        else:
            raise HTTPException(401, "Неверный логин или пароль")

    # Убедимся, что юзер существует в БД (для будущих логинов)
    if not get_user_by_username(body.username):
        # .env-юзер залогинился, но в БД его нет → замигрируем
        from .storage_users import migrate_from_env
        migrate_from_env()

    token = _make_token(body.username, role, settings.web_session_ttl_hours)
    # Secure=True: кука только по HTTPS. Сайт работает по https://, домен = gluman.tech
    # (HTTP не используется; reverse-proxy = Caddy на srv-proxy).
    is_https = bool(getattr(settings, "is_https", True))
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=is_https,
        max_age=settings.web_session_ttl_hours * 3600,
        path="/",
    )
    logger.info(f"web-auth: user '{body.username}' (role={role}) logged in")
    return {
        "ok": True,
        "user": body.username,
        "role": role,
        "ttl_hours": settings.web_session_ttl_hours,
        "_redirect": "/",
    }


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/check")
async def check(mp_session: str | None = Cookie(default=None)):
    """Проверяет сессию. Возвращает {ok, user, role} или 401."""
    if not is_web_auth_enabled():
        return {"ok": True, "auth_disabled": True, "user": None, "role": None}
    if not mp_session:
        raise HTTPException(401, "no session")
    payload = _verify_token(mp_session)
    if not payload:
        raise HTTPException(401, "invalid or expired session")
    username = payload.get("sub")
    user = get_user_by_username(username) if username else None
    if not user or not user["is_active"]:
        raise HTTPException(401, "user not found or disabled")
    return {
        "ok": True,
        "user": username,
        "role": user["role"],
    }


def is_session_valid(token: str | None) -> bool:
    """Используется в middleware: True если пускать запрос."""
    if not is_web_auth_enabled():
        return True
    if not token:
        return False
    return _verify_token(token) is not None
