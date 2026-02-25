"""API роуты для Gateway."""

from fastapi import APIRouter

from agentxyz.gateway.routes import admin, chat, stream, transcribe, websocket
from agentxyz.gateway.routes.auth_deps import AuthDepends


# Создать объединённый роутер
api_router = APIRouter(prefix="/api/v1")

# Подключить все роутеры
api_router.include_router(chat.router, tags=["chat"])
api_router.include_router(stream.router, tags=["stream"])
api_router.include_router(websocket.router, tags=["websocket"])
api_router.include_router(admin.router, tags=["admin"])
api_router.include_router(transcribe.router, tags=["transcribe"])

# Экспорт dependencies для использования в других роутах
__all__ = ["AuthDepends", "api_router"]
