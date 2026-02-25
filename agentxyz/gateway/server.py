"""Gateway сервер для agentxyz - FastAPI веб-интерфейс."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import aiofiles
from loguru import logger


__version__ = "0.1.0"


if TYPE_CHECKING:
    import asyncio

from agentxyz.gateway.auth import GatewayAuth
from agentxyz.gateway.schemas import RootResponse
from agentxyz.gateway.websocket import WebSocketManager


if TYPE_CHECKING:
    from agentxyz.bus.events import InboundMessage, OutboundMessage
    from agentxyz.bus.queue import MessageBus
    from agentxyz.config.schema import Config, GatewayConfig
    from agentxyz.session.manager import SessionManager


class GatewayServer:
    """
    Gateway сервер для agentxyz.

    Предоставляет HTTP/WebSocket API интерфейс для агента через MessageBus.
    Не является каналом - это отдельный веб-сервер.
    """

    def __init__(
        self,
        config: GatewayConfig,
        bus: MessageBus,
        root_config: Config | None = None,
        session_manager: SessionManager | None = None,
    ) -> None:
        """
        Инициализировать Gateway сервер.

        Args:
            config: Конфигурация gateway
            bus: MessageBus для коммуникации
            root_config: Полная конфигурация агента (для доступа к transcription)
            session_manager: Менеджер сессий для получения истории
        """
        self.name = "gateway"

        self._root_config = root_config
        self._session_manager = session_manager
        self._bus = bus
        self.host = config.host
        self.port = config.port
        self.timeout = config.timeout

        # Очереди ожидающих ответов: session_id -> Queue
        self._pending_responses: dict[str, asyncio.Queue[OutboundMessage | None]] = {}

        # WebSocket менеджер
        self._websocket_manager: WebSocketManager | None = None

        # Менеджер аутентификации
        self._auth = GatewayAuth(config.auth)

        # FastAPI app (создаётся лениво при start())
        self._app: Any = None
        self._server: Any = None
        self._running = False

    @property
    def is_running(self) -> bool:
        """Проверяет, запущен ли сервер."""
        return self._running

    @property
    def websocket_manager(self) -> WebSocketManager:
        """Получить WebSocket менеджер."""
        if self._websocket_manager is None:
            self._websocket_manager = WebSocketManager()
        return self._websocket_manager

    def register_pending_response(
        self, session_id: str, queue: asyncio.Queue[OutboundMessage | None]
    ) -> None:
        """
        Зарегистрировать очередь для ожидания ответа сессии.

        Args:
            session_id: ID сессии
            queue: Очередь для ответа
        """
        self._pending_responses[session_id] = queue

    def unregister_pending_response(self, session_id: str) -> None:
        """
        Удалить очередь ожидания ответа сессии.

        Args:
            session_id: ID сессии
        """
        self._pending_responses.pop(session_id, None)

    @property
    def pending_requests_count(self) -> int:
        """Получить количество ожидающих ответа запросов."""
        return len(self._pending_responses)

    def get_pending_session_ids(self) -> list[str]:
        """Получить список session_id с ожидающими запросами."""
        return list(self._pending_responses.keys())

    @property
    def session_manager(self) -> Any:
        """Получить менеджер сессий."""
        return self._session_manager

    async def start(self) -> None:
        """Запустить Gateway сервер (блокирующий)."""
        self._running = True

        # Инициализировать WebSocket менеджер
        if self._websocket_manager is None:
            self._websocket_manager = WebSocketManager()

        # Создать FastAPI app
        self._app = self._create_app()

        # Запустить сервер
        logger.info(f"Gateway сервер запускается на {self.host}:{self.port}")

        import uvicorn

        config = uvicorn.Config(
            app=self._app,
            host=self.host,
            port=self.port,
            log_level="info",
        )
        self._server = uvicorn.Server(config)

        try:
            await self._server.serve()
        finally:
            self._running = False

    async def stop(self) -> None:
        """Остановить Gateway сервер."""
        logger.info("Остановка Gateway сервера...")
        self._running = False

        # Отменить все ожидающие запросы
        for queue in self._pending_responses.values():
            try:
                await queue.put(None)
            except Exception:
                pass
        self._pending_responses.clear()

        # Остановить сервер если запущен
        if self._server:
            self._server.should_exit = True

    def _create_app(self) -> Any:
        """Создать FastAPI приложение."""
        from fastapi import FastAPI, Request, Response
        from fastapi.responses import HTMLResponse, JSONResponse

        # Создать app с lifespan
        @asynccontextmanager
        async def lifespan(app: FastAPI) -> Any:
            # Startup
            self._running = True
            logger.info("Gateway приложение запущено")
            yield
            # Shutdown
            self._running = False
            logger.info("Gateway приложение остановлено")

        app = FastAPI(
            title="agentxyz Gateway",
            version=__version__,
            description="HTTP интерфейс для agentxyz",
            lifespan=lifespan,
        )

        # Сохранить ссылку на сервер, auth и config в app.state
        app.state.gateway = self
        app.state.auth = self._auth
        app.state.config = self._root_config
        app.state.bus = self._bus

        # Корневой эндпоинт
        @app.get("/", response_class=JSONResponse)
        async def root() -> RootResponse:
            """Корневой эндпоинт с информацией."""
            return RootResponse(
                service="agentxyz",
                channel="fastapi",
                version=__version__,
                endpoints={
                    "chat": "/api/v1/chat",
                    "stream": "/api/v1/chat/stream",
                    "websocket": "/api/v1/ws",
                    "health": "/health",
                    "admin": "/api/v1/admin/*",
                    "test_ui": "/test",
                },
            )

        # Health check
        @app.get("/health")
        async def health() -> dict[str, Any]:
            """Проверка здоровья."""
            return {
                "status": "ok",
                "service": "gateway",
                "running": self.is_running,
            }

        # Защита документации, если включена аутентификация
        if self._auth.is_enabled():
            from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html

            # /openapi.json должен быть открыт для Swagger UI
            # Защищаем только страницы документации
            @app.get("/docs", include_in_schema=False)
            async def docs_protected(request: Request) -> Response:
                """Swagger UI с защитой по токену."""
                # Проверить токен из Authorization header или query parameter
                token: str | None = None

                auth_header = request.headers.get("Authorization")
                if auth_header and auth_header.startswith("Bearer "):
                    token = auth_header[7:]
                else:
                    # Также попробовать query parameter
                    token = request.query_params.get("token")

                if not token or token != self._auth.token:
                    return JSONResponse(
                        status_code=401,
                        content={
                            "detail": "Требуется токен: ?token=<ваш_токен> или Authorization: Bearer <токен>"
                        },
                    )

                body = get_swagger_ui_html(
                    openapi_url="/openapi.json", title="API docs"
                ).body
                if isinstance(body, memoryview):
                    body = bytes(body)
                return HTMLResponse(body.decode())

            @app.get("/redoc", include_in_schema=False)
            async def redoc_protected(request: Request) -> Response:
                """ReDoc с защитой по токену."""
                # Проверить токен из Authorization header или query parameter
                token: str | None = None

                auth_header = request.headers.get("Authorization")
                if auth_header and auth_header.startswith("Bearer "):
                    token = auth_header[7:]
                else:
                    # Также попробовать query parameter
                    token = request.query_params.get("token")

                if not token or token != self._auth.token:
                    return JSONResponse(
                        status_code=401,
                        content={
                            "detail": "Требуется токен: ?token=<ваш_токен> или Authorization: Bearer <токен>"
                        },
                    )

                body = get_redoc_html(
                    openapi_url="/openapi.json", title="API docs"
                ).body
                if isinstance(body, memoryview):
                    body = bytes(body)
                return HTMLResponse(body.decode())

        # Подключить API роутеры
        from agentxyz.gateway.routes import api_router

        app.include_router(api_router)

        # CORS middleware
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.staticfiles import StaticFiles

        # Logging middleware
        from agentxyz.gateway.middleware import LoggingMiddleware

        app.add_middleware(LoggingMiddleware)

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # Настроить в production
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Static files for test UI
        from pathlib import Path as StdPath

        static_dir = StdPath(__file__).parent.parent / "static"
        if not static_dir.exists():
            # Fallback to old location for transition
            static_dir = (
                StdPath(__file__).parent.parent.parent
                / "channels"
                / "fastapi"
                / "static"
            )

        if static_dir.exists():
            app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

            @app.get("/test", include_in_schema=False)
            async def test_ui() -> HTMLResponse:
                """Test UI redirect."""
                async with aiofiles.open(static_dir / "index.html") as f:
                    content = await f.read()
                    return HTMLResponse(content)

        return app

    async def receive_from_agent(self, msg: OutboundMessage) -> None:
        """
        Получить исходящее сообщение от агента.

        Если сообщение для этого шлюза и есть ожидающая очередь,
        поместить сообщение туда.

        Args:
            msg: Исходящее сообщение от агента
        """
        # Обрабатывать только сообщения для этого шлюза
        if msg.channel != "gateway":
            return

        # Найти ожидающую очередь
        queue = self._pending_responses.get(msg.chat_id)
        if queue:
            await queue.put(msg)

        # Также отправить в WebSocket если есть активные соединения
        if self._websocket_manager and self._websocket_manager.has_session(msg.chat_id):
            ws_response = {
                "type": "response",
                "content": str(msg.content),
                "session_id": msg.chat_id,
                "done": True,
            }
            await self._websocket_manager.send_to_session(msg.chat_id, ws_response)

    async def send_to_agent(self, msg: InboundMessage) -> None:
        """
        Отправить сообщение агенту через MessageBus.

        Args:
            msg: Входящее сообщение
        """
        await self._bus.publish_inbound(msg)

    def get_agent_info(self) -> dict[str, Any]:
        """
        Получить информацию об агенте.

        Returns:
            Словарь с информацией об агенте
        """
        if self._root_config is None:
            return {"running": self.is_running}

        defaults = self._root_config.agents.defaults
        enabled_channels = [
            name
            for name, config in [
                ("telegram", self._root_config.channels.telegram),
                ("email", self._root_config.channels.email),
            ]
            if getattr(config, "enabled", False)
        ]

        return {
            "model": defaults.model,
            "temperature": defaults.temperature,
            "max_tokens": defaults.max_tokens,
            "workspace": str(defaults.workspace),
            "enabled_channels": enabled_channels,
            "running": self.is_running,
        }
