"""CLI команды для agentxyz."""

import asyncio
import os
import select
import signal
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self


# Принудительное использование кодировки UTF-8 для консоли Windows
if sys.platform == "win32":
    if sys.stdout.encoding != "utf-8":
        os.environ["PYTHONIOENCODING"] = "utf-8"
        # Переоткрыть stdout/stderr с кодировкой UTF-8
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

if TYPE_CHECKING:
    from agentxyz.providers.litellm_provider import LiteLLMProvider

import typer
from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.formatted_text import ANSI, HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from agentxyz import __logo__, __version__
from agentxyz.config.paths import get_workspace_path
from agentxyz.config.schema import Config
from agentxyz.providers import CustomProvider, LiteLLMProvider
from agentxyz.utils.helpers import sync_workspace_templates


app = typer.Typer(
    name="agentxyz",
    help=f"{__logo__} agentxyz - Персональный AI помощник",
    no_args_is_help=True,
)

console = Console()
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}


# ---------------------------------------------------------------------------
# CLI input: prompt_toolkit для редактирования, вставки, истории и отображения
# ---------------------------------------------------------------------------

_PROMPT_SESSION: PromptSession | None = None
_SAVED_TERM_ATTRS = None  # исходные настройки termios, восстанавливаются при выходе


def _flush_pending_tty_input() -> None:
    """Отбрасывать непрочитанные нажатия клавиш, сделанные во время генерации вывода моделью."""
    try:
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return
    except Exception:
        return

    try:
        import termios

        termios.tcflush(fd, termios.TCIFLUSH)
        return
    except Exception:
        pass

    try:
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            if not os.read(fd, 4096):
                break
    except Exception:
        return


def _restore_terminal() -> None:
    """Восстановить терминал в исходное состояние (эхо, буферизация строк и т.д.)."""
    if _SAVED_TERM_ATTRS is None:
        return
    try:
        import termios

        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERM_ATTRS)
    except Exception:
        pass


def _init_prompt_session() -> None:
    """Создать сессию prompt_toolkit с постоянной историей в файле."""
    global _PROMPT_SESSION, _SAVED_TERM_ATTRS

    # Сохранить состояние терминала, чтобы можно было восстановить его при выходе
    try:
        import termios

        _SAVED_TERM_ATTRS = termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        pass

    from agentxyz.config.paths import get_cli_history_path

    history_file = get_cli_history_path()
    history_file.parent.mkdir(parents=True, exist_ok=True)

    _PROMPT_SESSION = PromptSession(
        history=FileHistory(str(history_file)),
        enable_open_in_editor=False,
        multiline=False,  # Enter подтверждает ввод (однострочный режим)
    )


def _make_console() -> Console:
    return Console(file=sys.stdout)


def _render_interactive_ansi(render_fn: Callable[[Console], None]) -> str:
    """Рендерить вывод Rich в ANSI, чтобы prompt_toolkit мог безопасно его печатать."""
    color_system: str | None = console.color_system or "standard"
    ansi_console = Console(
        force_terminal=True,
        color_system=color_system,  # type: ignore[arg-type]
        width=console.width,
    )
    with ansi_console.capture() as capture:
        render_fn(ansi_console)
    return capture.get()  # type: ignore[no-any-return]


def _print_agent_response(response: str, render_markdown: bool) -> None:
    """Вывести ответ ассистента с единым стилем терминала."""
    console = _make_console()
    content = response or ""
    body = Markdown(content) if render_markdown else Text(content)
    console.print()
    console.print(f"[cyan]{__logo__} agentxyz[/cyan]")
    console.print(body)
    console.print()


async def _print_interactive_line(text: str) -> None:
    """Выводить асинхронные интерактивные обновления с безопасным для prompt_toolkit стилем Rich."""

    def _write() -> None:
        ansi = _render_interactive_ansi(lambda c: c.print(f"  [dim]↳ {text}[/dim]"))
        print_formatted_text(ANSI(ansi), end="")

    await run_in_terminal(_write)


async def _print_interactive_response(response: str, render_markdown: bool) -> None:
    """Выводить асинхронные интерактивные ответы с безопасным для prompt_toolkit стилем Rich."""

    def _write() -> None:
        content = response or ""

        def _render(c: Console) -> None:
            c.print()
            c.print(f"[cyan]{__logo__} agentxyz[/cyan]")
            c.print(Markdown(content) if render_markdown else Text(content))
            c.print()

        ansi = _render_interactive_ansi(_render)
        print_formatted_text(ANSI(ansi), end="")

    await run_in_terminal(_write)


class _ThinkingSpinner:
    """Обёртка для спиннера с поддержкой паузы для чистого вывода прогресса."""

    def __init__(self, enabled: bool):
        self._spinner = (
            console.status("[dim]agentxyz думает...[/dim]", spinner="dots")
            if enabled
            else None
        )
        self._active = False

    def __enter__(self) -> Self:
        if self._spinner:
            self._spinner.start()
        self._active = True
        return self

    def __exit__(self, *exc: object) -> Literal[False]:
        self._active = False
        if self._spinner:
            self._spinner.stop()
        return False

    @contextmanager
    def pause(self) -> Iterator[None]:
        """Временно остановить спиннер при выводе прогресса."""
        if self._spinner and self._active:
            self._spinner.stop()
        try:
            yield
        finally:
            if self._spinner and self._active:
                self._spinner.start()


def _print_cli_progress_line(text: str, thinking: _ThinkingSpinner | None) -> None:
    """Вывести строку прогресса CLI, приостанавливая спиннер при необходимости."""
    with thinking.pause() if thinking else nullcontext():
        console.print(f"  [dim]↳ {text}[/dim]")


async def _print_interactive_progress_line(
    text: str, thinking: _ThinkingSpinner | None
) -> None:
    """Вывести интерактивную строку прогресса, приостанавливая спиннер при необходимости."""
    with thinking.pause() if thinking else nullcontext():
        await _print_interactive_line(text)


def _is_exit_command(command: str) -> bool:
    """Вернуть True, когда ввод должен завершить интерактивный чат."""
    return command.lower() in EXIT_COMMANDS


async def _read_interactive_input_async() -> str:
    """Читать пользовательский ввод с помощью prompt_toolkit (обрабатывает вставку, историю, отображение).

    prompt_toolkit изначально обрабатывает:
    - Многострочную вставку (режим bracketed paste)
    - Навигацию по истории (стрелки вверх/вниз)
    - Чистое отображение (без фантомных символов или артефактов)
    """
    if _PROMPT_SESSION is None:
        raise RuntimeError("Call _init_prompt_session() first")
    try:
        with patch_stdout():
            return str(
                await _PROMPT_SESSION.prompt_async(
                    HTML("<b fg='ansiblue'>You:</b> "),
                )
            )
    except EOFError as exc:
        raise KeyboardInterrupt from exc


def version_callback(value: bool) -> None:
    if value:
        console.print(f"{__logo__} agentxyz v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True
    ),
) -> None:
    """agentxyz - Персональный AI помощник."""
    pass


# ============================================================================
# Onboard / Setup
# ============================================================================


@app.command()
def onboard(
    workspace_param: str | None = typer.Option(
        None, "--workspace", "-w", help="Рабочая директория"
    ),
    config: str | None = typer.Option(
        None, "--config", "-c", help="Путь к файлу конфигурации"
    ),
) -> None:
    """Инициализация конфигурации и рабочего пространства agentxyz."""
    from agentxyz.config.loader import (
        get_config_path,
        load_config,
        save_config,
        set_config_path,
    )
    from agentxyz.config.schema import Config

    if config:
        config_path = Path(config).expanduser().resolve()
        set_config_path(config_path)
        console.print(f"[dim]Используется конфиг: {config_path}[/dim]")
    else:
        config_path = get_config_path()

    def _apply_workspace_override(loaded: Config) -> Config:
        if workspace_param:
            loaded.agents.defaults.workspace = workspace_param
        return loaded

    # Создать или обновить конфиг
    if config_path.exists():
        console.print(
            f"[yellow]Конфигурация уже существует по пути {config_path}[/yellow]"
        )
        console.print(
            "  [bold]y[/bold] = перезаписать значениями по умолчанию (существующие значения будут потеряны)"
        )
        console.print(
            "  [bold]N[/bold] = обновить конфигурацию, сохраняя существующие значения и добавляя новые поля"
        )
        if typer.confirm("Перезаписать?"):
            cfg_obj = _apply_workspace_override(Config())
            save_config(cfg_obj, config_path)
            console.print(
                f"[green]✓[/green] Конфигурация сброшена на значения по умолчанию в {config_path}"
            )
        else:
            cfg_obj = _apply_workspace_override(load_config(config_path))
            save_config(cfg_obj, config_path)
            console.print(
                f"[green]✓[/green] Конфигурация обновлена в {config_path} (существующие значения сохранены)"
            )
    else:
        cfg_obj = _apply_workspace_override(Config())
        save_config(cfg_obj, config_path)
        console.print(f"[green]✓[/green] Создана конфигурация по пути {config_path}")

    console.print(
        "[dim]Шаблон конфигурации теперь использует `maxTokens` + `contextWindowTokens`; `memoryWindow` больше не является настройкой времени выполнения.[/dim]"
    )
    # Обновить конфигурацию каналов (добавить отсутствующие поля)
    _onboard_plugins(config_path)

    # Создать рабочее пространство
    workspace = get_workspace_path(cfg_obj.workspace_path)

    if not workspace.exists():
        workspace.mkdir(parents=True, exist_ok=True)
        console.print(
            f"[green]✓[/green] Рабочее пространство создано по пути {workspace}"
        )

    # Создать файлы bootstrap по умолчанию
    sync_workspace_templates(workspace, console=console)

    agent_cmd = 'agentxyz agent -m "Hello!"'
    if config:
        agent_cmd += f" --config {config_path}"

    console.print(f"\n{__logo__} agentxyz готов к работе!")
    console.print("\nДальнейшие действия:")
    console.print("  1. Укажите API ключ в [cyan]~/.agentxyz/config.json[/cyan]")
    console.print("     Возьмите тут: https://openrouter.ai/keys")
    console.print("  2. Запустите Gateway: [cyan]agentxyz gateway[/cyan]")
    console.print("     Или диалог: [cyan]agentxyz agent[/cyan]")
    console.print(f"\n[dim]Пример команды: {agent_cmd}[/dim]")


def _merge_missing_defaults(existing: Any, defaults: Any) -> Any:
    """Рекурсивно заполнить отсутствующие значения из defaults без перезаписи пользовательской конфигурации."""
    if not isinstance(existing, dict) or not isinstance(defaults, dict):
        return existing

    merged = dict(existing)
    for key, value in defaults.items():
        if key not in merged:
            merged[key] = value
        else:
            merged[key] = _merge_missing_defaults(merged[key], value)
    return merged


def _onboard_plugins(config_path: Path) -> None:
    """Добавить конфигурацию по умолчанию для всех обнаруженных каналов (встроенные + плагины)."""
    import json

    from agentxyz.channels.registry import discover_all

    all_channels = discover_all()
    if not all_channels:
        return

    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)

    channels = data.setdefault("channels", {})
    for name, cls in all_channels.items():
        if name not in channels:
            channels[name] = cls.default_config()
        else:
            channels[name] = _merge_missing_defaults(
                channels[name], cls.default_config()
            )

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _make_provider(
    config: Config,
) -> LiteLLMProvider | CustomProvider:
    """Создать LiteLLMProvider из конфигурации. Завершает работу, если API-ключ не найден."""
    from agentxyz.providers.base import GenerationSettings

    model = config.agents.defaults.model
    provider_name = config.get_provider_name(model)
    p = config.get_provider(model)

    # Custom: прямой OpenAI-совместимый эндпоинт, в обход LiteLLM
    from agentxyz.providers.custom_provider import CustomProvider

    if provider_name == "custom":
        return CustomProvider(
            api_key=p.api_key if p else "no-key",
            api_base=config.get_api_base(model) or "http://localhost:8000/v1",
            default_model=model,
            extra_headers=p.extra_headers if p else None,
        )
    else:
        from agentxyz.providers.litellm_provider import LiteLLMProvider
        from agentxyz.providers.registry import find_by_name

        spec = find_by_name(provider_name or "")
        if (
            not model.startswith("bedrock/")
            and not (p and p.api_key)
            and not (spec and spec.is_local)
        ):
            console.print("[red]Ошибка: API-ключ не настроен.[/red]")
            console.print(
                "Установите его в ~/.agentxyz/config.json в разделе providers"
            )
            raise typer.Exit(1)
        provider = LiteLLMProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
            provider_name=provider_name,
        )

    defaults = config.agents.defaults
    provider.generation = GenerationSettings(
        temperature=defaults.temperature,
        max_tokens=defaults.max_tokens,
        reasoning_effort=defaults.reasoning_effort,
    )
    return provider


def _load_runtime_config(
    config: str | None = None, workspace: str | None = None
) -> Config:
    """Загружает конфиг и при необходимости меняет активную рабочую директорию."""
    from agentxyz.config.loader import load_config, set_config_path

    config_path = None
    if config:
        config_path = Path(config).expanduser().resolve()
        if not config_path.exists():
            console.print(
                f"[red]Ошибка: Файл конфигурации не найден: {config_path}[/red]"
            )
            raise typer.Exit(1)
        set_config_path(config_path)
        console.print(f"[dim]Используется конфиг: {config_path}[/dim]")

    loaded = load_config(config_path)
    if workspace:
        loaded.agents.defaults.workspace = workspace
    return loaded


def _print_deprecated_memory_window_notice(config: Config) -> None:
    """Предупредить при работе со старой конфигурацией только с memoryWindow."""
    if config.agents.defaults.should_warn_deprecated_memory_window:
        console.print(
            "[yellow]Подсказка:[/yellow] Обнаружен устаревший `memoryWindow` без "
            "`contextWindowTokens`. `memoryWindow` игнорируется; запустите "
            "[cyan]agentxyz onboard[/cyan] чтобы обновить шаблон конфигурации."
        )


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int | None = typer.Option(None, "--port", "-p", help="Gateway port"),
    workspace: str | None = typer.Option(
        None, "--workspace", "-w", help="Рабочий каталог"
    ),
    config: str | None = typer.Option(
        None, "--config", "-c", help="Путь к файлу конфигурации"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Подробный лог"),
) -> None:
    """Запустить agentxyz с веб-интерфейсом (Gateway)."""
    from agentxyz.agent.loop import AgentLoop
    from agentxyz.bus.queue import MessageBus
    from agentxyz.channels.manager import ChannelManager
    from agentxyz.config.paths import get_cron_dir
    from agentxyz.cron.service import CronService
    from agentxyz.cron.types import CronJob
    from agentxyz.gateway.server import GatewayServer
    from agentxyz.heartbeat.service import HeartbeatService
    from agentxyz.session.manager import SessionManager

    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    loaded_config = _load_runtime_config(config, workspace)
    _print_deprecated_memory_window_notice(loaded_config)
    port = port if port is not None else loaded_config.gateway.port

    if workspace:
        loaded_config.agents.defaults.workspace = workspace
    console.print(f"{__logo__} Запуск agentxyz Gateway на порту {port}...")
    sync_workspace_templates(loaded_config.workspace_path, silent=True)
    bus = MessageBus()
    provider = _make_provider(loaded_config)
    session_manager = SessionManager(loaded_config.workspace_path)

    # Создать сервис cron первым (callback устанавливается после создания агента)
    cron_store_path = get_cron_dir() / "jobs.json"
    cron = CronService(cron_store_path)

    # Инициализировать агент и сервис cron
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=loaded_config.workspace_path,
        model=loaded_config.agents.defaults.model,
        max_iterations=loaded_config.agents.defaults.max_tool_iterations,
        context_window_tokens=loaded_config.agents.defaults.context_window_tokens,
        web_search_config=loaded_config.tools.web.search,
        web_proxy=loaded_config.tools.web.proxy or None,
        exec_config=loaded_config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=loaded_config.tools.restrict_to_workspace,
        session_manager=session_manager,
        mcp_servers=loaded_config.tools.mcp_servers,
        channels_config=loaded_config.channels,
    )

    # Установить callback cron (требует агент)
    async def on_cron_job(job: CronJob) -> str | None:
        """Выполнить задачу cron через агента."""
        from agentxyz.agent.tools.cron import CronTool
        from agentxyz.agent.tools.message import MessageTool
        from agentxyz.utils.evaluator import evaluate_response

        reminder_note = (
            "[Scheduled Task] Timer finished.\n\n"
            f"Task '{job.name}' has been triggered.\n"
            f"Scheduled instruction: {job.payload.message}"
        )

        # Предотвратить запуск агентом новых заданий cron во время выполнения
        cron_tool = agent.tools.get("cron")
        cron_token = None
        if isinstance(cron_tool, CronTool):
            cron_token = cron_tool.set_cron_context(True)
        try:
            response = await agent.process_direct(
                reminder_note,
                session_key=f"cron:{job.id}",
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to or "direct",
            )
        finally:
            if isinstance(cron_tool, CronTool) and cron_token is not None:
                cron_tool.reset_cron_context(cron_token)

        message_tool = agent.tools.get("message")
        if isinstance(message_tool, MessageTool) and message_tool.sent_in_turn:
            return response

        if job.payload.deliver and job.payload.to and response:
            should_notify = await evaluate_response(
                response,
                job.payload.message,
                provider,
                agent.model,
            )
            if should_notify:
                from agentxyz.bus.events import OutboundMessage

                await bus.publish_outbound(
                    OutboundMessage(
                        channel=job.payload.channel or "cli",
                        chat_id=job.payload.to,
                        content=response or "",
                    )
                )
        return response

    cron.on_job = on_cron_job

    # Создать Gateway сервер (если включён)
    gateway_config = loaded_config.gateway
    gateway_server: GatewayServer | None = None

    if gateway_config.enabled:
        gateway_config.port = port

        gateway_server = GatewayServer(
            config=gateway_config,
            bus=bus,
            root_config=loaded_config,
            session_manager=session_manager,
        )

    # Создать менеджер каналов (telegram, email) после создания gateway_server
    channels = ChannelManager(
        loaded_config,
        bus,
        session_manager=session_manager,
        gateway_server=gateway_server,
    )

    def _pick_heartbeat_target() -> tuple[str, str]:
        """Выбирает доступный канал/чат для сообщений, инициированных heartbeat."""
        enabled = set(channels.enabled_channels)
        # Предпочитаем недавно обновлённую не-внутреннюю сессию на включённом канале.
        for item in session_manager.list_sessions():
            key = item.get("key") or ""
            if ":" not in key:
                continue
            channel, chat_id = key.split(":", 1)
            if channel in {"cli", "system", "gateway"}:
                continue
            if channel in enabled and chat_id:
                return channel, chat_id
        # Fallback сохраняет предыдущее поведение, но остаётся явным.
        return "cli", "direct"

    # Создать сервис heartbeat
    async def on_heartbeat_execute(tasks: str) -> str:
        """Фаза 2: выполнение heartbeat-задач через полный цикл агента."""
        channel, chat_id = _pick_heartbeat_target()

        async def _silent(*_args: Any, **_kwargs: Any) -> None:
            pass

        return await agent.process_direct(
            tasks,
            session_key="heartbeat",
            channel=channel,
            chat_id=chat_id,
            on_progress=_silent,  # suppress: heartbeat не должен отправлять прогресс во внешние каналы
        )

    async def on_heartbeat_notify(response: str) -> None:
        """Доставляет heartbeat-ответ пользователю в канал."""
        from agentxyz.bus.events import OutboundMessage

        channel, chat_id = _pick_heartbeat_target()
        if channel == "cli":
            return  # Нет доступного внешнего канала для доставки
        await bus.publish_outbound(
            OutboundMessage(channel=channel, chat_id=chat_id, content=response)
        )

    hb_cfg = loaded_config.gateway.heartbeat

    heartbeat = HeartbeatService(
        workspace=loaded_config.workspace_path,
        provider=provider,
        model=agent.model,
        on_execute=on_heartbeat_execute,
        on_notify=on_heartbeat_notify,
        interval_s=hb_cfg.interval_s,
        enabled=hb_cfg.enabled,
    )

    # Вывод статуса
    if gateway_server:
        console.print(
            f"[green]✓[/green] Gateway: http://localhost:{gateway_config.port}"
        )

    if channels.enabled_channels:
        console.print(
            f"[green]✓[/green] Каналы: {', '.join(channels.enabled_channels)}"
        )
    else:
        console.print("[yellow]Предупреждение: нет активных каналов[/yellow]")

    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(
            f"[green]✓[/green] Cron: {cron_status['jobs']} задач по расписанию"
        )

    console.print("[green]✓[/green] Heartbeat: раз в полчаса")

    # Предупреждение если нет ни gateway ни каналов
    if not gateway_server and not channels.enabled_channels:
        console.print(
            "[yellow]Предупреждение: не настроен ни Gateway ни внешние каналы.[/yellow]"
        )
        console.print(
            "[dim]Агент будет работать, но нет способа взаимодействовать с ним извне.[/dim]"
        )
        console.print(
            "[dim]Включите gateway.enabled=true или channels.telegram.enabled=true в конфиге.[/dim]"
        )
        console.print()

    async def run() -> None:
        try:
            await cron.start()
            await heartbeat.start()
            tasks = [agent.run(), channels.start_all()]
            if gateway_server:
                tasks.append(gateway_server.start())
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            console.print("\nЗавершение...")
        except Exception:
            import traceback

            console.print("\n[red]Ошибка: Шлюз неожиданно завершился сбоем[/red]")
            console.print(traceback.format_exc())
        finally:
            await agent.close_mcp()
            heartbeat.stop()
            cron.stop()
            agent.stop()
            await channels.stop_all()
            if gateway_server:
                await gateway_server.stop()

    asyncio.run(run())


# ============================================================================
# Команды агента
# ============================================================================


@app.command()
def agent(
    message: str = typer.Option(
        None, "--message", "-m", help="Сообщение для отправки агенту"
    ),
    session_id: str = typer.Option("cli:default", "--session", "-s", help="ID сеанса"),
    workspace: str | None = typer.Option(
        None, "--workspace", "-w", help="Рабочая директория"
    ),
    config: str | None = typer.Option(
        None, "--config", "-c", help="Путь к файлу конфигурации"
    ),
    markdown: bool = typer.Option(
        True,
        "--markdown/--no-markdown",
        help="Отображать вывод ассистента как Markdown",
    ),
    logs: bool = typer.Option(
        False,
        "--logs/--no-logs",
        help="Показывать журналы работы agentxyz во время чата",
    ),
) -> None:
    """Взаимодействовать напрямую."""
    from loguru import logger

    from agentxyz.agent.loop import AgentLoop
    from agentxyz.bus.queue import MessageBus
    from agentxyz.config.paths import get_cron_dir
    from agentxyz.cron.service import CronService

    loaded_config = _load_runtime_config(config, workspace)
    _print_deprecated_memory_window_notice(loaded_config)
    sync_workspace_templates(loaded_config.workspace_path, silent=True)

    bus = MessageBus()
    provider = _make_provider(loaded_config)

    # Создать сервис cron для использования инструмента (обратный вызов не нужен для CLI, если он не запущен)
    cron_store_path = get_cron_dir() / "jobs.json"
    cron = CronService(cron_store_path)

    if logs:
        logger.enable("agentxyz")
    else:
        logger.disable("agentxyz")

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=loaded_config.workspace_path,
        model=loaded_config.agents.defaults.model,
        max_iterations=loaded_config.agents.defaults.max_tool_iterations,
        context_window_tokens=loaded_config.agents.defaults.context_window_tokens,
        web_search_config=loaded_config.tools.web.search,
        web_proxy=loaded_config.tools.web.proxy or None,
        exec_config=loaded_config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=loaded_config.tools.restrict_to_workspace,
        mcp_servers=loaded_config.tools.mcp_servers,
        channels_config=loaded_config.channels,
    )

    # Общая ссылка для callbacks прогресса
    _thinking: _ThinkingSpinner | None = None

    async def _cli_progress(content: str, *, tool_hint: bool = False) -> None:
        ch = agent_loop.channels_config
        if ch and tool_hint and not ch.send_tool_hints:
            return
        if ch and not tool_hint and not ch.send_progress:
            return
        _print_cli_progress_line(content, _thinking)

    if message:
        # Режим одного сообщения — прямой вызов, без шины
        async def run_once() -> None:
            nonlocal _thinking
            _thinking = _ThinkingSpinner(enabled=not logs)
            with _thinking:
                response = await agent_loop.process_direct(
                    message, session_id, on_progress=_cli_progress
                )
            _thinking = None
            _print_agent_response(response, render_markdown=markdown)
            await agent_loop.close_mcp()

        asyncio.run(run_once())
    else:
        # Интерактивный режим
        from agentxyz.bus.events import InboundMessage

        _init_prompt_session()
        console.print(
            f"{__logo__} Интерактивный режим (введите [bold]exit[/bold] или [bold]Ctrl+C[/bold] для выхода)\n"
        )

        if ":" in session_id:
            cli_channel, cli_chat_id = session_id.split(":", 1)
        else:
            cli_channel, cli_chat_id = "cli", session_id

        def _handle_signal(signum: int, frame: object) -> None:
            sig_name = signal.Signals(signum).name
            _restore_terminal()

            console.print(f"\nПолучен сигнал {sig_name}, до свидания!")
            sys.exit(0)

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
        # SIGHUP недоступен на Windows
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, _handle_signal)
        # Игнорируем SIGPIPE, чтобы предотвратить тихое завершение процесса при записи в закрытые каналы
        # SIGPIPE недоступен на Windows
        if hasattr(signal, "SIGPIPE"):
            signal.signal(signal.SIGPIPE, signal.SIG_IGN)

        async def run_interactive() -> None:
            bus_task = asyncio.create_task(agent_loop.run())
            turn_done = asyncio.Event()
            turn_done.set()
            turn_response: list[str] = []

            async def _consume_outbound() -> None:
                while True:
                    try:
                        msg = await asyncio.wait_for(
                            bus.consume_outbound(), timeout=1.0
                        )
                        if msg.metadata.get("_progress"):
                            is_tool_hint = msg.metadata.get("_tool_hint", False)
                            ch = agent_loop.channels_config
                            if ch and is_tool_hint and not ch.send_tool_hints:
                                pass
                            elif ch and not is_tool_hint and not ch.send_progress:
                                pass
                            else:
                                await _print_interactive_progress_line(
                                    msg.content, _thinking
                                )

                        elif not turn_done.is_set():
                            if msg.content:
                                turn_response.append(msg.content)
                            turn_done.set()
                        elif msg.content:
                            await _print_interactive_response(
                                msg.content, render_markdown=markdown
                            )

                    except TimeoutError:
                        continue
                    except asyncio.CancelledError:
                        break

            outbound_task = asyncio.create_task(_consume_outbound())

            try:
                while True:
                    try:
                        _flush_pending_tty_input()
                        user_input = await _read_interactive_input_async()
                        command = user_input.strip()
                        if not command:
                            continue

                        if _is_exit_command(command):
                            _restore_terminal()
                            console.print("\nПока!")
                            break

                        turn_done.clear()
                        turn_response.clear()

                        await bus.publish_inbound(
                            InboundMessage(
                                channel=cli_channel,
                                sender_id="user",
                                chat_id=cli_chat_id,
                                content=user_input,
                            )
                        )

                        nonlocal _thinking
                        _thinking = _ThinkingSpinner(enabled=not logs)
                        with _thinking:
                            await turn_done.wait()
                        _thinking = None

                        if turn_response:
                            _print_agent_response(
                                turn_response[0], render_markdown=markdown
                            )
                    except KeyboardInterrupt:
                        _restore_terminal()
                        console.print("\nПока!")
                        break
                    except EOFError:
                        _restore_terminal()
                        console.print("\nПока!")
                        break
            finally:
                agent_loop.stop()
                outbound_task.cancel()
                await asyncio.gather(bus_task, outbound_task, return_exceptions=True)
                await agent_loop.close_mcp()

        asyncio.run(run_interactive())


# ============================================================================
# Команды каналов
# ============================================================================


channels_app = typer.Typer(help="Управление каналами")
app.add_typer(channels_app, name="channels")


@channels_app.command("status")
def channels_status() -> None:
    """Показать статус каналов."""
    from agentxyz.channels.registry import discover_all
    from agentxyz.config.loader import load_config

    config = load_config()

    table = Table(title="Статус каналов")
    table.add_column("Канал", style="cyan")
    table.add_column("Включён", style="green")
    table.add_column("Конфигурация", style="yellow")

    for name, cls in sorted(discover_all().items()):
        section = getattr(config.channels, name, None)
        if section is None:
            enabled = False
        elif isinstance(section, dict):
            enabled = section.get("enabled", False)
        else:
            enabled = getattr(section, "enabled", False)
        table.add_row(
            cls.display_name,
            "[green]\u2713[/green]" if enabled else "[dim]\u2717[/dim]",
        )

    console.print(table)


# ============================================================================
# Команды плагинов
# ============================================================================

plugins_app = typer.Typer(help="Управление плагинами каналов")
app.add_typer(plugins_app, name="plugins")


@plugins_app.command("list")
def plugins_list() -> None:
    """Показать все обнаруженные каналы (встроенные и плагины)."""
    from agentxyz.channels.registry import discover_all, discover_channel_names
    from agentxyz.config.loader import load_config

    config = load_config()
    builtin_names = set(discover_channel_names())
    all_channels = discover_all()

    table = Table(title="Плагины каналов")
    table.add_column("Имя", style="cyan")
    table.add_column("Источник", style="magenta")
    table.add_column("Включён", style="green")

    for name in sorted(all_channels):
        cls = all_channels[name]
        source = "builtin" if name in builtin_names else "plugin"
        section = getattr(config.channels, name, None)
        if section is None:
            enabled = False
        elif isinstance(section, dict):
            enabled = section.get("enabled", False)
        else:
            enabled = getattr(section, "enabled", False)
        table.add_row(
            cls.display_name,
            source,
            "[green]да[/green]" if enabled else "[dim]нет[/dim]",
        )

    console.print(table)


# ============================================================================
# Команды статуса
# ============================================================================


@app.command()
def status() -> None:
    """Статус системы."""
    from agentxyz.config.loader import get_config_path, load_config

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} Статус agentxyz\n")

    console.print(
        f"Конфиг: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}"
    )
    console.print(
        f"Рабочая папка: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}"
    )

    if config_path.exists():
        from agentxyz.providers.registry import PROVIDERS

        console.print(f"Модель: {config.agents.defaults.model}")

        # Проверить API-ключи из реестра
        for spec in PROVIDERS:
            p = getattr(config.providers, spec.name, None)
            if p is None:
                continue
            elif spec.is_local:
                # Локальные развёртывания показывают api_base вместо api_key
                if p.api_base:
                    console.print(f"{spec.label}: [green]✓ {p.api_base}[/green]")
                else:
                    console.print(f"{spec.label}: [dim]не настроен[/dim]")
            else:
                has_key = bool(p.api_key)
                console.print(
                    f"{spec.label}: {'[green]✓[/green]' if has_key else '[dim]не настроен[/dim]'}"
                )


if __name__ == "__main__":
    app()
