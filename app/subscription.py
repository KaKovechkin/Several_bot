"""Subscription tiers and feature gating.

Payment is NOT implemented — only the structure. `is_premium` reads the
`subscription` flag from user_settings (set manually / by a future payment flow).
"""
from datetime import datetime, timezone

from app.database.db import get_subscription

# Pricing (Telegram Stars) — used for display only
PREMIUM_MONTH_STARS = 120
PREMIUM_YEAR_STARS = 600

# Free tier limits
FREE_HISTORY_DAYS = 7

# Features that require Premium
PREMIUM_FEATURES = {
    'content',        # full message content in notifications/history
    'media',          # media forwarding
    'unlimited_history',
    'keyword_alerts',
    'stats',
    'export',
    'transcription',
    'bookmarks',
}


async def is_subscribed(user_id) -> bool:
    """True if the user has an active, non-expired Stars subscription/trial."""
    sub = await get_subscription(user_id)
    if not sub or not sub.get('is_active'):
        return False
    exp = sub.get('expires_at')
    if exp is None:
        return True
    try:
        return int(exp) >= int(datetime.now(tz=timezone.utc).timestamp())
    except (ValueError, TypeError):
        return True


async def is_premium(owner_id) -> bool:
    # Single source of truth: the `subscriptions` table. Premium == active,
    # non-expired subscription/trial. This makes premium fully resettable for
    # anyone (including the owner) via the admin /revoke command.
    return await is_subscribed(owner_id)
