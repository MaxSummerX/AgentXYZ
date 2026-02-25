"""Типы событий для шины сообщений"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class InboundMessage:
    """Событие входящего сообщения"""

    channel: str  # telegram, email
    sender_id: str  # ID пользователя
    chat_id: str  # ID канала/чата
    content: str  # Текст сообщения
    timestamp: datetime = field(default_factory=datetime.now)
    media: list[str] = field(
        default_factory=list
    )  # Список URL-адресов вложенных медиафайлов
    metadata: dict[str, Any] = field(default_factory=dict)  # Метаданные канала
    session_key_override: str | None = (
        None  # Пользовательский ключ сессии. Если None — генерируется автоматически
    )

    @property
    def session_key(self) -> str:
        return self.session_key_override or f"{self.channel}:{self.chat_id}"


@dataclass
class OutboundMessage:
    """Событие исходящего сообщения"""

    channel: str  # telegram, email
    chat_id: str  # ID канала/чата
    content: str  # Текст сообщения
    replay_to: str | None = None  # ID сообщения, на которое отвечаем
    media: list[str] = field(
        default_factory=list
    )  # Список URL-адресов вложенных медиафайлов
    metadata: dict[str, Any] = field(default_factory=dict)  # Метаданные канала
