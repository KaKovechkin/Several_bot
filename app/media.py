import os
from uuid import uuid4

from aiogram import Bot
from aiogram.types import FSInputFile
from aiogram.exceptions import TelegramBadRequest

from app.logger import logger

MEDIA_DIR = os.getenv('MEDIA_DIR', 'media')

_EXT = {
    'photo': '.jpg',
    'video': '.mp4',
    'video_note': '.mp4',
    'voice': '.ogg',
    'sticker': '.webp',
    'document': '',
    'animation': '.mp4',
    'audio': '.mp3',
}


async def download_media(bot: Bot, type_message: str, file_id: str,
                         doc_name: str | None = None) -> str | None:
    """Download a media file at capture time and return its local path.

    Business-message file_ids are not reliably reusable later, so we persist
    the bytes on disk. Returns None on failure (we keep file_id as fallback).
    """
    if not file_id or type_message not in _EXT:
        return None
    try:
        os.makedirs(MEDIA_DIR, exist_ok=True)
        ext = _EXT[type_message]
        if type_message == 'document' and doc_name and '.' in doc_name:
            ext = os.path.splitext(doc_name)[1]
        path = os.path.join(MEDIA_DIR, f'{uuid4().hex}{ext}')
        await bot.download(file_id, destination=path)
        return path
    except Exception as e:
        logger.warning(f'Failed to download media ({type_message}): {e}')
        return None


def media_source(local_path: str | None, file_id: str | None):
    """Prefer the locally stored file; fall back to the original file_id."""
    if local_path and os.path.exists(local_path):
        return FSInputFile(local_path)
    return file_id


async def send_media(bot: Bot, chat_id: int, type_message: str,
                     local_path: str | None, file_id: str | None,
                     info: str, reply_markup=None) -> list[int]:
    """Send a stored media item followed by an info message.

    Media is sent without a caption (info goes in a separate message) to avoid
    caption-length limits and to guarantee the info is shown even if the media
    can no longer be delivered. `reply_markup`, if given, is attached to the
    info message. Returns the message_ids of everything sent.
    """
    source = media_source(local_path, file_id)
    ids: list[int] = []
    media_failed = False

    if source is not None:
        try:
            if type_message == 'photo':
                m = await bot.send_photo(chat_id, source)
            elif type_message == 'video':
                m = await bot.send_video(chat_id, source)
            elif type_message == 'document':
                m = await bot.send_document(chat_id, source)
            elif type_message == 'sticker':
                m = await bot.send_sticker(chat_id, source)
            elif type_message == 'video_note':
                m = await bot.send_video_note(chat_id, source)
            elif type_message == 'voice':
                m = await bot.send_voice(chat_id, source)
            elif type_message == 'animation':
                m = await bot.send_animation(chat_id, source)
            elif type_message == 'audio':
                m = await bot.send_audio(chat_id, source)
            else:
                m = None
            if m is not None:
                ids.append(m.message_id)
        except TelegramBadRequest as e:
            logger.warning(f'Media send failed ({type_message}) to {chat_id}: {e}')
            media_failed = True
    else:
        media_failed = True

    if media_failed:
        info = f'{info}\n⚠️ Медиа не удалось восстановить.'
    info_msg = await bot.send_message(chat_id, info, reply_markup=reply_markup)
    ids.append(info_msg.message_id)
    return ids
