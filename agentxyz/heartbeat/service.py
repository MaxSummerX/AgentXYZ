"""Сервис Heartbeat для периодического пробуждения агента."""

import asyncio
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from loguru import logger


# Интервал по умолчанию: 30 минут
DEFAULT_HEARTBEAT_INTERVAL_S = 30 * 60

# Токен, обозначающий "ничего не делать"
HEARTBEAT_OK_TOKEN = "HEARTBEAT_OK"

# Промпт, отправляемый агенту при heartbeat
HEARTBEAT_PROMPT = (
    "Read HEARTBEAT.md in your workspace and follow any instructions listed there. "
    f"If nothing needs attention, reply with exactly: {HEARTBEAT_OK_TOKEN}"
)


def _is_heartbeat_empty(content: str | None) -> bool:
    """Проверить, нет ли задач в HEARTBEAT.md."""
    if not content:
        return True

    # Пропускаемые строки: пустые, заголовки, HTML-комментарии, пустые чекбоксы
    skip_patterns = {"- [ ]", "* [ ]", "- [x]", "* [x]"}

    for line in content.split("\n"):
        line = line.strip()
        if (
            not line
            or line.startswith("#")
            or line.startswith("<!--")
            or line in skip_patterns
        ):
            continue
        return False  # Найдено содержимое для выполнения

    return True


class HeartbeatService:
    """
    Периодический сервис пробуждения агента для проверки задач.

    Агент читает HEARTBEAT.md из рабочей области и выполняет указанные
    там задачи. Если есть что сообщить, ответ пересылается пользователю через
    on_notify. Если действий не требуется, агент отвечает HEARTBEAT_OK,
    и ответ автоматически отбрасывается.
    """

    def __init__(
        self,
        workspace: Path,
        on_heartbeat: Callable[[str], Coroutine[Any, Any, str]] | None = None,
        on_notify: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        interval_s: int = DEFAULT_HEARTBEAT_INTERVAL_S,
        enabled: bool = True,
    ):
        """
        Инициализировать сервис heartbeat.

        Args:
            workspace: Рабочая директория с HEARTBEAT.md.
            on_heartbeat: Асинхронная функция, вызываемая с промптом для агента.
                          Возвращает ответ агента.
            on_notify: Асинхронная функция для отправки уведомлений пользователю.
            interval_s: Интервал между проверками в секундах.
            enabled: Включён ли сервис.
        """
        self.workspace = workspace
        self.on_heartbeat = on_heartbeat
        self.on_notify = on_notify
        self.interval_s = interval_s
        self.enabled = enabled
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def heartbeat_file(self) -> Path:
        """Путь к файлу HEARTBEAT.md в рабочей директории."""
        return self.workspace / "HEARTBEAT.md"

    def _read_heartbeat_file(self) -> str | None:
        """Прочитать содержимое HEARTBEAT.md."""
        if self.heartbeat_file.exists():
            try:
                return self.heartbeat_file.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    async def start(self) -> None:
        """Запустить сервис heartbeat."""
        if not self.enabled:
            logger.info("Heartbeat отключён")
            return

        if self._task is not None:
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Heartbeat запущен (каждые {} секунд)", self.interval_s)

    def stop(self) -> None:
        """Остановить сервис heartbeat."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        """Основной цикл heartbeat."""
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat: ошибка: {}", e)

    async def _tick(self) -> None:
        """Выполнить один тик сервиса heartbeat."""
        content = self._read_heartbeat_file()

        # Пропуск, если HEARTBEAT.md пуст или не существует
        if _is_heartbeat_empty(content):
            logger.debug("Heartbeat: нет задач (HEARTBEAT.md пуст)")
            return

        logger.info("Heartbeat: проверка задач...")

        if self.on_heartbeat:
            try:
                response = await self.on_heartbeat(HEARTBEAT_PROMPT)

                # Проверить, ответил ли агент "ничего не делать"
                if HEARTBEAT_OK_TOKEN in response.upper():
                    logger.info("Heartbeat: OK (действий не требуется)")
                else:
                    logger.info("Heartbeat: задача выполнена")
                    if self.on_notify:
                        await self.on_notify(response)
            except Exception:
                logger.exception("Heartbeat execution failed")

    async def trigger_now(self) -> str | None:
        """Запустить heartbeat вручную."""
        if self.on_heartbeat:
            return await self.on_heartbeat(HEARTBEAT_PROMPT)
        return None
