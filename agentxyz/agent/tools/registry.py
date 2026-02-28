"""Реестр инструментов для динамического управления."""

from typing import Any

from agentxyz.agent.tools.base import Tool


class ToolRegistry:
    """
    Реестр инструментов агента.

    Позволяет динамически регистрировать и выполнять инструменты.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Зарегистрировать инструмент."""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Удалить инструмент из реестра по имени."""
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        """Получить инструмент по имени."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Проверить, зарегистрирован ли инструмент."""
        return name in self._tools

    def get_definitions(self) -> list[dict[str, Any]]:
        """Получить определения всех инструментов в формате OpenAI."""
        return [tool.to_schema() for tool in self._tools.values()]

    async def execute(self, name: str, params: dict[str, Any]) -> str:
        """
        Выполнить инструмент по имени используя параметры.

        Args:
            name: Имя инструмента.
            params: Параметры инструмента.

        Returns:
            Результат выполнения инструмента в виде строки.
            Если инструмент не найден или произошла ошибка, возвращается
            строка с сообщением об ошибке, начинающаяся с "Error:".
        """
        _hint = "\n\n[Analyze the error above and try a different approach.]"

        tool = self._tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"

        try:
            errors = tool.validate_params(params)
            if errors:
                return (
                    f"Error: Invalid parameters for tool '{name}': "
                    + "; ".join(errors)
                    + _hint
                )
            result = await tool.execute(**params)
            if isinstance(result, str) and result.startswith("Error"):
                return result + _hint
            return result
        except Exception as e:
            return f"Error executing {name}: {e!s}" + _hint

    @property
    def tool_names(self) -> list[str]:
        """Получить список имён зарегистрированных инструментов."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        """Получить количество зарегистрированных инструментов."""
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        """Проверить наличие инструмента по имени (оператор `in`)."""
        return name in self._tools
