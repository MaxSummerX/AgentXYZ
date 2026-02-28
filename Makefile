.PHONY: help build rebuild up down restart logs ps clean clean-all prune backup restore
.PHONY: agent agent-cmd status cron-list cron-add cron-remove cron-enable cron-disable cron-run shell
.PHONY: channels-status onboard test test-cov lint format format-check install typecheck dev-gateway
.PHONY: dev-up dev-logs dev-down

# ============================================================================
# Makefile для управления AgentXYZ
# ============================================================================

COMPOSE_PROD := docker compose -f docker-compose.prod.yml
COMPOSE := docker compose

help: ## Показать эту справку
	@echo "Доступные команды:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ============================================================================
# Основные команды
# ============================================================================

build: ## Собрать Docker образ (prod)
	$(COMPOSE_PROD) build

up: ## Запустить gateway (prod)
	$(COMPOSE_PROD) up -d

down: ## Остановить и удалить контейнеры
	$(COMPOSE_PROD) down

restart: ## Перезапустить gateway
	$(COMPOSE_PROD) restart app

rebuild: ## Пересобрать и перезапустить (prod)
	$(COMPOSE_PROD) up -d --build --force-recreate

logs: ## Логировать gateway (prod)
	$(COMPOSE_PROD) logs -f app

ps: ## Показать статус контейнеров
	$(COMPOSE_PROD) ps

clean: ## Удалить контейнеры и сети (сохранить данные)
	$(COMPOSE_PROD) down

clean-all: ## Удалить ВСЁ включая volumes (ОПАСНО!)
	$(COMPOSE_PROD) down -v

prune: ## Удалить остановленные контейнеры и образы <none>
	docker container prune -f
	docker image prune -f

# ============================================================================
# CLI команды (через --profile cli)
# ============================================================================

agent: ## Интерактивный режим агента
	$(COMPOSE_PROD) --profile cli run --rm cli agent

agent-cmd: ## Отправить одно сообщение (использование: make agent-cmd MSG="текст")
	@if [ -z "$(MSG)" ]; then echo "Укажите сообщение: make agent-cmd MSG='Привет!'"; exit 1; fi
	$(COMPOSE_PROD) --profile cli run --rm cli agent -m "$(MSG)"

status: ## Статус системы
	$(COMPOSE_PROD) --profile cli run --rm cli status

cron-list: ## Список cron задач
	$(COMPOSE_PROD) --profile cli run --rm cli cron list

cron-add: ## Добавить cron задачу (использование: make cron-add NAME="название" MSG="текст" EVERY=3600)
	@if [ -z "$(NAME)" ] || [ -z "$(MSG)" ] || [ -z "$(EVERY)" ]; then \
		echo "Использование: make cron-add NAME='название' MSG='сообщение' EVERY=3600"; \
		exit 1; \
	fi
	$(COMPOSE_PROD) --profile cli run --rm cli cron add -n "$(NAME)" -m "$(MSG)" -e "$(EVERY)"

cron-remove: ## Удалить cron задачу (использование: make cron-remove ID=task_id)
	@if [ -z "$(ID)" ]; then echo "Укажите ID: make cron-remove ID=task_id"; exit 1; fi
	$(COMPOSE_PROD) --profile cli run --rm cli cron remove $(ID)

shell: ## Bash shell в контейнере
	$(COMPOSE_PROD) --profile cli run --rm cli bash

cron-enable: ## Включить cron задачу (использование: make cron-enable ID=task_id)
	@if [ -z "$(ID)" ]; then echo "Укажите ID: make cron-enable ID=task_id"; exit 1; fi
	$(COMPOSE_PROD) --profile cli run --rm cli cron enable $(ID)

cron-disable: ## Отключить cron задачу (использование: make cron-disable ID=task_id)
	@if [ -z "$(ID)" ]; then echo "Укажите ID: make cron-disable ID=task_id"; exit 1; fi
	$(COMPOSE_PROD) --profile cli run --rm cli cron enable $(ID) --disable

cron-run: ## Выполнить cron задачу сейчас (использование: make cron-run ID=task_id FORCE=1)
	@if [ -z "$(ID)" ]; then echo "Укажите ID: make cron-run ID=task_id"; exit 1; fi
	@if [ -n "$(FORCE)" ]; then \
		$(COMPOSE_PROD) --profile cli run --rm cli cron run $(ID) -f; \
	else \
		$(COMPOSE_PROD) --profile cli run --rm cli cron run $(ID); \
	fi

channels-status: ## Статус каналов
	$(COMPOSE_PROD) --profile cli run --rm cli channels status

onboard: ## Инициализация конфигурации
	$(COMPOSE_PROD) --profile cli run --rm cli onboard

# ============================================================================
# Разработка (локально без лимитов ресурсов)
# ============================================================================

dev-up: ## Запустить gateway (dev - без лимитов)
	$(COMPOSE) up -d

dev-logs: ## Логировать gateway (dev)
	$(COMPOSE) logs -f app

dev-down: ## Остановить (dev)
	$(COMPOSE) down

dev-gateway: ## Запустить gateway локально (без Docker)
	agentxyz gateway

# ============================================================================
# Разработка Python
# ============================================================================

install: ## Установить зависимости (uv или pip)
	@command -v uv >/dev/null 2>&1 && uv pip install -e ".[dev]" || pip install -e ".[dev]"

test: ## Запустить тесты (pytest)
	pytest -v

test-cov: ## Запустить тесты с покрытием
	pytest --cov=agentxyz --cov-report=term-missing

lint: ## Проверить код (ruff check)
	ruff check agentxyz

format: ## Форматировать код (ruff format)
	ruff format agentxyz

format-check: ## Проверить форматирование
	ruff format --check agentxyz

typecheck: ## Проверить типы (mypy)
	mypy agentxyz

# ============================================================================
# Бэкапы
# ============================================================================

backup: ## Бэкап данных agentxyz
	@echo "Создание бэкапа..."
	@mkdir -p ./backups
	@tar -czf ./backups/agentxyz-$(shell date +%Y%m%d-%H%M%S).tar.gz ./agentxyz-data/
	@echo "Бэкап создан: ./backups/agentxyz-$(shell date +%Y%m%d-%H%M%S).tar.gz"

restore: ## Восстановить из бэкапа (использование: make restore BACKUP=file.tar.gz)
	@if [ -z "$(BACKUP)" ]; then echo "Укажите файл бэкапа: make restore BACKUP=./backups/file.tar.gz"; exit 1; fi
	@echo "Восстановление из $(BACKUP)..."
	@tar -xzf $(BACKUP)
	@echo "Восстановление завершено"

# ============================================================================
# Мониторинг
# ============================================================================

stats: ## Статистика ресурсов контейнеров
	@docker stats --no-stream 2>/dev/null || (echo "Нет запущенных контейнеров. Сначала выполни: make up" && exit 1)

health: ## Проверить здоровье контейнера
	@$(COMPOSE_PROD) --profile cli run --rm cli status
