"""Загрузчик навыков для возможностей агента."""

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any


# Директория встроенных навыков по умолчанию (относительно этого файла)
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"


class SkillsLoader:
    """
    Загрузчик навыков агента.

    Навыки — это файлы markdown (SKILL.md), которые учат агента использовать
    определённые инструменты или выполнять определённые задачи.
    """

    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None):
        self.workspace = workspace
        self.workspace_skills = workspace / "skills"
        self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR

    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]:
        """
        Список всех доступных навыков.

        Args:
            filter_unavailable: Если True, отфильтровать навыки с неудовлетворёнными требованиями.

        Returns:
            Список словарей информации о навыках с 'name', 'path', 'source'.
        """
        skills = []

        # Навыки рабочего пространства (высший приоритет)
        if self.workspace_skills.exists():
            for skill_dir in self.workspace_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        skills.append(
                            {
                                "name": skill_dir.name,
                                "path": str(skill_file),
                                "source": "workspace",
                            }
                        )

        # Встроенные навыки
        if self.builtin_skills and self.builtin_skills.exists():
            for skill_dir in self.builtin_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists() and not any(
                        skill["name"] == skill_dir.name for skill in skills
                    ):
                        skills.append(
                            {
                                "name": skill_dir.name,
                                "path": str(skill_file),
                                "source": "builtin",
                            }
                        )

        # Фильтр по требованиям
        if filter_unavailable:
            return [
                skill
                for skill in skills
                if self._check_requirements(self._get_skill_meta(skill["name"]))
            ]
        return skills

    def load_skill(self, name: str) -> str | None:
        """
        Загрузить навык по имени.

        Args:
            name: Имя навыка (имя директории).

        Returns:
            Содержимое навыка или None, если не найден.
        """
        # Сначала проверить рабочее пространство
        workspace_skill = self.workspace_skills / name / "SKILL.md"
        if workspace_skill.exists():
            return workspace_skill.read_text(encoding="utf-8")

        # Проверить встроенные
        if self.builtin_skills:
            builtin_skill = self.builtin_skills / name / "SKILL.md"
            if builtin_skill.exists():
                return builtin_skill.read_text(encoding="utf-8")

        return None

    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """
        Загрузить определённые навыки для включения в контекст агента.

        Args:
            skill_names: Список имён навыков для загрузки.

        Returns:
            Форматированное содержимое навыков.
        """
        parts = []
        for name in skill_names:
            content = self.load_skill(name)
            if content:
                content = self._strip_frontmatter(content)
                parts.append(f"### Skill: {name}\n\n{content}")

        return "\n\n---\n\n".join(parts) if parts else ""

    def build_skills_summary(self) -> str:
        """
        Построить сводку всех навыков (имя, описание, путь, доступность).

        Используется для прогрессивной загрузки — агент может прочитать полное
        содержимое навыка с помощью read_file при необходимости.

        Returns:
            Сводка навыков в формате XML.
        """
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""

        def escape_xml(s: str) -> str:
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        lines = ["<skills>"]
        for skill in all_skills:
            name = escape_xml(skill["name"])
            path = skill["path"]
            desc = escape_xml(self._get_skill_description(skill["name"]))
            skill_meta = self._get_skill_meta(skill["name"])
            available = self._check_requirements(skill_meta)

            lines.append(f'  <skill available="{str(available).lower()}">')
            lines.append(f"    <name>{name}</name>")
            lines.append(f"    <description>{desc}</description>")
            lines.append(f"    <location>{path}</location>")

            # Показать отсутствующие требования для недоступных навыков
            if not available:
                missing = self._get_missing_requirements(skill_meta)
                if missing:
                    lines.append(f"    <requires>{escape_xml(missing)}</requires>")

            lines.append("  </skill>")
        lines.append("</skills>")

        return "\n".join(lines)

    @staticmethod
    def _get_missing_requirements(skill_meta: dict) -> str:
        """Получить описание отсутствующих требований."""
        missing = []
        requires = skill_meta.get("requires", {})
        for b in requires.get("bins", []):
            if not shutil.which(b):
                missing.append(f"CLI: {b}")
        for env in requires.get("env", []):
            if not os.environ.get(env):
                missing.append(f"ENV: {env}")
        return ", ".join(missing)

    def _get_skill_description(self, name: str) -> str:
        """Получить описание навыка из его frontmatter."""
        meta = self.get_skill_metadata(name)
        if meta and meta.get("description"):
            return str(meta["description"])
        return name  # Резервный вариант — имя навыка

    @staticmethod
    def _strip_frontmatter(content: str) -> str:
        """Удалить YAML-frontmatter из содержимого markdown."""
        if content.startswith("---"):
            match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
            if match:
                return content[match.end() :].strip()
        return content

    @staticmethod
    def _parse_agentxyz_metadata(raw: str) -> dict[Any, Any]:
        """Разобрать JSON метаданных agentxyz из frontmatter (поддерживает ключи agentxyz и openclaw)."""
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                result = data.get("agentxyz") or data.get("openclaw")
                return result if isinstance(result, dict) else {}
            return {}
        except (json.JSONDecodeError, TypeError):
            return {}

    @staticmethod
    def _check_requirements(skill_meta: dict) -> bool:
        """Проверить, выполнены ли требования навыка (бинарные файлы, переменные окружения)."""
        requires = skill_meta.get("requires", {})
        for b in requires.get("bins", []):
            if not shutil.which(b):
                return False
        for env in requires.get("env", []):
            if not os.environ.get(env):
                return False
        return True

    def _get_skill_meta(self, name: str) -> dict:
        """Получить метаданные agentxyz для навыка (кешируются в frontmatter)."""
        meta = self.get_skill_metadata(name) or {}
        return self._parse_agentxyz_metadata(meta.get("metadata", ""))

    def get_always_skills(self) -> list[str]:
        """Получить навыки с пометкой always=true, которые удовлетворяют требованиям."""
        result = []
        for s in self.list_skills(filter_unavailable=True):
            meta = self.get_skill_metadata(s["name"]) or {}
            skill_meta = self._parse_agentxyz_metadata(meta.get("metadata", ""))
            if skill_meta.get("always") or meta.get("always"):
                result.append(s["name"])
        return result

    def get_skill_metadata(self, name: str) -> dict | None:
        """
        Получить метаданные из frontmatter навыка.

        Args:
            name: Имя навыка.

        Returns:
            Словарь метаданных или None.
        """
        content = self.load_skill(name)
        if not content:
            return None

        if content.startswith("---"):
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if match:
                # Простой разбор YAML
                metadata = {}
                for line in match.group(1).split("\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        metadata[key.strip()] = value.strip().strip("\"'")
                return metadata

        return None
