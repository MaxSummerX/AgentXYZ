FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl git jq tmux vim wget ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Установка Python-зависимостей (кэшируемый слой)
COPY pyproject.toml README.md LICENSE ./
RUN mkdir -p agentxyz && touch agentxyz/__init__.py && \
      uv pip install --system --no-cache . && \
      rm -rf agentxyz

# Копирование исходного кода и установка
COPY agentxyz/ agentxyz/
RUN uv pip install --system --no-cache .

# Создание директории конфигурации
RUN mkdir -p /root/.agentxyz

# Порт FastAPI по умолчанию
EXPOSE 8000

ENTRYPOINT ["agentxyz"]
CMD ["status"]
