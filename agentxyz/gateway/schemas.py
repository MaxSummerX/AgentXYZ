"""Pydantic модели для Gateway."""

from pydantic import BaseModel, Field

from agentxyz.gateway.server import __version__


# ============================================================================
# Request модели
# ============================================================================


class ChatRequest(BaseModel):
    """Запрос на отправку сообщения агенту."""

    message: str = Field(..., description="Сообщение для агента", min_length=1)
    session_id: str = Field(default="default", description="ID сессии")
    user_id: str | None = Field(default=None, description="ID пользователя")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "message": "Привет! Как дела?",
                    "session_id": "user-123",
                    "user_id": "optional-user-id",
                }
            ]
        }
    }


class StreamRequest(BaseModel):
    """Запрос на потоковый ответ."""

    message: str = Field(..., description="Сообщение для агента", min_length=1)
    session_id: str = Field(default="default", description="ID сессии")
    user_id: str | None = Field(default=None, description="ID пользователя")


# ============================================================================
# Response модели
# ============================================================================


class ChatResponse(BaseModel):
    """Ответ от агента."""

    content: str = Field(..., description="Содержимое ответа")
    session_id: str = Field(..., description="ID сессии")
    channel: str = Field(default="fastapi", description="Канал ответа")
    finish_reason: str = Field(default="stop", description="Причина завершения")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "content": "Привет! Всё отлично, спасибо!",
                    "session_id": "user-123",
                    "channel": "fastapi",
                    "finish_reason": "stop",
                }
            ]
        }
    }


class StreamChunk(BaseModel):
    """Часть потокового ответа."""

    content: str = Field(..., description="Часть ответа")
    done: bool = Field(default=False, description="Завершён ли ответ")


# ============================================================================
# Info модели
# ============================================================================


class StatusResponse(BaseModel):
    """Ответ о статусе сервиса."""

    status: str = Field(default="ok", description="Статус")
    channel: str = Field(default="fastapi", description="Название канала")
    running: bool = Field(..., description="Запущен ли канал")
    version: str = Field(default=__version__, description="Версия")


class RootResponse(BaseModel):
    """Ответ корневого эндпоинта."""

    service: str = Field(default="agentxyz", description="Название сервиса")
    channel: str = Field(default="fastapi", description="Название канала")
    version: str = Field(default=__version__, description="Версия")
    endpoints: dict[str, str] = Field(..., description="Доступные эндпоинты")


# ============================================================================
# Admin модели
# ============================================================================


class AgentStatusResponse(BaseModel):
    """Статус агента."""

    running: bool = Field(..., description="Запущен ли агент")
    model: str = Field(..., description="Используемая модель")
    temperature: float | None = Field(None, description="Температура сэмплирования")
    max_tokens: int | None = Field(None, description="Максимальное количество токенов")
    workspace: str | None = Field(None, description="Рабочая директория агента")
    enabled_channels: list[str] = Field(
        default_factory=list, description="Включённые каналы"
    )
    total_sessions: int = Field(..., description="Общее количество сессий")
    pending_requests: int = Field(
        ..., description="Количество ожидающих ответа запросов"
    )


class SessionInfo(BaseModel):
    """Информация о сессии."""

    key: str = Field(..., description="Ключ сессии (channel:chat_id)")
    created_at: str | None = Field(None, description="Время создания")
    updated_at: str | None = Field(None, description="Время последнего обновления")
    path: str | None = Field(None, description="Путь к файлу сессии")


class SessionListResponse(BaseModel):
    """Список сессий."""

    sessions: list[SessionInfo] = Field(default_factory=list, description="Все сессии")
    count: int = Field(..., description="Количество сессий")
    pending_requests: int = Field(
        ..., description="Количество ожидающих ответа запросов"
    )


class SessionMessage(BaseModel):
    """Сообщение в сессии."""

    role: str = Field(..., description="Роль (user, assistant, system)")
    content: str = Field(..., description="Содержимое сообщения")
    timestamp: str | None = Field(None, description="Время сообщения")


class SessionHistoryResponse(BaseModel):
    """История сессии."""

    session_key: str = Field(..., description="Ключ сессии")
    messages: list[SessionMessage] = Field(
        default_factory=list, description="Сообщения"
    )
    count: int = Field(..., description="Количество сообщений")
    created_at: str | None = Field(None, description="Время создания")
    updated_at: str | None = Field(None, description="Время последнего обновления")


# ============================================================================
# WebSocket модели
# ============================================================================


class WSMessage(BaseModel):
    """WebSocket сообщение от клиента."""

    type: str = Field(..., description="Тип сообщения: 'chat', 'audio' и другие")
    message: str = Field(default="", description="Содержимое сообщения (для type=chat)")
    session_id: str = Field(default="default", description="ID сессии")
    audio: str | None = Field(default=None, description="Base64 аудио (для type=audio)")
    filename: str | None = Field(default=None, description="Имя файла (для type=audio)")


class WSResponse(BaseModel):
    """WebSocket ответ клиенту."""

    type: str = Field(..., description="Тип ответа")
    content: str | None = Field(default=None, description="Содержимое")
    session_id: str = Field(..., description="ID сессии")
    done: bool = Field(default=False, description="Завершён ли ответ")
    error: str | None = Field(default=None, description="Ошибка если есть")
