"""Провайдер голосовой транскрипции."""

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from faster_whisper.transcribe import TranscriptionInfo
from loguru import logger


class TranscriptionProvider(ABC):
    """
    Абстрактный базовый класс для провайдера транскрипции аудио.

    Реализации должны поддерживать согласованный интерфейс для транскрибации
    аудиофайлов различными способами (локальные модели, API, заглушки).
    """

    @abstractmethod
    async def transcribe(self, file_path: str | Path) -> str:
        """
        Транскрибировать аудиофайл.

        Args:
            file_path: Путь к аудиофайлу.

        Returns:
            Распознанный текст.
        """
        pass


class WhisperTranscriptionProvider(TranscriptionProvider):
    """
    Локальный провайдер голосовой транскрипции на основе faster-whisper.

    Работает офлайн, не требует API-ключа. По умолчанию использует CPU.
    """

    def __init__(
        self, model_size: str = "medium", device: str = "cpu", language: str = "ru"
    ):
        self.model_size = model_size
        self.device = device
        self.language = language
        self._model = None

    def _get_model(self) -> Any:
        """Ленивая загрузка модели (singleton pattern)."""
        if self._model is None:
            try:
                from faster_whisper import WhisperModel  # type: ignore[import-untyped]

                logger.info(
                    "Loading Whisper model: {} on {}", self.model_size, self.device
                )
                self._model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type="int8" if self.device == "cpu" else "float16",
                )
            except ImportError:
                logger.error(
                    "faster-whisper not installed. Run: pip install faster-whisper"
                )
                raise
        return self._model

    async def transcribe(self, file_path: str | Path) -> str:
        """
        Транскрибация аудиофайла с использованием локальной модели Whisper.
        Args:
            file_path: Путь к аудиофайлу.
        Returns:
            Распознанный текст
        """

        path = Path(file_path)

        if not await asyncio.to_thread(path.exists):
            logger.error("Audio file not found: {}", file_path)
            return ""

        try:
            model = self._get_model()

            def _transcribe() -> tuple[str, TranscriptionInfo]:
                segs, info = model.transcribe(str(path), language=self.language)
                text = " ".join(s.text.strip() for s in segs)
                return text, info

            full_text, info = await asyncio.to_thread(_transcribe)
            logger.info(
                "Transcribed with Whisper: {} chars, lang={}",
                len(full_text),
                info.language,
            )
            return full_text
        except Exception as e:
            logger.error("Whisper transcription error: {}", e)
            return ""


class StubTranscriptionProvider(TranscriptionProvider):
    """
    Заглушка провайдера транскрипции для тестирования.

    Возвращает фиктивный текст без вызова реальных API.
    """

    def __init__(self, dummy_text: str = "Test transcription stub"):
        self.dummy_text = dummy_text

    async def transcribe(self, file_path: str | Path) -> str:
        """
        Заглушка транскрипции - возвращает фиктивный текст.

        Args:
            file_path: Путь к аудиофайлу (игнорируется).

        Returns:
            Фиктивный текст транскрипции.
        """
        logger.info("StubTranscription: returning dummy text for {}", file_path)
        return self.dummy_text
