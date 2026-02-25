"""
Базовый класс для инструментов.

Данный класс представляет собой базовый класс для инструментов, которые могут быть использованы в различных задачах.
"""

from abc import ABC, abstractmethod
from typing import Any, ClassVar


class Tool(ABC):
    """
    Абстрактный базовый класс для инструментов агента.

    Инструменты(Tools) - это возможности, которые агент может использовать для
    взаимодействия с окружением, такие как чтение файлов, выполнение команд.
    """

    _TYPE_MAP: ClassVar[dict[str, tuple[type, ...] | type]] = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    @property
    @abstractmethod
    def name(self) -> str:
        """Имя инструмента для вызова функций."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Описание назначения инструмента."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON-схема параметров инструмента."""
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """
        Выполнить инструмент с заданными параметрами.

        Args:
            **kwargs: Параметры конкретного инструмента.

        Returns:
            Результат выполнения инструмента в виде строки.
        """
        ...

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """Проверить параметры инструмента по JSON-схеме. Возвращает список ошибок (пустой если валидно)."""
        schema = self.parameters or {}
        if schema.get("type", "object") != "object":
            raise ValueError(f"Schema must be object type, got {schema.get('type')!r}")
        return self._validate(params, {**schema, "type": "object"}, "")

    def _validate(self, val: Any, schema: dict[str, Any], path: str) -> list[str]:
        """
        Валидация значения согласно JSON Schema.

        Проверяет соответствие значения заданной схеме и возвращает список
        найденных ошибок валидации.
        """

        t, label = schema.get("type"), path or "parameter"
        if t in self._TYPE_MAP and not isinstance(val, self._TYPE_MAP[t]):
            return [f"{label} should be {t}"]

        errors = []
        if "enum" in schema and val not in schema["enum"]:
            errors.append(f"{label} must be one of {schema['enum']}")
        if t in ("integer", "number"):
            if "minimum" in schema and val < schema["minimum"]:
                errors.append(f"{label} must be >= {schema['minimum']}")
            if "maximum" in schema and val > schema["maximum"]:
                errors.append(f"{label} must be <= {schema['maximum']}")
        if t == "string":
            if "minLength" in schema and len(val) < schema["minLength"]:
                errors.append(f"{label} must be at least {schema['minLength']} chars")
            if "maxLength" in schema and len(val) > schema["maxLength"]:
                errors.append(f"{label} must be at most {schema['maxLength']} chars")
        if t == "object":
            props = schema.get("properties", {})
            for k in schema.get("required", []):
                if k not in val:
                    errors.append(f"missing required {path + '.' + k if path else k}")
            for k, v in val.items():
                if k in props:
                    errors.extend(
                        self._validate(v, props[k], path + "." + k if path else k)
                    )
        if t == "array" and "items" in schema:
            for i, item in enumerate(val):
                errors.extend(
                    self._validate(
                        item, schema["items"], f"{path}[{i}]" if path else f"[{i}]"
                    )
                )
        return errors

    def to_schema(self) -> dict[str, Any]:
        """Конвертировать инструмент в формат схемы функций OpenAI."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
