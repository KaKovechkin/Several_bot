"""In-memory tracking of bot output messages so we can clear them.

Single-process bot, so module-level dicts are enough. Keyed by owner_id.
"""
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from app.logger import logger

# Message ids of the last rendered history output, per owner.
history_output: dict[int, list[int]] = {}

# Per-owner map: stored record id (messages.id) -> bot message ids that render
# it, so a "delete" button can remove exactly those messages from the chat.
item_messages: dict[int, dict[int, list[int]]] = {}


def track(owner_id: int, message_ids: list[int]) -> None:
    history_output.setdefault(owner_id, []).extend(message_ids)


def track_item(owner_id: int, db_id: int, message_ids: list[int]) -> None:
    item_messages.setdefault(owner_id, {})[db_id] = list(message_ids)


def pop_item(owner_id: int, db_id: int) -> list[int]:
    return item_messages.get(owner_id, {}).pop(db_id, [])


async def clear_history_output(bot: Bot, owner_id: int) -> int:
    """Delete the previously rendered history output for this owner."""
    ids = history_output.pop(owner_id, [])
    item_messages.pop(owner_id, None)
    deleted = 0
    for mid in ids:
        try:
            await bot.delete_message(owner_id, mid)
            deleted += 1
        except TelegramBadRequest:
            pass  # already gone or older than 48h
        except Exception as e:
            logger.warning(f'delete_message failed for {owner_id}/{mid}: {e}')
    return deleted


async def delete_chat_messages(bot: Bot, owner_id: int, message_ids: list[int]) -> int:
    """Delete specific bot messages from the chat (e.g. one history item)."""
    deleted = 0
    for mid in message_ids:
        try:
            await bot.delete_message(owner_id, mid)
            deleted += 1
        except TelegramBadRequest:
            pass
        except Exception as e:
            logger.warning(f'delete_message failed for {owner_id}/{mid}: {e}')
    return deleted
