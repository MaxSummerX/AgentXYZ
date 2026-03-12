"""
Реестр провайдеров — центральное место для настроек всех LLM-провайдеров.

  Как добавить новый провайдер:
  1. Добавить ProviderSpec в список PROVIDERS ниже
  2. Добавить поле в ProvidersConfig (файл config/schema.py)
  3. Всё! Остальное работает автоматически: переменные окружения, префиксы моделей, статус и т.д.

  ⚠️ Порядок важен — он определяет приоритет при выборе провайдера. Сначала идут шлюзы.
  Все поля показаны полностью — можно скопировать запись как шаблон.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderSpec:
    """Метаданные одного провайдера LLM. См. PROVIDERS ниже для реальных примеров.

    Заполнители в значениях env_extras:
    {api_key}  — API-ключ пользователя
    {api_base} — api_base из конфигурации или default_api_base этой спецификации
    """

    # идентификация
    name: str  # имя поля конфигурации, например "dashscope"
    keywords: tuple[
        str, ...
    ]  # ключевые слова в имени модели для сопоставления (строчные буквы)
    env_key: str  # переменная окружения LiteLLM, например "DASHSCOPE_API_KEY"
    display_name: str = ""  # отображается в `agentxyz status`

    # префиксирование модели
    litellm_prefix: str = ""  # "dashscope" → модель становится "dashscope/{model}"
    skip_prefixes: tuple[
        str, ...
    ] = ()  # не префиксировать, если модель уже начинается с этих

    # дополнительные переменные окружения, например (("ZAI_API_KEY", "{api_key}"),)
    env_extras: tuple[tuple[str, str], ...] = ()

    # определение шлюза / локального развёртывания
    is_gateway: bool = False  # маршрутизирует любую модель (OpenRouter, AiHubMix)
    is_local: bool = False  # локальное развёртывание (vLLM, Ollama)
    detect_by_key_prefix: str = ""  # сопоставить префикс api_key, например "sk-or-"
    detect_by_base_keyword: str = ""  # сопоставить подстроку в URL api_base
    default_api_base: str = ""  # резервный базовый URL

    # поведение шлюза
    strip_model_prefix: bool = (
        False  # удалить "provider/" перед повторным префиксированием
    )

    # переопределения параметров для конкретных моделей, например (("kimi-k2.5", {"temperature": 1.0}),)
    model_overrides: tuple[tuple[str, dict[str, Any]], ...] = ()

    # Прямые провайдеры полностью обходят LiteLLM (например, CustomProvider)
    is_direct: bool = False

    # Провайдер поддерживает cache_control для блоков контента (например, кэширование промптов от Anthropic)
    supports_prompt_caching: bool = False

    @property
    def label(self) -> str:
        return self.display_name or self.name.title()


# ---------------------------------------------------------------------------
# PROVIDERS — реестр. Порядок = приоритет. Копируйте любую запись как шаблон.
# ---------------------------------------------------------------------------

PROVIDERS: tuple[ProviderSpec, ...] = (
    # === Custom (предоставленный пользователем OpenAI-совместимый endpoint) =================
    # Без автоопределения — активируется только при явной настройке пользователям "custom".
    ProviderSpec(
        name="custom",
        keywords=(),
        env_key="",
        display_name="Custom",
        litellm_prefix="",
        is_direct=True,
    ),
    # === Шлюзы (определяются по api_key / api_base, а не по имени модели) =========
    # Шлюзы могут маршрутизировать любую модель, поэтому они имеют приоритет при откате.
    # OpenRouter: глобальный шлюз, ключи начинаются с 'sk-or-'
    ProviderSpec(
        name="openrouter",
        keywords=("openrouter",),
        env_key="OPENROUTER_API_KEY",
        display_name="OpenRouter",
        litellm_prefix="openrouter",  # claude-3 → openrouter/claude-3
        skip_prefixes=(),
        env_extras=(),
        is_gateway=True,
        is_local=False,
        detect_by_key_prefix="sk-or-",
        detect_by_base_keyword="openrouter",
        default_api_base="https://openrouter.ai/api/v1",
        strip_model_prefix=False,
        model_overrides=(),
        supports_prompt_caching=True,
    ),
    # AiHubMix: глобальный шлюз, OpenAI-совместимый интерфейс.
    # strip_model_prefix=True: не понимает "anthropic/claude-3",
    # поэтому удаляем до "claude-3", затем повторно префиксируем как "openai/claude-3".
    ProviderSpec(
        name="aihubmix",
        keywords=("aihubmix",),
        env_key="OPENAI_API_KEY",  # OpenAI-совместимый
        display_name="AiHubMix",
        litellm_prefix="openai",  # → openai/{model}
        skip_prefixes=(),
        env_extras=(),
        is_gateway=True,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="aihubmix",
        default_api_base="https://aihubmix.com/v1",
        strip_model_prefix=True,  # anthropic/claude-3 → claude-3 → openai/claude-3
        model_overrides=(),
    ),
    # === Стандартные провайдеры (сопоставляются по ключевым словам в имени модели) ===============
    # Anthropic: LiteLLM изначально распознаёт "claude-*", префикс не требуется.
    ProviderSpec(
        name="anthropic",
        keywords=("anthropic", "claude"),
        env_key="ANTHROPIC_API_KEY",
        display_name="Anthropic",
        litellm_prefix="",
        skip_prefixes=(),
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
        supports_prompt_caching=True,
    ),
    # OpenAI: LiteLLM изначально распознаёт "gpt-*", префикс не требуется.
    ProviderSpec(
        name="openai",
        keywords=("openai", "gpt"),
        env_key="OPENAI_API_KEY",
        display_name="OpenAI",
        litellm_prefix="",
        skip_prefixes=(),
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
    ),
    # DeepSeek: нужен префикс "deepseek/" для маршрутизации в LiteLLM.
    ProviderSpec(
        name="deepseek",
        keywords=("deepseek",),
        env_key="DEEPSEEK_API_KEY",
        display_name="DeepSeek",
        litellm_prefix="deepseek",  # deepseek-chat → deepseek/deepseek-chat
        skip_prefixes=("deepseek/",),  # избегаем двойного префикса
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
    ),
    # Gemini: нужен префикс "gemini/" для LiteLLM.
    ProviderSpec(
        name="gemini",
        keywords=("gemini",),
        env_key="GEMINI_API_KEY",
        display_name="Gemini",
        litellm_prefix="gemini",  # gemini-pro → gemini/gemini-pro
        skip_prefixes=("gemini/",),  # избегаем двойного префикса
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
    ),
    # ZAI: LiteLLM использует префикс "zai/".
    # Также дублирует ключ в ZAI_API_KEY (некоторые пути LiteLLM проверяют это).
    # skip_prefixes: не добавлять "zai/", когда уже маршрутизировано через шлюз.
    ProviderSpec(
        name="zai",
        keywords=("glm", "zai"),
        env_key="ZAI_API_KEY",
        display_name="ZAI",
        litellm_prefix="zai",  # glm-4 → zai/glm-4
        skip_prefixes=("zai/", "openrouter/", "hosted_vllm/"),
        env_extras=(("ZAI_API_KEY", "{api_key}"),),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
    ),
    # DashScope: модели Qwen, нужен префикс "dashscope/".
    ProviderSpec(
        name="dashscope",
        keywords=("qwen", "dashscope"),
        env_key="DASHSCOPE_API_KEY",
        display_name="DashScope",
        litellm_prefix="dashscope",  # qwen-max → dashscope/qwen-max
        skip_prefixes=("dashscope/", "openrouter/"),
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
    ),
    # Moonshot: модели Kimi, нужен префикс "moonshot/".
    # LiteLLM требует переменную окружения MOONSHOT_API_BASE для поиска эндпоинта.
    # API Kimi K2.5 требует temperature >= 1.0.
    ProviderSpec(
        name="moonshot",
        keywords=("moonshot", "kimi"),
        env_key="MOONSHOT_API_KEY",
        display_name="Moonshot",
        litellm_prefix="moonshot",  # kimi-k2.5 → moonshot/kimi-k2.5
        skip_prefixes=("moonshot/", "openrouter/"),
        env_extras=(("MOONSHOT_API_BASE", "{api_base}"),),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="https://api.moonshot.ai/v1",  # международный; для Китая используйте api.moonshot.cn
        strip_model_prefix=False,
        model_overrides=(("kimi-k2.5", {"temperature": 1.0}),),
    ),
    # MiniMax: требуется префикс "minimax/" для маршрутизации в LiteLLM.
    # Использует API, совместимый с OpenAI, на api.minimax.io/v1.
    ProviderSpec(
        name="minimax",
        keywords=("minimax",),
        env_key="MINIMAX_API_KEY",
        display_name="MiniMax",
        litellm_prefix="minimax",  # MiniMax-M2.1 → minimax/MiniMax-M2.1
        skip_prefixes=("minimax/", "openrouter/"),
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="https://api.minimax.io/v1",
        strip_model_prefix=False,
        model_overrides=(),
    ),
    # === Ollama (локальный, OpenAI-совместимый) ===================================
    ProviderSpec(
        name="ollama",
        keywords=("ollama", "nemotron"),
        env_key="OLLAMA_API_KEY",
        display_name="Ollama",
        litellm_prefix="ollama_chat",  # model → ollama_chat/model
        skip_prefixes=("ollama/", "ollama_chat/"),
        env_extras=(),
        is_gateway=False,
        is_local=True,
        detect_by_key_prefix="",
        detect_by_base_keyword="11434",
        default_api_base="http://localhost:11434",
        strip_model_prefix=False,
        model_overrides=(),
    ),
    # === Локальное развёртывание (сопоставляется по ключу конфигурации, НЕ по api_base) =========
    # vLLM / любой локальный сервер, совместимый с OpenAI.
    # Определяется, когда ключ конфигурации — "vllm" (provider_name="vllm").
    ProviderSpec(
        name="vllm",
        keywords=("vllm",),
        env_key="HOSTED_VLLM_API_KEY",
        display_name="vLLM/Local",
        litellm_prefix="hosted_vllm",  # Llama-3-8B → hosted_vllm/Llama-3-8B
        skip_prefixes=(),
        env_extras=(),
        is_gateway=False,
        is_local=True,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",  # пользователь должен указать в конфигурации
        strip_model_prefix=False,
        model_overrides=(),
    ),
)


# ---------------------------------------------------------------------------
# Вспомогательные функции поиска
# ---------------------------------------------------------------------------


def find_by_model(model: str) -> ProviderSpec | None:
    """Сопоставить стандартный провайдер по ключевому слову в имени модели (без учёта регистра).
    Пропускает шлюзы/локальные — они сопоставляются по api_key/api_base."""
    model_lower = model.lower()
    model_normalized = model_lower.replace("-", "_")
    model_prefix = model_lower.split("/", 1)[0] if "/" in model_lower else ""
    normalized_prefix = model_prefix.replace("-", "_")
    std_specs = [s for s in PROVIDERS if not s.is_gateway and not s.is_local]

    # Явный префикс провайдера имеет приоритет над ключевыми словами.
    # Например, `openai/gpt-4` должен найти openai, а не другой провайдер с похожими ключевыми словами.
    for spec in std_specs:
        if model_prefix and normalized_prefix == spec.name:
            return spec
    for spec in std_specs:
        if any(
            kw in model_lower or kw.replace("-", "_") in model_normalized
            for kw in spec.keywords
        ):
            return spec
    return None


def find_gateway(
    provider_name: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
) -> ProviderSpec | None:
    """Обнаружить провайдер шлюза/локального.

    Приоритет:
      1. provider_name — если соответствует спецификации шлюза/локального, использовать напрямую.
      2. префикс api_key — например, "sk-or-" → OpenRouter.
      3. ключевое слово api_base — например, "aihubmix" в URL → AiHubMix.

    Стандартный провайдер с кастомным api_base (например, DeepSeek за прокси)
    НЕ будет принят за vLLM — старый резервный вариант удалён.
    """
    # 1. Прямое сопоставление по ключу конфигурации
    if provider_name:
        spec = find_by_name(provider_name)
        if spec and (spec.is_gateway or spec.is_local):
            return spec

    # 2. Автоопределение по префиксу api_key / ключевому слову api_base
    for spec in PROVIDERS:
        if (
            spec.detect_by_key_prefix
            and api_key
            and api_key.startswith(spec.detect_by_key_prefix)
        ):
            return spec
        if (
            spec.detect_by_base_keyword
            and api_base
            and spec.detect_by_base_keyword in api_base
        ):
            return spec

    return None


def find_by_name(name: str) -> ProviderSpec | None:
    """Найти спецификацию провайдера по имени поля конфигурации, например "dashscope"."""
    for spec in PROVIDERS:
        if spec.name == name:
            return spec
    return None
