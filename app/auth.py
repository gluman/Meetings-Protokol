"""Зависимости FastAPI (auth)."""
import logging

from fastapi import Header, HTTPException, status

from .config import settings

logger = logging.getLogger(__name__)


async def require_bearer(
    authorization: str | None = Header(default=None),
) -> str:
    """
    Проверяет Bearer-токен. Если `settings.api_key` пустой — пропускает (dev mode).
    В production ОБЯЗАТЕЛЬНО задать API_KEY в .env.
    """
    if not settings.api_key:
        # Auth отключён (dev mode)
        return ""

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header. Use: Authorization: Bearer <api_key>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization[7:].strip()
    if token != settings.api_key:
        logger.warning("Auth failed: bad api_key from request")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )
    return token
