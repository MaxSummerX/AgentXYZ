"""WebSocket connection менеджер для FastAPI канала."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger


if TYPE_CHECKING:
    from fastapi import WebSocket


class WebSocketManager:
    """
    Управляет WebSocket соединениями.

    Хранит активные соединения и рассылает сообщения по сессиям.
    """

    def __init__(self) -> None:
        # Активные WebSocket соединения: session_id -> set of WebSockets
        self._connections: dict[str, set[WebSocket]] = {}

        # WebSocket по ID (для отправки конкретному соединению)
        self._ws_to_session: dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        """
        Принять новое WebSocket соединение.

        Args:
            websocket: WebSocket соединение
            session_id: ID сессии
        """
        await websocket.accept()

        if session_id not in self._connections:
            self._connections[session_id] = set()

        self._connections[session_id].add(websocket)
        self._ws_to_session[websocket] = session_id

        logger.debug(f"WebSocket подключён: session={session_id}")

    async def disconnect(self, websocket: WebSocket) -> None:
        """
        Отключить WebSocket соединение.

        Args:
            websocket: WebSocket соединение
        """
        session_id = self._ws_to_session.pop(websocket, None)

        if session_id and session_id in self._connections:
            self._connections[session_id].discard(websocket)

            # Удалить пустую сессию
            if not self._connections[session_id]:
                del self._connections[session_id]

        logger.debug(f"WebSocket отключён: session={session_id}")

    async def send_to_session(self, session_id: str, message: dict[str, Any]) -> None:
        """
        Отправить сообщение всем WebSocket в сессии.

        Args:
            session_id: ID сессии
            message: Сообщение для отправки
        """
        if session_id not in self._connections:
            logger.debug(f"Нет WebSocket соединений для сессии {session_id}")
            return

        # Копия множества для безопасной итерации
        websockets = self._connections[session_id].copy()

        disconnected = []
        for ws in websockets:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.warning(f"Ошибка отправки WebSocket: {e}")
                disconnected.append(ws)

        # Очистить отключённые
        for ws in disconnected:
            await self.disconnect(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """
        Отправить сообщение всем активным WebSocket соединениям.

        Args:
            message: Сообщение для отправки
        """
        for session_id in list(self._connections.keys()):
            await self.send_to_session(session_id, message)

    def get_connection_count(self, session_id: str | None = None) -> int:
        """
        Получить количество активных соединений.

        Args:
            session_id: Если указан, вернуть количество для конкретной сессии

        Returns:
            Количество активных соединений
        """
        if session_id:
            return len(self._connections.get(session_id, set()))
        return sum(len(conns) for conns in self._connections.values())

    def get_active_sessions(self) -> list[str]:
        """
        Получить список активных сессий.

        Returns:
            Список ID сессий с активными WebSocket соединениями
        """
        return list(self._connections.keys())

    def has_session(self, session_id: str) -> bool:
        """
        Проверить наличие активных соединений для сессии.

        Args:
            session_id: ID сессии

        Returns:
            True если есть активные соединения
        """
        return (
            session_id in self._connections and len(self._connections[session_id]) > 0
        )
