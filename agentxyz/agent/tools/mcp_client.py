"""Клиент MCP: подключается к MCP-серверам и оборачивает их инструменты как нативные инструменты agentxyz."""

import asyncio
from contextlib import AsyncExitStack
from typing import Any

import httpx
from loguru import logger

from agentxyz.agent.tools.base import Tool
from agentxyz.agent.tools.registry import ToolRegistry


class MCPToolWrapper(Tool):
    """Оборачивает один инструмент MCP-сервера как инструмент agentxyz."""

    def __init__(
        self,
        session: Any,
        server_name: str,
        tool_def: Any,
        tool_timeout: int | float = 30,
    ) -> None:
        self._session = session
        self._original_name = tool_def.name
        self._name = f"mcp_{server_name}_{tool_def.name}"
        self._description = str(tool_def.description or tool_def.name)
        self._parameters = tool_def.inputSchema or {"type": "object", "properties": {}}
        self._tool_timeout = tool_timeout

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def execute(self, **kwargs: Any) -> str:
        from mcp import types

        try:
            result = await asyncio.wait_for(
                self._session.call_tool(self._original_name, arguments=kwargs),
                timeout=self._tool_timeout,
            )
        except TimeoutError:
            logger.warning(
                "MCP tool '{}' timed out after {}s", self._name, self._tool_timeout
            )
            return f"(MCP tool call timed out after {self._tool_timeout}s)"

        except asyncio.CancelledError:
            # Области отмены anyio в MCP SDK могут пропускать CancelledError при таймауте/сбое.
            # Повторно вызываем исключение только если наша задача была отменена извне (например, /stop).
            task = asyncio.current_task()
            if task is not None and task.cancelling() > 0:
                raise
            logger.warning("Инструмент MCP '{}' был отменён сервером/SDK", self._name)
            return "(MCP tool call was cancelled)"
        except Exception as exc:
            logger.exception(
                "MCP tool '{}' failed: {}: {}",
                self._name,
                type(exc).__name__,
                exc,
            )
            return f"(MCP tool call failed: {type(exc).__name__})"

        parts = []
        for block in result.content:
            if isinstance(block, types.TextContent):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts) or "(no output)"


async def connect_mcp_servers(
    mcp_servers: dict, registry: ToolRegistry, stack: AsyncExitStack
) -> None:
    """Подключиться к настроенным MCP-серверам и зарегистрировать их инструменты."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.sse import sse_client
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamable_http_client

    for name, cfg in mcp_servers.items():
        try:
            transport_type = cfg.type
            if not transport_type:
                if cfg.command:
                    transport_type = "stdio"
                elif cfg.url:
                    # Конвенция: URL-адреса, оканчивающиеся на /sse, используют SSE-транспорт; остальные используют streamableHttp
                    transport_type = (
                        "sse"
                        if cfg.url.rstrip("/").endswith("/sse")
                        else "streamableHttp"
                    )
                else:
                    logger.warning(
                        "MCP-сервер '{}': не настроена команда или URL, пропускаем",
                        name,
                    )
                    continue

            if transport_type == "stdio":
                params = StdioServerParameters(
                    command=cfg.command, args=cfg.args, env=cfg.env or None
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            elif transport_type == "sse":

                def httpx_client_factory(
                    headers: dict[str, str] | None = None,
                    timeout: httpx.Timeout | None = None,
                    auth: httpx.Auth | None = None,
                    _cfg: Any = cfg,
                ) -> httpx.AsyncClient:
                    merged_headers = {**(_cfg.headers or {}), **(headers or {})}
                    return httpx.AsyncClient(
                        headers=merged_headers or None,
                        follow_redirects=True,
                        timeout=timeout,
                        auth=auth,
                    )

                read, write = await stack.enter_async_context(
                    sse_client(cfg.url, httpx_client_factory=httpx_client_factory)
                )
            elif transport_type == "streamableHttp":
                # Всегда передавайте явный httpx-клиент, чтобы HTTP-транспорт MCP не наследовал
                # стандартный 5-секундный тайм-аут httpx и не прерывал работу более высокого
                # уровня из-за истечения времени ожидания инструмента.
                http_client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        headers=cfg.headers or None,
                        follow_redirects=True,
                        timeout=None,
                    )
                )
                read, write, _ = await stack.enter_async_context(
                    streamable_http_client(cfg.url, http_client=http_client)
                )
            else:
                logger.warning(
                    "MCP-сервер '{}': неизвестный тип транспорта '{}'",
                    name,
                    transport_type,
                )
                continue

            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()

            tools = await session.list_tools()
            for tool_def in tools.tools:
                wrapper = MCPToolWrapper(
                    session, name, tool_def, tool_timeout=cfg.tool_timeout
                )
                registry.register(wrapper)
                logger.debug(
                    "MCP: зарегистрирован инструмент '{}' от сервера '{}'",
                    wrapper.name,
                    name,
                )

            logger.info(
                "MCP-сервер '{}': подключен, зарегистрировано {} инструментов",
                name,
                len(tools.tools),
            )
        except Exception as e:
            logger.error("MCP-сервер '{}': не удалось подключиться: {}", name, e)
