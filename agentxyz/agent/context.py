"""Конструктор контекста для сборки промптов агента."""

import base64
import mimetypes
import platform
import time
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from agentxyz.agent.memory import MemoryStore
from agentxyz.agent.skills import SkillsLoader
from agentxyz.utils.helpers import build_assistant_message, detect_image_mime


class ContextBuilder:
    """
    Строит контекст (системный промпт + сообщения) для агента.

    Собирает bootstrap-файлы, идентичность, память, навыки и историю разговора
    в единый промпт для LLM.
    """

    BOOTSTRAP_FILES: ClassVar[list[str]] = [
        "AGENTS.md",
        "SOUL.md",
        "USER.md",
        "TOOLS.md",
    ]
    RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)

    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
        """
        Собирает системный промпт из bootstrap-файлов, памяти и навыков.

        Args:
            skill_names: Опциональный список навыков для включения.

        Returns:
            Полный системный промпт.
        """
        # Основная идентичность
        parts = [self._get_identity()]

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

        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        platform_policy = ""
        if system == "Windows":
            platform_policy = """## Platform Policy (Windows)
        - You are running on Windows. Do not assume GNU tools like `grep`, `sed`, or `awk` exist.
        - Prefer Windows-native commands or file tools when they are more reliable.
        - If terminal output is garbled, retry with UTF-8 output enabled.
        """
        else:
            platform_policy = """## Platform Policy (POSIX)
        - You are running on a POSIX system. Prefer UTF-8 and standard shell tools.
        - Use file tools when they are simpler or more reliable than shell commands.
        """

        return f"""# agentxyz 🔥

You are agentxyz, a helpful AI assistant.

## Runtime
{runtime}

## Workspace
Your workspace is at: {workspace_path}
- Long-term memory: {workspace_path}/memory/MEMORY.md (write important facts here)
- History log: {workspace_path}/memory/HISTORY.md (grep-searchable). Each entry starts with [YYYY-MM-DD HH:MM].
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

{platform_policy}

## agentxyz Guidelines
- State intent before tool calls, but NEVER predict or claim results before receiving them.
- Before modifying a file, read it first. Do not assume files or directories exist.
- After writing or editing a file, re-read it if accuracy matters.
- If a tool call fails, analyze the error before retrying with a different approach.
- Ask for clarification when the request is ambiguous.

Reply directly with text for conversations. Only use the 'message' tool to send to a specific chat channel."""

    @staticmethod
    def build_runtime_context(channel: str | None, chat_id: str | None) -> str:
        """Построить блок метаданных исполняемой среды для вставки перед пользовательским сообщением."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = time.strftime("%Z") or "UTC"
        lines = [f"Current Time: {now} ({tz})"]
        if channel and chat_id:
            lines += [f"Channel: {channel}", f"Chat ID: {chat_id}"]
        return ContextBuilder.RUNTIME_CONTEXT_TAG + "\n" + "\n".join(lines)

    def _load_bootstrap_files(self) -> str:
        """Загрузить все загрузочные файлы из рабочего пространства."""
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
        runtime_ctx = self.build_runtime_context(channel, chat_id)
        user_content = self._build_user_content(current_message, media)

        # Объединить контекст выполнения и пользовательское содержимое в одно пользовательское сообщение,
        # чтобы избежать последовательных сообщений одной роли, которые некоторые провайдеры отклоняют.
        merged: str | list[dict[str, Any]]
        if isinstance(user_content, str):
            merged = f"{runtime_ctx}\n\n{user_content}"
        else:
            merged = [{"type": "text", "text": runtime_ctx}, *user_content]

        return [
            {"role": "system", "content": self.build_system_prompt(skill_names)},
            *history,
            {"role": "user", "content": merged},
        ]

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
            if not p.is_file():
                continue
            raw = p.read_bytes()
            # Определяем реальный MIME-тип по magic bytes; fallback на определение по имени файла
            mime = detect_image_mime(raw) or mimetypes.guess_type(path)[0]
            if not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(raw).decode()
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
        thinking_blocks: list[dict] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Добавить сообщение ассистента в список сообщений.

        Args:
            messages: Текущий список сообщений.
            content: Содержимое сообщения.
            tool_calls: Опциональные вызовы инструментов.
            reasoning_content: Цепочка рассуждений модели (для o1, DeepSeek-R1 и др.).
            thinking_blocks: Блоки рассуждений Claude (extended thinking).

        Returns:
            Обновленный список сообщений.
        """
        messages.append(
            build_assistant_message(
                content,
                tool_calls=tool_calls,
                reasoning_content=reasoning_content,
                thinking_blocks=thinking_blocks,
            )
        )
        return messages
