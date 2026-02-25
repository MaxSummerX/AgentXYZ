"""REST эндпоинт для чата."""

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status

from agentxyz.bus.events import InboundMessage, OutboundMessage
from agentxyz.gateway.routes.common import verify_auth
from agentxyz.gateway.schemas import ChatRequest, ChatResponse


if TYPE_CHECKING:
    from agentxyz.gateway.server import GatewayServer

router = APIRouter()


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(verify_auth)])
async def chat_endpoint(
    request: ChatRequest,
    http_request: Request,
) -> ChatResponse:
    """
    Отправить сообщение агенту и получить ответ.

    Этот эндпоинт публикует сообщение в MessageBus.inbound, ждёт
    обработки агентом, и возвращает ответ из MessageBus.outbound.

    Args:
        request: Запрос с сообщением
        http_request: FastAPI Request объект

    Returns:
        ChatResponse: Ответ от агента

    Raises:
        HTTPException: Если агент не ответил в течение timeout
        HTTPException: Если аутентификация не пройдена
    """
    channel: GatewayServer = http_request.app.state.gateway

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

        # Ждать ответа с timeout
        try:
            outbound = await asyncio.wait_for(
                response_queue.get(),
                timeout=channel.timeout,
            )

            if outbound is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Канал закрыт",
                )

            return ChatResponse(
                content=str(outbound.content),
                session_id=request.session_id,
                channel=outbound.channel,
            )

        except TimeoutError:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Агент не ответил в течение {channel.timeout}с",
            ) from None

    finally:
        # Очистка
        channel.unregister_pending_response(request.session_id)
