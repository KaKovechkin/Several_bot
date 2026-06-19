from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import Router, Bot, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
import aiosqlite

from app.logger import logger
from app.texts import t
import os

from app.subscription import is_premium, is_subscribed, FREE_HISTORY_DAYS
from app.keyboards import buy_kb, subscribe_kb, del_item_kb
from app.media import send_media
from app import state
from app.database.db import (
    get_connection, get_contacts_with_counts, get_user_stats,
    get_filtered_messages, get_edit_history, format_date, get_language,
    delete_message_by_id,
)
from app.callbacks import UserID, DeleteMsg

router = Router()

PAGE_SIZE = 20


async def send_contact_list(message: Message):
    """Shared by /history command and the menu buttons."""
    owner_id = message.from_user.id
    lang = await get_language(owner_id)
    if not await is_subscribed(owner_id):
        await message.answer(
            '🔒 Доступ к истории требует подписки.\n'
            'Оформите её, чтобы просматривать удалённые и изменённые сообщения.',
            reply_markup=subscribe_kb(),
        )
        return
    connection = await get_connection(owner_id)
    if connection is None:
        await message.answer(t(lang, 'no_connection'))
        return
    contacts = await get_contacts_with_counts(connection[0], owner_id)
    if not contacts:
        await message.answer('Пока нет сохранённых собеседников.')
        return
    builder = InlineKeyboardBuilder()
    for c in contacts:
        from_user_id, username, first_name, total, edited, deleted = c
        name = f'@{username}' if username else (first_name or str(from_user_id))
        label = f'{name} (✏️{edited or 0} 🗑{deleted or 0})'
        builder.button(text=label, callback_data=UserID(user_id=from_user_id).pack())
    builder.button(text=t(lang, 'btn_back'), callback_data='nav:back')
    builder.adjust(1)
    await message.answer('👥 Выберите собеседника:', reply_markup=builder.as_markup())


@router.message(Command('history'))
async def cmd_history(message: Message):
    await send_contact_list(message)


def _filter_kb(user_id: int, active: str) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    for mode, label in (('all', 'Всё'), ('deleted', '🗑 Удалённые'), ('edited', '✏️ Изменённые')):
        mark = '• ' if mode == active else ''
        b.button(text=f'{mark}{label}', callback_data=f'hist:{mode}:{user_id}:0')
    b.adjust(3)
    return b


def _pager_kb(user_id: int, mode: str, page: int, pages: int) -> InlineKeyboardMarkup:
    """Prev/next navigation for paginated history."""
    row = []
    if page > 0:
        row.append(InlineKeyboardButton(
            text='◀️ Назад', callback_data=f'hist:{mode}:{user_id}:{page - 1}'))
    if page < pages - 1:
        row.append(InlineKeyboardButton(
            text='Вперёд ▶️', callback_data=f'hist:{mode}:{user_id}:{page + 1}'))
    return InlineKeyboardMarkup(inline_keyboard=[row] if row else [])


async def _render_history(bot: Bot, owner_id: int, user_id: int, mode: str,
                          target: Message, page: int = 0):
    # Clear the previously rendered output so switching filters doesn't pile up.
    await state.clear_history_output(bot, owner_id)
    sent_ids: list[int] = []

    lang = await get_language(owner_id)
    conn = await get_connection(owner_id)
    if conn is None:
        m = await target.answer(t(lang, 'no_connection'))
        state.track(owner_id, [m.message_id])
        return
    bcid = conn[0]
    premium = await is_premium(owner_id)

    messages = await get_filtered_messages(bcid, user_id, mode=mode)

    # Free tier: limit to last N days
    if not premium:
        from datetime import datetime, timezone
        cutoff = int(datetime.now(tz=timezone.utc).timestamp()) - FREE_HISTORY_DAYS * 86400
        filtered = []
        for m in messages:
            d = m[4]
            ts = d if isinstance(d, (int, float)) else None
            if ts is None or ts >= cutoff:
                filtered.append(m)
        messages = filtered

    if not messages:
        m = await target.answer('Нет сообщений по этому фильтру.')
        state.track(owner_id, [m.message_id])
        return

    total = len(messages)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    page_items = messages[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    header = f'📋 Найдено: {total}'
    if pages > 1:
        header += f' — страница {page + 1}/{pages}'
    if premium:
        m = await target.answer(header)
    else:
        m = await target.answer(
            f'{header}\n\n🔒 Содержимое и медиа доступны в Premium.',
            reply_markup=buy_kb(lang),
        )
    sent_ids.append(m.message_id)

    for msg in page_items:
        db_id, text, is_edited, is_deleted, date, file_id, type_message, message_id, chat_id, local_path = msg
        if is_edited and is_deleted:
            status = '✏️🗑 Изменено и удалено'
        elif is_edited:
            status = '✏️ Изменено'
        else:
            status = '🗑 Удалено'
        caption = f'{format_date(date)} | {status}'

        # Edit history (было/стало)
        history_lines = ''
        if is_edited:
            edits = await get_edit_history(chat_id, message_id)
            if edits:
                parts = [
                    f'  ❌ Было: {old or "—"}\n  ✅ Стало: {new or "—"}'
                    for old, new, _ in edits
                ]
                history_lines = '\nИстория правок:\n' + '\n'.join(parts)

        if not premium:
            m = await target.answer(f'{caption}\n🔒 Содержимое доступно в Premium.')
            sent_ids.append(m.message_id)
            continue

        del_kb = del_item_kb(db_id, lang)
        if type_message == 'text':
            m = await target.answer(
                f'{caption}\nТекст: {text or "—"}{history_lines}', reply_markup=del_kb
            )
            item_ids = [m.message_id]
        elif type_message in ('photo', 'video', 'document', 'sticker', 'video_note', 'voice'):
            item_ids = await send_media(
                bot, owner_id, type_message, local_path, file_id,
                f'{caption}{history_lines}', reply_markup=del_kb,
            )
        else:
            m = await target.answer(
                f'{caption} | Неизвестный тип{history_lines}', reply_markup=del_kb
            )
            item_ids = [m.message_id]
        sent_ids.extend(item_ids)
        state.track_item(owner_id, db_id, item_ids)

    if pages > 1:
        nav = await target.answer(
            f'Страница {page + 1} из {pages}',
            reply_markup=_pager_kb(user_id, mode, page, pages),
        )
        sent_ids.append(nav.message_id)

    state.track(owner_id, sent_ids)


@router.callback_query(UserID.filter())
async def on_user_selected(callback: CallbackQuery, callback_data: UserID, bot: Bot):
    try:
        user_id = callback_data.user_id
        owner_id = callback.from_user.id
        conn = await get_connection(owner_id=owner_id)
        if conn is None:
            await callback.answer('Нет активного бизнес-соединения.', show_alert=True)
            return
        stats = await get_user_stats(conn[0], user_id)
        total, deleted, edited = stats if stats else (0, 0, 0)
        await callback.message.answer(
            f'📊 Статистика собеседника:\n'
            f'Всего сообщений: {total}\n'
            f'Удалено: {deleted or 0}\n'
            f'Отредактировано: {edited or 0}',
            reply_markup=_filter_kb(user_id, 'all').as_markup(),
        )
        await _render_history(bot, owner_id, user_id, 'all', callback.message)
        await callback.answer()
    except aiosqlite.Error as e:
        logger.error(f'DB error in on_user_selected: {e}')
        await callback.answer('⚠️ Ошибка базы данных.', show_alert=True)
    except Exception as e:
        logger.exception(f'Unexpected in on_user_selected: {e}')
        await callback.answer('⚠️ Что-то пошло не так.', show_alert=True)


@router.callback_query(DeleteMsg.filter())
async def on_delete_item(callback: CallbackQuery, callback_data: DeleteMsg, bot: Bot):
    """Delete a stored message (record + media + edits) and remove it from chat."""
    try:
        owner_id = callback.from_user.id
        db_id = callback_data.db_id
        local_path = await delete_message_by_id(db_id)
        # Remove the file from disk if we downloaded one.
        if local_path:
            try:
                if os.path.exists(local_path):
                    os.remove(local_path)
            except OSError as e:
                logger.warning(f'Failed to remove media file {local_path}: {e}')
        # Remove the bot messages that rendered this item from the chat.
        ids = state.pop_item(owner_id, db_id)
        if ids:
            await state.delete_chat_messages(bot, owner_id, ids)
        else:
            # Fallback: at least delete the message the button is attached to.
            try:
                await callback.message.delete()
            except Exception:
                pass
        await callback.answer('🗑 Удалено')
    except Exception as e:
        logger.exception(f'Unexpected in on_delete_item: {e}')
        await callback.answer('⚠️ Не удалось удалить.', show_alert=True)


@router.callback_query(F.data.startswith('hist:'))
async def on_filter(callback: CallbackQuery, bot: Bot):
    try:
        parts = callback.data.split(':')
        # Backward-compatible: hist:mode:user_id[:page]
        _, mode, user_id = parts[0], parts[1], parts[2]
        page = int(parts[3]) if len(parts) >= 4 else 0
        await _render_history(
            bot, callback.from_user.id, int(user_id), mode, callback.message, page
        )
        await callback.answer()
    except Exception as e:
        logger.exception(f'Unexpected in on_filter: {e}')
        await callback.answer('⚠️ Что-то пошло не так.', show_alert=True)
