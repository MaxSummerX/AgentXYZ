"""Вспомогательные утилиты для agentxyz."""

import re
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
    path = (
        Path(workspace).expanduser()
        if workspace
        else Path.home() / ".agentxyz" / "workspace"
    )
    return ensure_dir(path)


def timestamp() -> str:
    """Возвращает текущую метку времени в формате ISO 8601."""
    return datetime.now().isoformat()


_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')


def safe_filename(name: str) -> str:
    """Преобразует строку в безопасное имя файла."""
    # Замена небезопасных символов
    return _UNSAFE_CHARS.sub("_", name).strip()


def sync_workspace_templates(workspace: Path, silent: bool = False) -> list[str]:
    """Синхронизировать встроенные шаблоны с рабочим пространством. Создаёт только отсутствующие файлы.."""
    from importlib.resources import files as pkg_files
    from importlib.resources.abc import Traversable

    try:
        tpl = pkg_files("agentxyz") / "templates"
    except Exception:
        return []
    if not tpl.is_dir():
        return []

    added: list[str] = []

    def _write(src: Traversable | None, dest: Path) -> None:
        if dest.exists():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            src.read_text(encoding="utf-8") if src else "", encoding="utf-8"
        )
        added.append(str(dest.relative_to(workspace)))

    for item in tpl.iterdir():
        if item.name.endswith(".md"):
            _write(item, workspace / item.name)
    _write(tpl / "memory" / "MEMORY.md", workspace / "memory" / "MEMORY.md")
    _write(None, workspace / "memory" / "HISTORY.md")
    (workspace / "skills").mkdir(exist_ok=True)

    if added and not silent:
        from rich.console import Console

        for name in added:
            Console().print(f"  [dim]Создан {name}[/dim]")
    return added
