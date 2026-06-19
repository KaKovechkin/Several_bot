"""Telegram Stars subscriptions: plans, invoices, payments, trial, referrals.

Currency for Stars is always "XTR". Per the Bot API, `subscription_period`
must be exactly 2592000 (30 days) — Telegram has no native yearly recurring
period. So the monthly plan is a real recurring subscription, while the yearly
plan is a one-time invoice whose expiry we track manually.
See https://core.telegram.org/bots/api#sendinvoice and the changelog
https://core.telegram.org/bots/api-changelog
"""
from datetime import datetime, timezone

from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, PreCheckoutQuery,
    InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice,
)

from app.logger import logger
from app.texts import t
from app.keyboards import subscribe_kb
from app.database.db import (
    upsert_subscription, get_subscription, deactivate_subscription,
    mark_trial_used, get_referral_count, get_language, format_date,
)
from app.callbacks import PlanCallback

router = Router()

# Telegram requires subscription_period == 2592000 (30 days) for recurring Stars.
MONTH_SECONDS = 2592000
YEAR_SECONDS = 31536000
TRIAL_DAYS = 7

PLANS = {
    'month': {
        'stars': 60,
        'period_seconds': MONTH_SECONDS,
        'recurring': True,
        'title': 'Sevrax Premium — месяц',
        'label': 'Подписка на месяц',
    },
    'year': {
        'stars': 600,
        'period_seconds': YEAR_SECONDS,
        'recurring': False,  # Stars has no native yearly period → one-time invoice
        'title': 'Sevrax Premium — год',
        'label': 'Подписка на год',
    },
}


def plans_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f'📅 Месяц — {PLANS["month"]["stars"]} ⭐ (автопродление)',
            callback_data=PlanCallback(period='month').pack())],
        [InlineKeyboardButton(
            text=f'🗓 Год — {PLANS["year"]["stars"]} ⭐ (разово)',
            callback_data=PlanCallback(period='year').pack())],
        [InlineKeyboardButton(text='⬅️ Назад', callback_data='nav:back')],
    ])


async def send_plans(message: Message):
    await message.answer(
        '💎 <b>Sevrax Premium</b>\n\n'
        'Полный доступ: содержимое сообщений и медиа, история без ограничений, '
        'алерты по ключевым словам, статистика.\n\n'
        'Выберите тариф:',
        parse_mode='HTML',
        reply_markup=plans_kb(),
    )


@router.message(Command('subscribe'))
async def cmd_subscribe(message: Message):
    try:
        await send_plans(message)
    except Exception as e:
        logger.exception(f'cmd_subscribe error: {e}')


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


@router.callback_query(PlanCallback.filter())
async def cb_choose_plan(callback: CallbackQuery, callback_data: PlanCallback, bot: Bot):
    try:
        period = callback_data.period
        plan = PLANS.get(period)
        if plan is None:
            await callback.answer('Неизвестный тариф.', show_alert=True)
            return
        user_id = callback.from_user.id
        # NOTE: `subscription_period` is only supported by createInvoiceLink (not
        # sendInvoice) and must be exactly 2592000. We build an invoice *link* and
        # present it as a pay button; this works for both recurring and one-time.
        # Stars price is the integer number of Stars (NOT cents) in `amount`.
        kwargs = dict(
            title=plan['title'],
            description='Premium-доступ к Sevrax: удалённые/изменённые сообщения, медиа, статистика.',
            payload=f'sub_{period}_{user_id}',
            currency='XTR',
            prices=[LabeledPrice(label=plan['label'], amount=plan['stars'])],
        )
        if plan['recurring']:
            kwargs['subscription_period'] = MONTH_SECONDS
        link = await bot.create_invoice_link(**kwargs)
        pay_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f'⭐ Оплатить {plan["stars"]} Stars', url=link)],
        ])
        await callback.message.answer(
            f'<b>{plan["title"]}</b>\n{plan["stars"]} ⭐'
            + ('\nСписывается каждые 30 дней (можно отменить через /cancel_subscription).'
               if plan['recurring'] else '\nРазовый платёж на год.'),
            parse_mode='HTML', reply_markup=pay_kb,
        )
        await callback.answer()
    except Exception as e:
        logger.exception(f'cb_choose_plan error: {e}')
        await callback.answer('⚠️ Не удалось создать счёт.', show_alert=True)


@router.pre_checkout_query()
async def on_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    # Must answer within 10 seconds or the payment fails.
    try:
        payload = pre_checkout_query.invoice_payload or ''
        if not payload.startswith('sub_'):
            await pre_checkout_query.answer(ok=False, error_message='Некорректный счёт.')
            return
        await pre_checkout_query.answer(ok=True)
    except Exception as e:
        logger.exception(f'pre_checkout error: {e}')
        try:
            await pre_checkout_query.answer(ok=False, error_message='Временная ошибка, попробуйте позже.')
        except Exception:
            pass


@router.message(F.successful_payment)
async def on_successful_payment(message: Message):
    try:
        sp = message.successful_payment
        user_id = message.from_user.id
        payload = sp.invoice_payload or ''
        parts = payload.split('_')
        period = parts[1] if len(parts) >= 2 else 'month'

        charge_id = sp.telegram_payment_charge_id
        is_recurring = 1 if getattr(sp, 'is_recurring', None) else 0
        expires_at = getattr(sp, 'subscription_expiration_date', None)
        if isinstance(expires_at, datetime):
            expires_at = int(expires_at.timestamp())
        if not expires_at:
            # One-time (yearly) invoice has no expiration date from Telegram.
            secs = PLANS.get(period, {}).get('period_seconds', MONTH_SECONDS)
            expires_at = int(datetime.now(tz=timezone.utc).timestamp()) + secs

        await upsert_subscription(
            user_id=user_id, is_active=1, expires_at=expires_at,
            plan=period, charge_id=charge_id, is_recurring=is_recurring,
        )
        await message.answer(
            f'✅ Подписка активирована до {format_date(expires_at)}.\n'
            f'Спасибо! 🙌'
        )
    except Exception as e:
        logger.exception(f'on_successful_payment error: {e}')
        await message.answer('⚠️ Платёж получен, но возникла ошибка активации. Напишите в поддержку.')


@router.message(Command('cancel_subscription'))
async def cmd_cancel_subscription(message: Message, bot: Bot):
    try:
        user_id = message.from_user.id
        sub = await get_subscription(user_id)
        if not sub or not sub.get('is_active'):
            await message.answer('У вас нет активной подписки.')
            return
        charge_id = sub.get('charge_id')
        if sub.get('is_recurring') and charge_id:
            # Stops auto-renewal; access remains until the current period ends.
            await bot.edit_user_star_subscription(
                user_id=user_id, telegram_payment_charge_id=charge_id, is_canceled=True,
            )
            await upsert_subscription(
                user_id=user_id, is_active=1, expires_at=sub.get('expires_at'),
                plan=sub.get('plan'), charge_id=charge_id, is_recurring=0,
            )
            await message.answer(
                '🔕 Автопродление отключено. Доступ сохранится до '
                f'{format_date(sub.get("expires_at"))}.'
            )
        else:
            await message.answer(
                'Эта подписка не продлевается автоматически — она просто истечёт '
                f'{format_date(sub.get("expires_at"))}.'
            )
    except Exception as e:
        logger.exception(f'cmd_cancel_subscription error: {e}')
        await message.answer('⚠️ Не удалось отменить подписку.')


@router.message(Command('trial'))
async def cmd_trial(message: Message):
    try:
        user_id = message.from_user.id
        sub = await get_subscription(user_id)
        if sub and sub.get('trial_used'):
            await message.answer('Пробный период уже был использован.')
            return
        expires_at = int(datetime.now(tz=timezone.utc).timestamp()) + TRIAL_DAYS * 86400
        await upsert_subscription(
            user_id=user_id, is_active=1, expires_at=expires_at,
            plan='trial', charge_id=None, is_recurring=0,
        )
        await mark_trial_used(user_id)
        await message.answer(
            f'🎁 Пробный период на {TRIAL_DAYS} дней активирован '
            f'(до {format_date(expires_at)}).'
        )
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
