"""Инструмент для управления чек-листом задач в текущей сессии."""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from agentxyz.agent.tools.base import Tool


class TaskStatus(Enum):
    """Статусы задач."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"

    @classmethod
    def from_str(cls, value: str) -> "TaskStatus | None":
        """Парсинг из строки."""
        for status in cls:
            if status.value == value:
                return status
        return None


@dataclass
class TaskItem:
    """Элемент задачи."""

    id: int
    title: str
    status: TaskStatus = TaskStatus.PENDING


class TaskPlanTool(Tool):
    """
    Инструмент для управления чек-листом задач в текущей сессии.

    Позволяет разбить сложную работу на шаги и отслеживать прогресс.
    Задачи хранятся в памяти и пропадают при завершении сессии.
    """

    def __init__(self) -> None:
        self._tasks: list[TaskItem] = []
        self._next_id: int = 1

    @property
    def name(self) -> str:
        return "task_plan"

    @property
    def description(self) -> str:
        return (
            "Manage a task checklist for the current session. "
            "Use to break complex work into steps and track progress. "
            "Actions: create (batch), add (single), update (change status), list (view all), delete (clear all)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "add", "update", "list", "delete"],
                    "description": "Operation to perform",
                },
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                            },
                        },
                        "required": ["title"],
                    },
                    "description": "For 'create': list of tasks to create (replaces existing list)",
                },
                "title": {
                    "type": "string",
                    "description": "For 'add': title of the new task",
                },
                "id": {
                    "type": "integer",
                    "description": "For 'update': ID of the task to update",
                },
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed"],
                    "description": "For 'update': new status",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str, **kwargs: Any) -> str:  # type: ignore[override]
        if action == "create":
            return self._handle_create(kwargs.get("tasks", []))
        elif action == "add":
            return self._handle_add(kwargs.get("title", ""))
        elif action == "update":
            task_id = kwargs.get("id", 0)
            status = kwargs.get("status", "")
            return self._handle_update(task_id, status)
        elif action == "list":
            return self._handle_list()
        elif action == "delete":
            return self._handle_delete()
        else:
            available = "create, add, update, list, delete"
            return f"Error: Unknown action '{action}'. Valid: {available}"

    def _handle_create(self, tasks_val: list[Any]) -> str:
        """Создать список задач (заменяет существующий)."""
        if not tasks_val:
            return (
                "Error: Parameter 'tasks' must be a non-empty array of {title, status?}"
            )

        items = []
        for i, entry in enumerate(tasks_val, start=1):
            title = entry.get("title", "")
            if not title or not isinstance(title, str):
                return "Error: Each task must have a non-empty 'title' string"

            status_str = entry.get("status", "pending")
            status = TaskStatus.from_str(status_str) or TaskStatus.PENDING

            items.append(TaskItem(id=i, title=title, status=status))

        self._tasks = items
        self._next_id = len(items) + 1
        return f"Created {len(items)} task(s)."

    def _handle_add(self, title: str) -> str:
        """Добавить одну задачу."""
        if not title or not isinstance(title, str):
            return "Error: Parameter 'title' must be a non-empty string"

        task_id = self._next_id
        self._next_id += 1

        self._tasks.append(TaskItem(id=task_id, title=title, status=TaskStatus.PENDING))
        return f'Added task [{task_id}] "{title}".'

    def _handle_update(self, task_id: int, status_str: str) -> str:
        """Обновить статус задачи."""
        if task_id <= 0:
            return "Error: Parameter 'id' is required for update"

        if not status_str:
            return "Error: Parameter 'status' is required for update"

        status = TaskStatus.from_str(status_str)
        if not status:
            return "Error: Invalid status. Must be: pending, in_progress, completed"

        for task in self._tasks:
            if task.id == task_id:
                task.status = status
                return f"Task [{task_id}] updated to {status.value}."

        return f"Error: Task with id {task_id} not found"

    def _handle_list(self) -> str:
        """Показать все задачи."""
        if not self._tasks:
            return "No tasks."

        completed = sum(1 for t in self._tasks if t.status == TaskStatus.COMPLETED)
        total = len(self._tasks)

        lines = [f"Tasks ({completed}/{total} completed):"]
        for task in self._tasks:
            lines.append(f"- [{task.id}] [{task.status.value}] {task.title}")

        return "\n".join(lines)

    def _handle_delete(self) -> str:
        """Удалить все задачи."""
        self._tasks.clear()
        self._next_id = 1
        return "Task list cleared."

    # Дополнительные удобные методы

    def get_tasks(self) -> list[TaskItem]:
        """Получить копию списка задач."""
        return list(self._tasks)

    def get_pending_count(self) -> int:
        """Количество ожидающих задач."""
        return sum(1 for t in self._tasks if t.status == TaskStatus.PENDING)

    def get_completed_count(self) -> int:
        """Количество выполненных задач."""
        return sum(1 for t in self._tasks if t.status == TaskStatus.COMPLETED)

    def is_all_completed(self) -> bool:
        """Все ли задачи выполнены."""
        if not self._tasks:
            return True
        return all(t.status == TaskStatus.COMPLETED for t in self._tasks)

    def get_progress_summary(self) -> str:
        """Краткая сводка прогресса."""
        if not self._tasks:
            return "No tasks"

        completed = self.get_completed_count()
        total = len(self._tasks)
        percentage = (completed / total) * 100 if total > 0 else 0

        return f"Progress: {completed}/{total} tasks ({percentage:.0f}%)"
