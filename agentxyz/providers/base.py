"""Базовый интерфейс поставщика LLM."""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


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
    thinking_blocks: list[dict] | None = None  # Режим расширенных рассуждений Anthropic

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

    _CHAT_RETRY_DELAYS = (1, 2, 4)
    _TRANSIENT_ERROR_MARKERS = (
        "429",
        "rate limit",
        "500",
        "502",
        "503",
        "504",
        "overloaded",
        "timeout",
        "timed out",
        "connection",
        "server error",
        "temporarily unavailable",
    )

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

            if isinstance(content, dict):
                clean = dict(msg)
                clean["content"] = [content]
                result.append(clean)
                continue

            result.append(msg)
        return result

    @staticmethod
    def _sanitize_request_messages(
        messages: list[dict[str, Any]],
        allowed_keys: frozenset[str],
    ) -> list[dict[str, Any]]:
        """Сохранять только безопасные для провайдера ключи сообщений и нормализовать контент ассистента."""
        sanitized = []
        for msg in messages:
            clean = {k: v for k, v in msg.items() if k in allowed_keys}
            if clean.get("role") == "assistant" and "content" not in clean:
                clean["content"] = None
            sanitized.append(clean)
        return sanitized

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        """
        Отправить запрос на генерацию ответа.

        Args:
            messages: Список сообщений, где каждое имеет поля 'role' и 'content'.
            tools: Необязательный список определений инструментов.
            model: Идентификатор модели (зависит от провайдера).
            max_tokens: Максимальное количество токенов в ответе.
            temperature: Температура семплинга (параметр "креативности" модели. От 0 до 1).
            reasoning_effort: Уровень усилий моделирования для моделей с расширенным рассуждением (o1, o3, DeepSeek-R1). Например: "low", "medium", "high".

        Returns:
            LLMResponse, содержащий контент и/или вызовы инструментов.
        """
        pass

    @classmethod
    def _is_transient_error(cls, content: str | None) -> bool:
        err = (content or "").lower()
        return any(marker in err for marker in cls._TRANSIENT_ERROR_MARKERS)

    async def chat_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        """Вызвать chat() с повторными попытками при временных ошибках провайдера."""
        for attempt, delay in enumerate(self._CHAT_RETRY_DELAYS, start=1):
            try:
                response = await self.chat(
                    messages=messages,
                    tools=tools,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                response = LLMResponse(
                    content=f"Error calling LLM: {exc}",
                    finish_reason="error",
                )

            if response.finish_reason != "error":
                return response
            if not self._is_transient_error(response.content):
                return response

            err = (response.content or "").lower()
            logger.warning(
                "Временная ошибка LLM (попытка {}/{}), повтор через {}s: {}",
                attempt,
                len(self._CHAT_RETRY_DELAYS),
                delay,
                err[:120],
            )
            await asyncio.sleep(delay)

        try:
            return await self.chat(
                messages=messages,
                tools=tools,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return LLMResponse(
                content=f"Error calling LLM: {exc}",
                finish_reason="error",
            )

    @abstractmethod
    def get_default_model(self) -> str:
        """Получить модель по умолчанию для данного провайдера."""
        pass
