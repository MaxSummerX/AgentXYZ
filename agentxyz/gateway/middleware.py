"""Middleware для FastAPI канала."""

import time
from collections.abc import Callable
from typing import cast

from fastapi import Request, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware


class LoggingMiddleware(BaseHTTPMiddleware):
    """Логирует все запросы и ответы с таймингом."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Обрабатывает запрос и логирует его."""
        # Пропускаем health эндпоинт (слишком много логов)
        if request.url.path == "/health":
            return cast("Response", await call_next(request))

        # Логируем входящий запрос
        client_ip = self._get_client_ip(request)
        logger.info(f"➤ {request.method} {request.url.path} from {client_ip}")

        # Замеряем время выполнения
        start_time = time.time()

        try:
            response = await call_next(request)
            response = cast("Response", response)

            # Вычисляем время выполнения
            process_time = time.time() - start_time

            # Эмодзи индикатор статуса
            status_emoji = "✓" if response.status_code < 400 else "✗"

            # Логируем ответ
            logger.info(f"{status_emoji} {response.status_code} ({process_time:.2f}s)")

            # Добавляем заголовок с временем выполнения
            response.headers["X-Process-Time"] = str(process_time)

            return response

        except Exception as e:
            process_time = time.time() - start_time
            logger.error(
                f"✗ Ошибка: {e} ({process_time:.2f}s)",
                exc_info=e,
            )
            raise

    def _get_client_ip(self, request: Request) -> str:
        """Получает IP адрес клиента."""
        # Проверяем заголовки прокси
        forwarded: str | None = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()

        real_ip: str | None = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Иначе берем из client
        if request.client:
            return cast("str", request.client.host)

        return "unknown"
