"""Прямой OpenAI-совместимый провайдер — обходит LiteLLM."""

from __future__ import annotations

import uuid
from typing import Any, cast

import json_repair
from openai import AsyncOpenAI

from agentxyz.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class CustomProvider(LLMProvider):
    """
    Прямой OpenAI-совместимый провайдер, обходит LiteLLM.

    Использует AsyncOpenAI клиент напрямую для обращения к
    совместимым endpoint'ам (например, vLLM, Ollama, локальные модели).
    """

    def __init__(
        self,
        api_key: str = "no-key",
        api_base: str = "http://localhost:8000/v1",
        default_model: str = "default",
        extra_headers: dict[str, str] | None = None,
    ):
        """
        Инициализировать провайдер.

        Args:
            api_key: API-ключ для endpoint'а.
            api_base: Базовый URL OpenAI-совместимого API.
            default_model: Название модели по умолчанию.
        """
        super().__init__(api_key, api_base)
        self.default_model = default_model
        # Сохранять стабильность привязки для этого экземпляра провайдера, чтобы улучшить локальность кэша бэкенда,
        # при этом позволяя пользователям добавлять специфичные для провайдера заголовки для кастомных шлюзов.
        default_headers = {
            "x-session-affinity": uuid.uuid4().hex,
            **(extra_headers or {}),
        }
        # Удерживать affinity стабильным для этого экземпляра провайдера для улучшения локальности кэша бэкенда.
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            default_headers=default_headers,
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        """
        Отправить запрос на OpenAI-совместимый endpoint.

        Args:
            messages: Список сообщений диалога.
            tools: Опциональный список инструментов для вызова.
            model: Название модели (переопределяет default_model).
            max_tokens: Максимальное количество токенов в ответе.
            temperature: Температура генерации (0-1).
            reasoning_effort: Уровень усилий на рассуждение для моделей o1 (low/medium/high).
            tool_choice: Управление выбором инструмента ("auto", "none", имя функции или объект dict).

        Returns:
            LLMResponse с контентом и/или вызовами инструментов.
        """
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": self._sanitize_empty_content(messages),
            "max_tokens": max(1, max_tokens),
            "temperature": temperature,
        }
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        if tools:
            kwargs.update(tools=tools, tool_choice=tool_choice or "auto")
        try:
            return self._parse(await self._client.chat.completions.create(**kwargs))
        except Exception as e:
            return LLMResponse(content=f"Error: {e}", finish_reason="error")

    @staticmethod
    def _parse(response: Any) -> LLMResponse:
        """
        Парсить ответ OpenAI-совместимого API в LLMResponse.

        Args:
            response: Сырой ответ от AsyncOpenAI клиента.

        Returns:
            LLMResponse с извлечённым контентом, tool_calls и статистикой.
        """
        if not response.choices:
            return LLMResponse(
                content="Error: API returned empty choices. This may indicate a temporary service issue or an invalid model response.",
                finish_reason="error",
            )
        choice = response.choices[0]
        msg = choice.message
        tool_calls = [
            ToolCallRequest(
                id=tool_call.id,
                name=tool_call.function.name,
                arguments=cast(
                    "dict[str, Any]", json_repair.loads(tool_call.function.arguments)
                )
                if isinstance(tool_call.function.arguments, str)
                else tool_call.function.arguments or {},
            )
            for tool_call in (msg.tool_calls or [])
        ]
        u = response.usage
        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage={
                "prompt_tokens": u.prompt_tokens,
                "completion_tokens": u.completion_tokens,
                "total_tokens": u.total_tokens,
            }
            if u
            else {},
            reasoning_content=getattr(msg, "reasoning_content", None) or None,
        )

    def get_default_model(self) -> str:
        """Получить модель по умолчанию."""
        return self.default_model
