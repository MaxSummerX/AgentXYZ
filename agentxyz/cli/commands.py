"""CLI команды для agentxyz."""

import asyncio
import os
import select
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from agentxyz.providers.litellm_provider import LiteLLMProvider

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from agentxyz import __logo__, __version__
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

    history_file = Path.home() / ".agentxyz" / "history" / "cli_history"
    history_file.parent.mkdir(parents=True, exist_ok=True)

    _PROMPT_SESSION = PromptSession(
        history=FileHistory(str(history_file)),
        enable_open_in_editor=False,
        multiline=False,  # Enter подтверждает ввод (однострочный режим)
    )


def _print_agent_response(response: str, render_markdown: bool) -> None:
    """Вывести ответ ассистента с единым стилем терминала."""
    content = response or ""
    body = Markdown(content) if render_markdown else Text(content)
    console.print()
    console.print(f"[cyan]{__logo__} agentxyz[/cyan]")
    console.print(body)
    console.print()


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
def onboard() -> None:
    """Инициализация конфигурации и рабочего пространства agentxyz."""
    from agentxyz.config.loader import get_config_path, load_config, save_config
    from agentxyz.config.schema import Config
    from agentxyz.utils.helpers import get_workspace_path

    config_path = get_config_path()

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
            config = Config()
            save_config(config)
            console.print(
                f"[green]✓[/green] Конфигурация сброшена на значения по умолчанию в {config_path}"
            )
        else:
            config = load_config()
            save_config(config)
            console.print(
                f"[green]✓[/green] Конфигурация обновлена в {config_path} (существующие значения сохранены)"
            )
    else:
        save_config(Config())
        console.print(f"[green]✓[/green] Создана конфигурация по пути {config_path}")

    # Создать рабочее пространство
    workspace = get_workspace_path()

    if not workspace.exists():
        workspace.mkdir(parents=True, exist_ok=True)
        console.print(
            f"[green]✓[/green] Рабочее пространство создано по пути {workspace}"
        )

    # Создать файлы bootstrap по умолчанию
    sync_workspace_templates(workspace)

    console.print(f"\n{__logo__} agentxyz готов к работе!")
    console.print("\nДальнейшие действия:")
    console.print("  1. Укажите API ключ в [cyan]~/.agentxyz/config.json[/cyan]")
    console.print("     Возьмите тут: https://openrouter.ai/keys")
    console.print("  2. Запустите Gateway: [cyan]agentxyz gateway[/cyan]")
    console.print("     Или диалог: [cyan]agentxyz agent[/cyan]")


def _make_provider(
    config: Config,
) -> LiteLLMProvider | CustomProvider:
    """Создать LiteLLMProvider из конфигурации. Завершает работу, если API-ключ не найден."""
    from agentxyz.providers.custom_provider import CustomProvider
    from agentxyz.providers.litellm_provider import LiteLLMProvider

    model = config.agents.defaults.model
    provider_name = config.get_provider_name(model)
    p = config.get_provider(model)

    # Custom: прямой OpenAI-совместимый эндпоинт, в обход LiteLLM
    if provider_name == "custom":
        return CustomProvider(
            api_key=p.api_key if p else "no-key",
            api_base=config.get_api_base(model) or "http://localhost:8000/v1",
            default_model=model,
        )

    from agentxyz.providers.registry import find_by_name

    spec = find_by_name(provider_name or "")
    if not model.startswith("bedrock/") and not (p and p.api_key) and not spec:
        console.print("[red]Ошибка: API-ключ не настроен.[/red]")
        console.print("Установите его в ~/.agentxyz/config.json в разделе providers")
        raise typer.Exit(1)

    return LiteLLMProvider(
        api_key=p.api_key if p else None,
        api_base=config.get_api_base(model),
        default_model=model,
        extra_headers=p.extra_headers if p else None,
        provider_name=provider_name,
    )


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int = typer.Option(8888, "--port", "-p", help="Порт Gateway"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Подробный лог"),
) -> None:
    """Запустить agentxyz с веб-интерфейсом (Gateway)."""
    from agentxyz.agent.loop import AgentLoop
    from agentxyz.bus.queue import MessageBus
    from agentxyz.channels.manager import ChannelManager
    from agentxyz.config.loader import get_data_dir, load_config
    from agentxyz.cron.service import CronService
    from agentxyz.cron.types import CronJob
    from agentxyz.gateway.server import GatewayServer
    from agentxyz.heartbeat.service import HeartbeatService
    from agentxyz.session.manager import SessionManager

    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    console.print(f"{__logo__} Запуск agentxyz Gateway на порту {port}...")

    config = load_config()
    sync_workspace_templates(config.workspace_path)
    bus = MessageBus()
    provider = _make_provider(config)
    session_manager = SessionManager(config.workspace_path)

    # Создать сервис cron первым (callback устанавливается после создания агента)
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    # Инициализировать агент и сервис cron
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        temperature=config.agents.defaults.temperature,
        max_tokens=config.agents.defaults.max_tokens,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
    )

    # Установить callback cron (требует агент)
    async def on_cron_job(job: CronJob) -> str | None:
        """Выполнить задачу cron через агента."""
        response = await agent.process_direct(
            job.payload.message,
            session_key=f"cron:{job.id}",
            channel=job.payload.channel or "cli",
            chat_id=job.payload.to or "direct",
        )
        if job.payload.deliver and job.payload.to:
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
    gateway_config = config.gateway
    gateway_server: GatewayServer | None = None

    if gateway_config.enabled:
        # Override port from CLI if provided
        if port != 8888:
            gateway_config.port = port

        gateway_server = GatewayServer(
            config=gateway_config,
            bus=bus,
            root_config=config,
            session_manager=session_manager,
        )

    # Создать менеджер каналов (telegram, email) после создания gateway_server
    channels = ChannelManager(
        config, bus, session_manager=session_manager, gateway_server=gateway_server
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

    hb_cfg = config.gateway.heartbeat

    heartbeat = HeartbeatService(
        workspace=config.workspace_path,
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
        console.print(f"[green]✓[/green] Cron: {hb_cfg.interval_s} задач по расписанию")

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

            # Создать задачи для агента, каналов и опционально gateway
            tasks = [
                agent.run(),
                channels.start_all(),
            ]

            if gateway_server:
                tasks.append(gateway_server.start())
                # Gateway обрабатывается внутри ChannelManager через receive_from_agent

            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            console.print("\nЗавершение...")
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
    from agentxyz.config.loader import get_data_dir, load_config
    from agentxyz.cron.service import CronService

    config = load_config()
    sync_workspace_templates(config.workspace_path)
    bus = MessageBus()
    provider = _make_provider(config)

    # Создать сервис cron для использования инструмента (обратный вызов не нужен для CLI, если он не запущен)
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    if logs:
        logger.enable("agentxyz")
    else:
        logger.disable("agentxyz")

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        temperature=config.agents.defaults.temperature,
        max_tokens=config.agents.defaults.max_tokens,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
    )

    # Показывать спиннер, когда журналы отключены (нет вывода, который можно пропустить); пропускать, когда журналы включены
    def _thinking_ctx() -> Any:
        if logs:
            from contextlib import nullcontext

            return nullcontext()
        # Анимированный спиннер безопасно использовать с обработкой ввода prompt_toolkit
        return console.status("[dim]agentxyz думает...[/dim]", spinner="dots")

    async def _cli_progress(content: str, *, tool_hint: bool = False) -> None:
        ch = agent_loop.channels_config
        if ch and tool_hint and not ch.send_tool_hints:
            return
        if ch and not tool_hint and not ch.send_progress:
            return
        console.print(f"  [dim]↳ {content}[/dim]")

    if message:
        # Режим одного сообщения — прямой вызов, без шины
        async def run_once() -> None:
            with _thinking_ctx():
                response = await agent_loop.process_direct(
                    message, session_id, on_progress=_cli_progress
                )
            _print_agent_response(response, render_markdown=markdown)
            await agent_loop.close_mcp()

        asyncio.run(run_once())
    else:
        # Интерактивный режим
        from agentxyz.bus.events import InboundMessage

        _init_prompt_session()
        console.print(
            f"{__logo__} Interactive mode (type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit)\n"
        )

        if ":" in session_id:
            cli_channel, cli_chat_id = session_id.split(":", 1)
        else:
            cli_channel, cli_chat_id = "cli", session_id

        def _exit_on_sigint(signum: int, frame: object) -> None:
            _restore_terminal()
            console.print("\nДо свидания!")
            os._exit(0)

        signal.signal(signal.SIGINT, _exit_on_sigint)

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
                                console.print(f"  [dim]↳ {msg.content}[/dim]")
                        elif not turn_done.is_set():
                            if msg.content:
                                turn_response.append(msg.content)
                            turn_done.set()
                        elif msg.content:
                            console.print()
                            _print_agent_response(msg.content, render_markdown=markdown)
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

                        with _thinking_ctx():
                            await turn_done.wait()

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
    from agentxyz.config.loader import load_config

    config = load_config()

    table = Table(title="Статус каналов")
    table.add_column("Канал", style="cyan")
    table.add_column("Включён", style="green")
    table.add_column("Конфигурация", style="yellow")

    # Telegram
    tg = config.channels.telegram
    tg_config = f"token: {tg.token[:10]}..." if tg.token else "[dim]не настроен[/dim]"
    table.add_row("Telegram", "✓" if tg.enabled else "✗", tg_config)

    # Email
    em = config.channels.email
    em_config = em.imap_host if em.imap_host else "[dim]не настроен[/dim]"
    table.add_row("Email", "✓" if em.enabled else "✗", em_config)

    console.print(table)


# ============================================================================
# Команды Cron
# ============================================================================

cron_app = typer.Typer(help="Управление задачами по расписанию")
app.add_typer(cron_app, name="cron")


@cron_app.command("list")
def cron_list(
    all: bool = typer.Option(False, "--all", "-a", help="Включая выключенные"),
) -> None:
    """Список задач."""
    from agentxyz.config.loader import get_data_dir
    from agentxyz.cron.service import CronService

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    jobs = service.list_jobs(include_disabled=all)

    if not jobs:
        console.print("Нет задач по расписанию.")
        return

    table = Table(title="Scheduled Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Schedule")
    table.add_column("Status")
    table.add_column("Next Run")

    import time
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo

    for job in jobs:
        # Форматирование расписания
        if job.schedule.kind == "every":
            sched = f"every {(job.schedule.every_ms or 0) // 1000}s"
        elif job.schedule.kind == "cron":
            sched = (
                f"{job.schedule.expr or ''} ({job.schedule.tz})"
                if job.schedule.tz
                else (job.schedule.expr or "")
            )
        else:
            sched = "one-time"

        # Форматирование следующего запуска
        next_run = ""
        if job.state.next_run_at_ms:
            ts = job.state.next_run_at_ms / 1000
            try:
                tz = ZoneInfo(str(job.schedule.tz)) if job.schedule.tz else None
                next_run = _dt.fromtimestamp(ts, tz).strftime("%Y-%m-%d %H:%M")
            except Exception:
                next_run = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))

        status = "[green]активен[/green]" if job.enabled else "[dim]отключён[/dim]"

        table.add_row(job.id, job.name, sched, status, next_run)

    console.print(table)


@cron_app.command("add")
def cron_add(
    name: str = typer.Option(..., "--name", "-n", help="Имя задачи"),
    message: str = typer.Option(..., "--message", "-m", help="Сообщение боту"),
    every: int = typer.Option(None, "--every", "-e", help="Период: каждые N секунд"),
    cron_expr: str = typer.Option(
        None, "--cron", "-c", help="Выражение cron (например '0 9 * * *')"
    ),
    tz: str | None = typer.Option(
        None, "--tz", help="Часовой пояс IANA для cron (например, 'Europe/Moscow')"
    ),
    at: str = typer.Option(None, "--at", help="Выполнить однажды (ISO формат)"),
    deliver: bool = typer.Option(False, "--deliver", "-d", help="Отправить ответ"),
    to: str = typer.Option(None, "--to", help="Кому"),
    channel: str = typer.Option(
        None, "--channel", help="Через канал (например 'telegram')"
    ),
) -> None:
    """Добавить задачу."""
    from agentxyz.config.loader import get_data_dir
    from agentxyz.cron.service import CronService
    from agentxyz.cron.types import CronSchedule

    if tz and not cron_expr:
        console.print("[red]Ошибка: --tz можно использовать только с --cron[/red]")
        raise typer.Exit(1)

    # Определить тип расписания
    if every:
        schedule = CronSchedule(kind="every", every_ms=every * 1000)
    elif cron_expr:
        schedule = CronSchedule(kind="cron", expr=cron_expr, tz=tz)
    elif at:
        import datetime

        dt = datetime.datetime.fromisoformat(at)
        schedule = CronSchedule(kind="at", at_ms=int(dt.timestamp() * 1000))
    else:
        console.print("[red]Ошибка: укажите --every, --cron или --at[/red]")
        raise typer.Exit(1)

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    try:
        job = service.add_job(
            name=name,
            schedule=schedule,
            message=message,
            deliver=deliver,
            to=to,
            channel=channel,
        )
    except ValueError as e:
        console.print(f"[red]Ошибка: {e}[/red]")
        raise typer.Exit(1) from e

    console.print(f"[green]✓[/green] Задача добавлена: '{job.name}' ({job.id})")


@cron_app.command("remove")
def cron_remove(
    job_id: str = typer.Argument(..., help="ID задачи для удаления"),
) -> None:
    """Удалить задачу."""
    from agentxyz.config.loader import get_data_dir
    from agentxyz.cron.service import CronService

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    if service.remove_job(job_id):
        console.print(f"[green]✓[/green] Задача удалена: {job_id}")
    else:
        console.print(f"[red]Задача {job_id} не найдена[/red]")


@cron_app.command("enable")
def cron_enable(
    job_id: str = typer.Argument(..., help="ID задачи"),
    disable: bool = typer.Option(False, "--disable", help="Отключить вместо включить"),
) -> None:
    """Переключить задачу."""
    from agentxyz.config.loader import get_data_dir
    from agentxyz.cron.service import CronService

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    job = service.enable_job(job_id, enabled=not disable)
    if job:
        status = "disabled" if disable else "enabled"
        console.print(f"[green]✓[/green] Задача '{job.name}' {status}")
    else:
        console.print(f"[red]Задача {job_id} не найдена[/red]")


@cron_app.command("run")
def cron_run(
    job_id: str = typer.Argument(..., help="ID задачи для запуска"),
    force: bool = typer.Option(
        False, "--force", "-f", help="Запустить даже если отключено"
    ),
) -> None:
    """Выполнить сейчас."""
    from loguru import logger

    from agentxyz.agent.loop import AgentLoop
    from agentxyz.bus.queue import MessageBus
    from agentxyz.config.loader import get_data_dir, load_config
    from agentxyz.cron.service import CronService
    from agentxyz.cron.types import CronJob

    logger.disable("agentxyz")

    config = load_config()
    provider = _make_provider(config)
    bus = MessageBus()
    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        temperature=config.agents.defaults.temperature,
        max_tokens=config.agents.defaults.max_tokens,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
    )

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    result_holder = []

    async def on_job(job: CronJob) -> str | None:
        response = await agent_loop.process_direct(
            job.payload.message,
            session_key=f"cron:{job.id}",
            channel=job.payload.channel or "cli",
            chat_id=job.payload.to or "direct",
        )
        result_holder.append(response)
        return response

    service.on_job = on_job

    async def run() -> bool:
        return await service.run_job(job_id, force=force)

    if asyncio.run(run()):
        console.print("[green]✓[/green] Задача завершена")
        if result_holder:
            _print_agent_response(result_holder[0], render_markdown=True)
    else:
        console.print(f"[red]Ошибка выполнения: {job_id}[/red]")


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
                    f"{spec.label}: {'[green]✓[/green]' if has_key else '[dim]not set[/dim]'}"
                )


if __name__ == "__main__":
    app()
