"""Реализация провайдера LiteLLM для поддержки множества провайдеров"""

import hashlib
import os
import secrets
import string
from typing import Any

import json_repair
import litellm
from litellm import acompletion
from loguru import logger

from agentxyz.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from agentxyz.providers.registry import find_by_model, find_gateway


# Стандартные ключи сообщений OpenAI chat-completion; дополнительные (например, reasoning_content) удаляются для строгих провайдеров.
_ALLOWED_MSG_KEYS = frozenset(
    {"role", "content", "tool_calls", "tool_call_id", "name", "reasoning_content"}
)
_ANTHROPIC_EXTRA_KEYS = frozenset({"thinking_blocks"})
_ALNUM = string.ascii_letters + string.digits


def _short_tool_id() -> str:
    """Сгенерировать 9-символьный буквенно-цифровой идентификатор, совместимый со всеми провайдерами (включая Mistral)."""
    return "".join(secrets.choice(_ALNUM) for _ in range(9))


class LiteLLMProvider(LLMProvider):
    """
    Провайдер LLM через LiteLLM. Поддерживает множество API.

    Обеспечивает поддержку OpenRouter, Anthropic, OpenAI, Gemini и многих других
    провайдеров через единый интерфейс.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-6",
        extra_headers: dict[str, str] | None = None,
        provider_name: str | None = None,
    ) -> None:
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.extra_headers = extra_headers or {}

        # Определить шлюз / локальное развертывание.
        # provider_name (из ключа конфигурации) — основной сигнал;
        # api_key / api_base используются как резерв для автоопределения.
        self._gateway = find_gateway(provider_name, api_key, api_base)

        # Настроить переменные окружения
        if api_key:
            self._setup_env(api_key, api_base, default_model)

        if api_base:
            litellm.api_base = api_base

        # Отключить лишнее логирование LiteLLM
        litellm.suppress_debug_info = True
        # Отбрасывать неподдерживаемые параметры для провайдеров (например, gpt-5 отклоняет некоторые параметры)
        litellm.drop_params = True

    def _setup_env(self, api_key: str, api_base: str | None, model: str) -> None:
        """Установить переменные окружения на основе обнаруженного провайдера."""
        spec = self._gateway or find_by_model(model)
        if not spec:
            return
        if not spec.env_key:
            # Спецификации OAuth/только для провайдера (например: openai_codex)
            return

        # Шлюз/локальное развертывание перезаписывает существующие переменные окружения; стандартный провайдер — нет
        if self._gateway:
            os.environ[spec.env_key] = api_key
        else:
            os.environ.setdefault(spec.env_key, api_key)

        # Разрешить заполнители env_extras:
        #   {api_key}  → API-ключ пользователя
        #   {api_base} → api_base пользователя, с резервным вариантом spec.default_api_base
        effective_base = api_base or spec.default_api_base
        for env_name, env_val in spec.env_extras:
            resolved = env_val.replace("{api_key}", api_key)
            resolved = resolved.replace("{api_base}", effective_base)
            os.environ.setdefault(env_name, resolved)

    def _resolve_model(self, model: str) -> str:
        """Разрешить имя модели, применяя префиксы провайдера/шлюза."""
        if self._gateway:
            # Режим шлюза: применить префикс шлюза, пропустить специфичные для провайдера префиксы
            prefix = self._gateway.litellm_prefix
            if self._gateway.strip_model_prefix:
                model = model.split("/")[-1]
            if prefix and not model.startswith(f"{prefix}/"):
                model = f"{prefix}/{model}"
            return model

        # Стандартный режим: авто-префикс для известных провайдеров
        spec = find_by_model(model)
        if spec and spec.litellm_prefix:
            model = self._canonicalize_explicit_prefix(
                model, spec.name, spec.litellm_prefix
            )
            if not any(model.startswith(s) for s in spec.skip_prefixes):
                model = f"{spec.litellm_prefix}/{model}"

        return model

    @staticmethod
    def _canonicalize_explicit_prefix(
        model: str, spec_name: str, canonical_prefix: str
    ) -> str:
        """Нормализация явных префиксов провайдеров, таких как `github-copilot/...`."""
        if "/" not in model:
            return model
        prefix, remainder = model.split("/", 1)
        if prefix.lower().replace("-", "_") != spec_name:
            return model
        return f"{canonical_prefix}/{remainder}"

    def _supports_cache_control(self, model: str) -> bool:
        """Возвращает True если провайдер поддерживает cache_control для блоков контента"""
        if self._gateway is not None:
            return self._gateway.supports_prompt_caching
        spec = find_by_model(model)
        return spec is not None and spec.supports_prompt_caching

    @staticmethod
    def _apply_cache_control(
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        """Возвращает копии сообщений и инструментов с внедрённым cache_control."""
        new_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg["content"]
                if isinstance(content, str):
                    new_content = [
                        {
                            "type": "text",
                            "text": content,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ]
                else:
                    new_content = list(content)
                    new_content[-1] = {
                        **new_content[-1],
                        "cache_control": {"type": "ephemeral"},
                    }
                new_messages.append({**msg, "content": new_content})
            else:
                new_messages.append(msg)

        new_tools = tools
        if tools:
            new_tools = list(tools)
            new_tools[-1] = {**new_tools[-1], "cache_control": {"type": "ephemeral"}}

        return new_messages, new_tools

    @staticmethod
    def _apply_model_overrides(model: str, kwargs: dict[str, Any]) -> None:
        """Применить переопределения параметров для конкретной модели из реестра."""
        model_lower = model.lower()
        spec = find_by_model(model)
        if spec:
            for pattern, overrides in spec.model_overrides:
                if pattern in model_lower:
                    kwargs.update(overrides)
                    return

    @staticmethod
    def _extra_msg_keys(original_model: str, resolved_model: str) -> frozenset[str]:
        """Вернуть специфичные для провайдера дополнительные ключи для сохранения в запросах сообщений."""
        spec = find_by_model(original_model) or find_by_model(resolved_model)
        if (
            (spec and spec.name == "anthropic")
            or "claude" in original_model.lower()
            or resolved_model.startswith("anthropic/")
        ):
            return _ANTHROPIC_EXTRA_KEYS
        return frozenset()

    @staticmethod
    def _normalize_tool_call_id(tool_call_id: Any) -> Any:
        """Нормализовать tool_call_id в безопасную для провайдера буквенно-цифровую форму из 9 символов."""
        if not isinstance(tool_call_id, str):
            return tool_call_id
        if len(tool_call_id) == 9 and tool_call_id.isalnum():
            return tool_call_id
        return hashlib.sha1(tool_call_id.encode()).hexdigest()[:9]

    @staticmethod
    def _sanitize_messages(
        messages: list[dict[str, Any]], extra_keys: frozenset[str] = frozenset()
    ) -> list[dict[str, Any]]:
        """Удалить нестандартные ключи и убедиться, что сообщения ассистента имеют ключ content."""
        allowed = _ALLOWED_MSG_KEYS | extra_keys
        sanitized = LLMProvider._sanitize_request_messages(messages, allowed)
        id_map: dict[str, str] = {}

        def map_id(value: Any) -> Any:
            if not isinstance(value, str):
                return value
            return id_map.setdefault(
                value, LiteLLMProvider._normalize_tool_call_id(value)
            )

        for clean in sanitized:
            # Синхронизировать tool_calls[].id ассистента и tool_call_id инструмента после
            # сокращения, иначе строгие провайдеры отклоняют нарушенную связь.
            if isinstance(clean.get("tool_calls"), list):
                normalized_tool_calls = []
                for tc in clean["tool_calls"]:
                    if not isinstance(tc, dict):
                        normalized_tool_calls.append(tc)
                        continue
                    tc_clean = dict(tc)
                    tc_clean["id"] = map_id(tc_clean.get("id"))
                    normalized_tool_calls.append(tc_clean)
                clean["tool_calls"] = normalized_tool_calls

            if clean.get("tool_call_id"):
                clean["tool_call_id"] = map_id(clean["tool_call_id"])
        return sanitized

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
        Отправить запрос на генерацию ответа через LiteLLM

        Args:
            messages: Список сообщений, где каждое имеет поля 'role' и 'content'.
            tools: Необязательный список определений инструментов в формате OpenAI.
            model: Идентификатор модели (зависит от провайдера).
            max_tokens: Максимальное количество токенов в ответе.
            temperature: Температура семплинга (параметр "креативности" модели. От 0 до 1).
            reasoning_effort: Уровень усилий на рассуждение для моделей o1 (low/medium/high).

        Returns:
            LLMResponse, содержащий контент и/или вызовы инструментов.
        """
        # Определяем модель: сохраняем оригинальное имя и разрешаем через реестр
        original_model = model or self.default_model
        # _resolve_model добавляет префикс провайдера (например, "anthropic/claude-3-5-sonnet")
        # и нормализует имя модели для вызова через LiteLLM
        model = self._resolve_model(original_model)
        extra_msg_keys = self._extra_msg_keys(original_model, model)

        # Если провайдер поддерживает prompt caching (Anthropic), добавляем cache_control
        # в системное сообщение и последний tool — это позволяет кэшировать длинный контекст
        # и снижает стоимость повторных запросов с тем же промптом
        if self._supports_cache_control(original_model):
            messages, tools = self._apply_cache_control(messages, tools)

        # Ограничиваем max_tokens минимумом 1 — отрицательные или нулевые значения
        # вызывают ошибку LiteLLM: "max_tokens must be at least 1".
        max_tokens = max(1, max_tokens)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": self._sanitize_messages(
                self._sanitize_empty_content(messages), extra_keys=extra_msg_keys
            ),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        # Применить переопределения для конкретной модели (например, температура для kimi-k2.5)
        self._apply_model_overrides(model, kwargs)

        # Передавать api_key напрямую — надёжнее, чем только переменные окружения
        if self.api_key:
            kwargs["api_key"] = self.api_key

        # Загружаем endpoint из конфигурационного файла
        if self.api_base:
            kwargs["api_base"] = self.api_base

        # Передать дополнительные заголовки (например, APP-Code для AiHubMix)
        if self.extra_headers:
            kwargs["extra_headers"] = self.extra_headers

        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
            kwargs["drop_params"] = True

        # Добавляем к словарю запрос вызовы инструментов если есть
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            # Отправляем запрос через метод LiteLLM
            response = await acompletion(**kwargs)
            # Возвращаем обработанный объект
            return self._parse_response(response)
        except Exception as e:
            # Возвращаем ошибку как content для корректной обработки
            return LLMResponse(
                content=f"Ошибка вызова LLM: {e!s}",
                finish_reason="error",
            )

    @staticmethod
    def _parse_response(response: Any) -> LLMResponse:
        """
        Парсит ответ от LiteLLM в формат LLMResponse.

        Args:
            response: Сырой ответ от LiteLLM

        Returns:
            LLMResponse, содержащий контент, вызовы инструментов и статистику
        """
        # Получаем первый (и единственный) выбор из ответа модели
        choice = response.choices[0]
        message = choice.message
        content = message.content
        finish_reason = choice.finish_reason

        # Некоторые провайдеры разделяют content и tool_calls
        # на несколько вариантов. Объединяем их, чтобы tool_calls не потерялись.
        raw_tool_calls = []
        for ch in response.choices:
            msg = ch.message
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                raw_tool_calls.extend(msg.tool_calls)
                if ch.finish_reason in ("tool_calls", "stop"):
                    finish_reason = ch.finish_reason
            if not content and msg.content:
                content = msg.content

        if len(response.choices) > 1:
            logger.debug(
                "LiteLLM response has {} choices, merged {} tool_calls",
                len(response.choices),
                len(raw_tool_calls),
            )

        # Обрабатываем вызовы инструментов (tool calls), если они есть
        tool_calls = []
        for tool_call in raw_tool_calls:
            # Парсим аргументы из JSON-строки при необходимости
            args = tool_call.function.arguments
            if isinstance(args, str):
                args = json_repair.loads(args)

            tool_calls.append(
                ToolCallRequest(
                    id=_short_tool_id(),
                    name=tool_call.function.name,
                    arguments=args,
                )
            )

        # Собираем статистику использования токенов, если она есть в ответе
        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        reasoning_content = getattr(message, "reasoning_content", None) or None
        thinking_blocks = getattr(message, "thinking_blocks", None) or None

        # Формируем и возвращаем итоговый объект LLMResponse
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason or "stop",
            usage=usage,
            reasoning_content=reasoning_content,
            thinking_blocks=thinking_blocks,
        )

    def get_default_model(self) -> str:
        """Получить модель по умолчанию для данного провайдера."""
        return self.default_model
