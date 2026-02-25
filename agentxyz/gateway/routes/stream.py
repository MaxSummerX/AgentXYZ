"""SSE streaming эндпоинт для потоковых ответов."""

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agentxyz.bus.events import InboundMessage, OutboundMessage
from agentxyz.gateway.schemas import StreamChunk, StreamRequest


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


async def _stream_event_generator(
    request: StreamRequest,
    channel: "GatewayServer",
) -> AsyncGenerator[str]:
    """
    Генератор SSE событий.

    Args:
        request: Запрос с сообщением
        channel: FastAPI канал

    Yields:
        SSE события (строки в формате data: ...)
    """
    # Создать входящее сообщение
    inbound = InboundMessage(
        channel="fastapi",
        sender_id=request.user_id or "api",
        chat_id=request.session_id,
        content=request.message,
    )

    # Создать очередь для ответа
    response_queue: asyncio.Queue[OutboundMessage | None] = asyncio.Queue()
    channel.register_pending_response(request.session_id, response_queue)

    try:
        # Отправить агенту
        await channel.send_to_agent(inbound)

        # Ждать ответа с таймаутом
        try:
            outbound = await asyncio.wait_for(
                response_queue.get(),
                timeout=channel.timeout,
            )

            if outbound is None:
                # Канал закрыт
                error_data = {
                    "type": "error",
                    "content": "Канал закрыт",
                    "done": True,
                }
                yield f"data: {json.dumps(error_data)}\n\n"
                yield "data: [DONE]\n\n"
                return

            # Отправить содержимое как SSE
            chunk = StreamChunk(
                content=str(outbound.content),
                done=True,
            )
            yield f"data: {chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"

        except TimeoutError:
            error_data = {
                "type": "error",
                "content": f"Таймаут: агент не ответил в течение {channel.timeout}с",
                "done": True,
            }
            yield f"data: {json.dumps(error_data)}\n\n"
            yield "data: [DONE]\n\n"

    finally:
        # Очистка
        channel.unregister_pending_response(request.session_id)


@router.post("/chat/stream", dependencies=[Depends(verify_auth)])
async def stream_endpoint(
    request: StreamRequest,
    http_request: Request,
) -> StreamingResponse:
    """
    Отправить сообщение агенту с потоковым ответом.

    Использует Server-Sent Events (SSE) для передачи ответа.

    Args:
        request: Запрос с сообщением
        http_request: FastAPI Request объект

    Returns:
        StreamingResponse с SSE событиями

    Raises:
        HTTPException: Если аутентификация не пройдена
    """
    channel: GatewayServer = http_request.app.state.gateway

    return StreamingResponse(
        _stream_event_generator(request, channel),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Отключить буферизацию nginx
        },
    )
