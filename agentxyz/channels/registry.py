"""Авто-обнаружение модулей каналов — без жёстко прописанного реестра."""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

from loguru import logger


if TYPE_CHECKING:
    from agentxyz.channels.base import BaseChannel

_INTERNAL = frozenset({"base", "manager", "registry"})


def discover_channel_names() -> list[str]:
    """Вернуть все имена модулей каналов сканированием пакета (без импортов).

    Returns:
        Список имён модулей каналов, исключая внутренние (base, manager, registry).
    """
    import agentxyz.channels as pkg

    return [
        name
        for _, name, ispkg in pkgutil.iter_modules(pkg.__path__)
        if name not in _INTERNAL and not ispkg
    ]


def load_channel_class(module_name: str) -> type[BaseChannel]:
    """Импортировать модуль и вернуть первый найденный класс-наследник BaseChannel.

    Args:
        module_name: Имя модуля канала для импорта (например, "telegram", "email").

    Returns:
        Класс канала, наследующий BaseChannel.

    Raises:
        ImportError: Если в модуле не найден класс-наследник BaseChannel.
    """
    from agentxyz.channels.base import BaseChannel as _Base

    mod = importlib.import_module(f"agentxyz.channels.{module_name}")
    for attr in dir(mod):
        obj = getattr(mod, attr)
        if isinstance(obj, type) and issubclass(obj, _Base) and obj is not _Base:
            return obj
    raise ImportError(f"No BaseChannel subclass in agentxyz.channels.{module_name}")


def discover_plugins() -> dict[str, type[BaseChannel]]:
    """Обнаружить внешние плагины каналов, зарегистрированные через entry_points."""
    from importlib.metadata import entry_points

    plugins: dict[str, type[BaseChannel]] = {}
    for ep in entry_points(group="agentxyz.channels"):
        try:
            cls = ep.load()
            plugins[ep.name] = cls
        except Exception as e:
            logger.warning("Не удалось загрузить плагин канала '{}': {}", ep.name, e)
    return plugins


def discover_all() -> dict[str, type[BaseChannel]]:
    """Вернуть все каналы: встроенные (pkgutil) объединённые с внешними (entry_points).

    Встроенные каналы имеют приоритет — внешний плагин не может перезаписать встроенное имя.
    """
    builtin: dict[str, type[BaseChannel]] = {}
    for modname in discover_channel_names():
        try:
            builtin[modname] = load_channel_class(modname)
        except ImportError as e:
            logger.debug("Пропуск встроенного канала '{}': {}", modname, e)

    external = discover_plugins()
    shadowed = set(external) & set(builtin)
    if shadowed:
        logger.warning(
            "Плагин(ы) перезаписаны встроенными каналами (игнорируется): {}", shadowed
        )

    return {**external, **builtin}
