"""Реализация канала Telegram через python-telegram-bot."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any, ClassVar

from loguru import logger
from telegram import BotCommand, ReplyParameters, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from agentxyz.channels.base import BaseChannel
from agentxyz.config.schema import TranscriptionConfig


if TYPE_CHECKING:
    from agentxyz.bus.events import OutboundMessage
    from agentxyz.bus.queue import MessageBus
    from agentxyz.config.schema import TelegramConfig


def _markdown_to_telegram_html(text: str) -> str:
    """
    Конвертировать markdown в безопасный HTML для Telegram.
    """
    if not text:
        return ""

    # 1. Извлечь и защитить блоки кода (сохранить от другой обработки)
    code_blocks: list[str] = []

    def save_code_block(m: re.Match) -> str:
        code_blocks.append(m.group(1))
        return f"\x00CB{len(code_blocks) - 1}\x00"

    text = re.sub(r"```[\w]*\n?([\s\S]*?)```", save_code_block, text)

    # 2. Извлечь и защитить встроенный код
    inline_codes: list[str] = []

    def save_inline_code(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00IC{len(inline_codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", save_inline_code, text)

    # 3. Заголовки # Title -> только текст заголовка
    text = re.sub(r"^#{1,6}\s+(.+)$", r"\1", text, flags=re.MULTILINE)

    # 4. Цитаты > text -> только текст (до экранирования HTML)
    text = re.sub(r"^>\s*(.*)$", r"\1", text, flags=re.MULTILINE)

    # 5. Экранировать спецсимволы HTML
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 6. Ссылки [text](url) - до bold/italic для вложенных случаев
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    # 7. Жирный **text** или __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # 8. Курсив _text_ (избегать совпадений внутри слов вроде some_var_name)
    text = re.sub(r"(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])", r"<i>\1</i>", text)

    # 9. Зачёркнутый ~~text~~
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # 10. Маркированные перечни - item -> • item
    text = re.sub(r"^[-*]\s+", "• ", text, flags=re.MULTILINE)

    # 11. Восстановить встроенный код через HTML-теги
    for i, code in enumerate(inline_codes):
        # Экранировать HTML в содержимом коде
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00IC{i}\x00", f"<code>{escaped}</code>")

    # 12. Восстановить блоки кода через HTML-теги
    for i, code in enumerate(code_blocks):
        # Экранировать HTML в содержимом кода
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00CB{i}\x00", f"<pre><code>{escaped}</code></pre>")

    return text


def _split_message(content: str, max_len: int = 4000) -> list[str]:
    """Разбить содержимое на части размером не более max_len, предпочитая разрывы строк."""
    if len(content) <= max_len:
        return [content]
    chunks: list[str] = []
    while content:
        if len(content) <= max_len:
            chunks.append(content)
            break
        cut = content[:max_len]
        pos = cut.rfind("\n")
        if pos == -1:
            pos = cut.rfind(" ")
        if pos == -1:
            pos = max_len
        chunks.append(content[:pos])
        content = content[pos:].lstrip()
    return chunks


class TelegramChannel(BaseChannel):
    """
    Канал Telegram через long polling.

    Просто и надёжно - не требует webhook/public IP.
    """

    name = "telegram"

    # Команды, зарегистрированные в меню команд Telegram
    BOT_COMMANDS: ClassVar[list[BotCommand]] = [
        BotCommand("start", "Запустить бота"),
        BotCommand("new", "Начать новый диалог"),
        BotCommand("stop", "Прекратить текущую задачу"),
        BotCommand("help", "Показать доступные команды"),
    ]

    def __init__(
        self,
        config: TelegramConfig,
        bus: MessageBus,
        transcription_config: TranscriptionConfig | None = None,
        groq_api_key: str = "",
    ):
        super().__init__(config, bus)
        self.config: TelegramConfig = config
        self.groq_api_key = groq_api_key
        self._app: Application | None = None
        self._chat_ids: dict[str, int] = {}  # Карта sender_id в chat_id для ответов
        self._typing_tasks: dict[
            str, asyncio.Task
        ] = {}  # chat_id -> задача цикла печати (typing loop task)
        self._media_group_buffers: dict[str, dict] = {}
        self._media_group_tasks: dict[str, asyncio.Task] = {}
        self.transcription_config = transcription_config or TranscriptionConfig()

    async def start(self) -> None:
        """Запустить бота Telegram через long polling."""
        if not self.config.token:
            logger.error("Токен бота Telegram не настроен")
            return

        self._running = True

        # Создать приложение
        req = HTTPXRequest(
            connection_pool_size=16,
            pool_timeout=5.0,
            connect_timeout=30.0,
            read_timeout=30.0,
        )
        builder = (
            Application.builder()
            .token(self.config.token)
            .request(req)
            .get_updates_request(req)
        )
        if self.config.proxy:
            builder = builder.proxy(self.config.proxy).get_updates_proxy(
                self.config.proxy
            )
        self._app = builder.build()
        self._app.add_error_handler(self._on_error)

        # Добавить обработчики команд
        self._app.add_handler(CommandHandler("start", self._on_start))
        self._app.add_handler(CommandHandler("new", self._forward_command))
        self._app.add_handler(CommandHandler("help", self._on_help))

        # Добавить обработчик сообщений для текста, фото, голоса, документов
        self._app.add_handler(
            MessageHandler(
                (
                    filters.TEXT
                    | filters.PHOTO
                    | filters.VOICE
                    | filters.AUDIO
                    | filters.Document.ALL
                )
                & ~filters.COMMAND,
                self._on_message,
            )
        )

        logger.info("Запуск бота Telegram (режим polling)...")

        # Инициализация и запуск polling
        await self._app.initialize()
        await self._app.start()

        # Получить данные бота
        bot_info = await self._app.bot.get_me()
        logger.info("Бот Telegram @{} подключён", bot_info.username)

        try:
            await self._app.bot.set_my_commands(self.BOT_COMMANDS)
            logger.debug("Команды бота Telegram зарегистрированы")
        except Exception as e:
            logger.warning("Не удалось зарегистрировать команды бота: {}", e)

        # Запустить polling (работает до остановки)
        if self._app and self._app.updater:
            await self._app.updater.start_polling(
                allowed_updates=["message"],
                drop_pending_updates=True,  # Игнорировать старые сообщения при запуске
            )

        # Работать пока не остановлен
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Остановить бота Telegram."""
        self._running = False

        # Отменить все индикаторы набора текста
        for chat_id in list(self._typing_tasks):
            self._stop_typing(chat_id)

        for task in self._media_group_tasks.values():
            task.cancel()
        self._media_group_tasks.clear()
        self._media_group_buffers.clear()

        if self._app:
            logger.info("Остановка бота Telegram...")
            if self._app.updater:
                await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._app = None

    @staticmethod
    def _get_media_type(path: str) -> str:
        """Определить тип медиа по расширению файла."""
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if ext in ("jpg", "jpeg", "png", "webp"):
            return "photo"
        if ext == "gif":
            return "animation"
        if ext == "ogg":
            return "voice"
        if ext in ("mp3", "m4a", "wav", "aac"):
            return "audio"
        return "document"

    async def send(self, msg: OutboundMessage) -> None:
        """Отправить сообщение через Telegram."""
        if not self._app:
            logger.warning("Бот Telegram не запущен")
            return

        # Остановить индикатор набора текста для этого чата
        if not msg.metadata.get("_progress", False):
            self._stop_typing(msg.chat_id)

        try:
            # chat_id должен быть числовым ID чата Telegram (integer)
            chat_id = int(msg.chat_id)
        except ValueError:
            logger.error("Invalid chat_id: {}", msg.chat_id)
            return

        reply_params = None
        if self.config.reply_to_message:
            reply_to_message_id = msg.metadata.get("message_id")
            if reply_to_message_id:
                reply_params = ReplyParameters(
                    message_id=reply_to_message_id, allow_sending_without_reply=True
                )

        # Отправить медиафайлы
        for media_path in msg.media or []:
            try:
                media_type = self._get_media_type(media_path)
                sender = {
                    "photo": self._app.bot.send_photo,
                    "animation": self._app.bot.send_animation,
                    "voice": self._app.bot.send_voice,
                    "audio": self._app.bot.send_audio,
                }.get(media_type, self._app.bot.send_document)
                param = (
                    "photo"
                    if media_type == "photo"
                    else media_type
                    if media_type in ("voice", "audio")
                    else "document"
                )

                await sender(
                    chat_id=chat_id,
                    **{param: media_path},
                    reply_parameters=reply_params,
                )

            except Exception as e:
                filename = media_path.rsplit("/", 1)[-1]
                logger.error("Failed to send media {}: {}", media_path, e)
                await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=f"[Failed to send: {filename}]",
                    reply_parameters=reply_params,
                )

        # Отправить текстовое содержимое
        if msg.content and msg.content != "[empty message]":
            is_progress = msg.metadata.get("_progress", False)
            draft_id = msg.metadata.get("message_id")

            for chunk in _split_message(msg.content):
                try:
                    html = _markdown_to_telegram_html(chunk)
                    if is_progress and draft_id:
                        await self._app.bot.send_message_draft(
                            chat_id=chat_id,
                            draft_id=draft_id,
                            text=html,
                            parse_mode="HTML",
                        )
                    else:
                        await self._app.bot.send_message(
                            chat_id=chat_id,
                            text=html,
                            parse_mode="HTML",
                            reply_parameters=reply_params,
                        )
                except Exception as e:
                    logger.warning(
                        "Ошибка парсинга HTML, переключаемся на обычный текст: {}", e
                    )
                    try:
                        if is_progress and draft_id:
                            await self._app.bot.send_message_draft(
                                chat_id=chat_id, draft_id=draft_id, text=chunk
                            )
                        else:
                            await self._app.bot.send_message(
                                chat_id=chat_id,
                                text=chunk,
                                reply_parameters=reply_params,
                            )
                    except Exception as e2:
                        logger.error("Ошибка отправки сообщения в Telegram: {}", e2)

    @staticmethod
    async def _on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработать команду /start."""
        if not update.message or not update.effective_user:
            return

        user = update.effective_user
        await update.message.reply_text(
            f"👋 Привет {user.first_name}! Я agentxyz.\n\n"
            "Отправь мне сообщение, и я отвечу!"
            "Введите /help чтобы увидеть доступные команды."
        )

    @staticmethod
    async def _on_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command, bypassing ACL so all users can access it."""
        if not update.message:
            return
        await update.message.reply_text(
            "🔥 Команды agentxyz:\n"
            "/new — Начать новый диалог\n"
            "/stop — Stop the current task\n"
            "/help — Показать доступные команды"
        )

    @staticmethod
    def _sender_id(user: Any) -> str:
        """Собрать sender_id с username для проверки в allowlist."""
        sid = str(user.id)
        return f"{sid}|{user.username}" if user.username else sid

    async def _forward_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Пересылать слэш-команды в шину для унифицированной обработки в AgentLoop."""
        if not update.message or not update.effective_user or not update.message.text:
            return
        await self._handle_message(
            sender_id=self._sender_id(update.effective_user),
            chat_id=str(update.message.chat_id),
            content=update.message.text,
        )

    async def _on_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Обработать входящие сообщения (текст, фото, голос, документы)."""
        if not update.message or not update.effective_user:
            return

        message = update.message
        user = update.effective_user
        chat_id = message.chat_id
        sender_id = self._sender_id(user)

        # Храним chat_id для ответов
        self._chat_ids[sender_id] = chat_id

        # Формируем содержание из текста и/или медиа
        content_parts = []
        media_paths = []

        # Текстовое содержание
        if message.text:
            content_parts.append(message.text)
        if message.caption:
            content_parts.append(message.caption)

        # Обработка медиафайлов
        media_file: Any = None
        media_type: str | None = None

        if message.photo:
            media_file = message.photo[-1]  # Крупнейшее фото
            media_type = "image"
        elif message.voice:
            media_file = message.voice
            media_type = "voice"
        elif message.audio:
            media_file = message.audio
            media_type = "audio"
        elif message.document:
            media_file = message.document
            media_type = "file"

        # Скачать медиа если есть
        if media_file and self._app:
            try:
                file = await self._app.bot.get_file(media_file.file_id)
                ext = self._get_extension(
                    media_type or "", getattr(media_file, "mime_type", None)
                )

                # Сохранить в workspace/media/
                from pathlib import Path

                media_dir = Path.home() / ".agentxyz" / "media"
                media_dir.mkdir(parents=True, exist_ok=True)

                file_path = media_dir / f"{media_file.file_id[:16]}{ext}"
                logger.info("Скачивание в {}...", file_path)
                await file.download_to_drive(str(file_path))
                logger.info(
                    "Успешно загружен {} в {} (размер: {} bytes)",
                    media_type,
                    file_path,
                    file_path.stat().st_size if file_path.exists() else "N/A",
                )

                media_paths.append(str(file_path))

                # Обработка транскрипции голоса
                if media_type == "voice" or media_type == "audio":
                    if self.transcription_config.provider == "whisper":
                        from agentxyz.providers.transcription import (
                            WhisperTranscriptionProvider,
                        )

                        whisper_transcriber = WhisperTranscriptionProvider(
                            model_size=self.transcription_config.whisper_model,
                            device=self.transcription_config.whisper_device,
                            language=self.transcription_config.language,
                        )
                        transcription = await whisper_transcriber.transcribe(file_path)
                    else:
                        transcription = None

                    if transcription:
                        logger.info(
                            "Транскрипция {}: {}...", media_type, transcription[:50]
                        )
                        content_parts.append(f"[транскрипция: {transcription}]")
                    else:
                        content_parts.append(f"[{media_type}: {file_path}]")
                else:
                    content_parts.append(f"[{media_type}: {file_path}]")

                logger.debug("Загружен {} в {}", media_type, file_path)
            except Exception as e:
                import traceback

                logger.error(
                    "[DEBUG] Ошибка загрузки медиа: type={}, file_id={}, error={}, traceback={}",
                    media_type,
                    getattr(media_file, "file_id", "N/A")[:20],
                    str(e),
                    traceback.format_exc()[-500:],
                )

                content_parts.append(f"[{media_type}: загрузка неудачна]")

        content = "\n".join(content_parts) if content_parts else "[пустое сообщение]"

        logger.debug("Сообщение Telegram от {}: {}...", sender_id, content[:50])

        str_chat_id = str(chat_id)

        # Группы медиа в Telegram: кратковременная буферизация, пересылка как одного агрегированного сообщения.
        if media_group_id := getattr(message, "media_group_id", None):
            key = f"{str_chat_id}:{media_group_id}"
            if key not in self._media_group_buffers:
                self._media_group_buffers[key] = {
                    "sender_id": sender_id,
                    "chat_id": str_chat_id,
                    "contents": [],
                    "media": [],
                    "metadata": {
                        "message_id": message.message_id,
                        "user_id": user.id,
                        "username": user.username,
                        "first_name": user.first_name,
                        "is_group": message.chat.type != "private",
                    },
                }
                self._start_typing(str_chat_id)
            buf = self._media_group_buffers[key]
            if content and content != "[empty message]":
                buf["contents"].append(content)
            buf["media"].extend(media_paths)
            if key not in self._media_group_tasks:
                self._media_group_tasks[key] = asyncio.create_task(
                    self._flush_media_group(key)
                )
            return

        # Запустить индикатор набора текста перед обработкой
        self._start_typing(str_chat_id)

        # Переслать в шину сообщений
        await self._handle_message(
            sender_id=sender_id,
            chat_id=str_chat_id,
            content=content,
            media=media_paths,
            metadata={
                "message_id": message.message_id,
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "is_group": message.chat.type != "private",
            },
        )

    async def _flush_media_group(self, key: str) -> None:
        """Непродолжительная пауза, после которой буферизованная группа медиа пересылается за один шаг"""
        try:
            await asyncio.sleep(0.6)
            if not (buf := self._media_group_buffers.pop(key, None)):
                return
            content = "\n".join(buf["contents"]) or "[empty message]"
            await self._handle_message(
                sender_id=buf["sender_id"],
                chat_id=buf["chat_id"],
                content=content,
                media=list(dict.fromkeys(buf["media"])),
                metadata=buf["metadata"],
            )
        finally:
            self._media_group_tasks.pop(key, None)

    def _start_typing(self, chat_id: str) -> None:
        """Начать отправку индикатора 'набирает...' для чата."""
        # Отменить любую существующую задачу индикатора набора текста для этого чата
        self._stop_typing(chat_id)
        self._typing_tasks[chat_id] = asyncio.create_task(self._typing_loop(chat_id))

    def _stop_typing(self, chat_id: str) -> None:
        """Остановить индикатор набора текста для чата."""
        task = self._typing_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()

    async def _typing_loop(self, chat_id: str) -> None:
        """Периодически отправлять действие 'typing' до отмены."""
        try:
            while self._app:
                await self._app.bot.send_chat_action(
                    chat_id=int(chat_id), action="typing"
                )
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("Индикатор набора текста остановлен для {}: {}", chat_id, e)

    @staticmethod
    async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Логировать polling и ошибки обработчика вместо их тихого игнорирования."""
        logger.error("Telegram error: {}", context.error)

    @staticmethod
    def _get_extension(media_type: str, mime_type: str | None) -> str:
        """Получить расширение файла по типу медиа."""
        if mime_type:
            ext_map = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/gif": ".gif",
                "audio/ogg": ".ogg",
                "audio/mpeg": ".mp3",
                "audio/mp4": ".m4a",
            }
            if mime_type in ext_map:
                return ext_map[mime_type]

        type_map = {"image": ".jpg", "voice": ".ogg", "audio": ".mp3", "file": ""}
        return type_map.get(media_type, "")
