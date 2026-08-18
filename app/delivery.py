"""Resilient Telegram delivery helpers: text clipping and retry on flood control."""
import asyncio

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramNetworkError

from app.logger import logger

MAX_TEXT = 4096


def clip(text: str) -> str:
    """Truncate text to Telegram's 4096-char message limit."""
    if text and len(text) > MAX_TEXT:
        return text[:MAX_TEXT - 3] + '…'
    return text


async def send_message_retry(bot: Bot, chat_id, text, attempts: int = 5, **kwargs):
    """send_message with retry on flood control (429) and network errors.

    Permanent errors (TelegramBadRequest etc.) are raised immediately.
    """
    text = clip(text)
    last_exc = None
    for i in range(attempts):
        try:
            return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except TelegramRetryAfter as e:
            last_exc = e
            wait = min(e.retry_after, 30)
            logger.warning(
                f'Flood control to {chat_id} (retry_after={e.retry_after}s), sleeping {wait}s'
            )
            await asyncio.sleep(wait + 0.5)
        except TelegramNetworkError as e:
            last_exc = e
            logger.warning(f'Network error to {chat_id}, attempt {i + 1}/{attempts}: {e}')
            await asyncio.sleep(2 ** i)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError('send_message retries exhausted')
