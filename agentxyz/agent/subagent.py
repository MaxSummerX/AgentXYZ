"""Менеджер субагентов для выполнения фоновых задач."""

import asyncio
import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from agentxyz.agent.tools.filesystem import (
    EditFileTool,
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
)
from agentxyz.agent.tools.registry import ToolRegistry
from agentxyz.agent.tools.shell import ExecTool
from agentxyz.agent.tools.web import WebFetchTool, WebSearchTool
from agentxyz.bus.events import InboundMessage
from agentxyz.bus.queue import MessageBus
from agentxyz.providers.base import LLMProvider


if TYPE_CHECKING:
    from agentxyz.config.schema import ExecToolConfig


class SubagentManager:
    """
    Управляет выполнением фоновых субагентов.

    Субагенты — это облегчённые экземпляры агента, которые работают в фоне
    для выполнения определённых задач. Они используют того же провайдера LLM,
    но имеют изолированный контекст и сфокусированный системный промпт.
    """

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        restrict_to_workspace: bool = False,
    ):
        from agentxyz.config.schema import ExecToolConfig

        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or provider.get_default_model()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._session_tasks: dict[str, set[str]] = {}  # session_key -> {task_id, ...}

    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        session_key: str | None = None,
    ) -> str:
        """
        Запустить субагента для выполнения задачи в фоне.

        Args:
            task: Описание задачи для субагента.
            label: Опциональная читаемая метка для задачи.
            origin_channel: Канал для анонсирования результатов.
            origin_chat_id: ID чата для анонсирования результатов.
            session_key: Ключ сессии для отслеживания связанных задач.

        Returns:
            Статусное сообщение, указывающее, что субагент был запущен.
        """
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")

        origin = {
            "channel": origin_channel,
            "chat_id": origin_chat_id,
        }

        # Создать фоновую задачу
        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin)
        )
        self._running_tasks[task_id] = bg_task
        if session_key:
            self._session_tasks.setdefault(session_key, set()).add(task_id)

        def _cleanup(_: asyncio.Task) -> None:
            self._running_tasks.pop(task_id, None)
            if session_key and (ids := self._session_tasks.get(session_key)):
                ids.discard(task_id)
                if not ids:
                    del self._session_tasks[session_key]

        bg_task.add_done_callback(_cleanup)

        logger.info("Запущен субагент [{}]: {}", task_id, display_label)
        return f"Subagent [{display_label}] started (id: {task_id}). I'll notify you when it completes."

    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
    ) -> None:
        """Выполнить задачу субагента и анонсировать результат."""
        logger.info("Субагент [{}] начинает задачу: {}", task_id, label)

        try:
            # Собрать инструменты субагента (без message-инструмента, без spawn-инструмента)
            tools = ToolRegistry()
            allowed_dir = self.workspace if self.restrict_to_workspace else None
            tools.register(
                ReadFileTool(workspace=self.workspace, allowed_dir=allowed_dir)
            )
            tools.register(
                WriteFileTool(workspace=self.workspace, allowed_dir=allowed_dir)
            )
            tools.register(
                EditFileTool(workspace=self.workspace, allowed_dir=allowed_dir)
            )
            tools.register(
                ListDirTool(workspace=self.workspace, allowed_dir=allowed_dir)
            )
            tools.register(
                ExecTool(
                    working_dir=str(self.workspace),
                    timeout=self.exec_config.timeout,
                    restrict_to_workspace=self.restrict_to_workspace,
                )
            )
            tools.register(WebSearchTool())
            tools.register(WebFetchTool())

            # Построить сообщения со специфическим промптом субагента
            system_prompt = self._build_subagent_prompt(task)
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]

            # Запуск цикла агента (ограниченное количество итераций)
            max_iterations = 15
            iteration = 0
            final_result: str | None = None

            while iteration < max_iterations:
                iteration += 1

                response = await self.provider.chat(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    reasoning_effort=self.reasoning_effort,
                )

                if response.has_tool_calls:
                    # Добавить сообщение ассистента с вызовами инструментов
                    tool_call_dicts = [
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_call.name,
                                "arguments": json.dumps(
                                    tool_call.arguments, ensure_ascii=False
                                ),
                            },
                        }
                        for tool_call in response.tool_calls
                    ]
                    messages.append(
                        {
                            "role": "assistant",
                            "content": response.content or "",
                            "tool_calls": tool_call_dicts,
                        }
                    )

                    # Выполнить инструменты
                    for tool_call in response.tool_calls:
                        args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                        logger.debug(
                            "Субагент [{}] выполняет: {} с аргументами: {}",
                            task_id,
                            tool_call.name,
                            args_str,
                        )
                        result = await tools.execute(
                            tool_call.name, tool_call.arguments
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": tool_call.name,
                                "content": result,
                            }
                        )
                else:
                    final_result = response.content
                    break

            if final_result is None:
                final_result = "task completed but no final response was generated."

            logger.info("Субагент [{}] успешно завершён", task_id)
            await self._announce_result(
                task_id, label, task, final_result, origin, "ok"
            )

        except Exception as e:
            error_msg = f"Ошибка: {e!s}"
            logger.error("Субагент [{}] завершился с ошибкой: {}", task_id, e)
            await self._announce_result(
                task_id, label, task, error_msg, origin, "error"
            )

    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str],
        status: str,
    ) -> None:
        """Анонсировать результат субагента основному агенту через шину сообщений."""
        status_text = "completed successfully" if status == "ok" else "failed"

        announce_content = f"""[Subagent '{label}' {status_text}]

Task: {task}

Result:
{result}

Summarize this naturally for the user. Keep it brief (1-2 sentences). Do not mention technical details like "subagent" or task IDs."""

        # Внедрить как системное сообщение для запуска основного агента
        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
        )

        await self.bus.publish_inbound(msg)
        logger.debug(
            "Субагент [{}] анонсировал результат в {}:{}",
            task_id,
            origin["channel"],
            origin["chat_id"],
        )

    def _build_subagent_prompt(self, task: str) -> str:
        """Построить сфокусированный системный промпт для субагента."""
        from agentxyz.agent.context import ContextBuilder
        from agentxyz.agent.skills import SkillsLoader

        time_ctx = ContextBuilder.build_runtime_context(None, None)
        parts = [
            f"""# Subagent

{time_ctx}

You are a subagent spawned by the main agent to complete a specific task.
Stay focused on the assigned task. Your final response will be reported back to the main agent.

## Workspace
{self.workspace}"""
        ]

        skills_summary = SkillsLoader(self.workspace).build_skills_summary()
        if skills_summary:
            parts.append(
                f"## Skills\n\nRead SKILL.md with read_file to use a skill.\n\n{skills_summary}"
            )

        return "\n\n".join(parts)

    async def cancel_by_session(self, session_key: str) -> int:
        """Отменить все субагенты для указанной сессии. Возвращает количество отменённых."""
        tasks = [
            self._running_tasks[tid]
            for tid in self._session_tasks.get(session_key, [])
            if tid in self._running_tasks and not self._running_tasks[tid].done()
        ]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return len(tasks)

    def get_running_count(self) -> int:
        """Вернуть количество текущих выполняющихся субагентов."""
        return len(self._running_tasks)
