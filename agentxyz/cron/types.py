"""Типы для Cron."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class CronSchedule:
    """Расписание для задачи cron."""

    kind: Literal["at", "every", "cron"]
    # Для "at": метка времени в мс
    at_ms: int | None = None
    # Для "every": интервал в мс
    every_ms: int | None = None
    # Для "cron": cron-выражение (например "0 9 * * *")
    expr: str | None = None
    # Часовой пояс для cron-выражений
    tz: str | None = None


@dataclass
class CronPayload:
    """Действия при выполнении задачи."""

    kind: Literal["system_event", "agent_turn"] = "agent_turn"
    message: str = ""
    # Доставить ответ в канал
    deliver: bool = False
    channel: str | None = None  # например "telegram"
    to: str | None = None  # например user_id


@dataclass
class CronJobState:
    """Состояние выполнения задачи."""

    next_run_at_ms: int | None = None
    last_run_at_ms: int | None = None
    last_status: Literal["ok", "error", "skipped"] | None = None
    last_error: str | None = None


@dataclass
class CronJob:
    """Запланированная задача."""

    id: str
    name: str
    enabled: bool = True
    schedule: CronSchedule = field(default_factory=lambda: CronSchedule(kind="every"))
    payload: CronPayload = field(default_factory=CronPayload)
    state: CronJobState = field(default_factory=CronJobState)
    created_at_ms: int = 0
    updated_at_ms: int = 0
    delete_after_run: bool = False


@dataclass
class CronStore:
    """Хранилище задач cron."""

    version: int = 1
    jobs: list[CronJob] = field(default_factory=list)
