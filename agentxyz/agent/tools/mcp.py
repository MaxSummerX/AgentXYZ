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
        self, session: Any, server_name: str, tool_def: Any, tool_timeout: int = 30
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
    from mcp.client.stdio import stdio_client

    for name, cfg in mcp_servers.items():
        try:
            if cfg.command:
                params = StdioServerParameters(
                    command=cfg.command, args=cfg.args, env=cfg.env or None
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            elif cfg.url:
                from mcp.client.streamable_http import streamable_http_client

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
                    "MCP-сервер '{}': не указаны command или url, пропускаем", name
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
