"""Асинхронная шина сообщений для развязанной коммуникации между каналами и агентом."""

import asyncio

from agentxyz.bus.events import InboundMessage, OutboundMessage


class MessageBus:
    """
    Асинхронная шина сообщений, развязывающая чат-каналы и ядро агента.

    Каналы помещают сообщения во входящую очередь, а агент обрабатывает их.
    После чего помещает ответы в исходящую очередь.
    """

    def __init__(self) -> None:
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, message: InboundMessage) -> None:
        """Публикация сообщения от канала к агенту."""
        await self.inbound.put(message)

    async def consume_inbound(self) -> InboundMessage:
        """Читать следующее входящее сообщение от канала (ожидает появления, если очередь пуста)."""
        return await self.inbound.get()

    async def publish_outbound(self, message: OutboundMessage) -> None:
        """Публикация сообщения от агента для каналов."""
        await self.outbound.put(message)

    async def consume_outbound(self) -> OutboundMessage:
        """Читать следующее исходящее сообщение от агента (ожидает появления, если очередь пуста)."""
        return await self.outbound.get()

    @property
    def inbound_size(self) -> int:
        """Количество ожидающих входящих сообщений."""
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        """Количество ожидающих исходящих сообщений."""
        return self.outbound.qsize()
