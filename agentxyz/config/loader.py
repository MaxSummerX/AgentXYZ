"""Утилиты для загрузки конфигурации."""

import json
from pathlib import Path
from typing import cast

from agentxyz.config.schema import Config


def get_config_path() -> Path:
    """Получить путь к файлу конфигурации по умолчанию."""
    return Path.home() / ".agentxyz" / "config.json"


def get_data_dir() -> Path:
    """Получить директорию данных agentxyz."""
    from agentxyz.utils.helpers import get_data_path

    return get_data_path()


def load_config(config_path: Path | None = None) -> Config:
    """
    Загрузить конфигурацию из файла или создать по умолчанию.

    Args:
        config_path: Опциональный путь к файлу конфигурации. Используется путь по умолчанию, если не указан.

    Returns:
        Загруженный объект конфигурации.
    """
    path = config_path or get_config_path()

    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data = _migrate_config(data)
            return cast("Config", Config.model_validate(data))
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Warning: Failed to load config from {path}: {e}")
            print("Using default configuration.")

    return Config()


def save_config(config: Config, config_path: Path | None = None) -> None:
    """
    Сохранить конфигурацию в файл.

    Args:
        config: Конфигурация для сохранения.
        config_path: Опциональный путь для сохранения. Используется путь по умолчанию, если не указан.
    """

    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(by_alias=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _migrate_config(data: dict) -> dict:
    """Миграция старых форматов конфигурации в текущий."""
    # Перемещение tools.exec.restrictToWorkspace → tools.restrictToWorkspace
    tools = data.get("tools", {})
    exec_cfg = tools.get("exec", {})
    if "restrictToWorkspace" in exec_cfg and "restrictToWorkspace" not in tools:
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")
    return data
