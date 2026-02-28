# AgentXYZ

📚 Образовательный форк [HKUDS/nanobot](https://github.com/HKUDS/nanobot) — русскоязычный многоагентный AI-ассистент

## О проекте

Личный обучающий проект для изучения архитектуры и разработки многоагентных AI-систем на практике.

## Особенности этого форка

### 🌐 Русификация
- **Полный перевод** — докстринги и комментарии переведены на русский
- **Русскоязычный интерфейс** — Makefile и документация на русском языке

### 🔧 Инструменты разработки
- **Полная типизация** — все функции аннотированы типами
- **mypy** — статическая проверка типов
- **ruff** — линтер и форматтер (вместо нескольких инструментов)
- **pre-commit** — автоматические проверки перед коммитом
- **bandit** — проверка безопасности кода

### 🐳 Docker и DevOps
- **Makefile** — удобные команды для управления проектом
- **docker-compose.yml** — конфигурация для Docker

### 🔄 Синхронизация
- **Активный мердж** — регулярная интеграция изменений из оригинального репозитория

### 💻 Изменения в кодовой базе

- **providers/transcription.py** — архитектурное изменение для независимости
  - **Оригинал**: Groq API → **AgentXYZ**: faster-whisper medium (локальный, офлайн)
  - Модель "medium" — баланс веса/качества для русского языка

- **tools/web.py** — полностью переработан
  - **WebSearchTool**: fallback с 4 движками (Exa → Tavily → DDGS → Brave)
  - **WebFetchTool**: fallback с 3 методами (Tavily → Exa → Readability), Readability принимает markdown от CDN/Cloudflare

- **gateway/** — FastAPI + WebSocket сервер с HTTP/WebSocket API, авторизацией и routes (admin, chat, auth_deps)

### Упрощение архитектуры
Убраны неиспользуемые каналы, провайдеры и навыки для фокусировки на основном функционале:
- **Каналы**: только `telegram` и `email` (убраны: discord, feishu, matrix, mochat, slack и т.д)
- **Провайдеры**: убран `openai_codex_provider`, OAuth login
- **Навыки**: убраны `clawhub` и `summarize`
- **CLI**: убраны WhatsApp bridge, OAuth login

### Личный опыт

Использую AgentXYZ ежедневно через **Docker** + **ZAI codingplan** на отдельном сервере.


## 📦 Установка

> ⚠️ **Важно**: AgentXYZ не опубликован на PyPI. Установка только из исходников.

```bash
git clone https://github.com/MaxSummerX/AgentXYZ.git
cd AgentXYZ
pip install -e .
```

После установки команды доступны как `agentxyz`. Если `agentxyz` не работает, используйте `python -m agentxyz`.

Примеры:
```bash
# Интерактивный режим
agentxyz agent
# или
python -m agentxyz agent

# Отправить сообщение
agentxyz agent -m "Привет!"
# или
python -m agentxyz agent -m "Привет!"

# Запустить шлюз
agentxyz gateway
# или
python -m agentxyz gateway
```


## 🚀 Быстрый старт

**1. Инициализация**

```bash
agentxyz onboard
```

**2. Конфигурация** (`~/.agentxyz/config.json`)

Добавьте API ключ (например, OpenRouter):

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  }
}
```

**3. Запуск**

```bash
agentxyz agent
```

## 💬 Каналы связи

| Канал | Что нужно |
|-------|-----------|
| **Telegram** | Bot token от @BotFather |
| **Email** | IMAP/SMTP учетные данные |

### Telegram

**1. Создайте бота**
- Telegram → `@BotFather` → `/newbot`
- Скопируйте токен

**2. Настройте**

> **Важно**: `allowFrom` ограничивает доступ к боту. Укажите ваш Telegram User ID (узнать можно через бота @userinfobot). Оставьте пустым массивом `[]` для публичного доступа.

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

**3. Запустите**

```bash
agentxyz gateway
```

### Email

**1. Создайте отдельный email для бота**

**2. Настройте**

```json
{
  "channels": {
    "email": {
      "enabled": true,
      "consentGranted": true,
      "imapHost": "imap.gmail.com",
      "imapPort": 993,
      "imapUsername": "bot@gmail.com",
      "imapPassword": "app-password",
      "smtpHost": "smtp.gmail.com",
      "smtpPort": 587,
      "smtpUsername": "bot@gmail.com",
      "smtpPassword": "app-password",
      "fromAddress": "bot@gmail.com",
      "allowFrom": ["your-email@gmail.com"]
    }
  }
}
```

**3. Запустите**

```bash
agentxyz gateway
```

## ⚙️ Конфигурация

Провайдеры LLM (все поддерживают русскоязычные модели):

| Провайдер | Назначение | Получить API ключ |
|-----------|------------|-------------------|
| `openrouter` | LLM (рекомендуется) | [openrouter.ai](https://openrouter.ai) |
| `anthropic` | Claude | [console.anthropic.com](https://console.anthropic.com) |
| `openai` | GPT | [platform.openai.com](https://platform.openai.com) |
| `deepseek` | DeepSeek | [platform.deepseek.com](https://platform.deepseek.com) |

### API ключи для веб-инструментов

Для работы веб-поиска и извлечения контента создайте `.env` файл в корне проекта:

```bash
# ~/.agentxyz/.env или .env в корне проекта
EXA_API_KEY=your_exa_api_key
TAVILY_API_KEY=your_tavily_api_key
BRAVE_API_KEY=your_brave_api_key
```

| API ключ | Назначение | Получить |
|----------|------------|----------|
| `EXA_API_KEY` | Web-поиск и извлечение (рекомендуется) | [exa.ai](https://exa.ai) |
| `TAVILY_API_KEY` | Web-поиск и извлечение | [tavily.com](https://tavily.com) |
| `BRAVE_API_KEY` | Web-поиск (fallback) | [search.brave.com/api](https://search.brave.com/api) |

## 🛠️ CLI команды

| Команда | Описание |
|---------|----------|
| `agentxyz onboard` | Инициализация конфига и workspace |
| `agentxyz agent` | Интерактивный режим чата |
| `agentxyz agent -m "..."` | Отправить одно сообщение |
| `agentxyz gateway` | Запуск шлюза |
| `agentxyz status` | Статус системы |
| `agentxyz cron add/list/remove` | Управление расписанием |

Выход из интерактивного режима: `exit`, `quit`, `Ctrl+D`

## 🐳 Docker

```bash
# Сборка
make build

# Инициализация
make run-onboard

# Редактирование конфига
vim ~/.agentxyz/config.json

# Запуск шлюза
make run-gateway

# CLI
make run-cli
```

## 📁 Структура проекта

```
agentxyz/
├── agent/          # 🧠 Логика агента
│   ├── loop.py     #    Agent loop (LLM ↔ инструменты)
│   ├── context.py  #    Построитель промптов
│   ├── memory.py   #    Постоянная память
│   ├── skills.py   #    Загрузчик навыков
│   ├── subagent.py #    Фоновые задачи
│   └── tools/      #    Встроенные инструменты
├── skills/         # 🎯 Навыки (github, weather, tmux, cron, memory, agent-skills)
├── channels/       # 📱 Интеграции с каналами связи (telegram, email)
├── bus/            # 🚌 Маршрутизация сообщений
├── cli/            # 🖥️ CLI команды
├── config/         # ⚙️ Конфигурация
├── cron/           # ⏰ Планировщик задач
├── gateway/        # 🌐 FastAPI + WebSocket сервер
├── heartbeat/      # 💓 Периодические задачи
├── providers/      # 🤖 LLM провайдеры
├── session/        # 💬 Сессии бесед
├── templates/      # 📄 Шаблоны (AGENTS.md, HEARTBEAT.md, TOOLS.md, USER.md, SOUL.md)
└── utils/          # 🔧 Утилиты

```

## 🔒 Безопасность

> ⚠️ **Важно**: AgentXYZ даёт агенту доступ к выполнению команд и файлам. Следуйте этим рекомендациям:

### Базовые меры безопасности

```bash
# Ограничьте доступ к конфигу
chmod 600 ~/.agentxyz/config.json
chmod 700 ~/.agentxyz
```

### Управление доступом

- **`allowFrom`** — ограничьте доступ к боту (см. настройку Telegram)
- **`tools.restrictToWorkspace`** — ограничьте файловые операции workspace-директорией

```json
{
  "tools": {
    "restrictToWorkspace": true
  },
  "agents": {
    "defaults": {
      "workspace": "~/.agentxyz/workspace"
    }
  }
}
```

При включении `restrictToWorkspace` агент не сможет:
- Читать файлы вне `~/.agentxyz/workspace`
- Записывать файлы вне `~/.agentxyz/workspace`
- Выполнять команды вне этой директории

### Для продакшена

- ✅ Используйте Docker для изоляции
- ✅ Отдельный пользователь для запуска
- ✅ Лимиты на API-ключах
- ✅ Регулярно обновляйте зависимости

Политика безопасности: [nanobot/SECURITY.md](https://github.com/HKUDS/nanobot/blob/master/SECURITY.md)

## Благодарности

Этот проект основан на [HKUDS/nanobot](https://github.com/HKUDS/nanobot) — многоагентном фреймворке.
Я регулярно синхронизирую изменения из оригинального репозитория и расширяю его дополнительными возможностями.

**Репозиторий**: [github.com/MaxSummerX/AgentXYZ](https://github.com/MaxSummerX/AgentXYZ)
