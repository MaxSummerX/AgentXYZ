"""Общие dependencies для аутентификации в роутах."""

from typing import Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


security = HTTPBearer(auto_error=False)


def get_auth_dependency(request: Request) -> Any:
    """
    Получить dependency для проверки аутентификации.

    Используется внутри каждого роута для доступа к auth из app.state.

    Args:
        request: FastAPI запрос

    Returns:
        Auth dependency функция
    """

    async def verify_auth(
        credentials: HTTPAuthorizationCredentials | None = Depends(security),
    ) -> None:
        """Проверить credentials."""
        auth = request.app.state.auth
        await auth.authenticate(request, credentials)

    return verify_auth


# Удобная функция для создания dependency
def create_auth_protected_route() -> Any:
    """
    Создаёт wrapper для роутов требующих аутентификацию.

    Usage:
        @router.post("/chat", dependencies=[Depends(create_auth_protected_route())])
        async def chat_endpoint(request: ChatRequest):
            ...
    """

    async def verify(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(security),
    ) -> None:
        auth = request.app.state.auth
        await auth.authenticate(request, credentials)

    return verify


# Готовая dependency для использования в Depends()
AuthDepends = create_auth_protected_route()
