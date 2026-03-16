"""Цикл агента: основное ядро обработки."""

import asyncio
import json
import os
import re
import sys
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from loguru import logger

from agentxyz.agent.context import ContextBuilder
from agentxyz.agent.memory import MemoryConsolidator
from agentxyz.agent.skills import BUILTIN_SKILLS_DIR
from agentxyz.agent.subagent import SubagentManager
from agentxyz.agent.tools.cron import CronTool
from agentxyz.agent.tools.filesystem import (
    EditFileTool,
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
)
from agentxyz.agent.tools.message import MessageTool
from agentxyz.agent.tools.registry import ToolRegistry
from agentxyz.agent.tools.shell import ExecTool
from agentxyz.agent.tools.spawn import SpawnTool
from agentxyz.agent.tools.web import WebFetchTool, WebSearchTool
from agentxyz.bus.events import InboundMessage, OutboundMessage
from agentxyz.bus.queue import MessageBus
from agentxyz.config.schema import ChannelsConfig, ExecToolConfig, WebSearchConfig
from agentxyz.cron.service import CronService
from agentxyz.providers.base import LLMProvider
from agentxyz.session.manager import Session, SessionManager


class AgentLoop:
    """
    Цикл агента — это основное ядро обработки.

    Он:
    1. Получает сообщения из шины
    2. Строит контекст с историей, памятью, навыками
    3. Вызывает LLM
    4. Выполняет вызовы инструментов
    5. Отправляет ответы обратно
    """

    _TOOL_RESULT_MAX_CHARS = 16_000

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 40,
        context_window_tokens: int = 65_536,
        web_search_config: WebSearchConfig | None = None,
        web_proxy: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
    ):
        from agentxyz.config.schema import ExecToolConfig, WebSearchConfig

        self.bus = bus
        self.channels_config = channels_config
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.context_window_tokens = context_window_tokens
        self.web_search_config = web_search_config or WebSearchConfig()
        self.web_proxy = web_proxy
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace

        self.context = ContextBuilder(workspace)
        self.sessions = session_manager or SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            web_search_config=self.web_search_config,
            web_proxy=web_proxy,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> tasks
        self._background_tasks: list[asyncio.Task] = []
        self._processing_lock = asyncio.Lock()
        self.memory_consolidator = MemoryConsolidator(
            workspace=workspace,
            provider=provider,
            model=self.model,
            sessions=self.sessions,
            context_window_tokens=context_window_tokens,
            build_messages=self.context.build_messages,
            get_tool_definitions=self.tools.get_definitions,
        )
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Зарегистрировать набор инструментов по умолчанию."""
        # Файловые инструменты (ограничить рабочим пространством, если настроено)
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        extra_read = [BUILTIN_SKILLS_DIR] if allowed_dir else None
        self.tools.register(
            ReadFileTool(
                workspace=self.workspace,
                allowed_dir=allowed_dir,
                extra_allowed_dirs=extra_read,
            )
        )
        for cls in (WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))

        # Инструмент оболочки
        self.tools.register(
            ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
                path_append=self.exec_config.path_append,
            )
        )

        # Веб-инструменты
        self.tools.register(
            WebSearchTool(config=self.web_search_config, proxy=self.web_proxy)
        )
        self.tools.register(WebFetchTool(proxy=self.web_proxy))

        # Инструмент сообщений
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))

        # Инструмент запуска (для субагентов)
        self.tools.register(SpawnTool(manager=self.subagents))

        # Инструмент cron (для планирования)
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

    async def _connect_mcp(self) -> None:
        """Подключиться к настроенным MCP-серверам (один раз, lazy)."""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from agentxyz.agent.tools.mcp_client import connect_mcp_servers

        try:
            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)
            self._mcp_connected = True
        except BaseException as e:
            logger.error(
                "Не удалось подключиться к MCP-серверам (повторная попытка при следующем сообщении): {}",
                e,
            )
            if self._mcp_stack:
                try:
                    await self._mcp_stack.aclose()
                except Exception:
                    pass
                self._mcp_stack = None
        finally:
            self._mcp_connecting = False

    def _set_tool_context(
        self, channel: str, chat_id: str, message_id: str | None = None
    ) -> None:
        """Обновить контекст для всех инструментов, которым нужна информация о маршрутизации."""
        for name in ("message", "spawn", "cron"):
            if tool := self.tools.get(name):
                if hasattr(tool, "set_context"):
                    tool.set_context(
                        channel, chat_id, *([message_id] if name == "message" else [])
                    )

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Удаляет служебные блоки (например, thinking), которые некоторые модели добавляют в свой ответ."""
        if not text:
            return None
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip() or None

    @staticmethod
    def _tool_hint(tool_calls: list) -> str:
        """Форматирует вызовы инструментов в виде краткой подсказки, например 'web_search("query")'."""

        def _fmt(tc: Any) -> Any:
            args = (
                tc.arguments[0] if isinstance(tc.arguments, list) else tc.arguments
            ) or {}
            val = next(iter(args.values()), None) if isinstance(args, dict) else None
            if not isinstance(val, str):
                return tc.name
            return (
                f'{tc.name}("{val[:40]}…")' if len(val) > 40 else f'{tc.name}("{val}")'
            )

        return ", ".join(_fmt(tool_call) for tool_call in tool_calls)

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[str], list[dict]]:
        """
        Выполнить итерационный цикл агента.

        Args:
            initial_messages: Начальные сообщения для разговора с LLM.
            on_progress: Опциональный callback для отправки промежуточного содержимого пользователю.

        Returns:
            Кортеж из (final_content, list_of_tools_used, messages).
        """
        messages = initial_messages
        iteration = 0
        final_content = None
        tools_used: list[str] = []

        while iteration < self.max_iterations:
            iteration += 1

            tool_defs = self.tools.get_definitions()

            response = await self.provider.chat_with_retry(
                messages=messages,
                tools=tool_defs,
                model=self.model,
            )

            if response.has_tool_calls:
                if on_progress:
                    thought = self._strip_think(response.content)
                    if thought:
                        await on_progress(thought)
                    tool_hint = self._tool_hint(response.tool_calls)
                    tool_hint_stripped = self._strip_think(tool_hint)
                    if tool_hint_stripped:
                        await on_progress(tool_hint_stripped, tool_hint=True)

                tool_call_dicts = [
                    tc.to_openai_tool_call() for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages,
                    response.content,
                    tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )

                for tool_call in response.tool_calls:
                    tools_used.append(tool_call.name)
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info("Tool call: {}({})", tool_call.name, args_str[:200])
                    result = await self.tools.execute(
                        tool_call.name, tool_call.arguments
                    )
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                clean = self._strip_think(response.content)
                # Не сохранять ответы с ошибками в историю сессии — они могут
                # загрязнить контекст и вызвать бесконечные циклы 400-х ошибок (#1303).
                if response.finish_reason == "error":
                    logger.error("LLM returned error: {}", (clean or "")[:200])
                    final_content = (
                        clean or "Sorry, I encountered an error calling the AI model."
                    )
                    break
                messages = self.context.add_assistant_message(
                    messages,
                    clean,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )
                final_content = clean
                break

        if final_content is None and iteration >= self.max_iterations:
            logger.warning(
                "Достигнуто максимальное число итераций ({})", self.max_iterations
            )
            final_content = (
                f"Я достиг максимального количества итераций вызова инструментов ({self.max_iterations}) "
                "не завершив задачу. Вы можете попробовать разбить задачу на более мелкие шаги."
            )

        return final_content, tools_used, messages

    async def run(self) -> None:
        """Запустить цикл агента, обрабатывая сообщения из шины."""
        self._running = True
        await self._connect_mcp()
        logger.info("Цикл агента запущен")

        while self._running:
            try:
                # Ожидание следующего сообщения
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except TimeoutError:
                continue
            except Exception as e:
                logger.warning(
                    "Ошибка при получении входящего сообщения: {}, продолжаем...", e
                )
                continue

            cmd = msg.content.strip().lower()
            if cmd == "/stop":
                await self._handle_stop(msg)
            elif cmd == "/restart":
                await self._handle_restart(msg)
            else:
                task = asyncio.create_task(self._dispatch(msg))
                self._active_tasks.setdefault(msg.session_key, []).append(task)
                task.add_done_callback(self._make_done_callback(msg.session_key))

    def _make_done_callback(
        self, session_key: str
    ) -> Callable[[asyncio.Task[Any]], None]:
        """Создаёт callback для удаления выполненной задачи из списка активных."""

        def _remove_done(task: asyncio.Task[Any]) -> None:
            tasks_list = self._active_tasks.get(session_key)
            if tasks_list and task in tasks_list:
                tasks_list.remove(task)

        return _remove_done

    async def _handle_stop(self, msg: InboundMessage) -> None:
        """Отменить все активные задачи и субагенты для сессии."""
        tasks = self._active_tasks.pop(msg.session_key, [])
        cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        sub_cancelled = await self.subagents.cancel_by_session(msg.session_key)
        total = cancelled + sub_cancelled
        content = f"⏹ Stopped {total} task(s)." if total else "No active task to stop."
        await self.bus.publish_outbound(
            OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=content,
            )
        )

    async def _handle_restart(self, msg: InboundMessage) -> None:
        """Перезапустить процесс на месте через os.execv."""
        await self.bus.publish_outbound(
            OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="Restarting...",
            )
        )

        async def _do_restart() -> None:
            await asyncio.sleep(1)
            # Используйте -m agentxyz вместо sys.argv[0] для совместимости с Windows
            # (sys.argv[0] может быть просто "agentxyz" без полного пути в Windows)
            os.execv(sys.executable, [sys.executable, "-m", "agentxyz", *sys.argv[1:]])

        task = asyncio.create_task(_do_restart())
        self._background_tasks.append(task)
        task.add_done_callback(self._background_tasks.remove)

    async def _dispatch(self, msg: InboundMessage) -> None:
        """Обработать сообщение под глобальной блокировкой."""
        async with self._processing_lock:
            try:
                response = await self._process_message(msg)
                if response is not None:
                    await self.bus.publish_outbound(response)
                elif msg.channel == "cli":
                    await self.bus.publish_outbound(
                        OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content="",
                            metadata=msg.metadata or {},
                        )
                    )
            except asyncio.CancelledError:
                logger.info("Задача отменена для сессии {}", msg.session_key)
                raise
            except Exception:
                logger.exception(
                    "Ошибка обработки сообщения для сессии {}", msg.session_key
                )
                await self.bus.publish_outbound(
                    OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content="К сожалению, произошла ошибка.",
                    )
                )

    async def close_mcp(self) -> None:
        """Обработать ожидающие фоновые задачи архивации, затем закрыть MCP-соединения."""
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                pass  # Очистка при закрытии соединений MCP SDK создает много логов, но это нормально и не вызывает проблем.
            self._mcp_stack = None

    def _schedule_background(self, coro: Coroutine) -> None:
        """Запланировать корутину как фоновую задачу с отслеживанием (завершается при выключении)."""
        task = asyncio.create_task(coro)
        self._background_tasks.append(task)
        task.add_done_callback(self._background_tasks.remove)

    def stop(self) -> None:
        """Остановить цикл агента."""
        self._running = False
        logger.info("Цикл агента останавливается")

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """
        Обработать одно входящее сообщение.

        Args:
            msg: Входящее сообщение для обработки.
            on_progress: Опциональный callback для промежуточного вывода (по умолчанию публикуется в bus).
        Returns:
            Ответное сообщение или None, если ответ не требуется.
        """
        # Обработка системных сообщений (анонсы субагентов)
        # chat_id содержит исходный "channel:chat_id" для возврата
        if msg.channel == "system":
            channel, chat_id = (
                msg.chat_id.split(":", 1)
                if ":" in msg.chat_id
                else ("cli", msg.chat_id)
            )
            logger.info("Processing system message from {}", msg.sender_id)
            key = f"{channel}:{chat_id}"
            session = self.sessions.get_or_create(key)
            await self.memory_consolidator.maybe_consolidate_by_tokens(session)
            self._set_tool_context(channel, chat_id, msg.metadata.get("message_id"))
            history = session.get_history(max_messages=0)
            messages = self.context.build_messages(
                history=history,
                current_message=msg.content,
                channel=channel,
                chat_id=chat_id,
            )
            final_content, _, all_msgs = await self._run_agent_loop(messages)
            self._save_turn(session, all_msgs, 1 + len(history))
            self.sessions.save(session)
            self._schedule_background(
                self.memory_consolidator.maybe_consolidate_by_tokens(session)
            )
            return OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=final_content or "Background task completed.",
            )

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info(
            "Обработка сообщения от {}:{}: {}", msg.channel, msg.sender_id, preview
        )

        # Получить или создать сессию
        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)

        # Обрабатываем слэш-команды
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            snapshot = session.messages[session.last_consolidated :]
            session.clear()
            self.sessions.save(session)
            self.sessions.invalidate(session.key)

            if snapshot:
                self._schedule_background(
                    self.memory_consolidator.archive_messages(snapshot)
                )

            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="🔥 Начата новая сессия.",
            )
        if cmd == "/help":
            lines = [
                "🔥 agentxyz команды:",
                "/new — Начать новый разговор",
                "/stop — Остановить текущую задачу",
                "/restart — Перезапустить бота",
                "/help — Показать доступные команды",
            ]
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="\n".join(lines),
            )
        await self.memory_consolidator.maybe_consolidate_by_tokens(session)

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        # Построить начальные сообщения (использовать get_history для сообщений в формате LLM)
        history = session.get_history(max_messages=0)
        initial_messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
        )

        async def _bus_progress(content: str, *, tool_hint: bool = False) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=content,
                    metadata=meta,
                )
            )

        final_content, _, all_msgs = await self._run_agent_loop(
            initial_messages,
            on_progress=on_progress or _bus_progress,
        )

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        # Сохранить в сеанс
        self._save_turn(session, all_msgs, 1 + len(history))
        self.sessions.save(session)
        self._schedule_background(
            self.memory_consolidator.maybe_consolidate_by_tokens(session)
        )

        if (
            (mt := self.tools.get("message"))
            and isinstance(mt, MessageTool)
            and mt.sent_in_turn
        ):
            return None

        preview = (
            final_content[:120] + "..." if len(final_content) > 120 else final_content
        )
        logger.info("Ответ от {}:{}: {}", msg.channel, msg.sender_id, preview)

        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata=msg.metadata
            or {},  # Пропустить для специфичных нужд канала (например, thread_ts в Slack)
        )

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
        """Save new-turn messages into session, truncating large tool results."""
        from datetime import datetime

        for m in messages[skip:]:
            entry = dict(m)
            role, content = entry.get("role"), entry.get("content")
            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue  # skip empty assistant messages — they poison session context
            if (
                role == "tool"
                and isinstance(content, str)
                and len(content) > self._TOOL_RESULT_MAX_CHARS
            ):
                entry["content"] = (
                    content[: self._TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"
                )
            elif role == "user":
                if isinstance(content, str) and content.startswith(
                    ContextBuilder.RUNTIME_CONTEXT_TAG
                ):
                    # Strip the runtime-context prefix, keep only the user text.
                    parts = content.split("\n\n", 1)
                    if len(parts) > 1 and parts[1].strip():
                        entry["content"] = parts[1]
                    else:
                        continue
                if isinstance(content, list):
                    filtered = []
                    for c in content:
                        if (
                            c.get("type") == "text"
                            and isinstance(c.get("text"), str)
                            and c["text"].startswith(ContextBuilder.RUNTIME_CONTEXT_TAG)
                        ):
                            continue  # Удалить контекст выполнения из мультимедийных сообщений
                        if c.get("type") == "image_url" and c.get("image_url", {}).get(
                            "url", ""
                        ).startswith("data:image/"):
                            filtered.append({"type": "text", "text": "[image]"})
                        else:
                            filtered.append(c)
                    if not filtered:
                        continue
                    entry["content"] = filtered
            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)
        session.updated_at = datetime.now()

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """
        Обработать сообщение напрямую (для CLI или cron).

        Args:
            content: Содержимое сообщения.
            session_key: Идентификатор сессии.
            channel: Исходный канал (для контекста).
            chat_id: Исходный ID чата (для контекста).
            on_progress: Опциональный callback для промежуточного вывода.

        Returns:
            Ответ агента.
        """
        await self._connect_mcp()
        msg = InboundMessage(
            channel=channel, sender_id="user", chat_id=chat_id, content=content
        )

        response = await self._process_message(
            msg, session_key=session_key, on_progress=on_progress
        )
        return response.content if response else ""
