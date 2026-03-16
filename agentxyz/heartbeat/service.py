"""Сервис Heartbeat для периодического пробуждения агента."""

import asyncio
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from loguru import logger

from agentxyz.providers.base import LLMProvider


_HEARTBEAT_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "heartbeat",
            "description": "Report heartbeat decision after reviewing tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["skip", "run"],
                        "description": "skip = nothing to do, run = has active tasks",
                    },
                    "tasks": {
                        "type": "string",
                        "description": "Natural-language summary of active tasks (required for run)",
                    },
                },
                "required": ["action"],
            },
        },
    }
]


class HeartbeatService:
    """
    Периодический сервис пробуждения агента для проверки задач.

    Фаза 1 (решение): читает HEARTBEAT.md и спрашивает LLM — через виртуальный
    вызов инструмента — есть ли активные задачи. Это позволяет избежать
    парсинга свободного текста и ненадёжного токена HEARTBEAT_OK.

    Фаза 2 (выполнение): запускается только если фаза 1 вернула ``run``.
    Колбэк ``on_execute`` выполняет задачу через полный цикл агента и
    возвращает результат для доставки
    """

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        on_execute: Callable[[str], Coroutine[Any, Any, str]] | None = None,
        on_notify: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        interval_s: int = 30 * 60,
        enabled: bool = True,
    ):
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.on_execute = on_execute
        self.on_notify = on_notify
        self.interval_s = interval_s
        self.enabled = enabled
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def heartbeat_file(self) -> Path:
        return self.workspace / "HEARTBEAT.md"

    def _read_heartbeat_file(self) -> str | None:
        """Прочитать содержимое HEARTBEAT.md."""
        if self.heartbeat_file.exists():
            try:
                return self.heartbeat_file.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    async def _decide(self, content: str) -> tuple[str, str]:
        """
        Фаза 1: запрашивает у LLM решение пропустить/выполнить через виртуальный вызов инструмента.

        Возвращает (action, tasks), где action — 'skip' или 'run'.
        """
        from agentxyz.utils.helpers import current_time_str

        response = await self.provider.chat_with_retry(
            messages=[
                {
                    "role": "system",
                    "content": "You are a heartbeat agent. Call the heartbeat tool to report your decision.",
                },
                {
                    "role": "user",
                    "content": (
                        f"Current Time: {current_time_str()}\n\n"
                        "Review the following HEARTBEAT.md and decide whether there are active tasks.\n\n"
                        f"{content}"
                    ),
                },
            ],
            tools=_HEARTBEAT_TOOL,
            model=self.model,
        )

        if not response.has_tool_calls:
            return "skip", ""

        args = response.tool_calls[0].arguments
        return args.get("action", "skip"), args.get("tasks", "")

    async def start(self) -> None:
        """Запустить сервис heartbeat."""
        if not self.enabled:
            logger.info("Heartbeat отключён")
            return

        if self._running:
            logger.warning("Heartbeat уже запущен")
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
        from agentxyz.utils.evaluator import evaluate_response

        content = self._read_heartbeat_file()

        # Пропуск, если HEARTBEAT.md пуст или не существует
        if not content:
            logger.debug("Heartbeat: нет задач (HEARTBEAT.md пуст)")
            return

        logger.info("Heartbeat: проверка задач...")

        try:
            action, tasks = await self._decide(content)

            # Проверить, ответил ли агент "ничего не делать"
            if action != "run":
                logger.info("Heartbeat: OK (действий не требуется)")
                return

            logger.info("Heartbeat: задачи найдены, выполнение...")

            if self.on_execute:
                response = await self.on_execute(tasks)

                if response:
                    should_notify = await evaluate_response(
                        response,
                        tasks,
                        self.provider,
                        self.model,
                    )
                    if should_notify and self.on_notify:
                        logger.info("Heartbeat: завершено, доставка ответа")
                        await self.on_notify(response)
                    else:
                        logger.info("Heartbeat: подавлен пост-оценкой")
        except Exception:
            logger.exception("Сбой выполнения Heartbeat")

    async def trigger_now(self) -> str | None:
        """Запустить heartbeat вручную."""
        content = self._read_heartbeat_file()
        if not content:
            return None
        action, tasks = await self._decide(content)
        if action != "run" or not self.on_execute:
            return None
        return await self.on_execute(tasks)
