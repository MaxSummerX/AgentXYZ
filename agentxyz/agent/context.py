"""Конструктор контекста для сборки промптов агента."""

import base64
import mimetypes
import platform
from pathlib import Path
from typing import Any, ClassVar

from agentxyz.agent.memory import MemoryStore
from agentxyz.agent.skills import SkillsLoader


class ContextBuilder:
    """
    Строит контекст (системный промпт + сообщения) для агента.

    Собирает bootstrap-файлы, память, навыки и историю разговора
    в единый промпт для LLM.
    """

    BOOTSTRAP_FILES: ClassVar[list[str]] = [
        "AGENTS.md",
        "SOUL.md",
        "USER.md",
    ]

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)

    def build_system_prompt(
        self, skill_names: list[str] | None = None
    ) -> str:  # TODO: реализоавать добавляение скилов в системный пропмт
        """
        Собирает системный промпт из bootstrap-файлов, памяти и навыков.

        Args:
            skill_names: Опциональный список навыков для включения.

        Returns:
            Полный системный промпт.
        """
        parts = []

        # Основная идентичность
        parts.append(self._get_identity())

        # Файлы начальной загрузки
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        # Контекст памяти
        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")

        if skill_names:
            # Режим override: ТОЛЬКО запрошенные навыки
            requested_skills = self.skills.load_skills_for_context(skill_names)
            if requested_skills:
                parts.append(f"# Active Skills\n\n{requested_skills}")
        else:
            # Навыки - прогрессивная загрузка
            # 1. Всегда загружаемые навыки: включать полное содержание
            always_skills = self.skills.get_always_skills()
            if always_skills:
                always_content = self.skills.load_skills_for_context(always_skills)
                if always_content:
                    parts.append(f"# Active Skills\n\n{always_content}")

            # 2. Доступные навыки: показывать только сводку (агент использует read_file для загрузки)
            skills_summary = self.skills.build_skills_summary()
            if skills_summary:
                parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew/pacman.

{skills_summary}""")

        return "\n\n---\n\n".join(parts)

    def _get_identity(self) -> str:
        """Получить основную секцию идентичности."""
        import time as _time
        from datetime import datetime

        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = _time.strftime("%Z") or "UTC"
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        return f"""# agentxyz 🔥

You are agentxyz, a helpful AI assistant.

## Current Time
{now} ({tz})

## Runtime
{runtime}

## Workspace
Your workspace is at: {workspace_path}
- Long-term memory: {workspace_path}/memory/MEMORY.md
- History log: {workspace_path}/memory/HISTORY.md (grep-searchable)
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

Reply directly with text for conversations. Only use the 'message' tool to send to a specific chat channel.

## Tool Call Guidelines
- Before calling tools, you may briefly state your intent (e.g. "Let me check that"), but NEVER predict or describe the expected result before receiving it.
- Before modifying a file, read it first to confirm its current content.
- Do not assume a file or directory exists — use list_dir or read_file to verify.
- After writing or editing a file, re-read it if accuracy matters.
- If a tool call fails, analyze the error before retrying with a different approach.

## Memory
- Remember important facts: write to {workspace_path}/memory/MEMORY.md
- Recall past events: grep {workspace_path}/memory/HISTORY.md"""

    def _load_bootstrap_files(self) -> str:
        """Загрузить все bootstrap-файлы из рабочего пространства."""
        parts = []

        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")

        return "\n\n".join(parts) if parts else ""

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Собрать полный список сообщений для вызова LLM.

        Args:
            history: Предыдущие сообщения разговора.
            current_message: Новое сообщение пользователя.
            skill_names: Опциональные навыки для включения.
            media: Опциональный список локальных путей к файлам изображений/медиа.
            channel: Текущий канал (telegram, feishu и т.д.).
            chat_id: Текущий ID чата/пользователя.

        Returns:
            Список сообщений включая системный промпт.
        """
        messages = []

        # Системный промпт
        system_prompt = self.build_system_prompt(skill_names)
        if channel and chat_id:
            system_prompt += (
                f"\n\n## Current Session\nChannel: {channel}\nChat ID: {chat_id}"
            )

        messages.append({"role": "system", "content": system_prompt})

        # История
        messages.extend(history)

        # Текущее сообщение (с возможными вложениями изображений)
        user_content = self._build_user_content(current_message, media)
        user_msg: dict[str, Any] = {"role": "user", "content": user_content}
        messages.append(user_msg)

        return messages

    @staticmethod
    def _build_user_content(
        text: str, media: list[str] | None
    ) -> str | list[dict[str, Any]]:
        """Создать содержимое сообщения пользователя с опциональными base64-кодированными изображениями."""
        if not media:
            return text

        images = []
        for path in media:
            p = Path(path)
            mime, _ = mimetypes.guess_type(path)
            if not p.is_file() or not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(p.read_bytes()).decode()
            images.append(
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
            )

        if not images:
            return text
        return [*images, {"type": "text", "text": text}]

    @staticmethod
    def add_tool_result(
        messages: list[dict[str, Any]],
        tool_call_id: str,
        tool_name: str,
        result: str,
    ) -> list[dict[str, Any]]:
        """
        Добавить результат инструмента в список сообщений.

        Args:
            messages: Текущий список сообщений.
            tool_call_id: ID вызова инструмента.
            tool_name: Имя инструмента.
            result: Результат выполнения инструмента.

        Returns:
            Обновленный список сообщений.
        """
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "content": result,
            }
        )
        return messages

    @staticmethod
    def add_assistant_message(
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Добавить сообщение ассистента в список сообщений.

        Args:
            messages: Текущий список сообщений.
            content: Содержимое сообщения.
            tool_calls: Опциональные вызовы инструментов.
            reasoning_content: Цепочка рассуждений модели (для o1, DeepSeek-R1 и др.).

        Returns:
            Обновленный список сообщений.
        """
        msg: dict[str, Any] = {"role": "assistant"}

        # Пропускать пустое содержимое — некоторые бэкенды отклоняют пустые текстовые блоки
        if content:
            msg["content"] = content

        if tool_calls:
            msg["tool_calls"] = tool_calls

        # Модели рассуждения не принимают историю без этого
        if reasoning_content is not None:
            msg["reasoning_content"] = reasoning_content

        messages.append(msg)
        return messages
