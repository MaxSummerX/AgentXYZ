"""Вспомогательные функции для работы с путями, основанные на активном контексте конфигурации."""

from __future__ import annotations

from pathlib import Path

from agentxyz.config.loader import get_config_path
from agentxyz.utils.helpers import ensure_dir


def get_data_dir() -> Path:
    """Возвращает директорию данных уровня инстанса."""
    return ensure_dir(get_config_path().parent)


def get_runtime_subdir(name: str) -> Path:
    """Возвращает именованную поддиректорию в директории данных инстанса."""
    return ensure_dir(get_data_dir() / name)


def get_media_dir(channel: str | None = None) -> Path:
    """Возвращает директорию медиа, опционально с пространством имён на канал."""
    base = get_runtime_subdir("media")
    return ensure_dir(base / channel) if channel else base


def get_cron_dir() -> Path:
    """Возвращает директорию хранения cron."""
    return get_runtime_subdir("cron")


def get_logs_dir() -> Path:
    """Возвращает директорию логов."""
    return get_runtime_subdir("logs")


def get_workspace_path(workspace: str | Path | None = None) -> Path:
    """Разрешает и гарантирует существование пути к рабочей области агента."""
    path = (
        Path(workspace).expanduser()
        if workspace
        else Path.home() / ".agentxyz" / "workspace"
    )
    return ensure_dir(path)


def get_cli_history_path() -> Path:
    """Возвращает путь к общему файлу истории CLI."""
    return Path.home() / ".agentxyz" / "history" / "cli_history"


def get_bridge_install_dir() -> Path:
    """Возвращает директорию установки общего WhatsApp моста."""
    return Path.home() / ".agentxyz" / "bridge"


def get_legacy_sessions_dir() -> Path:
    """Возвращает устаревшую глобальную директорию сессий, используемую как резерв при миграции."""
    return Path.home() / ".agentxyz" / "sessions"
