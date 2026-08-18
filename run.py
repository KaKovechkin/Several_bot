import os
import asyncio
from datetime import datetime, timezone

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.types import ErrorEvent

from app.logger import setup_logging, logger
from app.delivery import send_message_retry
from app.handlers.menu import router as menu_router
from app.handlers.history import router as history_router
from app.handlers.business import router as business_router, _in_quiet
from app.handlers.subscription import router as subscription_router
from app.handlers.admin import router as admin_router
from app.database.db import (
    init_db, close_db, get_owners_with_pending, get_settings,
    pop_pending_notifications, purge_old_messages, vacuum,
    get_expiring_subscriptions, deactivate_subscription,
    get_pending_payments, set_payment_status, upsert_subscription, format_date,
)
from app.payments import is_configured, get_payment, YEAR_SECONDS

DIGEST_INTERVAL = 300          # 5 min — check if quiet window ended
MAINTENANCE_INTERVAL = 86400   # daily DB cleanup
RETENTION_DAYS = 90
SUB_CHECK_INTERVAL = 3600      # hourly: expire/notify lapsed subscriptions
HEARTBEAT_INTERVAL = 300       # ping external uptime monitor every 5 min
PAY_POLL_INTERVAL = 300        # check pending YooKassa payments every 5 min


async def digest_flusher(bot: Bot):
    """Deliver queued quiet-mode notifications once the quiet window ends."""
    while True:
        try:
            for owner_id in await get_owners_with_pending():
                settings = await get_settings(owner_id)
                if settings and _in_quiet(settings):
                    continue
                pending = await pop_pending_notifications(owner_id)
                if pending:
                    await send_message_retry(bot, owner_id, f'🌅 Дайджест ({len(pending)}):')
                    for _, text in pending:
                        try:
                            await send_message_retry(bot, owner_id, text)
                        except Exception as e:
                            logger.warning(f'Digest send failed for {owner_id}: {e}')
        except Exception as e:
            logger.exception(f'digest_flusher error: {e}')
        await asyncio.sleep(DIGEST_INTERVAL)


async def maintenance(bot: Bot):
    """Periodic retention cleanup + VACUUM to keep the DB small."""
    while True:
        await asyncio.sleep(MAINTENANCE_INTERVAL)
        try:
            paths = await purge_old_messages(days=RETENTION_DAYS)
            removed = 0
            for p in paths:
                try:
                    if p and os.path.exists(p):
                        os.remove(p)
                        removed += 1
                except OSError as e:
                    logger.warning(f'Failed to remove media file {p}: {e}')
            await vacuum()
            logger.info(f'DB maintenance done (purge + vacuum, removed {removed} media)')
        except Exception as e:
            logger.exception(f'maintenance error: {e}')


async def subscription_expiry_checker(bot: Bot):
    """Deactivate lapsed subscriptions and notify the users."""
    while True:
        try:
            now = int(datetime.now(tz=timezone.utc).timestamp())
            for user_id, expires_at, plan in await get_expiring_subscriptions(now):
                await deactivate_subscription(user_id)
                try:
                    await send_message_retry(
                        bot, user_id,
                        '⏳ Ваша подписка истекла. Оформить заново: /subscribe',
                    )
                except Exception as e:
                    logger.warning(f'Expiry notice failed for {user_id}: {e}')
        except Exception as e:
            logger.exception(f'subscription_expiry_checker error: {e}')
        await asyncio.sleep(SUB_CHECK_INTERVAL)


async def heartbeat(bot: Bot):
    """Optional uptime monitoring: ping HEALTHCHECK_URL so an external monitor
    (UptimeRobot / Healthchecks.io) can alert the owner if the bot goes down."""
    url = os.getenv('HEALTHCHECK_URL')
    if not url:
        return  # monitoring not configured
    import aiohttp
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    await resp.read()
        except Exception as e:
            logger.warning(f'heartbeat ping failed: {e}')
        await asyncio.sleep(HEARTBEAT_INTERVAL)


async def payment_poller(bot: Bot):
    """Check pending YooKassa payments and activate subscriptions on success."""
    while True:
        await asyncio.sleep(PAY_POLL_INTERVAL)
        if not is_configured():
            continue
        try:
            for payment_id, user_id in await get_pending_payments():
                try:
                    data = await get_payment(payment_id)
                    status = data.get('status')
                    if status == 'succeeded':
                        await set_payment_status(payment_id, 'succeeded')
                        expires_at = int(datetime.now(tz=timezone.utc).timestamp()) + YEAR_SECONDS
                        await upsert_subscription(
                            user_id=user_id, is_active=1, expires_at=expires_at,
                            plan='year', charge_id=payment_id, is_recurring=0,
                        )
                        await send_message_retry(
                            bot, user_id,
                            f'✅ Подписка активирована до {format_date(expires_at)}. Спасибо! 🙌',
                        )
                    elif status in ('canceled',):
                        await set_payment_status(payment_id, status)
                except Exception as e:
                    logger.warning(f'payment_poller error for {payment_id}: {e}')
        except Exception as e:
            logger.exception(f'payment_poller error: {e}')


async def main():
    load_dotenv()
    setup_logging()

    token = os.getenv('TG_TOKEN')
    if not token:
        raise RuntimeError('TG_TOKEN is not set in .env')

    dp = Dispatcher()
    bot = Bot(token=token)

    dp.include_router(admin_router)
    dp.include_router(subscription_router)
    dp.include_router(menu_router)
    dp.include_router(history_router)
    dp.include_router(business_router)

    @dp.error()
    async def error_handler(event: ErrorEvent):
        logger.exception(f'Unhandled update error: {event.exception}')

    dp.shutdown.register(shutdown)

    # Initialise the DB BEFORE starting background tasks — they query the DB
    # immediately and would otherwise hit a None connection (race condition).
    await init_db()
    logger.info('Бот запущен')

    bg = [
        asyncio.create_task(digest_flusher(bot)),
        asyncio.create_task(maintenance(bot)),
        asyncio.create_task(subscription_expiry_checker(bot)),
        asyncio.create_task(heartbeat(bot)),
        asyncio.create_task(payment_poller(bot)),
    ]
    try:
        await dp.start_polling(bot)
    finally:
        for task in bg:
            task.cancel()


async def shutdown(dispatcher: Dispatcher):
    await close_db()
    logger.info('Бот завершил работу')


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info('Бот выключен')
