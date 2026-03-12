"""Аутентификация для Gateway."""

from __future__ import annotations

import ipaddress
import secrets
from typing import TYPE_CHECKING, Any, cast

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger


if TYPE_CHECKING:
    from agentxyz.config.schema import GatewayAuthConfig as GatewayAuthConfigType


class GatewayAuth:
    """
    Менеджер аутентификации для Gateway.

    Поддерживает:
    - Bearer token аутентификацию
    - Проверку IP адресов (опционально)
    """

    security = HTTPBearer(auto_error=False)

    def __init__(self, config: GatewayAuthConfigType) -> None:
        """
        Инициализировать аутентификацию.

        Args:
            config: Конфигурация аутентификации
        """
        self.config = config
        self._token_generated = False

        # Генерировать токен если не указан
        if config.enabled and not config.api_token:
            self._token = self._generate_token()
            self._token_generated = True
            logger.warning(f"Сгенерирован новый API токен: {self._token}")
            logger.warning("Сохраните его в конфигурации!")
        else:
            self._token = config.api_token

    @staticmethod
    def _generate_token() -> str:
        """
        Сгенерировать случайный API токен.

        Returns:
            Токен в формате sk-<random>
        """
        random_part = secrets.token_urlsafe(32)
        return f"sk-{random_part}"

    @property
    def token(self) -> str:
        """Получить текущий токен."""
        return self._token

    @property
    def was_token_generated(self) -> bool:
        """Был ли токен сгенерирован при старте."""
        return self._token_generated

    def is_enabled(self) -> bool:
        """Включена ли аутентификация."""
        return self.config.enabled

    async def authenticate(
        self,
        request: Request,
        credentials: HTTPAuthorizationCredentials | None,
    ) -> None:
        """
        Проверить аутентификацию запроса.

        Args:
            request: FastAPI запрос
            credentials: Bearer токен из заголовка Authorization

        Raises:
            HTTPException: Если аутентификация не пройдена
        """
        # Если аутентификация отключена - разрешить всё
        if not self.config.enabled:
            return

        # Проверить токен (credentials может быть None или HTTPBearer при auto_error=False)
        token = None
        if credentials and hasattr(credentials, "credentials"):
            token = credentials.credentials

        # DEBUG
        logger.info(
            f"Auth check: token={token[:10] if token else 'None'}... expected={self._token[:10]}..."
        )

        if token != self._token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный или отсутствующий API токен",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Проверить IP если указан список
        if self.config.allowed_ips:
            client_ip = self._get_client_ip(request)
            if not self._is_ip_allowed(client_ip):
                logger.warning(f"Доступ запрещён для IP: {client_ip}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"IP {client_ip} не в списке разрешённых",
                )

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        """
        Получить IP адрес клиента.

        Args:
            request: FastAPI запрос

        Returns:
            IP адрес клиента
        """
        # Проверить заголовки прокси
        forwarded_for: str | None = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Первый IP в списке - это оригинальный клиент
            return forwarded_for.split(",")[0].strip()

        real_ip: str | None = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Иначе использовать прямой IP
        if request.client:
            return cast("str", request.client.host)

        return "unknown"

    def _is_ip_allowed(self, client_ip: str) -> bool:
        """
        Проверить IP адрес в белом списке.

        Args:
            client_ip: IP адрес клиента

        Returns:
            True если IP разрешён
        """
        try:
            client = ipaddress.ip_address(client_ip)

            for allowed in self.config.allowed_ips:
                # Поддержка CIDR нотации (например 192.168.1.0/24)
                if "/" in allowed:
                    network = ipaddress.ip_network(allowed, strict=False)
                    if client in network:
                        return True
                # Точное совпадение IP
                else:
                    if client == ipaddress.ip_address(allowed):
                        return True

            return False

        except ValueError:
            logger.warning(f"Неверный формат IP: {client_ip}")
            return False


def require_auth(auth: GatewayAuth) -> Any:
    """
    Создать dependency для проверки аутентификации.

    Usage:
        @router.get("/protected")
        async def protected(
            request: Request,
            credentials: HTTPAuthorizationCredentials = Depends(require_auth(auth))
        ):
            return {"message": "OK"}

    Args:
        auth: Менеджер аутентификации

    Returns:
        Dependency функция
    """

    async def check(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(
            GatewayAuth.security
        ),
    ) -> None:
        await auth.authenticate(request, credentials)

    return check


# ============================================================================
# FASTAPI DEPENDENCY ДЛЯ УДОБНОГО ИСПОЛЬЗОВАНИЯ
# ============================================================================


def create_auth_dependency(auth: GatewayAuth) -> Any:
    """
    Создаёт dependency для использования в роутах.

    Пример использования в routes:
        from fastapi import Depends

        auth_dependency = create_auth_dependency(auth_manager)

        @router.get("/protected")
        async def protected(
            _: None = Depends(auth_dependency)
        ):
            return {"message": "OK"}

    Args:
        auth: Менеджер аутентификации

    Returns:
        Callable для Depends()
    """

    async def verify(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(
            GatewayAuth.security
        ),
    ) -> None:
        await auth.authenticate(request, credentials)

    return verify
