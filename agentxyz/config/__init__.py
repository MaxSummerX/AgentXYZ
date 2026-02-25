"""Модуль конфигурации для agentxyz."""

from agentxyz.config.loader import get_config_path, load_config
from agentxyz.config.schema import Config


__all__ = ["Config", "get_config_path", "load_config"]
