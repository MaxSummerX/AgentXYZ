"""Вспомогательные утилиты для agentxyz."""

from datetime import datetime
from pathlib import Path


def ensure_dir(path: Path) -> Path:
    """Гарантирует существование директории, создаёт при необходимости."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_data_path() -> Path:
    """Возвращает путь к корневой директории данных agentxyz (~/.agentxyz)."""
    return ensure_dir(Path.home() / ".agentxyz")


def get_workspace_path(workspace: str | None = None) -> Path:
    """Возвращает путь к рабочей директории.

    Args:
        workspace: Опциональный путь к рабочей директории.
            По умолчанию ~/.agentxyz/workspace.

    Returns:
        Расширенный и гарантированно существующий путь.
    """
    if workspace:
        path = Path(workspace).expanduser()
    else:
        path = Path.home() / ".agentxyz" / "workspace"
    return ensure_dir(path)


def get_sessions_path() -> Path:
    """Получить директорию хранения сеансов."""
    return ensure_dir(get_data_path() / "sessions")


def get_skills_path(workspace: Path | None = None) -> Path:
    """Возвращает директорию навыков в рабочем пространстве."""
    ws = workspace or get_workspace_path()
    return ensure_dir(ws / "skills")


def timestamp() -> str:
    """Возвращает текущую метку времени в формате ISO 8601."""
    return datetime.now().isoformat()


def truncate_string(text: str, max_len: int = 100, suffix: str = "...") -> str:
    """Обрезает строку до указанной длины, добавляя суффикс при усечении."""
    if len(text) <= max_len:
        return text
    return text[: max_len - len(suffix)] + suffix


def safe_filename(name: str) -> str:
    """Преобразует строку в безопасное имя файла."""
    # Замена небезопасных символов
    unsafe = r'<>:"/\|?*'
    for char in unsafe:
        name = name.replace(char, "_")
    return name.strip()


def parse_session_key(key: str) -> tuple[str, str]:
    """
    Парсит ключ сессии на канал и идентификатор чата.

    Args:
        key: Ключ сессии в формате 'channel:chat_id'.

    Returns:
        Кортеж из (channel, chat_id).
    """
    parts = key.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid session key format: {key}")
    return parts[0], parts[1]
