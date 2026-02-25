"""Admin эндпоинты для управления и мониторинга."""

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agentxyz.gateway import __version__
from agentxyz.gateway.schemas import (
    AgentStatusResponse,
    SessionHistoryResponse,
    SessionInfo,
    SessionListResponse,
    StatusResponse,
)


if TYPE_CHECKING:
    from agentxyz.gateway.server import GatewayServer

router = APIRouter()
security = HTTPBearer(auto_error=False)


async def verify_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> None:
    """Проверить аутентификацию."""
    auth = request.app.state.auth
    await auth.authenticate(request, credentials)


@router.get(
    "/admin/status", response_model=StatusResponse, dependencies=[Depends(verify_auth)]
)
async def admin_status(http_request: Request) -> StatusResponse:
    """
    Получить статус FastAPI канала.

    Returns:
        StatusResponse: Статус канала
    """
    channel: GatewayServer = http_request.app.state.gateway

    return StatusResponse(
        status="ok",
        channel="fastapi",
        running=channel.is_running,
        version=__version__,
    )


@router.get(
    "/admin/agent",
    response_model=AgentStatusResponse,
    dependencies=[Depends(verify_auth)],
)
async def admin_agent_status(http_request: Request) -> AgentStatusResponse:
    """
    Получить статус агента.

    Returns:
        AgentStatusResponse: Статус агента
    """
    channel: GatewayServer = http_request.app.state.gateway

    # Получить информацию от агента
    agent_info = channel.get_agent_info() if hasattr(channel, "get_agent_info") else {}

    # Получить количество сессий
    total_sessions = 0
    if channel.session_manager:
        sessions_data = channel.session_manager.list_sessions()
        total_sessions = len(sessions_data)

    # Количество ожидающих запросов
    pending_requests = channel.pending_requests_count

    return AgentStatusResponse(
        running=agent_info.get("running", channel.is_running),
        model=agent_info.get("model", "unknown"),
        temperature=agent_info.get("temperature"),
        max_tokens=agent_info.get("max_tokens"),
        workspace=agent_info.get("workspace"),
        enabled_channels=agent_info.get("enabled_channels", []),
        total_sessions=total_sessions,
        pending_requests=pending_requests,
    )


@router.get(
    "/admin/sessions",
    response_model=SessionListResponse,
    dependencies=[Depends(verify_auth)],
)
async def admin_list_sessions(http_request: Request) -> SessionListResponse:
    """
    Получить список всех сессий (бесед).

    Returns:
        SessionListResponse: Список всех сессий
    """
    channel: GatewayServer = http_request.app.state.gateway

    # Получить все сессии из SessionManager
    all_sessions = []
    if channel.session_manager:
        sessions_data = channel.session_manager.list_sessions()
        all_sessions = [SessionInfo(**s) for s in sessions_data]

    # Получить количество ожидающих запросов
    pending_count = channel.pending_requests_count

    return SessionListResponse(
        sessions=all_sessions,
        count=len(all_sessions),
        pending_requests=pending_count,
    )


@router.get("/admin/websockets", dependencies=[Depends(verify_auth)])
async def admin_websocket_info(http_request: Request) -> dict:
    """
    Получить информацию о WebSocket соединениях.

    Returns:
        Информация о WebSocket соединениях
    """
    channel: GatewayServer = http_request.app.state.gateway

    ws_manager = channel.websocket_manager

    return {
        "total_connections": ws_manager.get_connection_count(),
        "active_sessions": ws_manager.get_active_sessions(),
        "connections_by_session": {
            session_id: ws_manager.get_connection_count(session_id)
            for session_id in ws_manager.get_active_sessions()
        },
    }


@router.get(
    "/admin/sessions/{session_key}",
    response_model=SessionHistoryResponse,
    dependencies=[Depends(verify_auth)],
)
async def admin_session_history(
    http_request: Request, session_key: str
) -> SessionHistoryResponse:
    """
    Получить историю сессии по ключу.

    Args:
        session_key: Ключ сессии (формат: channel:chat_id или просто chat_id для fastapi)

    Returns:
        SessionHistoryResponse: История сессии
    """
    from agentxyz.gateway.schemas import SessionMessage

    channel: GatewayServer = http_request.app.state.gateway

    if not channel.session_manager:
        return SessionHistoryResponse(
            session_key=session_key,
            messages=[],
            count=0,
            created_at=None,
            updated_at=None,
        )

    # Если ключ не содержит двоеточия, добавляем префикс fastapi:
    if ":" not in session_key:
        session_key = f"fastapi:{session_key}"

    session = channel.session_manager.get_or_create(session_key)
    messages = [
        SessionMessage(
            role=msg.get("role", "unknown"),
            content=msg.get("content", ""),
            timestamp=msg.get("timestamp"),
        )
        for msg in session.messages
    ]

    return SessionHistoryResponse(
        session_key=session_key,
        messages=messages,
        count=len(messages),
        created_at=session.created_at.isoformat() if session.created_at else None,
        updated_at=session.updated_at.isoformat() if session.updated_at else None,
    )
