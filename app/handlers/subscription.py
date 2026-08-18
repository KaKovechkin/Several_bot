"""YooKassa subscriptions: one-time yearly plan (500 ₽ / year).

Payment is created as a YooKassa redirect; confirmation is checked on demand via
the «Я оплатил» button plus a background poller (see run.py). A 7-day free trial
and referrals remain.
"""
from datetime import datetime, timezone

from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
)

from app.logger import logger
from app.texts import t
from app.keyboards import subscribe_kb
from app.database.db import (
    upsert_subscription, get_subscription, mark_trial_used, get_referral_count,
    get_language, format_date, save_payment, set_payment_status,
)
from app.callbacks import PayCheck
from app.payments import (
    create_payment, get_payment, is_configured, PRICE_RUB, YEAR_SECONDS,
)

router = Router()

TRIAL_DAYS = 7


def plans_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f'💎 Оплатить {PRICE_RUB} ₽ / год', callback_data='pay_year')],
        [InlineKeyboardButton(text='🎁 Пробный период 7 дней', callback_data='start_trial')],
        [InlineKeyboardButton(text='⬅️ Назад', callback_data='nav:back')],
    ])


async def send_plans(message: Message):
    await message.answer(
        '💎 <b>Sevrax Premium</b>\n\n'
        'Полный доступ: содержимое сообщений и медиа, история без ограничений, '
        'алерты по ключевым словам, статистика.\n\n'
        f'Тариф: <b>{PRICE_RUB} ₽ / год</b> (разово).\n'
        f'Новый пользователь может активировать бесплатный пробный период на {TRIAL_DAYS} дней.',
        parse_mode='HTML',
        reply_markup=plans_kb(),
    )


async def _grant_trial(user_id: int) -> str:
    """Activate the 7-day trial. Returns a user-facing confirmation message."""
    expires_at = int(datetime.now(tz=timezone.utc).timestamp()) + TRIAL_DAYS * 86400
    await upsert_subscription(
        user_id=user_id, is_active=1, expires_at=expires_at,
        plan='trial', charge_id=None, is_recurring=0,
    )
    await mark_trial_used(user_id)
    return f'🎁 Пробный период на {TRIAL_DAYS} дней активирован (до {format_date(expires_at)}).'


@router.message(Command('subscribe'))
async def cmd_subscribe(message: Message):
    try:
        await send_plans(message)
    except Exception as e:
        logger.exception(f'cmd_subscribe error: {e}')


@router.callback_query(F.data == 'start_trial')
async def cb_start_trial(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id
        sub = await get_subscription(user_id)
        if sub and sub.get('trial_used'):
            await callback.answer('Пробный период уже был использован.', show_alert=True)
            return
        text = await _grant_trial(user_id)
        await callback.message.answer(text)
        await callback.answer()
    except Exception as e:
        logger.exception(f'cb_start_trial error: {e}')
        await callback.answer('⚠️ Не удалось активировать пробный период.', show_alert=True)


@router.callback_query(F.data == 'pay_year')
async def cb_pay_year(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    if not is_configured():
        await callback.message.answer(
            '💳 Оплата подключится через несколько дней.\n'
            'Пока можно активировать бесплатный пробный период: /trial'
        )
        await callback.answer()
        return
    try:
        me = await bot.get_me()
        return_url = f'https://t.me/{me.username}'
        data = await create_payment(user_id, return_url=return_url)
    except Exception as e:
        logger.exception(f'cb_pay_year error: {e}')
        await callback.answer('⚠️ Не удалось создать платёж. Попробуйте позже.', show_alert=True)
        return

    payment_id = data['id']
    confirmation_url = data['confirmation']['confirmation_url']
    await save_payment(payment_id, user_id, 'pending')
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='💳 Перейти к оплате', url=confirmation_url)],
        [InlineKeyboardButton(text='✅ Я оплатил', callback_data=PayCheck(payment_id=payment_id).pack())],
    ])
    await callback.message.answer(
        f'💳 Для активации Premium оплатите {PRICE_RUB} ₽:\n\n'
        f'После оплаты нажмите «✅ Я оплатил».',
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(PayCheck.filter())
async def cb_check_payment(callback: CallbackQuery, callback_data: PayCheck):
    user_id = callback.from_user.id
    payment_id = callback_data.payment_id
    try:
        data = await get_payment(payment_id)
        status = data.get('status')
    except Exception as e:
        logger.exception(f'cb_check_payment error: {e}')
        await callback.answer('⚠️ Не удалось проверить платёж, попробуйте позже.', show_alert=True)
        return

    if status == 'succeeded':
        await set_payment_status(payment_id, 'succeeded')
        expires_at = int(datetime.now(tz=timezone.utc).timestamp()) + YEAR_SECONDS
        await upsert_subscription(
            user_id=user_id, is_active=1, expires_at=expires_at,
            plan='year', charge_id=payment_id, is_recurring=0,
        )
        await callback.message.answer(
            f'✅ Подписка активирована до {format_date(expires_at)}. Спасибо! 🙌'
        )
    elif status == 'pending':
        await callback.answer('Платёж ещё не подтверждён. Нажмите «✅ Я оплатил» ещё раз через минуту.', show_alert=True)
    else:
        await set_payment_status(payment_id, status)
        await callback.answer('Платёж не прошёл. Попробуйте оформить заново.', show_alert=True)
    await callback.answer()


@router.callback_query(F.data == 'show_locked')
async def cb_show_locked(callback: CallbackQuery):
    """Free user tapped «show message» on a notification — prompt to subscribe."""
    try:
        lang = await get_language(callback.from_user.id)
        await callback.message.answer(
            t(lang, 'premium_only'), parse_mode='HTML', reply_markup=subscribe_kb(lang),
        )
        await callback.answer()
    except Exception as e:
        logger.exception(f'cb_show_locked error: {e}')
        await callback.answer('💎 Доступно по подписке: /subscribe', show_alert=True)


@router.callback_query(F.data == 'open_subscribe')
async def cb_open_subscribe(callback: CallbackQuery):
    try:
        await send_plans(callback.message)
        await callback.answer()
    except Exception as e:
        logger.exception(f'cb_open_subscribe error: {e}')
        await callback.answer('⚠️ Не удалось открыть тарифы.', show_alert=True)


@router.message(Command('trial'))
async def cmd_trial(message: Message):
    try:
        user_id = message.from_user.id
        sub = await get_subscription(user_id)
        if sub and sub.get('trial_used'):
            await message.answer('Пробный период уже был использован.')
            return
        text = await _grant_trial(user_id)
        await message.answer(text)
    except Exception as e:
        logger.exception(f'cmd_trial error: {e}')
        await message.answer('⚠️ Не удалось активировать пробный период.')


@router.message(Command('myref'))
async def cmd_myref(message: Message, bot: Bot):
    try:
        user_id = message.from_user.id
        me = await bot.get_me()
        link = f'https://t.me/{me.username}?start=ref_{user_id}'
        count = await get_referral_count(user_id)
        await message.answer(
            '🔗 <b>Ваша реферальная ссылка:</b>\n'
            f'<code>{link}</code>\n\n'
            f'👥 Приглашено: <b>{count}</b>',
            parse_mode='HTML',
        )
    except Exception as e:
        logger.exception(f'cmd_myref error: {e}')
        await message.answer('⚠️ Не удалось получить реферальную информацию.')
