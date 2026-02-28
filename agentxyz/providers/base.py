"""Базовый интерфейс поставщика LLM."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCallRequest:
    """Запрос на использование инструмента от LLM"""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Ответ от провайдера LLM услуг."""

    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    reasoning_content: str | None = None  # Kimi, DeepSeek-R1 etc.

    @property
    def has_tool_calls(self) -> bool:
        """Проверка, содержит ли ответ вызовы инструментов."""
        return len(self.tool_calls) > 0


class LLMProvider(ABC):
    """
    Абстрактный базовый класс для провайдера LLM услуг.

    Реализации должны учитывать специфику API каждого поставщика,
    при этом поддерживая согласованный интерфейс.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_base = api_base

    @staticmethod
    def _sanitize_empty_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Заменять пустой текстовый контент, вызывающий ошибки 400 от провайдера.

        Пустой контент может появляться, когда MCP инструменты ничего не возвращают.
        Большинство провайдеров отклоняют пустые строки или пустые текстовые блоки в списочном контенте.
        """
        result: list[dict[str, Any]] = []
        for msg in messages:
            content = msg.get("content")

            if isinstance(content, str) and not content:
                clean = dict(msg)
                clean["content"] = (
                    None
                    if (msg.get("role") == "assistant" and msg.get("tool_calls"))
                    else "(empty)"
                )
                result.append(clean)
                continue

            if isinstance(content, list):
                filtered = [
                    item
                    for item in content
                    if not (
                        isinstance(item, dict)
                        and item.get("type") in ("text", "input_text", "output_text")
                        and not item.get("text")
                    )
                ]
                if len(filtered) != len(content):
                    clean = dict(msg)
                    if filtered:
                        clean["content"] = filtered
                    elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                        clean["content"] = None
                    else:
                        clean["content"] = "(empty)"
                    result.append(clean)
                    continue

            result.append(msg)
        return result

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Отправить запрос на генерацию ответа.

        Args:
            messages: Список сообщений, где каждое имеет поля 'role' и 'content'.
            tools: Необязательный список определений инструментов.
            model: Идентификатор модели (зависит от провайдера).
            max_tokens: Максимальное количество токенов в ответе.
            temperature: Температура семплинга (параметр "креативности" модели. От 0 до 1).

        Returns:
            LLMResponse, содержащий контент и/или вызовы инструментов.
        """
        pass

    @abstractmethod
    def get_default_model(self) -> str:
        """Получить модель по умолчанию для данного провайдера."""
        pass
