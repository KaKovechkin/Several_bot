"""One-time deploy step: deactivate unlimited test subscriptions.

Deactivates any active subscription with no expiry (expires_at IS NULL) — these
were granted during test mode and would otherwise never lapse. Trial/paid
subscriptions keep their expiry and lapse on their own.

Run before enabling real YooKassa payments:

    python scripts/reset_subscriptions.py
"""
import asyncio

from dotenv import load_dotenv

from app.database.db import init_db, close_db, reset_unlimited_subscriptions


async def main():
    load_dotenv()
    await init_db()
    await reset_unlimited_subscriptions()
    await close_db()
    print('Unlimited test subscriptions deactivated.')


if __name__ == '__main__':
    asyncio.run(main())
