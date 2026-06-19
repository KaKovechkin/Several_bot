from datetime import datetime, timezone

from aiogram.types import (
    Message, BusinessMessagesDeleted, BusinessConnection,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram import Router, Bot
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
import aiosqlite

from app.logger import logger
from app.subscription import is_premium
from app.media import download_media, send_media
from app.database.db import (
    save_message, message_update, mark_deleted, get_message, save_connection,
    ensure_settings, get_settings, get_keywords, queue_notification,
    enforce_user_limit, format_date, get_owner_by_connection,
)

router = Router()

USER_MSG_LIMIT = 1000

# Cache business_connection_id -> owner_id to avoid an API call per message.
_owner_cache: dict[str, int] = {}


async def _resolve_owner(bot: Bot, bcid: str):
    """Return the owner_id for a business connection (cache -> DB -> API)."""
    if bcid in _owner_cache:
        return _owner_cache[bcid]
    owner_id = await get_owner_by_connection(bcid)
    if owner_id is None:
        try:
            conn = await bot.get_business_connection(bcid)
            owner_id = conn.user.id
            await save_connection(owner_id, bcid)
        except Exception as e:
            logger.warning(f'Could not resolve owner for {bcid}: {e}')
            return None
    _owner_cache[bcid] = owner_id
    return owner_id


def _to_ts(date) -> int:
    """Normalize an aiogram message date to a unix timestamp."""
    if isinstance(date, datetime):
        return int(date.timestamp())
    if isinstance(date, (int, float)):
        return int(date)
    return int(datetime.now(tz=timezone.utc).timestamp())


def _in_quiet(settings: dict) -> bool:
    if not settings or not settings.get('quiet_enabled'):
        return False
    start = settings.get('quiet_start', 23)
    end = settings.get('quiet_end', 8)
    hour = datetime.now(tz=timezone.utc).hour
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


async def _matched_keyword(owner_id, text) -> str | None:
    if not text:
        return None
    low = text.lower()
    for w in await get_keywords(owner_id):
        if w and w in low:
            return w
    return None


def _locked_kb() -> InlineKeyboardMarkup:
    """Shown to free users instead of message content."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='👁 Показать сообщение', callback_data='show_locked')],
    ])


async def _deliver_text(bot: Bot, owner_id, settings, brief: str, full: str):
    """Send a text notification respecting Free/Premium and quiet mode.

    Free users get the brief notice (no content) plus a «show message» button
    that prompts them to subscribe. Premium users get the full content.
    """
    premium = await is_premium(owner_id)
    text = full if premium else brief
    markup = None if premium else _locked_kb()
    if _in_quiet(settings):
        await queue_notification(owner_id, text)
        return
    try:
        await bot.send_message(chat_id=owner_id, text=text, reply_markup=markup)
    except TelegramBadRequest as e:
        logger.warning(f'TG error delivering to {owner_id}: {e}')


async def _deliver(bot: Bot, owner_id, settings, premium, type_message,
                   local_path, file_id, brief: str, full: str):
    """Route a notification: free→brief text, premium media→file, else text.
    Respects quiet mode by queueing text for the morning digest."""
    if not premium or type_message == 'text' or not file_id:
        await _deliver_text(bot, owner_id, settings, brief, full)
        return
    if _in_quiet(settings):
        await queue_notification(owner_id, full)
        return
    try:
        await send_media(bot, owner_id, type_message, local_path, file_id, full)
    except TelegramBadRequest as e:
        logger.warning(f'TG error sending media to {owner_id}: {e}')
        await bot.send_message(owner_id, text=f'{full}\n(медиа недоступно)')


@router.business_connection()
async def handle_business_connection(connection: BusinessConnection, bot: Bot):
    """Fires when the owner connects/disconnects the bot in Telegram Business."""
    try:
        owner_id = connection.user.id
        await ensure_settings(owner_id)
        if connection.is_enabled:
            await save_connection(owner_id, connection.id)
            logger.info(f'Business connection enabled for owner {owner_id}')
            # NOTE: scanning the last 200 messages here is not possible —
            # the Bot API does not expose chat history. New messages are
            # captured live via business_message below.
        else:
            logger.info(f'Business connection disabled for owner {owner_id}')
    except Exception as e:
        logger.exception(f'Error in handle_business_connection: {e}')


@router.business_message()
async def handle_business_message(message: Message, bot: Bot):
    try:
        # Ignore the owner's own messages — they aren't a "contact".
        owner_id = await _resolve_owner(bot, message.business_connection_id)
        if owner_id is not None and message.from_user and message.from_user.id == owner_id:
            return

        text = message.text or message.caption
        doc_name = None
        if message.photo:
            type_message, file_id = 'photo', message.photo[-1].file_id
        elif message.video:
            type_message, file_id = 'video', message.video.file_id
        elif message.animation:
            type_message, file_id = 'animation', message.animation.file_id
        elif message.sticker:
            type_message, file_id = 'sticker', message.sticker.file_id
        elif message.video_note:
            type_message, file_id = 'video_note', message.video_note.file_id
        elif message.voice:
            type_message, file_id = 'voice', message.voice.file_id
        elif message.audio:
            type_message, file_id = 'audio', message.audio.file_id
        elif message.document:
            type_message, file_id = 'document', message.document.file_id
            doc_name = message.document.file_name
        elif message.text:
            type_message, file_id = 'text', None
        else:
            logger.info(f'Unhandled message type: {type(message)}')
            type_message, file_id = 'other_type', None

        # Persist media to disk now — business file_ids may be unusable later.
        local_path = None
        if file_id and type_message != 'text':
            local_path = await download_media(bot, type_message, file_id, doc_name)

        await save_message(
            message.chat.id, message.business_connection_id, message.message_id,
            file_id, type_message, message.from_user.id, text, _to_ts(message.date),
            message.from_user.first_name, message.from_user.username, local_path,
        )
        await enforce_user_limit(
            message.business_connection_id, message.from_user.id, USER_MSG_LIMIT
        )
    except aiosqlite.Error as e:
        logger.error(f'DB error saving business message: {e}')
    except Exception as e:
        logger.exception(f'Unexpected in handle_business_message: {e}')


@router.edited_business_message()
async def handle_business_message_update(message: Message, bot: Bot):
    owner_id = None
    try:
        connection = await bot.get_business_connection(message.business_connection_id)
        owner_id = connection.user.id
        _owner_cache[message.business_connection_id] = owner_id
        settings = await ensure_settings(owner_id)
        await save_connection(owner_id, message.business_connection_id)

        # Don't notify the owner about edits to their own messages.
        if message.from_user and message.from_user.id == owner_id:
            return

        old_message = await get_message(chat_id=message.chat.id, message_id=message.message_id)
        if old_message is None:
            logger.info('Edited message not found in DB')
            return
        type_message = old_message[3]
        file_id = old_message[2]
        username = old_message[1] or 'Без username'
        old_text = old_message[0]
        local_path = old_message[4]
        new_text = message.text or message.caption
        now_str = format_date(datetime.now(tz=timezone.utc))

        premium = await is_premium(owner_id)

        brief = f'✏️ @{username} изменил(а) сообщение\n🕐 Изменено: {now_str}'
        full = (
            f'✏️ @{username} изменил(а) сообщение\n\n'
            f'❌ Было: "{old_text or "—"}"\n'
            f'✅ Стало: "{new_text or "—"}"\n'
            f'🕐 Изменено: {now_str}'
        )

        kw = await _matched_keyword(owner_id, old_text) if premium else None
        if kw:
            full = f'⚠️ Важно (слово «{kw}»)\n\n' + full

        # Free tier gets a brief notice; subscribers get full content (see _deliver).
        await _deliver(bot, owner_id, settings, premium, type_message,
                       local_path, file_id, brief, full)

        await message_update(
            new_text, chat_id=message.chat.id, message_id=message.message_id, is_edited=1
        )
    except TelegramBadRequest as e:
        logger.warning(f'TG error on edit: {e}')
    except aiosqlite.Error as e:
        logger.error(f'DB error on edit: {e}')
    except Exception as e:
        logger.exception(f'Unexpected in handle_business_message_update: {e}')


@router.deleted_business_messages()
async def handle_deleted(event: BusinessMessagesDeleted, bot: Bot):
    owner_id = None
    try:
        connection = await bot.get_business_connection(event.business_connection_id)
        owner_id = connection.user.id
        _owner_cache[event.business_connection_id] = owner_id
        settings = await ensure_settings(owner_id)
        await save_connection(owner_id, event.business_connection_id)
    except Exception as e:
        logger.exception(f'Error resolving connection on delete: {e}')
        return

    premium = await is_premium(owner_id)
    now_str = format_date(datetime.now(tz=timezone.utc))

    for message_id in event.message_ids:
        try:
            await mark_deleted(message_id=message_id, chat_id=event.chat.id)
            row = await get_message(event.chat.id, message_id)
            if row is None:
                logger.info(f'Deleted message {message_id} not found in DB')
                continue
            type_message = row[3]
            file_id = row[2]
            username = row[1] or 'Без username'
            text = row[0]
            local_path = row[4]

            brief = f'🗑 @{username} удалил(а) сообщение\n🕐 Удалено: {now_str}'
            base = (
                f'🗑 @{username} удалил(а) сообщение\n\n'
                f'📝 Текст: "{text or "—"}"\n'
                f'🕐 Удалено: {now_str}'
            )
            kw = await _matched_keyword(owner_id, text) if premium else None
            full = (f'⚠️ Важно (слово «{kw}»)\n\n' + base) if kw else base

            await _deliver(bot, owner_id, settings, premium, type_message,
                           local_path, file_id, brief, full)
        except TelegramBadRequest as e:
            logger.warning(f'TG error on delete of {message_id}: {e}')
        except aiosqlite.Error as e:
            logger.error(f'DB error on delete of {message_id}: {e}')
        except Exception as e:
            logger.exception(f'Unexpected on delete of {message_id}: {e}')
