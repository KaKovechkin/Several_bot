import os
import aiosqlite
from datetime import datetime, timezone, timedelta


db_connection = None

# Path is configurable so Docker can point it at a mounted volume.
DB_PATH = os.getenv('DB_PATH', 'messages.db')

# Moscow time (UTC+3) for all dates shown to the user.
MSK = timezone(timedelta(hours=3))


MONTHS_RU = [
    '', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'
]


def format_date(date) -> str:
    """Converts a date/datetime/timestamp to '16 июня 16:43' in Moscow time."""
    if date is None:
        return '—'
    if isinstance(date, (int, float)):
        dt = datetime.fromtimestamp(date, tz=timezone.utc)
    elif isinstance(date, str):
        try:
            dt = datetime.fromisoformat(date)
        except ValueError:
            return str(date)
    elif isinstance(date, datetime):
        dt = date
    else:
        return str(date)
    # Assume naive datetimes are UTC, then convert to Moscow time.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(MSK)
    return f'{dt.day} {MONTHS_RU[dt.month]} {dt.hour:02d}:{dt.minute:02d}'


async def init_db():
    global db_connection
    db_connection = await aiosqlite.connect(DB_PATH)
    await db_connection.execute("""CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    business_connection_id TEXT,
    message_id INTEGER,
    file_id TEXT,
    type_message TEXT,
    from_user_id INTEGER,
    text TEXT,
    date INTEGER,
    is_deleted INTEGER,
    first_name TEXT,
    username TEXT,
    is_edited INTEGER DEFAULT 0,
    owner_id INTEGER,
    deleted_at INTEGER
    )""")
    await db_connection.execute("""CREATE TABLE IF NOT EXISTS connections (
        owner_id TEXT,
        business_connection_id TEXT,
        UNIQUE(owner_id)
        )""")
    await db_connection.execute("""CREATE TABLE IF NOT EXISTS message_edits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        message_id INTEGER,
        old_text TEXT,
        new_text TEXT,
        edited_at INTEGER
        )""")
    await db_connection.execute("""CREATE TABLE IF NOT EXISTS user_settings (
        owner_id TEXT PRIMARY KEY,
        language TEXT DEFAULT 'ru',
        quiet_enabled INTEGER DEFAULT 0,
        quiet_start INTEGER DEFAULT 23,
        quiet_end INTEGER DEFAULT 8,
        subscription TEXT DEFAULT 'free',
        sub_until INTEGER
        )""")
    await db_connection.execute("""CREATE TABLE IF NOT EXISTS keywords (
        owner_id TEXT,
        word TEXT,
        UNIQUE(owner_id, word)
        )""")
    await db_connection.execute("""CREATE TABLE IF NOT EXISTS bookmarks (
        owner_id TEXT,
        message_db_id INTEGER,
        UNIQUE(owner_id, message_db_id)
        )""")
    await db_connection.execute("""CREATE TABLE IF NOT EXISTS pending_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id TEXT,
        text TEXT,
        created_at INTEGER
        )""")
    await db_connection.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
        user_id INTEGER PRIMARY KEY,
        is_active INTEGER DEFAULT 0,
        expires_at INTEGER,
        plan TEXT,
        charge_id TEXT,
        is_recurring INTEGER DEFAULT 0,
        trial_used INTEGER DEFAULT 0
        )""")
    await db_connection.execute("""CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER,
        referred_id INTEGER,
        created_at INTEGER,
        bonus_granted INTEGER DEFAULT 0,
        UNIQUE(referred_id)
        )""")
    await db_connection.execute("""CREATE TABLE IF NOT EXISTS owners (
        owner_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        connected_at INTEGER,
        last_seen INTEGER
        )""")
    await db_connection.execute("""CREATE TABLE IF NOT EXISTS yoo_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payment_id TEXT UNIQUE,
        user_id INTEGER,
        status TEXT,
        created_at INTEGER
        )""")
    # Indexes for frequently queried fields
    await db_connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages (chat_id)"
    )
    await db_connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_message_id ON messages (message_id)"
    )
    await db_connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_from_user_id ON messages (from_user_id)"
    )
    await db_connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_biz_conn ON messages (business_connection_id)"
    )
    await db_connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_owner_id ON messages (owner_id)"
    )
    # Migration: add local_path column for downloaded media if missing.
    cursor = await db_connection.execute("PRAGMA table_info(messages)")
    cols = [r[1] for r in await cursor.fetchall()]
    if 'local_path' not in cols:
        await db_connection.execute("ALTER TABLE messages ADD COLUMN local_path TEXT")
    if 'owner_id' not in cols:
        await db_connection.execute("ALTER TABLE messages ADD COLUMN owner_id INTEGER")
        # Backfill owner_id from the connections map so pre-existing messages
        # remain visible in history after the switch to owner_id-based queries.
        await db_connection.execute('''
            UPDATE messages SET owner_id = (
                SELECT CAST(c.owner_id AS INTEGER) FROM connections c
                WHERE c.business_connection_id = messages.business_connection_id
            ) WHERE owner_id IS NULL AND business_connection_id IS NOT NULL
        ''')
    if 'deleted_at' not in cols:
        await db_connection.execute("ALTER TABLE messages ADD COLUMN deleted_at INTEGER")
    # Migration: add trial_used to subscriptions if an older table exists without it.
    cursor = await db_connection.execute("PRAGMA table_info(subscriptions)")
    sub_cols = [r[1] for r in await cursor.fetchall()]
    if 'trial_used' not in sub_cols:
        await db_connection.execute("ALTER TABLE subscriptions ADD COLUMN trial_used INTEGER DEFAULT 0")
    # One-time deploy step: deactivate unlimited test subscriptions (granted
    # during test mode, expires_at IS NULL — they would never lapse on their
    # own). Runs once, marked in app_meta so it is not repeated.
    await db_connection.execute(
        "CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    cursor = await db_connection.execute(
        "SELECT value FROM app_meta WHERE key = 'subs_reset_done'"
    )
    if await cursor.fetchone() is None:
        await reset_unlimited_subscriptions()
        now = int(datetime.now(tz=timezone.utc).timestamp())
        await db_connection.execute(
            "INSERT INTO app_meta (key, value) VALUES ('subs_reset_done', ?)",
            (str(now),),
        )
    await db_connection.commit()


async def close_db():
    global db_connection
    await db_connection.close()


async def save_message(chat_id, business_connection_id, message_id, file_id, type_message, from_user_id, text, date, first_name, username, local_path=None, owner_id=None):
    await db_connection.execute('''
        INSERT INTO messages (chat_id, business_connection_id, message_id, file_id, type_message, from_user_id, text, date, first_name, username, is_deleted, local_path, owner_id)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (chat_id, business_connection_id, message_id, file_id, type_message, from_user_id, text, date, first_name, username, 0, local_path, owner_id))
    await db_connection.commit()


async def mark_deleted(message_id, chat_id):
    now = int(datetime.now(tz=timezone.utc).timestamp())
    await db_connection.execute('''
        UPDATE messages SET is_deleted = 1, deleted_at = ? WHERE chat_id = ? AND message_id = ?
    ''', (now, chat_id, message_id))
    await db_connection.commit()


async def message_update(text, chat_id, message_id, is_edited):
    # Save old text to edit history before overwriting
    cursor = await db_connection.execute(
        'SELECT text FROM messages WHERE chat_id = ? AND message_id = ?',
        (chat_id, message_id)
    )
    row = await cursor.fetchone()
    if row:
        old_text = row[0]
        now = int(datetime.now(tz=timezone.utc).timestamp())
        await db_connection.execute('''
            INSERT INTO message_edits (chat_id, message_id, old_text, new_text, edited_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (chat_id, message_id, old_text, text, now))
    await db_connection.execute('''
        UPDATE messages SET text = ?, is_edited = ? WHERE chat_id = ? AND message_id = ?
    ''', (text, is_edited, chat_id, message_id))
    await db_connection.commit()


async def get_message(chat_id, message_id):
    cursor = await db_connection.execute('''
        SELECT text, username, file_id, type_message, local_path FROM messages WHERE chat_id = ? AND message_id = ?
    ''', (chat_id, message_id))
    row = await cursor.fetchone()
    return row


async def get_list_usernames(business_connection_id):
    cursor = await db_connection.execute('''
        SELECT DISTINCT username, from_user_id, first_name FROM messages WHERE business_connection_id = ?
    ''', (business_connection_id,))
    row = await cursor.fetchall()
    return row


async def save_connection(owner_id, business_connection_id):
    # Telegram issues a NEW business_connection_id whenever the bot is
    # reconnected, so we must update the stored id, not ignore the new one.
    await db_connection.execute("""
        INSERT INTO connections (owner_id, business_connection_id)
        VALUES(?, ?)
        ON CONFLICT(owner_id) DO UPDATE SET
            business_connection_id = excluded.business_connection_id
    """, (str(owner_id), business_connection_id))
    await db_connection.commit()


async def get_connection(owner_id):
    cursor = await db_connection.execute('''
        SELECT business_connection_id FROM connections WHERE owner_id = ?
    ''', (owner_id,))
    row = await cursor.fetchone()
    return row


async def get_owner_by_connection(business_connection_id):
    cursor = await db_connection.execute('''
        SELECT owner_id FROM connections WHERE business_connection_id = ?
    ''', (business_connection_id,))
    row = await cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else None


# ----------------------------- owners (profiles) -----------------------------

async def upsert_owner(owner_id, username=None, first_name=None):
    now = int(datetime.now(tz=timezone.utc).timestamp())
    await db_connection.execute('''
        INSERT INTO owners (owner_id, username, first_name, connected_at, last_seen)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(owner_id) DO UPDATE SET
            username = COALESCE(NULLIF(excluded.username, ''), owners.username),
            first_name = COALESCE(NULLIF(excluded.first_name, ''), owners.first_name),
            last_seen = excluded.last_seen
    ''', (int(owner_id), username, first_name, now, now))
    await db_connection.commit()


async def find_owner_by_username(username):
    if not username:
        return None
    u = username.lower().lstrip('@')
    cursor = await db_connection.execute(
        'SELECT owner_id FROM owners WHERE LOWER(username) = ?', (u,)
    )
    row = await cursor.fetchone()
    return int(row[0]) if row else None


async def get_owner_profile(owner_id):
    cursor = await db_connection.execute(
        'SELECT owner_id, username, first_name FROM owners WHERE owner_id = ?',
        (int(owner_id),)
    )
    return await cursor.fetchone()


async def get_connections_map():
    cursor = await db_connection.execute(
        'SELECT owner_id, business_connection_id FROM connections'
    )
    return {int(r[0]): r[1] for r in await cursor.fetchall() if r[0] is not None}


async def get_update_message(business_connection_id, from_user_id):
    cursor = await db_connection.execute('''
        SELECT text, is_edited, is_deleted, date, file_id, type_message, message_id, chat_id
        FROM messages
        WHERE business_connection_id = ? AND from_user_id = ? AND (is_edited = 1 OR is_deleted = 1)
    ''', (business_connection_id, from_user_id))
    row = await cursor.fetchall()
    return row


async def get_user_stats(owner_id, from_user_id):
    cursor = await db_connection.execute('''
        SELECT
            COUNT(*) AS total,
            SUM(is_deleted) AS deleted,
            SUM(is_edited) AS edited
        FROM messages
        WHERE owner_id = ? AND from_user_id = ?
    ''', (owner_id, from_user_id))
    row = await cursor.fetchone()
    return row


async def get_edit_history(chat_id, message_id):
    cursor = await db_connection.execute('''
        SELECT old_text, new_text, edited_at FROM message_edits
        WHERE chat_id = ? AND message_id = ?
        ORDER BY edited_at ASC
    ''', (chat_id, message_id))
    rows = await cursor.fetchall()
    return rows


# ----------------------------- settings -----------------------------

async def get_settings(owner_id):
    cursor = await db_connection.execute('''
        SELECT language, quiet_enabled, quiet_start, quiet_end, subscription, sub_until
        FROM user_settings WHERE owner_id = ?
    ''', (str(owner_id),))
    row = await cursor.fetchone()
    if row is None:
        return None
    return {
        'language': row[0],
        'quiet_enabled': row[1],
        'quiet_start': row[2],
        'quiet_end': row[3],
        'subscription': row[4],
        'sub_until': row[5],
    }


async def ensure_settings(owner_id):
    await db_connection.execute(
        'INSERT OR IGNORE INTO user_settings (owner_id) VALUES (?)',
        (str(owner_id),)
    )
    await db_connection.commit()
    return await get_settings(owner_id)


async def update_setting(owner_id, field, value):
    allowed = {'language', 'quiet_enabled', 'quiet_start', 'quiet_end', 'subscription', 'sub_until'}
    if field not in allowed:
        raise ValueError(f'Unknown setting field: {field}')
    await ensure_settings(owner_id)
    await db_connection.execute(
        f'UPDATE user_settings SET {field} = ? WHERE owner_id = ?',
        (value, str(owner_id))
    )
    await db_connection.commit()


async def get_language(owner_id) -> str:
    settings = await get_settings(owner_id)
    return settings['language'] if settings else 'ru'


# ----------------------------- keywords -----------------------------

async def add_keyword(owner_id, word):
    await db_connection.execute(
        'INSERT OR IGNORE INTO keywords (owner_id, word) VALUES (?, ?)',
        (str(owner_id), word.lower().strip())
    )
    await db_connection.commit()


async def remove_keyword(owner_id, word):
    await db_connection.execute(
        'DELETE FROM keywords WHERE owner_id = ? AND word = ?',
        (str(owner_id), word.lower().strip())
    )
    await db_connection.commit()


async def get_keywords(owner_id):
    cursor = await db_connection.execute(
        'SELECT word FROM keywords WHERE owner_id = ?', (str(owner_id),)
    )
    rows = await cursor.fetchall()
    return [r[0] for r in rows]


# ----------------------------- bookmarks -----------------------------

async def add_bookmark(owner_id, message_db_id):
    await db_connection.execute(
        'INSERT OR IGNORE INTO bookmarks (owner_id, message_db_id) VALUES (?, ?)',
        (str(owner_id), message_db_id)
    )
    await db_connection.commit()


async def get_bookmarks(owner_id):
    cursor = await db_connection.execute('''
        SELECT m.id, m.text, m.type_message, m.file_id, m.date, m.username, m.first_name
        FROM bookmarks b JOIN messages m ON m.id = b.message_db_id
        WHERE b.owner_id = ?
        ORDER BY m.date DESC
    ''', (str(owner_id),))
    return await cursor.fetchall()


# ----------------------------- contacts & stats -----------------------------

async def get_contacts_with_counts(owner_id):
    """List of contacts with counts of edited/deleted messages, excluding the owner."""
    cursor = await db_connection.execute('''
        SELECT from_user_id,
               MAX(username) AS username,
               MAX(first_name) AS first_name,
               COUNT(*) AS total,
               SUM(is_edited) AS edited,
               SUM(is_deleted) AS deleted
        FROM messages
        WHERE owner_id = ? AND from_user_id != ?
        GROUP BY from_user_id
        ORDER BY (SUM(is_edited) + SUM(is_deleted)) DESC
    ''', (owner_id, owner_id))
    return await cursor.fetchall()


async def get_top_deleters(owner_id, limit=5):
    cursor = await db_connection.execute('''
        SELECT MAX(username), MAX(first_name), from_user_id, SUM(is_deleted) AS deleted
        FROM messages WHERE owner_id = ?
        GROUP BY from_user_id HAVING deleted > 0
        ORDER BY deleted DESC LIMIT ?
    ''', (owner_id, limit))
    return await cursor.fetchall()


async def get_top_editors(owner_id, limit=5):
    cursor = await db_connection.execute('''
        SELECT MAX(username), MAX(first_name), from_user_id, SUM(is_edited) AS edited
        FROM messages WHERE owner_id = ?
        GROUP BY from_user_id HAVING edited > 0
        ORDER BY edited DESC LIMIT ?
    ''', (owner_id, limit))
    return await cursor.fetchall()


async def get_deletion_hours(owner_id):
    """Rows of (hour, count) for deleted messages, by deletion timestamp (MSK)."""
    cursor = await db_connection.execute('''
        SELECT CAST(strftime('%H', datetime(deleted_at, 'unixepoch', '+3 hours')) AS INTEGER) AS hour,
               COUNT(*) AS cnt
        FROM messages
        WHERE owner_id = ? AND is_deleted = 1 AND deleted_at IS NOT NULL
        GROUP BY hour ORDER BY cnt DESC
    ''', (owner_id,))
    return await cursor.fetchall()


async def get_filtered_messages(owner_id, from_user_id, mode='all', query=None):
    """mode: 'all' | 'deleted' | 'edited'. query: optional substring search."""
    sql = '''
        SELECT id, text, is_edited, is_deleted, date, file_id, type_message, message_id, chat_id, local_path
        FROM messages
        WHERE owner_id = ? AND from_user_id = ?
    '''
    params = [owner_id, from_user_id]
    if mode == 'deleted':
        sql += ' AND is_deleted = 1'
    elif mode == 'edited':
        sql += ' AND is_edited = 1'
    else:
        sql += ' AND (is_edited = 1 OR is_deleted = 1)'
    if query:
        sql += ' AND text LIKE ?'
        params.append(f'%{query}%')
    sql += ' ORDER BY date DESC'
    cursor = await db_connection.execute(sql, tuple(params))
    return await cursor.fetchall()


# ----------------------------- quiet-mode digest -----------------------------

async def queue_notification(owner_id, text):
    now = int(datetime.now(tz=timezone.utc).timestamp())
    await db_connection.execute(
        'INSERT INTO pending_notifications (owner_id, text, created_at) VALUES (?, ?, ?)',
        (str(owner_id), text, now)
    )
    await db_connection.commit()


async def pop_pending_notifications(owner_id):
    cursor = await db_connection.execute(
        'SELECT id, text FROM pending_notifications WHERE owner_id = ? ORDER BY created_at',
        (str(owner_id),)
    )
    rows = await cursor.fetchall()
    if rows:
        await db_connection.execute(
            'DELETE FROM pending_notifications WHERE owner_id = ?', (str(owner_id),)
        )
        await db_connection.commit()
    return rows


async def get_owners_with_pending():
    cursor = await db_connection.execute(
        'SELECT DISTINCT owner_id FROM pending_notifications'
    )
    return [r[0] for r in await cursor.fetchall()]


# ----------------------------- maintenance -----------------------------

async def enforce_user_limit(owner_id, from_user_id, limit=1000):
    """Keep only the newest `limit` messages per user; drop the oldest.

    Returns the local media paths of the dropped rows so the caller can delete
    the files from disk.
    """
    cursor = await db_connection.execute('''
        SELECT id, local_path FROM messages
        WHERE owner_id = ? AND from_user_id = ?
        ORDER BY date DESC
        LIMIT -1 OFFSET ?
    ''', (owner_id, from_user_id, limit))
    rows = await cursor.fetchall()
    ids = [r[0] for r in rows]
    paths = [r[1] for r in rows if r[1]]
    if ids:
        await db_connection.executemany(
            'DELETE FROM messages WHERE id = ?', [(i,) for i in ids]
        )
    await db_connection.commit()
    return paths


async def purge_old_messages(days=30):
    """Delete messages older than `days` (by stored date timestamp).

    Also removes orphaned edit history and bookmarks. Returns local media paths
    so the caller can delete the files from disk.
    """
    cutoff = int(datetime.now(tz=timezone.utc).timestamp()) - days * 86400
    cursor = await db_connection.execute(
        'SELECT chat_id, message_id, local_path FROM messages WHERE date < ?', (cutoff,)
    )
    rows = await cursor.fetchall()
    paths = [r[2] for r in rows if r[2]]
    for chat_id, message_id, _ in rows:
        await db_connection.execute(
            'DELETE FROM message_edits WHERE chat_id = ? AND message_id = ?',
            (chat_id, message_id)
        )
    await db_connection.execute('DELETE FROM messages WHERE date < ?', (cutoff,))
    await db_connection.execute(
        'DELETE FROM bookmarks WHERE message_db_id NOT IN (SELECT id FROM messages)'
    )
    await db_connection.commit()
    return paths


async def vacuum():
    await db_connection.execute('VACUUM')
    await db_connection.commit()


# ----------------------------- subscriptions (Telegram Stars) -----------------------------

async def upsert_subscription(user_id, is_active, expires_at, plan, charge_id, is_recurring):
    """Create or replace a subscription row. Preserves trial_used across replaces."""
    await db_connection.execute('''
        INSERT OR REPLACE INTO subscriptions
            (user_id, is_active, expires_at, plan, charge_id, is_recurring, trial_used)
        VALUES (?, ?, ?, ?, ?, ?,
                COALESCE((SELECT trial_used FROM subscriptions WHERE user_id = ?), 0))
    ''', (user_id, is_active, expires_at, plan, charge_id, is_recurring, user_id))
    await db_connection.commit()


async def get_subscription(user_id):
    cursor = await db_connection.execute('''
        SELECT user_id, is_active, expires_at, plan, charge_id, is_recurring, trial_used
        FROM subscriptions WHERE user_id = ?
    ''', (user_id,))
    row = await cursor.fetchone()
    if row is None:
        return None
    return {
        'user_id': row[0],
        'is_active': row[1],
        'expires_at': row[2],
        'plan': row[3],
        'charge_id': row[4],
        'is_recurring': row[5],
        'trial_used': row[6],
    }


async def deactivate_subscription(user_id):
    await db_connection.execute(
        'UPDATE subscriptions SET is_active = 0 WHERE user_id = ?', (user_id,)
    )
    await db_connection.commit()


async def get_expiring_subscriptions(before_timestamp):
    """Active subscriptions whose expires_at is already in the past."""
    cursor = await db_connection.execute('''
        SELECT user_id, expires_at, plan FROM subscriptions
        WHERE is_active = 1 AND expires_at IS NOT NULL AND expires_at < ?
    ''', (before_timestamp,))
    return await cursor.fetchall()


async def mark_trial_used(user_id):
    await db_connection.execute('''
        INSERT INTO subscriptions (user_id, trial_used) VALUES (?, 1)
        ON CONFLICT(user_id) DO UPDATE SET trial_used = 1
    ''', (user_id,))
    await db_connection.commit()


async def reset_trial(user_id):
    """Deactivate the subscription and clear trial_used so the user can take
    the free trial again."""
    await db_connection.execute(
        'UPDATE subscriptions SET is_active = 0, trial_used = 0 WHERE user_id = ?',
        (user_id,)
    )
    await db_connection.commit()


# ----------------------------- referrals -----------------------------

async def add_referral(referrer_id, referred_id, created_at):
    await db_connection.execute('''
        INSERT OR IGNORE INTO referrals (referrer_id, referred_id, created_at)
        VALUES (?, ?, ?)
    ''', (referrer_id, referred_id, created_at))
    await db_connection.commit()


async def mark_referral_bonus_granted(referred_id):
    await db_connection.execute(
        'UPDATE referrals SET bonus_granted = 1 WHERE referred_id = ?', (referred_id,)
    )
    await db_connection.commit()


async def get_referral_count(referrer_id):
    cursor = await db_connection.execute(
        'SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (referrer_id,)
    )
    row = await cursor.fetchone()
    return row[0] if row else 0


async def grant_referral_bonus(referrer_id, referred_id, bonus_days=7):
    """Extend the referrer's subscription by bonus_days and mark the referral.

    Manual for now (called by an admin command) — automatic triggering is left
    for a later iteration once the award condition is decided.
    """
    now = int(datetime.now(tz=timezone.utc).timestamp())
    sub = await get_subscription(referrer_id)
    current_exp = (sub.get('expires_at') if sub else None) or now
    base = max(int(current_exp), now)
    new_expires = base + bonus_days * 86400
    plan = (sub.get('plan') if sub else None) or 'referral_bonus'
    charge_id = sub.get('charge_id') if sub else None
    is_recurring = (sub.get('is_recurring') if sub else 0) or 0
    await upsert_subscription(referrer_id, 1, new_expires, plan, charge_id, is_recurring)
    await mark_referral_bonus_granted(referred_id)
    return new_expires


async def get_all_owners():
    """Return all known owners (from the owners table) ordered by id."""
    cursor = await db_connection.execute(
        'SELECT owner_id, username, first_name, connected_at, last_seen '
        'FROM owners ORDER BY owner_id'
    )
    return await cursor.fetchall()


async def get_admin_stats():
    """Detailed per-owner stats for the admin panel."""
    owners = await get_all_owners()
    conns = await get_connections_map()
    result = []
    for owner_id, username, first_name, connected_at, last_seen in owners:
        owner_id = int(owner_id)
        sub = await get_subscription(owner_id)
        bcid = conns.get(owner_id)
        agg = await _owner_message_aggregate(bcid)
        refs = await get_referral_count(owner_id)
        result.append({
            'owner_id': owner_id,
            'username': username,
            'first_name': first_name,
            'connected': bcid is not None,
            'last_seen': last_seen,
            'subscription': sub,
            'contacts': agg['contacts'],
            'total': agg['total'],
            'edited': agg['edited'],
            'deleted': agg['deleted'],
            'referrals': refs,
        })
    return result


async def _owner_message_aggregate(business_connection_id):
    if not business_connection_id:
        return {'contacts': 0, 'total': 0, 'edited': 0, 'deleted': 0}
    cursor = await db_connection.execute('''
        SELECT COUNT(DISTINCT from_user_id), COUNT(*),
               COALESCE(SUM(is_edited), 0), COALESCE(SUM(is_deleted), 0)
        FROM messages WHERE business_connection_id = ?
    ''', (business_connection_id,))
    row = await cursor.fetchone()
    contacts, total, edited, deleted = row if row else (0, 0, 0, 0)
    return {
        'contacts': contacts or 0,
        'total': total or 0,
        'edited': edited or 0,
        'deleted': deleted or 0,
    }


async def reset_unlimited_subscriptions():
    """Deactivate test subscriptions that have no expiry (expires_at IS NULL).

    Trial/paid subscriptions keep their expiry and lapse on their own.
    """
    await db_connection.execute(
        'UPDATE subscriptions SET is_active = 0 WHERE is_active = 1 AND expires_at IS NULL'
    )
    await db_connection.commit()


# ----------------------------- yoo payments -----------------------------

async def save_payment(payment_id, user_id, status):
    now = int(datetime.now(tz=timezone.utc).timestamp())
    await db_connection.execute('''
        INSERT INTO yoo_payments (payment_id, user_id, status, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(payment_id) DO UPDATE SET status = excluded.status
    ''', (payment_id, int(user_id), status, now))
    await db_connection.commit()


async def set_payment_status(payment_id, status):
    await db_connection.execute(
        'UPDATE yoo_payments SET status = ? WHERE payment_id = ?', (status, payment_id)
    )
    await db_connection.commit()


async def get_pending_payments():
    cursor = await db_connection.execute(
        "SELECT payment_id, user_id FROM yoo_payments WHERE status = 'pending'"
    )
    return await cursor.fetchall()


async def delete_message_by_id(db_id):
    """Delete a single stored message (and its edit history) by messages.id.

    Returns the local media path (if any) so the caller can remove the file.
    """
    cursor = await db_connection.execute(
        'SELECT chat_id, message_id, local_path FROM messages WHERE id = ?', (db_id,)
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    chat_id, message_id, local_path = row
    await db_connection.execute(
        'DELETE FROM message_edits WHERE chat_id = ? AND message_id = ?',
        (chat_id, message_id)
    )
    await db_connection.execute('DELETE FROM messages WHERE id = ?', (db_id,))
    await db_connection.commit()
    return local_path


async def delete_all_messages(business_connection_id):
    """Wipe all stored messages/edits for a connection. Returns local media
    paths so the caller can also remove the files from disk."""
    cursor = await db_connection.execute(
        'SELECT local_path FROM messages WHERE business_connection_id = ? AND local_path IS NOT NULL',
        (business_connection_id,)
    )
    paths = [r[0] for r in await cursor.fetchall()]
    await db_connection.execute('''
        DELETE FROM message_edits WHERE chat_id IN (
            SELECT chat_id FROM messages WHERE business_connection_id = ?
        )
    ''', (business_connection_id,))
    await db_connection.execute(
        'DELETE FROM messages WHERE business_connection_id = ?',
        (business_connection_id,)
    )
    await db_connection.commit()
    return paths
