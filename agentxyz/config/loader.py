"""Утилиты для загрузки конфигурации"""

import json
from pathlib import Path
from typing import cast

from agentxyz.config.schema import Config


# Глобальная переменная для хранения текущего пути к конфигу (для поддержки нескольких инстансов)
_current_config_path: Path | None = None


def set_config_path(path: Path) -> None:
    """Установить текущий путь к конфигу (используется для определения директории данных)."""
    global _current_config_path
    _current_config_path = path


def get_config_path() -> Path:
    """Получить путь к файлу конфигурации по умолчанию."""
    if _current_config_path:
        return _current_config_path
    return Path.home() / ".agentxyz" / "config.json"


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
            print(f"Предупреждение: не удалось загрузить конфиг из {path}: {e}")
            print("Используется конфигурация по умолчанию.")

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
