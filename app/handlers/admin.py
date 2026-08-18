"""In-bot admin panel (login by password) for manual subscription management.

Security notes:
- ADMIN_PASSWORD lives only in .env, never hardcoded, never logged.
- Password comparison uses secrets.compare_digest (constant-time).
- ADMIN_IDS is a sanity-check allowlist of user_ids permitted to even attempt
  login. Login state is kept in process memory only.

Account management accepts either @username or user_id (fallback to id when
there is no username).
"""
import os
import secrets
from datetime import datetime, timezone
from html import escape

from aiogram import Router, Bot, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
)

from app.logger import logger
from app.database.db import (
    upsert_subscription, deactivate_subscription, get_subscription,
    grant_referral_bonus, reset_trial, format_date, get_admin_stats,
    find_owner_by_username, get_owner_profile,
)

router = Router()

# user_ids currently authenticated as admin (process memory only).
admin_sessions: set[int] = set()


class AdminFlow(StatesGroup):
    grant = State()
    revoke = State()


def _admin_password() -> str:
    # Read at call-time: .env is loaded after this module is imported.
    return os.getenv('ADMIN_PASSWORD', '')


def _admin_ids() -> set[int]:
    raw = os.getenv('ADMIN_IDS', '')
    ids = set()
    for part in raw.split(','):
        part = part.strip()
        if part:
            try:
                ids.add(int(part))
            except ValueError:
                continue
    return ids


async def resolve_user(arg: str) -> int | None:
    """Resolve a target to user_id: numeric -> id, otherwise @username."""
    arg = (arg or '').strip()
    if not arg:
        return None
    if arg.isdigit():
        return int(arg)
    return await find_owner_by_username(arg)


async def _display_target(target_id: int) -> str:
    profile = await get_owner_profile(target_id)
    if profile and profile[1]:
        return f'@{profile[1]} ({target_id})'
    return str(target_id)


@router.message(Command('admin'))
async def cmd_admin(message: Message, command: CommandObject, bot: Bot):
    user_id = message.from_user.id
    # Try to delete the message so the password doesn't linger in chat history.
    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    password = (command.args or '').strip()
    configured = _admin_password()
    allowlist = _admin_ids()

    # Allowlist sanity-check + configured password must exist.
    if not configured or (allowlist and user_id not in allowlist):
        await message.answer('Неверный пароль')
        return
    if password and secrets.compare_digest(password, configured):
        admin_sessions.add(user_id)
        await message.answer(
            '✅ Доступ получен.\n'
            'Команды: /grant, /revoke, /reset_trial, /admin_status, '
            '/grant_ref_bonus, /admin_stats, /admin_help, /admin_logout\n\n'
            'В командах можно указывать @username или user_id.'
        )
    else:
        await message.answer('Неверный пароль')


@router.message(Command('admin_help'))
async def cmd_admin_help(message: Message):
    if message.from_user.id not in admin_sessions:
        return
    await message.answer(
        '🛠 <b>Админ-команды</b>\n'
        '/grant &lt;@username|user_id&gt; &lt;days&gt; — выдать подписку\n'
        '/revoke &lt;@username|user_id&gt; — отозвать подписку\n'
        '/reset_trial &lt;@username|user_id&gt; — сбросить пробный период\n'
        '/admin_status &lt;@username|user_id&gt; — статус подписки\n'
        '/grant_ref_bonus &lt;referrer&gt; &lt;referred&gt; [days] — начислить реф-бонус\n'
        '/admin_stats — подробная статистика всех пользователей\n'
        '/admin_logout — выйти',
        parse_mode='HTML',
    )


@router.message(Command('grant'))
async def cmd_grant(message: Message, command: CommandObject, bot: Bot):
    if message.from_user.id not in admin_sessions:
        return
    parts = (command.args or '').split()
    if len(parts) != 2:
        await message.answer('Использование: /grant <@username|user_id> <days>')
        return
    target_id = await resolve_user(parts[0])
    if target_id is None:
        await message.answer('Пользователь не найден. Укажи @username или user_id.')
        return
    try:
        days = int(parts[1])
        if days <= 0:
            raise ValueError
    except ValueError:
        await message.answer('days должно быть целым положительным числом.')
        return

    expires_at = int(datetime.now(tz=timezone.utc).timestamp()) + days * 86400
    await upsert_subscription(
        user_id=target_id, is_active=1, expires_at=expires_at,
        plan='admin_grant', charge_id=None, is_recurring=0,
    )
    await message.answer(
        f'✅ {await _display_target(target_id)} выдано {days} дн. '
        f'(до {format_date(expires_at)}).'
    )
    try:
        await bot.send_message(target_id, f'🎁 Вам выдан доступ на {days} дней.')
    except Exception as e:
        logger.warning(f'Could not notify granted user {target_id}: {e}')


@router.message(Command('revoke'))
async def cmd_revoke(message: Message, command: CommandObject):
    if message.from_user.id not in admin_sessions:
        return
    target_id = await resolve_user((command.args or '').strip())
    if target_id is None:
        await message.answer('Пользователь не найден. Укажи @username или user_id.')
        return
    await deactivate_subscription(target_id)
    await message.answer(f'✅ Подписка {await _display_target(target_id)} отозвана.')


@router.message(Command('reset_trial'))
async def cmd_reset_trial(message: Message, command: CommandObject, bot: Bot):
    if message.from_user.id not in admin_sessions:
        return
    target_id = await resolve_user((command.args or '').strip())
    if target_id is None:
        await message.answer('Пользователь не найден. Укажи @username или user_id.')
        return
    await reset_trial(target_id)
    await message.answer(
        f'✅ Пробный период {await _display_target(target_id)} сброшен. '
        f'Текущая подписка снята, он может снова активировать /trial.'
    )
    try:
        await bot.send_message(
            target_id,
            'ℹ️ Ваш пробный период сброшен — можете активировать /trial заново.',
        )
    except Exception as e:
        logger.warning(f'Could not notify user {target_id} about trial reset: {e}')


@router.message(Command('admin_status'))
async def cmd_admin_status(message: Message, command: CommandObject):
    if message.from_user.id not in admin_sessions:
        return
    target_id = await resolve_user((command.args or '').strip())
    if target_id is None:
        await message.answer('Пользователь не найден. Укажи @username или user_id.')
        return
    sub = await get_subscription(target_id)
    if not sub:
        await message.answer(f'У пользователя {target_id} нет подписки.')
        return
    await message.answer(
        f'📋 Подписка {await _display_target(target_id)}:\n'
        f'Активна: {"да" if sub.get("is_active") else "нет"}\n'
        f'Истекает: {format_date(sub.get("expires_at"))}\n'
        f'Тариф: {sub.get("plan")}\n'
        f'Автопродление: {"да" if sub.get("is_recurring") else "нет"}\n'
        f'Триал использован: {"да" if sub.get("trial_used") else "нет"}'
    )


@router.message(Command('grant_ref_bonus'))
async def cmd_grant_ref_bonus(message: Message, command: CommandObject):
    if message.from_user.id not in admin_sessions:
        return
    parts = (command.args or '').split()
    if len(parts) < 2:
        await message.answer(
            'Использование: /grant_ref_bonus <referrer> <referred> [days]'
        )
        return
    referrer_id = await resolve_user(parts[0])
    referred_id = await resolve_user(parts[1])
    if referrer_id is None or referred_id is None:
        await message.answer('Один из пользователей не найден.')
        return
    try:
        bonus_days = int(parts[2]) if len(parts) >= 3 else 7
        if bonus_days <= 0:
            raise ValueError
    except ValueError:
        await message.answer('days должно быть целым положительным числом.')
        return
    new_exp = await grant_referral_bonus(referrer_id, referred_id, bonus_days)
    await message.answer(
        f'✅ Реферу {await _display_target(referrer_id)} начислено {bonus_days} дн. '
        f'(до {format_date(new_exp)}).'
    )


@router.message(Command('admin_stats'))
async def cmd_admin_stats(message: Message):
    if message.from_user.id not in admin_sessions:
        return
    rows = await get_admin_stats()
    total = len(rows)
    if total == 0:
        await message.answer('📊 Пользователей пока нет.')
        return

    active = sum(1 for r in rows if r['subscription'] and r['subscription'].get('is_active'))
    connected = sum(1 for r in rows if r['connected'])

    lines = [
        f'📊 <b>Пользователи бота</b> — всего: {total}',
        f'Подключены: {connected} | Активные подписки: {active}',
        '',
    ]
    for r in rows:
        name = f'@{r["username"]}' if r['username'] else (r['first_name'] or '—')
        sub = r['subscription']
        if sub and sub.get('is_active'):
            exp = sub.get('expires_at')
            plan = sub.get('plan') or '—'
            sub_s = f'✅ {plan} до {format_date(exp)}' if exp else f'✅ {plan} (бессрочно)'
        else:
            sub_s = '—'
        trial = 'да' if sub and sub.get('trial_used') else 'нет'
        conn_s = 'да' if r['connected'] else 'нет'
        line = (
            f'• <code>{r["owner_id"]}</code> {escape(name)}\n'
            f'  подкл: {conn_s} | подписка: {escape(sub_s)}\n'
            f'  триал: {trial} | контактов: {r["contacts"]} | сообщ: {r["total"]} '
            f'(✏️{r["edited"]} 🗑{r["deleted"]}) | рефералов: {r["referrals"]}'
        )
        lines.append(line)

    # Telegram limit is 4096 chars; split if needed, buttons go on the last chunk.
    chunks = []
    chunk = ''
    for line in lines:
        if len(chunk) + len(line) + 1 > 4000:
            chunks.append(chunk)
            chunk = line
        else:
            chunk = (chunk + '\n' + line) if chunk else line
    if chunk:
        chunks.append(chunk)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='➕ Выдать подписку', callback_data='adm:grant'),
            InlineKeyboardButton(text='➖ Отозвать подписку', callback_data='adm:revoke'),
        ],
    ])

    for i, part in enumerate(chunks):
        await message.answer(part, parse_mode='HTML', reply_markup=kb if i == len(chunks) - 1 else None)


@router.message(Command('admin_logout'))
async def cmd_admin_logout(message: Message):
    admin_sessions.discard(message.from_user.id)
    await message.answer('👋 Вы вышли из админ-режима.')


# --------------------------- inline grant/revoke flow ---------------------------

@router.callback_query(F.data == 'adm:grant')
async def cb_adm_grant(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in admin_sessions:
        await callback.answer('Не авторизован', show_alert=True)
        return
    await callback.message.answer('➕ Укажи, кому выдать: `@username 30` или `user_id 30`.')
    await state.set_state(AdminFlow.grant)
    await callback.answer()


@router.callback_query(F.data == 'adm:revoke')
async def cb_adm_revoke(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in admin_sessions:
        await callback.answer('Не авторизован', show_alert=True)
        return
    await callback.message.answer('➖ Укажи, у кого отозвать: `@username` или `user_id`.')
    await state.set_state(AdminFlow.revoke)
    await callback.answer()


@router.message(AdminFlow.grant)
async def on_adm_grant_input(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id not in admin_sessions:
        await state.clear()
        return
    parts = (message.text or '').split()
    if len(parts) != 2:
        await message.answer('Формат: `@username 30` или `user_id 30`.')
        return
    target_id = await resolve_user(parts[0])
    if target_id is None:
        await message.answer('Пользователь не найден. Укажи @username или user_id.')
        return
    try:
        days = int(parts[1])
        if days <= 0:
            raise ValueError
    except ValueError:
        await message.answer('Дни должны быть целым положительным числом.')
        return
    expires_at = int(datetime.now(tz=timezone.utc).timestamp()) + days * 86400
    await upsert_subscription(
        user_id=target_id, is_active=1, expires_at=expires_at,
        plan='admin_grant', charge_id=None, is_recurring=0,
    )
    await message.answer(
        f'✅ {await _display_target(target_id)} выдано {days} дн. '
        f'(до {format_date(expires_at)}).'
    )
    try:
        await bot.send_message(target_id, f'🎁 Вам выдан доступ на {days} дней.')
    except Exception as e:
        logger.warning(f'Could not notify granted user {target_id}: {e}')
    await state.clear()


@router.message(AdminFlow.revoke)
async def on_adm_revoke_input(message: Message, state: FSMContext):
    if message.from_user.id not in admin_sessions:
        await state.clear()
        return
    target_id = await resolve_user((message.text or '').strip())
    if target_id is None:
        await message.answer('Пользователь не найден. Укажи @username или user_id.')
        return
    await deactivate_subscription(target_id)
    await message.answer(f'✅ Подписка {await _display_target(target_id)} отозвана.')
    await state.clear()
