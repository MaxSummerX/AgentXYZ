"""Система памяти для постоянного хранения памяти агента."""

import json
from pathlib import Path

from loguru import logger

from agentxyz.providers.base import LLMProvider
from agentxyz.session.manager import Session
from agentxyz.utils.helpers import ensure_dir


_SAVE_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save the memory consolidation result to persistent storage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "history_entry": {
                        "type": "string",
                        "description": "A paragraph (2-5 sentences) summarizing key events/decisions/topics. "
                        "Start with [YYYY-MM-DD HH:MM]. Include detail useful for grep search.",
                    },
                    "memory_update": {
                        "type": "string",
                        "description": "Full updated long-term memory as markdown. Include all existing "
                        "facts plus new ones. Return unchanged if nothing new.",
                    },
                },
                "required": ["history_entry", "memory_update"],
            },
        },
    }
]


class MemoryStore:
    """Двухуровневая память: MEMORY.md (долгосрочные факты) + HISTORY.md (лог, доступный для поиска через grep)."""

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"

    def read_long_term(self) -> str:
        """Прочитать долгосрочную память (MEMORY.md)."""
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        """Записать в долгосрочную память (MEMORY.md)."""
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    def get_memory_context(self) -> str:
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""

    async def consolidate(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
    ) -> bool:
        """
        Объединить старые сообщения в MEMORY.md + HISTORY.md через вызов LLM инструмента.

        Возвращает True при успехе (включая случай, когда действие не требовалось), False при ошибке.
        """
        if archive_all:
            old_messages = session.messages
            keep_count = 0
            logger.info(
                "Консолидация памяти (archive_all): {} сообщений", len(session.messages)
            )
        else:
            keep_count = memory_window // 2
            if len(session.messages) <= keep_count:
                return True
            if len(session.messages) - session.last_consolidated <= 0:
                return True
            old_messages = session.messages[session.last_consolidated : -keep_count]
            if not old_messages:
                return True
            logger.info(
                "Консолидация памяти: {} для объединения, {} оставить",
                len(old_messages),
                keep_count,
            )

        lines = []
        for m in old_messages:
            if not m.get("content"):
                continue
            tools = (
                f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
            )
            lines.append(
                f"[{m.get('timestamp', '?')[:16]}] {m['role'].upper()}{tools}: {m['content']}"
            )

        current_memory = self.read_long_term()
        prompt = f"""Process this conversation and call the save_memory tool with your consolidation.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{chr(10).join(lines)}"""

        try:
            response = await provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a memory consolidation agent. Call the save_memory tool with your consolidation of the conversation.",
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_MEMORY_TOOL,
                model=model,
            )

            if not response.has_tool_calls:
                logger.warning(
                    "Консолидация памяти: LLM не вызвал save_memory, пропуск"
                )
                return False

            args = response.tool_calls[0].arguments
            if entry := args.get("history_entry"):
                if not isinstance(entry, str):
                    entry = json.dumps(entry, ensure_ascii=False)
                self.append_history(entry)
            if update := args.get("memory_update"):
                if not isinstance(update, str):
                    update = json.dumps(update, ensure_ascii=False)
                if update != current_memory:
                    self.write_long_term(update)

            session.last_consolidated = (
                0 if archive_all else len(session.messages) - keep_count
            )
            logger.info(
                "Консолидация памяти завершена: {} сообщений, last_consolidated={}",
                len(session.messages),
                session.last_consolidated,
            )

            return True
        except Exception:
            logger.exception("Ошибка консолидации памяти")
            return False
