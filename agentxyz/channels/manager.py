"""Менеджер каналов для координации чат-каналов."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger


if TYPE_CHECKING:
    from agentxyz.bus.queue import MessageBus
    from agentxyz.channels.base import BaseChannel
    from agentxyz.config.schema import Config
    from agentxyz.session.manager import SessionManager


class ChannelManager:
    """
    Управляет чат-каналами и координирует маршрутизацию сообщений.

    Обязанности:
    - Инициализация включённых каналов (Telegram, Discord и др.)
    - Запуск/остановка каналов
    - Маршрутизация исходящих сообщений
    """

    def __init__(
        self,
        config: Config,
        bus: MessageBus,
        session_manager: SessionManager | None = None,
        gateway_server: Any = None,  # Для обработки gateway сообщений
    ):
        self.config = config
        self.bus = bus
        self.session_manager = session_manager
        self.channels: dict[str, BaseChannel] = {}
        self._dispatch_task: asyncio.Task | None = None
        self._gateway_server = gateway_server  # Сохранить ссылку на gateway

        self._init_channels()

    def _init_channels(self) -> None:
        """Инициализация каналов на основе конфигурации."""

        # Канал Telegram
        if self.config.channels.telegram.enabled:
            try:
                from agentxyz.channels.telegram import (
                    TelegramChannel,  # type: ignore[misc]
                )

                self.channels["telegram"] = TelegramChannel(
                    self.config.channels.telegram,
                    self.bus,
                    groq_api_key=self.config.providers.groq.api_key,
                )
                logger.info("Telegram канал включён")
            except ImportError as e:
                logger.warning("Telegram канал недоступен: {}", e)

        # Канал Email
        if self.config.channels.email.enabled:
            try:
                from agentxyz.channels.email import EmailChannel  # type: ignore[misc]

                self.channels["email"] = EmailChannel(
                    self.config.channels.email, self.bus
                )
                logger.info("Email канал включён")
            except ImportError as e:
                logger.warning("Email канал недоступен: {}", e)

    @staticmethod
    async def _start_channel(name: str, channel: BaseChannel) -> None:
        """Запустить канал и логировать любые исключения."""
        try:
            await channel.start()
        except Exception as e:
            logger.error("Не удалось запустить канал {}: {}", name, e)

    async def start_all(self) -> None:
        """Запустить все каналы и диспетчер исходящих сообщений."""
        if not self.channels:
            logger.warning("Нет включённых каналов")
            return

        # Запуск диспетчера исходящих
        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())

        # Запуск каналов
        tasks = []
        for name, channel in self.channels.items():
            logger.info("Запуск канала {}...", name)
            tasks.append(asyncio.create_task(self._start_channel(name, channel)))

        # Ждём завершения всех (они работают бесконечно)
        await asyncio.gather(*tasks, return_exceptions=True)

    async def stop_all(self) -> None:
        """Остановить все каналы и диспетчер."""
        logger.info("Остановка всех каналов...")

        # Остановка диспетчера
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass

        # Остановка всех каналов
        for name, channel in self.channels.items():
            try:
                await channel.stop()
                logger.info("Канал {} остановлен", name)
            except Exception as e:
                logger.error("Ошибка при остановке {}: {}", name, e)

    async def _dispatch_outbound(self) -> None:
        """Отправлять исходящие сообщения в соответствующий канал."""
        logger.info("Диспетчер исходящих запущен")

        while True:
            try:
                msg = await asyncio.wait_for(self.bus.consume_outbound(), timeout=1.0)

                if msg.metadata.get("_progress"):
                    if (
                        msg.metadata.get("_tool_hint")
                        and not self.config.channels.send_tool_hints
                    ):
                        continue
                    if (
                        not msg.metadata.get("_tool_hint")
                        and not self.config.channels.send_progress
                    ):
                        continue

                # Обработка gateway/fastapi сообщений
                if msg.channel in ("gateway", "fastapi") and self._gateway_server:
                    try:
                        await self._gateway_server.receive_from_agent(msg)
                    except Exception as e:
                        logger.error("Ошибка отправки в gateway: {}", e)
                    continue

                channel = self.channels.get(msg.channel)
                if channel:
                    try:
                        await channel.send(msg)
                    except Exception as e:
                        logger.error("Ошибка отправки в {}: {}", msg.channel, e)
                else:
                    logger.warning("Неизвестный канал: {}", msg.channel)

            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    def get_channel(self, name: str) -> BaseChannel | None:
        """Получить канал по имени."""
        return self.channels.get(name)

    def get_status(self) -> dict[str, Any]:
        """Получить статус всех каналов."""
        return {
            name: {"enabled": True, "running": channel.is_running}
            for name, channel in self.channels.items()
        }

    @property
    def enabled_channels(self) -> list[str]:
        """Получить перечень имён включённых каналов."""
        return list(self.channels.keys())
