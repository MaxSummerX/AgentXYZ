"""REST эндпоинт для транскрипции аудио."""

import asyncio
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger


if TYPE_CHECKING:
    from agentxyz.providers.transcription import TranscriptionProvider


router = APIRouter()
security = HTTPBearer(auto_error=False)

# Поддерживаемые форматы аудио
ALLOWED_EXTENSIONS = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".opus": "audio/opus",
    ".webm": "audio/webm",
}


async def verify_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> None:
    """Проверить аутентификацию."""
    auth = request.app.state.auth
    await auth.authenticate(request, credentials)


@router.post("/transcribe", response_class=PlainTextResponse)
async def transcribe_endpoint(
    request: Request,
    file: UploadFile = File(
        ..., description="Аудиофайл (mp3, wav, ogg, m4a, opus, webm)"
    ),
    provider: Literal["whisper", "groq"] | None = Form(
        None, description="Провайдер транскрипции"
    ),
    language: str | None = Form(None, description="Язык аудио (ru, en, auto)"),
) -> str:
    """
    Транскрибировать аудиофайл.

    Ограничения (настраиваются в глобальной конфигурации transcription):
    - Макс. размер: 50MB (по умолчанию)
    - Таймаут: 3 минуты (по умолчанию)
    - Форматы: mp3, wav, ogg, m4a, opus, webm

    Args:
        request: FastAPI Request
        file: Аудиофайл для транскрипции
        provider: Провайдер (whisper/groq), по умолчанию из конфига
        language: Язык кода (по умолчанию из конфига)

    Returns:
        Текст транскрипции (text/plain)

    Raises:
        HTTPException: При ошибках валидации или транскрипции
    """
    config = request.app.state.config
    transcribe_config = config.transcription

    # Получить ограничения из конфига
    max_file_size = transcribe_config.max_file_size_mb * 1024 * 1024
    timeout = transcribe_config.timeout_seconds
    default_provider = transcribe_config.provider
    default_language = transcribe_config.language

    # 1. Проверить расширение файла
    filename = file.filename or "audio"
    file_ext = Path(filename).suffix.lower()

    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Неподдерживаемый формат. Используйте: {', '.join(ALLOWED_EXTENSIONS.keys())}",
        )

    # 2. Проверить размер файла
    content = await file.read()
    if len(content) > max_file_size:
        raise HTTPException(
            status_code=413,
            detail=f"Размер файла превышает {transcribe_config.max_file_size_mb}MB",
        )

    if len(content) == 0:
        raise HTTPException(
            status_code=400,
            detail="Пустой файл",
        )

    # 3. Создать временный файл
    temp_dir = Path("/tmp")
    temp_filename = f"transcribe_{uuid.uuid4().hex}{file_ext}"
    temp_path = temp_dir / temp_filename

    try:
        # Сохранить загруженный файл
        await asyncio.to_thread(temp_path.write_bytes, content)
        logger.info(f"Файл сохранён: {temp_path} ({len(content)} bytes)")

        # 4. Определить провайдер и язык
        effective_provider = provider or default_provider
        effective_language = language or default_language

        # 5. Выбрать провайдер транскрипции
        #
        transcriber: TranscriptionProvider
        if effective_provider == "whisper":
            from agentxyz.providers.transcription import WhisperTranscriptionProvider

            transcriber = WhisperTranscriptionProvider(
                model_size=transcribe_config.whisper_model,
                device=transcribe_config.whisper_device,
                language=effective_language,
            )
        else:  # (заглушка)
            from agentxyz.providers.transcription import StubTranscriptionProvider

            transcriber = StubTranscriptionProvider(
                dummy_text="Stub transcription result"
            )

        # 6. Запустить транскрипцию с таймаутом
        try:
            result: str = await asyncio.wait_for(
                transcriber.transcribe(temp_path),  # type: ignore[no-any-return]
                timeout=timeout,
            )
        except TimeoutError:
            raise HTTPException(
                status_code=408,
                detail=f"Транскрипция не завершилась за {timeout}с",
            ) from None

        if not result:
            raise HTTPException(
                status_code=500,
                detail="Не удалось транскрибировать аудио",
            )

        logger.info(
            f"Транскрипция завершена: {len(result)} символов (provider={effective_provider})"
        )
        return result

    except HTTPException:
        # Пробросить HTTP ошибки как есть
        raise

    except Exception as e:
        logger.error(f"Ошибка транскрипции: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Внутренняя ошибка при транскрипции: {e!s}",
        ) from None

    finally:
        # 7. Удалить временный файл
        if temp_path.exists():
            await asyncio.to_thread(temp_path.unlink)
            logger.debug(f"Временный файл удалён: {temp_path}")
