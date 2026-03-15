"""Базовый интерфейс канала для чат-платформ.

Этот модуль определяет абстрактный базовый класс BaseChannel, который должен
реализовывать каждый чат-канал (Telegram, email и др.) для интеграции в
систему agentxyz.

Канал отвечает за:
- Подключение к чат-платформе
- Приём входящих сообщений от пользователей
- Отправку исходящих сообщений пользователям
- Проверку прав доступа через белый список
- Маршрутизацию сообщений через MessageBus

Пример использования:
    channel = TelegramChannel(config, message_bus)
    await channel.start()
    # Канал начинает приём и отправку сообщений
    await channel.stop()
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from loguru import logger

from agentxyz.bus.events import InboundMessage, OutboundMessage
from agentxyz.bus.queue import MessageBus


class BaseChannel(ABC):
    """
    Абстрактный базовый класс для реализаций чат-каналов.

    Каждый канал (Telegram, email и др.) должен реализовать этот интерфейс
    для интеграции в шину сообщений agentxyz.
    """

    name: str = "base"
    display_name: str = "Base"
    transcription_api_key: str = ""

    def __init__(self, config: Any, bus: MessageBus):
        """
        Инициализация канала.

        Args:
            config: Конфигурация канала.
            bus: Шина сообщений для коммуникации.
        """
        self.config = config
        self.bus = bus
        self._running = False

    async def transcribe_audio(self, file_path: str | Path) -> str:
        """Транскрибировать аудиофайл в текст с помощью Whisper."""
        if not self.transcription_api_key:
            return ""
        try:
            from agentxyz.providers.transcription import WhisperTranscriptionProvider

            provider = WhisperTranscriptionProvider()
            return await provider.transcribe(file_path)
        except Exception as e:
            logger.warning("{}: audio transcription failed: {}", self.name, e)
            return ""

    @abstractmethod
    async def start(self) -> None:
        """
        Запустить канал и начать приём сообщений.

        Это должна быть долго работающая асинхронная задача, которая:
        1. Подключается к чат-платформе
        2. Слушает входящие сообщения
        3. Перенаправляет сообщения в шину через _handle_message()
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Остановить канал и освободить ресурсы."""
        pass

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """
        Отправить сообщение через этот канал.

        Args:
            msg: Сообщение для отправки.
        """
        pass

    def is_allowed(self, sender_id: str) -> bool:
        """
        Проверить, имеет ли отправитель право использовать бота.

        Args:
            sender_id: Идентификатор отправителя.

        Returns:
            True если разрешён, иначе False.
        """
        allow_list = getattr(self.config, "allow_from", [])

        # Если белый список пуст, разрешаем всем
        if not allow_list:
            logger.warning("{}: allow_from пустой — весь доступ запрещён", self.name)
            return False
        if "*" in allow_list:
            return True

        return str(sender_id) in allow_list

    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        session_key: str | None = None,
    ) -> None:
        """
        Обработать входящее сообщение от чат-платформы.

        Этот метод проверяет права доступа и перенаправляет в шину.

        Args:
            sender_id: Идентификатор отправителя.
            chat_id: Идентификатор чата/канала.
            content: Текстовое содержание сообщения.
            media: Опциональный перечень URL медиафайлов.
            metadata: Опциональные метаданные канала.
        """
        if not self.is_allowed(sender_id):
            logger.warning(
                "Доступ запрещён для {} на канале {}. Добавьте в allowFrom в конфиге для доступа.",
                sender_id,
                self.name,
            )
            return

        msg = InboundMessage(
            channel=self.name,
            sender_id=str(sender_id),
            chat_id=str(chat_id),
            content=content,
            media=media or [],
            metadata=metadata or {},
            session_key_override=session_key,
        )

        await self.bus.publish_inbound(msg)

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        """Вернуть конфигурацию по умолчанию для onboard. Переопределить в плагинах для автозаполнения config.json."""
        return {"enabled": False}

    @property
    def is_running(self) -> bool:
        """Проверить, работает ли канал."""
        return self._running
