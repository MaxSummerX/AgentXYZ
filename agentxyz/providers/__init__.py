"""Модуль абстракции провайдера LLM."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from agentxyz.providers.base import LLMProvider, LLMResponse


__all__ = ["CustomProvider", "LLMProvider", "LLMResponse", "LiteLLMProvider"]

_LAZY_IMPORTS = {
    "LiteLLMProvider": ".litellm_provider",
    "CustomProvider": ".custom_provider",
}

if TYPE_CHECKING:
    from agentxyz.providers.custom_provider import CustomProvider
    from agentxyz.providers.litellm_provider import LiteLLMProvider


def __getattr__(name: str) -> object:
    """Лениво экспортировать реализации провайдеров без предварительного импорта всех бэкендов."""
    module_name = _LAZY_IMPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    return getattr(module, name)
