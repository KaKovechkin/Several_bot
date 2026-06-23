"""In-bot admin panel (login by password) for manual subscription management.

Security notes:
- ADMIN_PASSWORD lives only in .env, never hardcoded, never logged.
- Password comparison uses secrets.compare_digest (constant-time).
- ADMIN_IDS is a sanity-check allowlist of user_ids permitted to even attempt
  login. Login state is kept in process memory only.
"""
import os
import secrets
from datetime import datetime, timezone

from aiogram import Router, Bot
from aiogram.filters import Command, CommandObject

from aiogram.types import Message

from app.logger import logger
from app.database.db import (
    upsert_subscription, deactivate_subscription, get_subscription,
    grant_referral_bonus, reset_trial, format_date, get_all_owners,
)

router = Router()

# user_ids currently authenticated as admin (process memory only).
admin_sessions: set[int] = set()


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
            '/grant_ref_bonus, /admin_help, /admin_logout'
        )
    else:
        await message.answer('Неверный пароль')


@router.message(Command('admin_help'))
async def cmd_admin_help(message: Message):
    if message.from_user.id not in admin_sessions:
        return
    await message.answer(
        '🛠 <b>Админ-команды</b>\n'
        '/grant &lt;user_id&gt; &lt;days&gt; — выдать подписку\n'
        '/revoke &lt;user_id&gt; — отозвать подписку\n'
        '/reset_trial &lt;user_id&gt; — сбросить пробный период\n'
        '/admin_status &lt;user_id&gt; — статус подписки\n'
        '/grant_ref_bonus &lt;referrer_id&gt; &lt;referred_id&gt; — начислить реф-бонус\n'
        '/admin_stats — список всех пользователей с бизнес-подключением\n'
        '/admin_logout — выйти',
        parse_mode='HTML',
    )


@router.message(Command('grant'))
async def cmd_grant(message: Message, command: CommandObject, bot: Bot):
    if message.from_user.id not in admin_sessions:
        return
    parts = (command.args or '').split()
    if len(parts) != 2:
        await message.answer('Использование: /grant <user_id> <days>')
        return
    try:
        target_id = int(parts[0])
        days = int(parts[1])
        if days <= 0:
            raise ValueError
    except ValueError:
        await message.answer('user_id и days должны быть целыми положительными числами.')
        return

    expires_at = int(datetime.now(tz=timezone.utc).timestamp()) + days * 86400
    await upsert_subscription(
        user_id=target_id, is_active=1, expires_at=expires_at,
        plan='admin_grant', charge_id=None, is_recurring=0,
    )
    await message.answer(
        f'✅ Пользователю {target_id} выдан доступ на {days} дн. '
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
    arg = (command.args or '').strip()
    try:
        target_id = int(arg)
    except ValueError:
        await message.answer('Использование: /revoke <user_id>')
        return
    await deactivate_subscription(target_id)
    await message.answer(f'✅ Подписка пользователя {target_id} отозвана.')


@router.message(Command('reset_trial'))
async def cmd_reset_trial(message: Message, command: CommandObject, bot: Bot):
    if message.from_user.id not in admin_sessions:
        return
    arg = (command.args or '').strip()
    try:
        target_id = int(arg)
    except ValueError:
        await message.answer('Использование: /reset_trial <user_id>')
        return
    await reset_trial(target_id)
    await message.answer(
        f'✅ Пробный период пользователя {target_id} сброшен. '
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
    arg = (command.args or '').strip()
    try:
        target_id = int(arg)
    except ValueError:
        await message.answer('Использование: /admin_status <user_id>')
        return
    sub = await get_subscription(target_id)
    if not sub:
        await message.answer(f'У пользователя {target_id} нет подписки.')
        return
    await message.answer(
        f'📋 Подписка {target_id}:\n'
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
        await message.answer('Использование: /grant_ref_bonus <referrer_id> <referred_id> [days]')
        return
    try:
        referrer_id = int(parts[0])
        referred_id = int(parts[1])
        bonus_days = int(parts[2]) if len(parts) >= 3 else 7
        if bonus_days <= 0:
            raise ValueError
    except ValueError:
        await message.answer('id и days должны быть целыми положительными числами.')
        return
    new_exp = await grant_referral_bonus(referrer_id, referred_id, bonus_days)
    await message.answer(
        f'✅ Реферу {referrer_id} начислено {bonus_days} дн. '
        f'(до {format_date(new_exp)}).'
    )


@router.message(Command('admin_stats'))
async def cmd_admin_stats(message: Message):
    if message.from_user.id not in admin_sessions:
        return
    owners = await get_all_owners()
    total = len(owners)
    if total == 0:
        await message.answer('📊 Пользователей с бизнес-подключением: 0')
        return

    lines = [f'📊 <b>Пользователи бота</b> — всего: {total}\n']
    for owner_id, username, first_name in owners:
        name_part = f'@{username}' if username else (first_name or '—')
        lines.append(f'• <code>{owner_id}</code> {name_part}')

    # Telegram limit is 4096 chars; split if needed.
    chunk, chunks = '', []
    for line in lines:
        if len(chunk) + len(line) + 1 > 4000:
            chunks.append(chunk)
            chunk = line
        else:
            chunk = (chunk + '\n' + line) if chunk else line
    if chunk:
        chunks.append(chunk)

    for part in chunks:
        await message.answer(part, parse_mode='HTML')


@router.message(Command('admin_logout'))
async def cmd_admin_logout(message: Message):
    admin_sessions.discard(message.from_user.id)
    await message.answer('👋 Вы вышли из админ-режима.')
