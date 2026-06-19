from datetime import datetime, timezone
from html import escape

from aiogram import Router, Bot, F
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
import aiosqlite

import os

from app.logger import logger
from app.texts import t
from app import state
from app.keyboards import (
    onboarding_kb, main_menu_kb, buy_kb, share_kb, settings_kb, confirm_wipe_kb,
    support_kb,
)


def _support_username() -> str:
    # Read at call-time: .env is loaded after this module is imported.
    return os.getenv('SUPPORT_USERNAME', 'support')
from app.subscription import is_premium
from app.database.db import (
    get_connection, ensure_settings, get_settings, get_language, update_setting,
    add_keyword, remove_keyword, get_keywords,
    get_top_deleters, get_top_editors, get_deletion_hours,
    delete_all_messages, add_referral, upsert_subscription,
)
from app.handlers.history import send_contact_list

router = Router()


class Flow(StatesGroup):
    add_keyword = State()


def _name(message: Message) -> str:
    return message.from_user.first_name or 'друг'


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    owner_id = message.from_user.id
    await ensure_settings(owner_id)
    # Referral deep-link: /start ref_<referrer_id>
    arg = (command.args or '').strip()
    if arg.startswith('ref_'):
        try:
            referrer_id = int(arg[4:])
            if referrer_id != owner_id:
                now = int(datetime.now(tz=timezone.utc).timestamp())
                await add_referral(referrer_id, owner_id, now)
        except ValueError:
            pass
    lang = await get_language(owner_id)
    await message.answer(
        t(lang, 'start', name=escape(_name(message))),
        parse_mode='HTML',
        reply_markup=onboarding_kb(lang),
    )


@router.callback_query(F.data == 'instruction')
async def cb_instruction(callback: CallbackQuery):
    lang = await get_language(callback.from_user.id)
    await callback.message.answer(t(lang, 'instruction'), parse_mode='HTML')
    await callback.answer()


@router.callback_query(F.data == 'check_conn')
async def cb_check_conn(callback: CallbackQuery):
    owner_id = callback.from_user.id
    lang = await get_language(owner_id)
    conn = await get_connection(owner_id)
    if conn:
        await callback.message.answer(t(lang, 'connected_ok'), reply_markup=main_menu_kb(lang))
    else:
        await callback.message.answer(t(lang, 'connected_fail'))
    await callback.answer()


# --------------------------- help & support ---------------------------

async def _send_help(message: Message):
    lang = await get_language(message.from_user.id)
    await message.answer(t(lang, 'help'), parse_mode='HTML', reply_markup=main_menu_kb(lang))


async def _send_support(message: Message):
    lang = await get_language(message.from_user.id)
    await message.answer(
        t(lang, 'support'), parse_mode='HTML',
        reply_markup=support_kb(_support_username(), lang),
    )


@router.message(Command('help'))
async def cmd_help(message: Message):
    await _send_help(message)


@router.message(Command('support'))
async def cmd_support(message: Message):
    await _send_support(message)


@router.message(F.text.startswith('❓'))
async def menu_help(message: Message):
    await _send_help(message)


@router.message(F.text.startswith('🆘'))
async def menu_support(message: Message):
    await _send_support(message)


@router.callback_query(F.data == 'nav:back')
async def cb_nav_back(callback: CallbackQuery):
    """Close the current inline menu."""
    try:
        await callback.message.delete()
    except Exception:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await callback.answer()


# --------------------------- main-menu buttons ---------------------------

async def _menu_match(message: Message, key: str) -> bool:
    lang = await get_language(message.from_user.id)
    return message.text == t(lang, key)


@router.message(F.text.startswith('📜'))
async def menu_history(message: Message, bot: Bot):
    await send_contact_list(message)


@router.message(F.text.startswith('👥'))
async def menu_contacts(message: Message, bot: Bot):
    await send_contact_list(message)


@router.message(F.text.startswith('📊'))
async def menu_stats(message: Message):
    owner_id = message.from_user.id
    lang = await get_language(owner_id)
    if not await is_premium(owner_id):
        await message.answer(t(lang, 'premium_only'), parse_mode='HTML', reply_markup=buy_kb(lang))
        return
    conn = await get_connection(owner_id)
    if conn is None:
        await message.answer(t(lang, 'no_connection'))
        return
    bcid = conn[0]
    deleters = await get_top_deleters(bcid)
    editors = await get_top_editors(bcid)
    hours = await get_deletion_hours(bcid)

    def fmt(rows):
        if not rows:
            return '  —'
        out = []
        for r in rows:
            username, first_name, uid, cnt = r
            name = f'@{username}' if username else (first_name or str(uid))
            out.append(f'  {escape(name)}: {cnt}')
        return '\n'.join(out)

    text = '📊 <b>Статистика</b>\n\n'
    text += '🗑 <b>Чаще всех удаляют:</b>\n' + fmt(deleters) + '\n\n'
    text += '✏️ <b>Чаще всех редактируют:</b>\n' + fmt(editors) + '\n\n'
    if hours:
        peak = hours[0]
        text += f'🕐 Чаще всего удаляют около <b>{peak[0]:02d}:00</b> ({peak[1]} раз)'
    await message.answer(text, parse_mode='HTML')


@router.message(F.text.startswith('💎'))
async def menu_subscription(message: Message, bot: Bot):
    owner_id = message.from_user.id
    lang = await get_language(owner_id)
    if await is_premium(owner_id):
        me = await bot.get_me()
        await message.answer(
            t(lang, 'sub_active'), parse_mode='HTML',
            reply_markup=share_kb(lang, me.username),
        )
    else:
        await message.answer(
            t(lang, 'sub_test_offer'), parse_mode='HTML',
            reply_markup=buy_kb(lang),
        )


@router.callback_query(F.data == 'buy_premium')
async def cb_buy(callback: CallbackQuery, bot: Bot):
    # Тестовый режим: приём оплаты не подключён, поэтому «покупка»
    # активирует Premium бесплатно.
    owner_id = callback.from_user.id
    lang = await get_language(owner_id)
    await ensure_settings(owner_id)
    # Записываем в таблицу subscriptions (единый источник правды), чтобы premium
    # можно было сбросить через /revoke. expires_at=None — бессрочно на время теста.
    await upsert_subscription(owner_id, 1, None, 'test', None, 0)
    me = await bot.get_me()
    await callback.message.answer(
        t(lang, 'sub_activated'), parse_mode='HTML',
        reply_markup=share_kb(lang, me.username),
    )
    await callback.answer('Premium активирован 🎉')


# --------------------------- settings ---------------------------

@router.message(F.text.startswith('⚙️'))
async def menu_settings(message: Message):
    settings = await ensure_settings(message.from_user.id)
    await message.answer('⚙️ Настройки:', reply_markup=settings_kb(settings))


@router.callback_query(F.data == 'set:quiet')
async def cb_quiet(callback: CallbackQuery):
    owner_id = callback.from_user.id
    settings = await ensure_settings(owner_id)
    new_val = 0 if settings.get('quiet_enabled') else 1
    await update_setting(owner_id, 'quiet_enabled', new_val)
    state = 'включён (23:00–08:00)' if new_val else 'выключен'
    await callback.message.answer(f'🔕 Тихий режим {state}.')
    await callback.answer()


@router.callback_query(F.data == 'set:lang')
async def cb_lang(callback: CallbackQuery):
    owner_id = callback.from_user.id
    settings = await ensure_settings(owner_id)
    new_lang = 'en' if settings.get('language') == 'ru' else 'ru'
    await update_setting(owner_id, 'language', new_lang)
    await callback.message.answer(
        f'🌐 Язык: {new_lang.upper()}',
        reply_markup=main_menu_kb(new_lang),
    )
    await callback.answer()


@router.callback_query(F.data == 'set:keywords')
async def cb_keywords(callback: CallbackQuery, fsm: FSMContext):
    owner_id = callback.from_user.id
    if not await is_premium(owner_id):
        lang = await get_language(owner_id)
        await callback.message.answer(t(lang, 'premium_only'), parse_mode='HTML', reply_markup=buy_kb(lang))
        await callback.answer()
        return
    words = await get_keywords(owner_id)
    current = ', '.join(words) if words else '—'
    await callback.message.answer(
        f'🔑 Текущие ключевые слова: {current}\n\n'
        f'Отправь слово чтобы добавить (или «-слово» чтобы удалить).'
    )
    await fsm.set_state(Flow.add_keyword)
    await callback.answer()


@router.message(Flow.add_keyword)
async def on_keyword_input(message: Message, fsm: FSMContext):
    owner_id = message.from_user.id
    word = (message.text or '').strip()
    if word.startswith('-'):
        await remove_keyword(owner_id, word[1:])
        await message.answer(f'➖ Удалено: {word[1:]}')
    else:
        await add_keyword(owner_id, word)
        await message.answer(f'➕ Добавлено: {word.lower()}')
    await fsm.clear()


# --------------------------- clear chat / wipe DB ---------------------------

@router.callback_query(F.data == 'set:clearchat')
async def cb_clearchat(callback: CallbackQuery, bot: Bot):
    owner_id = callback.from_user.id
    deleted = await state.clear_history_output(bot, owner_id)
    await callback.answer(
        f'Удалено сообщений: {deleted}' if deleted else 'Нечего очищать.',
        show_alert=False,
    )


@router.callback_query(F.data == 'set:wipe')
async def cb_wipe(callback: CallbackQuery):
    await callback.message.answer(
        '⚠️ Удалить <b>всю</b> сохранённую историю переписок (все собеседники, '
        'медиа и правки)? Это действие необратимо.',
        parse_mode='HTML',
        reply_markup=confirm_wipe_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == 'wipe:no')
async def cb_wipe_no(callback: CallbackQuery):
    await callback.message.edit_text('↩️ Отменено. История сохранена.')
    await callback.answer()


@router.callback_query(F.data == 'wipe:yes')
async def cb_wipe_yes(callback: CallbackQuery, bot: Bot):
    owner_id = callback.from_user.id
    conn = await get_connection(owner_id)
    if conn is None:
        await callback.message.edit_text('Нет активного бизнес-соединения.')
        await callback.answer()
        return
    paths = await delete_all_messages(conn[0])
    # Remove downloaded media files from disk too.
    removed = 0
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
                removed += 1
        except OSError as e:
            logger.warning(f'Failed to remove media file {p}: {e}')
    await state.clear_history_output(bot, owner_id)
    await callback.message.edit_text(
        f'🗑 История удалена. Очищено медиафайлов: {removed}.'
    )
    await callback.answer('Готово')
