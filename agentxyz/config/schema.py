"""Схема конфигурации использующий Pydantic."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings, SettingsConfigDict


class Base(BaseModel):
    """Базовая модель, которая принимает ключи как в camelCase, так и в snake_case."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class TelegramConfig(Base):
    """Конфигурация канала Telegram."""

    enabled: bool = False
    token: str = ""  # Токен бота от @BotFather
    allow_from: list[str] = Field(
        default_factory=list
    )  # Разрешенные ID пользователей или имена пользователей
    proxy: str | None = (
        None  # HTTP/SOCKS5 прокси URL, например "http://127.0.0.1:7890" или "socks5://127.0.0.1:1080
    )
    reply_to_message: bool = (
        False  # Если true, ответы бота цитируют исходное сообщение"
    )


class EmailConfig(Base):
    """Конфигурация канала электронной почты (IMAP входящие + SMTP исходящие)."""

    enabled: bool = False
    consent_granted: bool = (
        False  # Явное разрешение владельца на доступ к данным почтового ящика
    )

    # IMAP (получение)
    imap_host: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_mailbox: str = "INBOX"
    imap_use_ssl: bool = True

    # SMTP (отправка)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    from_address: str = ""

    # Поведение
    auto_reply_enabled: bool = True  # Если false, входящая почта читается, но автоматический ответ не отправляется
    poll_interval_seconds: int = 30
    mark_seen: bool = True
    max_body_chars: int = 12000
    subject_prefix: str = "Re: "
    allow_from: list[str] = Field(
        default_factory=list
    )  # Разрешённые адреса электронной почты отправителей


class HeartbeatConfig(Base):
    """Heartbeat service configuration."""

    enabled: bool = True
    interval_s: int = 30 * 60  # 30 minutes


class GatewayAuthConfig(Base):
    """Конфигурация аутентификации Gateway."""

    enabled: bool = True  # Включить аутентификацию
    api_token: str = ""  # API токен (если пустой - сгенерируется при старте)
    allowed_ips: list[str] = Field(
        default_factory=list
    )  # Белый список IP (пустой = любой IP)


class GatewayConfig(Base):
    """Конфигурация Gateway (веб-сервер)."""

    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8888
    timeout: float = 60.0  # Таймаут ожидания ответа агента в секундах
    auth: GatewayAuthConfig = Field(default_factory=GatewayAuthConfig)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)


class ChannelsConfig(Base):
    """Конфигурация чат-каналов."""

    send_progress: bool = True  # отправлять прогресс текста агента в канал
    send_tool_hints: bool = (
        False  # отправлять подсказки о вызовах инструментов (напр. read_file("…")
    )
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)


class AgentDefaults(Base):
    """Конфигурация агента по умолчанию."""

    workspace: str = "~/.agentxyz/workspace"
    model: str = "anthropic/claude-opus-4-6"
    provider: str = "auto"  # Название провайдера (например, "anthropic", "openrouter") или "auto" для автоматического определения
    max_tokens: int = 8192
    temperature: float = 0.2
    max_tool_iterations: int = 40
    memory_window: int = 100
    reasoning_effort: str | None = (
        None  # low / medium / high — включает режим мышления LLM
    )


class AgentsConfig(Base):
    """Конфигурация агента."""

    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


class ProviderConfig(Base):
    """Конфигурация LLM-провайдера."""

    api_key: str = ""
    api_base: str | None = None
    extra_headers: dict[str, str] | None = (
        None  # Custom headers (например, APP-Code для AiHubMix)
    )


class TranscriptionConfig(Base):
    """Конфигурация голосовой транскрипции."""

    provider: Literal["whisper"] = "whisper"
    whisper_model: str = "medium"  # tiny, base, small, medium, large-v3
    whisper_device: str = "cpu"  # cpu или cuda
    language: str = "ru"  # язык по умолчанию
    max_file_size_mb: int = 50
    timeout_seconds: float = 180.0


class ProvidersConfig(Base):
    """Конфигурация LLM-провайдеров."""

    custom: ProviderConfig = Field(
        default_factory=ProviderConfig
    )  # Любой OpenAI-совместимый endpoint
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
    zai: ProviderConfig = Field(default_factory=ProviderConfig)
    dashscope: ProviderConfig = Field(default_factory=ProviderConfig)
    vllm: ProviderConfig = Field(default_factory=ProviderConfig)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    moonshot: ProviderConfig = Field(default_factory=ProviderConfig)
    minimax: ProviderConfig = Field(default_factory=ProviderConfig)
    aihubmix: ProviderConfig = Field(default_factory=ProviderConfig)


class WebSearchConfig(Base):
    """Конфигурация веб-поиска."""

    api_key: str = ""  # Brave Search API key
    max_results: int = 5


class WebToolsConfig(Base):
    """Конфигурация веб-инструментов."""

    proxy: str | None = (
        None  # URL прокси-сервера HTTP/SOCKS5, например: "socks5://127.0.0.1:1080"
    )
    search: WebSearchConfig = Field(default_factory=WebSearchConfig)


class ExecToolConfig(Base):
    """Конфигурация shell-исполнения."""

    timeout: int = 60
    path_append: str = ""


class MCPServerConfig(Base):
    """Конфигурация подключения MCP-сервера (stdio или HTTP)."""

    command: str = ""  # Stdio: команда для запуска (например, "npx")
    args: list[str] = Field(default_factory=list)  # Stdio: аргументы команды
    env: dict[str, str] = Field(
        default_factory=dict
    )  # Stdio: дополнительные переменные окружения
    url: str = ""  # HTTP: URL streaming-HTTP endpoint'а
    tool_timeout: int = 30  # Таймаут в секундах до отмены вызова инструмента


class ToolsConfig(Base):
    """Конфигурация инструментов."""

    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    restrict_to_workspace: bool = (
        False  # Если включено, ограничить доступ всех инструментов рабочей директорией
    )
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)


class Config(BaseSettings):
    """Корневая конфигурация для agentxyz."""

    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    transcription: TranscriptionConfig = Field(default_factory=TranscriptionConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)

    @property
    def workspace_path(self) -> Path:
        """Получить раскрытый путь к рабочей директории."""
        return Path(self.agents.defaults.workspace).expanduser()

    def _match_provider(
        self, model: str | None = None
    ) -> tuple["ProviderConfig | None", str | None]:
        """Сопоставить конфигурацию провайдера и его имя в реестре. Возвращает (config, spec_name)."""
        from agentxyz.providers.registry import PROVIDERS

        forced = self.agents.defaults.provider
        if forced != "auto":
            p = getattr(self.providers, forced, None)
            return (p, forced) if p else (None, None)

        model_lower = (model or self.agents.defaults.model).lower()
        model_normalized = model_lower.replace("-", "_")
        model_prefix = model_lower.split("/", 1)[0] if "/" in model_lower else ""
        normalized_prefix = model_prefix.replace("-", "_")

        def _kw_matches(kw: str) -> bool:
            kw = kw.lower()
            return kw in model_lower or kw.replace("-", "_") in model_normalized

        # Явный префикс провайдера имеет приоритет над ключевыми словами.
        # Например, `openai/gpt-4` должен найти openai, а не другой провайдер с похожими ключевыми словами.
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and model_prefix and normalized_prefix == spec.name:
                if p.api_key:
                    return p, spec.name

        # Сопоставление по ключевому слову (порядок следует реестру PROVIDERS)
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and any(_kw_matches(kw) for kw in spec.keywords):
                if p.api_key:
                    return p, spec.name

        # Fallback: сначала шлюзы, затем другие (следует порядку реестра)
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and p.api_key:
                return p, spec.name
        return None, None

    def get_provider(self, model: str | None = None) -> ProviderConfig | None:
        """Получить соответствующую конфигурацию провайдера (api_key, api_base, extra_headers). При необходимости использует первый доступный."""
        p, _ = self._match_provider(model)
        return p

    def get_provider_name(self, model: str | None = None) -> str | None:
        """Получить имя в реестре соответствующего провайдера (например, "deepseek", "openrouter")."""
        _, name = self._match_provider(model)
        return name

    def get_api_key(self, model: str | None = None) -> str | None:
        """Получить API-ключ для указанной модели. При необходимости использует первый доступный ключ."""
        p = self.get_provider(model)
        return p.api_key if p else None

    def get_api_base(self, model: str | None = None) -> str | None:
        """Получить базовый URL API для указанной модели. Применяет URL-адреса по умолчанию для известных шлюзов."""
        from agentxyz.providers.registry import find_by_name

        p, name = self._match_provider(model)
        if p and p.api_base:
            return p.api_base
        # Только шлюзы получают здесь api_base по умолчанию. Стандартные провайдеры
        # (например, Moonshot) устанавливают свой базовый URL через переменные окружения в _setup_env
        # чтобы избежать загрязнения глобального litellm.api_base.
        if name:
            spec = find_by_name(name)
            if spec and spec.is_gateway and spec.default_api_base:
                return spec.default_api_base
        return None

    model_config = SettingsConfigDict(env_prefix="AGENTXYZ_", env_nested_delimiter="__")
