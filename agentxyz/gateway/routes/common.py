"""Общие dependencies для всех роутов."""

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


security = HTTPBearer(auto_error=False)


async def verify_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> None:
    """
    Проверить аутентификацию запроса.

    Используется как dependency в защищённых роутах.

    Args:
        request: FastAPI запрос
        credentials: Bearer токен из заголовка Authorization

    Raises:
        HTTPException: Если аутентификация не пройдена
    """
    auth = request.app.state.auth
    await auth.authenticate(request, credentials)


# Готовая dependency для использования в Depends()
AuthDepends = verify_auth
