"""Модуль шины сообщений для развязанной коммуникации между каналами и агентами."""

from agentxyz.bus.events import InboundMessage, OutboundMessage
from agentxyz.bus.queue import MessageBus


__all__ = [
    "InboundMessage",
    "MessageBus",
    "OutboundMessage",
]
