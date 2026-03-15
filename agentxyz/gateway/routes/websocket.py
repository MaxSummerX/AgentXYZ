"""WebSocket эндпоинт для двусторонней коммуникации."""

import asyncio
import base64
import binascii
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from loguru import logger

from agentxyz.bus.events import InboundMessage, OutboundMessage
from agentxyz.gateway.schemas import WSMessage, WSResponse


if TYPE_CHECKING:
    from agentxyz.gateway.server import GatewayServer

router = APIRouter()


async def handle_audio_message(
    websocket: WebSocket,
    ws_msg: WSMessage,
    session_id: str,
    channel: "GatewayServer",
) -> str | None:
    """
    Обработать аудио сообщение для транскрипции.

    Args:
        websocket: WebSocket соединение
        ws_msg: WebSocket сообщение с аудио
        session_id: ID сессии
        channel: GatewayServer

    Returns:
        Транскрибированный текст или None при ошибке.
    """
    # Проверить наличие аудио данных
    if not ws_msg.audio:
        error_response = WSResponse(
            type="error",
            content="Отсутствуют аудио данные",
            session_id=session_id,
            done=True,
            error="missing_audio",
        )
        await websocket.send_json(error_response.model_dump())
        return None

    try:
        # Декодировать base64
        audio_data = base64.b64decode(ws_msg.audio)

        # Определить расширение файла
        filename = ws_msg.filename or "audio.webm"
        file_ext = Path(filename).suffix.lower() or ".webm"

        # Создать временный файл
        temp_dir = Path("/tmp")
        temp_filename = f"ws_transcribe_{uuid.uuid4().hex}{file_ext}"
        temp_path = temp_dir / temp_filename

        # Сохранить аудио
        await asyncio.to_thread(temp_path.write_bytes, audio_data)
        logger.info(f"Аудио сохранено: {temp_path} ({len(audio_data)} bytes)")

        # Получить конфигурацию транскрипции
        config = websocket.app.state.config
        transcribe_config = config.transcription

        # Выбрать провайдер
        from agentxyz.providers.transcription import TranscriptionProvider

        transcriber: TranscriptionProvider
        if transcribe_config.provider == "whisper":
            from agentxyz.providers.transcription import WhisperTranscriptionProvider

            transcriber = WhisperTranscriptionProvider(
                model_size=transcribe_config.whisper_model,
                device=transcribe_config.whisper_device,
                language=transcribe_config.language,
            )
        else:
            from agentxyz.providers.transcription import StubTranscriptionProvider

            transcriber = StubTranscriptionProvider(dummy_text="Stub")

        # Транскрибировать
        result = await asyncio.wait_for(
            transcriber.transcribe(temp_path),
            timeout=transcribe_config.timeout_seconds,
        )

        if not result:
            raise ValueError("Пустой результат транскрипции")

        logger.info(f"Транскрипция завершена: {len(result)} символов")
        return result

    except binascii.Error as e:
        error_response = WSResponse(
            type="error",
            content=f"Ошибка декодирования base64: {e}",
            session_id=session_id,
            done=True,
            error="invalid_base64",
        )
        await websocket.send_json(error_response.model_dump())
        return None

    except Exception as e:
        logger.error(f"Ошибка обработки аудио: {e}")
        error_response = WSResponse(
            type="error",
            content=f"Внутренняя ошибка: {e}",
            session_id=session_id,
            done=True,
            error=str(type(e).__name__),
        )
        await websocket.send_json(error_response.model_dump())
        return None

    finally:
        # Удалить временный файл
        if "temp_path" in locals() and temp_path.exists():
            try:
                await asyncio.to_thread(temp_path.unlink)
                logger.debug(f"Временный файл удалён: {temp_path}")
            except Exception as e:
                logger.warning(f"Не удалось удалить временный файл: {e}")


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str = "default",
    token: str | None = Query(None),  # API токен для аутентификации
) -> None:
    """
    WebSocket эндпоинт для двусторонней коммуникации в реальном времени.

    Аутентификация:
    - Передайте токен как query параметр: ws://localhost:8000/api/v1/ws?token=sk-xxx
    - Или в заголовке: Authorization: Bearer sk-xxx

    Сообщения от клиента:

    1. Чат сообщение:
    {
        "type": "chat",
        "message": "Привет!",
        "session_id": "user-123"  # опционально, переопределяет параметр
    }

    2. Аудио сообщение (транскрипция):
    {
        "type": "audio",
        "audio": "<base64>",
        "filename": "audio.webm",
        "session_id": "user-123"  # опционально
    }
    Аудио будет транскрибировано, а результат отправлен агенту как сообщение.

    Ответы от сервера:
    {
        "type": "response" | "error",
        "content": "Текст ответа агента",
        "session_id": "user-123",
        "done": true,
        "error": null  # только для type="error"
    }

    Args:
        websocket: WebSocket соединение
        session_id: ID сессии (может быть переопределён в сообщении)
        token: API токен для аутентификации
    """
    # Получить канал и auth из app.state
    channel: GatewayServer = websocket.app.state.gateway
    auth = websocket.app.state.auth

    # Проверить аутентификацию
    if auth.is_enabled():
        # Попробовать получить токен из query параметра
        credentials = None

        if token:
            # Создать мок credentials из query параметра
            from fastapi.security import HTTPAuthorizationCredentials

            credentials = HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials=token,
            )
        else:
            # Попробовать из заголовка
            auth_header = websocket.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                from fastapi.security import HTTPAuthorizationCredentials

                credentials = HTTPAuthorizationCredentials(
                    scheme="Bearer",
                    credentials=auth_header[7:],  # Убрать "Bearer "
                )

        # Проверить credentials
        try:
            # Создать мок request для auth.authenticate
            # WebSocket не имеет такого же интерфейса как Request,
            # поэтому мы передаём параметры напрямую
            if credentials:
                if credentials.credentials != auth.token:
                    await websocket.close(code=1008, reason="Unauthorized")
                    return
            else:
                await websocket.close(code=1008, reason="Missing token")
                return

        except Exception as e:
            from loguru import logger

            logger.warning(f"WebSocket auth failed: {e}")
            await websocket.close(code=1008, reason="Authentication failed")
            return

    # Подключить WebSocket
    ws_manager = channel.websocket_manager
    await ws_manager.connect(websocket, session_id)

    try:
        while True:
            # Получить сообщение от клиента
            data = await websocket.receive_json()

            # Валидация
            try:
                ws_msg = WSMessage(**data)
            except Exception:
                error_response = WSResponse(
                    type="error",
                    content="Неверный формат сообщения",
                    session_id=session_id,
                    done=True,
                    error="invalid_format",
                )
                await websocket.send_json(error_response.model_dump())
                continue

            # Использовать session_id из сообщения если указан
            effective_session_id = ws_msg.session_id or session_id

            # Определить содержимое сообщения
            message_content = ws_msg.message

            # Обработка аудио сообщений
            if ws_msg.type == "audio":
                transcribed_text = await handle_audio_message(
                    websocket, ws_msg, effective_session_id, channel
                )
                if transcribed_text is None:
                    # Ошибка транскрипции, ответ уже отправлен
                    continue
                # Использовать транскрибированный текст как сообщение
                message_content = transcribed_text

            # Создать входящее сообщение
            inbound = InboundMessage(
                channel="fastapi",
                sender_id="websocket",
                chat_id=effective_session_id,
                content=message_content,
            )

            # Регистрировать WebSocket для получения ответа
            response_queue: asyncio.Queue[OutboundMessage | None] | None = None
            if not ws_manager.has_session(effective_session_id):
                # Если это единственный WebSocket в сессии, используем очередь
                response_queue = asyncio.Queue()
                channel.register_pending_response(effective_session_id, response_queue)

            try:
                # Отправить агенту
                await channel.send_to_agent(inbound)

                # Ждать ответа если есть очередь
                if response_queue:
                    try:
                        outbound = await asyncio.wait_for(
                            response_queue.get(),
                            timeout=channel.timeout,
                        )

                        if outbound is None:
                            # Канал закрыт
                            error_response = WSResponse(
                                type="error",
                                content="Канал закрыт",
                                session_id=effective_session_id,
                                done=True,
                                error="channel_closed",
                            )
                            await websocket.send_json(error_response.model_dump())
                        else:
                            response = WSResponse(
                                type="response",
                                content=str(outbound.content),
                                session_id=effective_session_id,
                                done=True,
                            )
                            await websocket.send_json(response.model_dump())

                    except TimeoutError:
                        error_response = WSResponse(
                            type="error",
                            content=f"Таймаут: агент не ответил в течение {channel.timeout}с",
                            session_id=effective_session_id,
                            done=True,
                            error="timeout",
                        )
                        await websocket.send_json(error_response.model_dump())
                    finally:
                        channel.unregister_pending_response(effective_session_id)

            except Exception as e:
                from loguru import logger

                logger.error(f"Ошибка в WebSocket: {e}")

                error_response = WSResponse(
                    type="error",
                    content=f"Внутренняя ошибка: {e}",
                    session_id=effective_session_id,
                    done=True,
                    error=str(type(e).__name__),
                )
                await websocket.send_json(error_response.model_dump())

    except WebSocketDisconnect:
        # Нормальное отключение
        pass
    finally:
        await ws_manager.disconnect(websocket)
