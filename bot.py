import os
import time
import asyncio
import sqlite3
import logging
from contextlib import closing

try:
    from pymongo import MongoClient
    MONGO_AVAILABLE = True
except ImportError:
    MONGO_AVAILABLE = False

from pyrogram import Client, filters
from pyrogram.enums import ChatType, ChatMemberStatus, ParseMode
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import RPCError, FloodWait


# ============================================================
#                    KIRTI GUARDIAN BOT
# ============================================================

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

MONGO_URI = os.getenv("MONGO_URI", "").strip()
MONGO_DB_NAME = os.getenv(
    "MONGO_DB_NAME",
    "kirti_guardian"
).strip()

START_IMAGE = os.getenv(
    "START_IMAGE",
    "https://h.uguu.se/FekWWcsz.jpg"
).strip()

BOT_USERNAME = os.getenv(
    "BOT_USERNAME",
    "KirtiGuardianBot"
).strip().lstrip("@")

OWNER_USERNAME = os.getenv(
    "OWNER_USERNAME",
    ""
).strip().lstrip("@")

SUPPORT_USERNAME = os.getenv(
    "SUPPORT_USERNAME",
    ""
).strip().lstrip("@")

SQLITE_DB = os.getenv(
    "SQLITE_DB",
    "kirti_guardian.db"
)


# ============================================================
#                         CONFIG
# ============================================================

if not API_ID:
    raise RuntimeError("API_ID is missing.")

if not API_HASH:
    raise RuntimeError("API_HASH is missing.")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing.")

if not OWNER_ID:
    raise RuntimeError("OWNER_ID is missing.")


# ============================================================
#                         LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("KirtiGuardian")


# ============================================================
#                         PYROGRAM
# ============================================================

app = Client(
    "kirti_guardian_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="."
)


# ============================================================
#                         DATABASE
# ============================================================

USE_MONGO = False

mongo = None
mongo_db = None

users_col = None
local_auth_col = None
global_auth_col = None
settings_col = None
stats_col = None


# ============================================================
#                         SQLITE
# ============================================================

def sqlite_conn():
    con = sqlite3.connect(
        SQLITE_DB,
        timeout=30
    )
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_sqlite():

    with closing(sqlite_conn()) as con:

        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                is_bot INTEGER DEFAULT 0,
                updated_at REAL
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS local_auth (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY(chat_id, user_id)
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS global_auth (
                user_id INTEGER PRIMARY KEY
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                chat_id INTEGER PRIMARY KEY,
                admin_edit INTEGER DEFAULT 0
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value INTEGER DEFAULT 0
            )
        """)

        con.commit()


# ============================================================
#                    DATABASE INITIALIZATION
# ============================================================

def init_database():

    global USE_MONGO
    global mongo
    global mongo_db
    global users_col
    global local_auth_col
    global global_auth_col
    global settings_col
    global stats_col

    init_sqlite()

    if not MONGO_URI:
        log.warning("MONGO_URI not configured.")
        log.warning("Using SQLite fallback.")
        return

    if not MONGO_AVAILABLE:
        log.warning("pymongo not installed.")
        log.warning("Using SQLite fallback.")
        return

    try:

        mongo = MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=5000
        )

        mongo.admin.command("ping")

        mongo_db = mongo[MONGO_DB_NAME]

        users_col = mongo_db["users"]
        local_auth_col = mongo_db["local_auth"]
        global_auth_col = mongo_db["global_auth"]
        settings_col = mongo_db["settings"]
        stats_col = mongo_db["stats"]

        users_col.create_index(
            "user_id",
            unique=True
        )

        local_auth_col.create_index(
            [
                ("chat_id", 1),
                ("user_id", 1)
            ],
            unique=True
        )

        global_auth_col.create_index(
            "user_id",
            unique=True
        )

        settings_col.create_index(
            "chat_id",
            unique=True
        )

        USE_MONGO = True

        log.info("MongoDB connected successfully.")

    except Exception as e:

        USE_MONGO = False

        log.warning(
            "MongoDB connection failed: %s",
            e
        )

        log.warning(
            "Using SQLite fallback."
        )


# ============================================================
#                         STATISTICS
# ============================================================

def stat_inc(key, amount=1):

    if USE_MONGO:

        try:

            stats_col.update_one(
                {"key": key},
                {
                    "$inc": {
                        "value": amount
                    }
                },
                upsert=True
            )

            return

        except Exception:
            pass

    with closing(sqlite_conn()) as con:

        con.execute("""
            INSERT INTO stats(key, value)
            VALUES(?, ?)
            ON CONFLICT(key)
            DO UPDATE SET
                value=value+excluded.value
        """, (
            key,
            amount
        ))

        con.commit()


def get_stat(key):

    if USE_MONGO:

        try:

            data = stats_col.find_one(
                {"key": key}
            )

            if data:
                return int(
                    data.get("value", 0)
                )

            return 0

        except Exception:
            pass

    with closing(sqlite_conn()) as con:

        row = con.execute(
            """
            SELECT value
            FROM stats
            WHERE key=?
            """,
            (key,)
        ).fetchone()

    return int(row[0]) if row else 0


# ============================================================
#                           USERS
# ============================================================

def save_user(user):

    if not user:
        return

    if USE_MONGO:

        try:

            users_col.update_one(
                {"user_id": user.id},
                {
                    "$set": {
                        "user_id": user.id,
                        "username": user.username,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "is_bot": user.is_bot,
                        "updated_at": time.time()
                    }
                },
                upsert=True
            )

            return

        except Exception:
            pass

    with closing(sqlite_conn()) as con:

        con.execute("""
            INSERT INTO users(
                user_id,
                username,
                first_name,
                last_name,
                is_bot,
                updated_at
            )
            VALUES(?,?,?,?,?,?)

            ON CONFLICT(user_id)
            DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                is_bot=excluded.is_bot,
                updated_at=excluded.updated_at
        """, (
            user.id,
            user.username,
            user.first_name,
            user.last_name,
            int(user.is_bot),
            time.time()
        ))

        con.commit()


def save_message_user(message):

    if message and message.from_user:
        save_user(message.from_user)


def user_count():

    if USE_MONGO:

        try:

            return users_col.count_documents({
                "is_bot": {
                    "$ne": True
                }
            })

        except Exception:
            pass

    with closing(sqlite_conn()) as con:

        row = con.execute(
            """
            SELECT COUNT(*)
            FROM users
            WHERE is_bot=0
            """
        ).fetchone()

    return int(row[0])


def all_user_ids():

    if USE_MONGO:

        try:

            return [
                x["user_id"]
                for x in users_col.find(
                    {
                        "is_bot": {
                            "$ne": True
                        }
                    },
                    {
                        "_id": 0,
                        "user_id": 1
                    }
                )
            ]

        except Exception:
            pass

    with closing(sqlite_conn()) as con:

        rows = con.execute(
            """
            SELECT user_id
            FROM users
            WHERE is_bot=0
            """
        ).fetchall()

    return [
        row[0]
        for row in rows
    ]


def remove_user(user_id):

    if USE_MONGO:

        try:
            users_col.delete_one(
                {"user_id": user_id}
            )
            return
        except Exception:
            pass

    with closing(sqlite_conn()) as con:

        con.execute(
            """
            DELETE FROM users
            WHERE user_id=?
            """,
            (user_id,)
        )

        con.commit()


# ============================================================
#                       GROUP CHECK
# ============================================================

def is_group(message):

    return bool(
        message
        and message.chat
        and message.chat.type in (
            ChatType.GROUP,
            ChatType.SUPERGROUP
        )
    )


# ============================================================
#                       ADMIN CHECK
# ============================================================

async def is_admin(
    message,
    user_id=None
):

    if not message:
        return False

    if user_id is None:

        if not message.from_user:
            return False

        user_id = message.from_user.id

    if user_id == OWNER_ID:
        return True

    if not is_group(message):
        return False

    try:

        member = await app.get_chat_member(
            message.chat.id,
            user_id
        )

        return member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER
        )

    except RPCError:

        return False


async def is_owner(message):

    return bool(
        message
        and message.from_user
        and message.from_user.id == OWNER_ID
    )


# ============================================================
#                         SETTINGS
# ============================================================

def get_setting(chat_id):

    if USE_MONGO:

        try:

            data = settings_col.find_one(
                {"chat_id": chat_id}
            )

            return bool(
                data.get(
                    "admin_edit",
                    False
                )
            ) if data else False

        except Exception:
            pass

    with closing(sqlite_conn()) as con:

        row = con.execute(
            """
            SELECT admin_edit
            FROM settings
            WHERE chat_id=?
            """,
            (chat_id,)
        ).fetchone()

    return bool(row[0]) if row else False


def set_setting(
    chat_id,
    enabled
):

    if USE_MONGO:

        try:

            settings_col.update_one(
                {"chat_id": chat_id},
                {
                    "$set": {
                        "chat_id": chat_id,
                        "admin_edit": bool(enabled)
                    }
                },
                upsert=True
            )

            return

        except Exception:
            pass

    with closing(sqlite_conn()) as con:

        con.execute("""
            INSERT INTO settings(
                chat_id,
                admin_edit
            )
            VALUES(?, ?)
            ON CONFLICT(chat_id)
            DO UPDATE SET
                admin_edit=excluded.admin_edit
        """, (
            chat_id,
            int(enabled)
        ))

        con.commit()


# ============================================================
#                       LOCAL AUTH
# ============================================================

def local_authed(
    chat_id,
    user_id
):

    if USE_MONGO:

        try:

            return (
                local_auth_col.find_one(
                    {
                        "chat_id": chat_id,
                        "user_id": user_id
                    }
                )
                is not None
            )

        except Exception:
            pass

    with closing(sqlite_conn()) as con:

        row = con.execute(
            """
            SELECT 1
            FROM local_auth
            WHERE chat_id=?
            AND user_id=?
            """,
            (
                chat_id,
                user_id
            )
        ).fetchone()

    return row is not None


def add_local(
    chat_id,
    user_id
):

    if USE_MONGO:

        try:

            local_auth_col.update_one(
                {
                    "chat_id": chat_id,
                    "user_id": user_id
                },
                {
                    "$set": {
                        "chat_id": chat_id,
                        "user_id": user_id
                    }
                },
                upsert=True
            )

            return

        except Exception:
            pass

    with closing(sqlite_conn()) as con:

        con.execute(
            """
            INSERT OR IGNORE INTO local_auth
            (chat_id,user_id)
            VALUES(?,?)
            """,
            (
                chat_id,
                user_id
            )
        )

        con.commit()


def remove_local(
    chat_id,
    user_id
):

    if USE_MONGO:

        try:

            result = local_auth_col.delete_one(
                {
                    "chat_id": chat_id,
                    "user_id": user_id
                }
            )

            return result.deleted_count

        except Exception:
            pass

    with closing(sqlite_conn()) as con:

        cur = con.execute(
            """
            DELETE FROM local_auth
            WHERE chat_id=?
            AND user_id=?
            """,
            (
                chat_id,
                user_id
            )
        )

        con.commit()

    return cur.rowcount


def clear_local(chat_id):

    if USE_MONGO:

        try:

            result = local_auth_col.delete_many(
                {
                    "chat_id": chat_id
                }
            )

            return result.deleted_count

        except Exception:
            pass

    with closing(sqlite_conn()) as con:

        cur = con.execute(
            """
            DELETE FROM local_auth
            WHERE chat_id=?
            """,
            (chat_id,)
        )

        con.commit()

    return cur.rowcount


def list_local(chat_id):

    if USE_MONGO:

        try:

            return [
                x["user_id"]
                for x in local_auth_col.find(
                    {"chat_id": chat_id},
                    {
                        "_id": 0,
                        "user_id": 1
                    }
                ).sort(
                    "user_id",
                    1
                )
            ]

        except Exception:
            pass

    with closing(sqlite_conn()) as con:

        rows = con.execute(
            """
            SELECT user_id
            FROM local_auth
            WHERE chat_id=?
            ORDER BY user_id
            """,
            (chat_id,)
        ).fetchall()

    return [
        row[0]
        for row in rows
    ]


# ============================================================
#                       GLOBAL AUTH
# ============================================================

def global_authed(user_id):

    if USE_MONGO:

        try:

            return (
                global_auth_col.find_one(
                    {"user_id": user_id}
                )
                is not None
            )

        except Exception:
            pass

    with closing(sqlite_conn()) as con:

        row = con.execute(
            """
            SELECT 1
            FROM global_auth
            WHERE user_id=?
            """,
            (user_id,)
        ).fetchone()

    return row is not None


def add_global(user_id):

    if USE_MONGO:

        try:

            global_auth_col.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "user_id": user_id
                    }
                },
                upsert=True
            )

            return

        except Exception:
            pass

    with closing(sqlite_conn()) as con:

        con.execute(
            """
            INSERT OR IGNORE INTO global_auth(user_id)
            VALUES(?)
            """,
            (user_id,)
        )

        con.commit()


def remove_global(user_id):

    if USE_MONGO:

        try:

            result = global_auth_col.delete_one(
                {"user_id": user_id}
            )

            return result.deleted_count

        except Exception:
            pass

    with closing(sqlite_conn()) as con:

        cur = con.execute(
            """
            DELETE FROM global_auth
            WHERE user_id=?
            """,
            (user_id,)
        )

        con.commit()

    return cur.rowcount


def clear_global():

    if USE_MONGO:

        try:

            result = global_auth_col.delete_many({})

            return result.deleted_count

        except Exception:
            pass

    with closing(sqlite_conn()) as con:

        cur = con.execute(
            "DELETE FROM global_auth"
        )

        con.commit()

    return cur.rowcount


def list_global():

    if USE_MONGO:

        try:

            return [
                x["user_id"]
                for x in global_auth_col.find(
                    {},
                    {
                        "_id": 0,
                        "user_id": 1
                    }
                ).sort(
                    "user_id",
                    1
                )
            ]

        except Exception:
            pass

    with closing(sqlite_conn()) as con:

        rows = con.execute(
            """
            SELECT user_id
            FROM global_auth
            ORDER BY user_id
            """
        ).fetchall()

    return [
        row[0]
        for row in rows
    ]


# ============================================================
#                       USER RESOLVER
# ============================================================

def target_user(message):

    if (
        message.reply_to_message
        and message.reply_to_message.from_user
    ):

        return message.reply_to_message.from_user.id

    parts = (
        message.text or ""
    ).split(
        maxsplit=1
    )

    if len(parts) < 2:
        return None

    value = parts[1].strip()

    if value.isdigit():
        return int(value)

    return value.lstrip("@")


async def resolve_user(message):

    target = target_user(message)

    if target is None:
        return None

    if isinstance(target, int):
        return target

    try:

        user = await app.get_users(
            target
        )

        return user.id

    except RPCError:

        return None


# ============================================================
#                     DELETE EDITED MESSAGE
# ============================================================

async def delete_quietly(message):

    try:

        await message.delete()

        stat_inc(
            "deleted_edits"
        )

        return True

    except FloodWait as e:

        await asyncio.sleep(
            e.value
        )

        try:

            await message.delete()

            stat_inc(
                "deleted_edits"
            )

            return True

        except Exception:
            return False

    except RPCError:

        return False

    except Exception:

        return False


# ============================================================
#                         START TEXT
# ============================================================

def start_text(
    user,
    bot
):

    user_name = (
        user.first_name
        or "User"
    )

    bot_name = (
        bot.first_name
        or "Kirti Guardian"
    )

    user_mention = (
        f'<a href="tg://user?id={user.id}">'
        f'{user_name}</a>'
    )

    bot_mention = (
        f'<a href="https://t.me/'
        f'{BOT_USERNAME}">'
        f'{bot_name}</a>'
    )

    return f"""
╭━━━━━━━━━━━━━━━━━━━━━━╮
       🛡️ <b>Kɪʀᴛɪ Gᴜᴀʀᴅɪᴀɴ</b>
              <i>Bᴏᴛ V𝟸</i>
╰━━━━━━━━━━━━━━━━━━━━━━╯

👋 <b>Hᴇʟʟᴏ {user_mention} ❤️</b>

🤖 <b>Wᴇʟᴄᴏᴍᴇ Tᴏ
{bot_mention}</b>

🚨 <b>Aᴜᴛᴏ Eᴅɪᴛ Gᴜᴀʀᴅɪᴀɴ</b>

🛡️ <b>I Cᴀɴ Aᴜᴛᴏ-Dᴇʟᴇᴛᴇ
Eᴅɪᴛᴇᴅ Mᴇssᴀɢᴇs
Fʀᴏᴍ Yᴏᴜʀ Gʀᴏᴜᴘ.</b>

✨ <b>Cʟᴇᴀɴ • Sᴀғᴇ • Sᴇᴄᴜʀᴇ</b>

⭐ <b>Aᴅᴅ Mᴇ Tᴏ Yᴏᴜʀ Gʀᴏᴜᴘ</b>

<b>Aɴᴅ Gɪᴠᴇ Mᴇ
Dᴇʟᴇᴛᴇ Mᴇssᴀɢᴇs
Pᴇʀᴍɪssɪᴏɴ.</b>

━━━━━━━━━━━━━━━━━━━━━━

💎 <b>Pᴏᴡᴇʀᴇᴅ Bʏ {bot_mention}</b>
❤️ <i>Mᴀᴅᴇ Fᴏʀ Tᴇʟᴇɢʀᴀᴍ</i>
"""


# ============================================================
#                            HELP
# ============================================================

HELP_TEXT = """
<blockquote>
<b>📚 ʜᴇʟᴘ & ᴄᴏᴍᴍᴀɴᴅs ~</b>

<b>👑 ʟᴏᴄᴀʟ ᴀᴜᴛʜ ( ᴀᴅᴍɪɴ ᴏɴʟʏ )-</b>

<b>• /auth - ᴀᴜᴛʜᴏʀɪᴢᴇ ᴀ ᴜsᴇʀ</b>
<b>• /unauth - ʀᴇᴍᴏᴠᴇ ᴀᴜᴛʜ</b>
<b>• /authusers - ᴠɪᴇᴡ ᴀᴜᴛʜ ᴜsᴇʀs</b>
<b>• /clearauthusers - ᴄʟᴇᴀʀ ᴀʟʟ ᴀᴜᴛʜ ᴜsᴇʀs</b>

<b>🌐 ɢʟᴏʙᴀʟ ᴀᴜᴛʜ ( ᴏᴡɴᴇʀ ᴏɴʟʏ )-</b>

<b>• /gauth - ɢʟᴏʙᴀʟ ᴀᴜᴛʜ ᴜsᴇʀ</b>
<b>• /gunauth - ʀᴇᴍᴏᴠᴇ ɢʟᴏʙᴀʟ ᴀᴜᴛʜ</b>
<b>• /gusers - ᴠɪᴇᴡ ɢʟᴏʙᴀʟ ᴀᴜᴛʜ ᴜsᴇʀs</b>
<b>• /cleargusers - ᴄʟᴇᴀʀ ᴀʟʟ ɢʟᴏʙᴀʟ ᴀᴜᴛʜ ᴜsᴇʀs</b>

<b>🛡️ ᴇᴅɪᴛ ᴅᴇʟᴇᴛᴇ ( ᴀᴅᴍɪɴ ᴏɴʟʏ )-</b>

<b>• /adminedit on - ᴅᴇʟᴇᴛᴇ ᴀᴅᴍɪɴ ᴇᴅɪᴛs</b>
<b>• /adminedit off - ɪɢɴᴏʀᴇ ᴀᴅᴍɪɴ ᴇᴅɪᴛs</b>
<b>• ᴅᴇғᴜʟᴛ : 🔴 ᴏғғ</b>

<b>📢 ʙʀᴏᴀᴅᴄᴀsᴛ ( ᴏᴡɴᴇʀ ᴏɴʟʏ )-</b>

<b>• /broadcast MESSAGE</b>
<b>• /broadcast - ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴍᴇssᴀɢᴇ</b>
<b>• /broadcast_stats - sᴛᴀᴛɪsᴛɪᴄs</b>

<b>📊 ᴏᴛʜᴇʀ-</b>

<b>• /start - ᴄʜᴇᴄᴋ ʙᴏᴛ</b>
<b>• /stats - ᴄʜᴇᴄᴋ sᴛᴀᴛs</b>
<b>• /help - ᴄʜᴇᴄᴋ ʜᴇʟᴘ</b>
<b>• /id - ᴄʜᴇᴄᴋ ʏᴏᴜʀ ɪᴅ</b>

<b>⚡ ᴀᴅᴅ ᴍᴇ ɪɴ ʏᴏᴜʀ ɢʀᴏᴜᴘ
ᴀɴᴅ ɢɪᴠᴇ ᴍᴇ "ᴅᴇʟᴇᴛᴇ ᴍᴇssᴀɢᴇs"
ᴘᴇʀᴍɪssɪᴏɴ.</b>

<b>✨ ᴋᴇᴇᴘ ʏᴏᴜʀ ɢʀᴏᴜᴘ ᴄʟᴇᴀɴ
ᴀɴᴅ sᴀғᴇ ʙʏ ᴅᴇᴛᴇᴄᴛɪɴɢ &
ʀᴇᴍᴏᴠɪɴɢ ᴇᴅɪᴛᴇᴅ
ᴍᴇssᴀɢᴇs ɪɴsᴛᴀɴᴛʟʏ.</b>
</blockquote>
"""


# ============================================================
#                       START BUTTONS
# ============================================================

def start_buttons():

    rows = []

    rows.append([
        InlineKeyboardButton(
            "✚ ᴀᴅᴅ ᴍᴇ ɪɴ ʏᴏᴜʀ ɢʀᴏᴜᴘ ✚",
            url=(
                f"https://t.me/"
                f"{BOT_USERNAME}"
                f"?startgroup=true"
            )
        )
    ])

    contact_row = []

    if OWNER_USERNAME:

        contact_row.append(
            InlineKeyboardButton(
                "👑 ᴏᴡɴᴇʀ",
                url=(
                    f"https://t.me/"
                    f"{OWNER_USERNAME}"
                )
            )
        )

    if SUPPORT_USERNAME:

        contact_row.append(
            InlineKeyboardButton(
                "🛠️ sᴜᴘᴘᴏʀᴛ",
                url=(
                    f"https://t.me/"
                    f"{SUPPORT_USERNAME}"
                )
            )
        )

    if contact_row:
        rows.append(contact_row)

    rows.append([
        InlineKeyboardButton(
            "📚 ʜᴇʟᴘ & ᴄᴏᴍᴍᴀɴᴅs",
            callback_data="help"
        )
    ])

    return InlineKeyboardMarkup(rows)


def home_buttons():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🏠 ʜᴏᴍᴇ",
                callback_data="home"
            )
        ]
    ])


# ============================================================
#                     START LOGGER
# ============================================================

async def send_start_logger(
    user,
    bot
):

    if not user:
        return

    try:

        username = (
            f"@{user.username}"
            if user.username
            else "N/A"
        )

        full_name = (
            user.first_name
            or "Unknown"
        )

        if user.last_name:
            full_name += (
                f" {user.last_name}"
            )

        bot_name = (
            bot.first_name
            if bot
            else "Kirti Guardian"
        )

        logger_text = (
            "╭━━━━━━━━━━━━━━━━━━━━╮\n"
            "       🚀 <b>ɴᴇᴡ sᴛᴀʀᴛ ʟᴏɢ</b>\n"
            "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
            f"👤 <b>ɴᴀᴍᴇ:</b> "
            f"{full_name}\n"
            f"🔗 <b>ᴜsᴇʀɴᴀᴍᴇ:</b> "
            f"{username}\n"
            f"🆔 <b>ᴜsᴇʀ ɪᴅ:</b> "
            f"<code>{user.id}</code>\n\n"
            f"🤖 <b>ʙᴏᴛ:</b> "
            f"{bot_name}\n\n"
            "✅ <b>ᴜsᴇʀ sᴛᴀʀᴛᴇᴅ ᴛʜᴇ ʙᴏᴛ.</b>"
        )

        await app.send_message(
            OWNER_ID,
            logger_text,
            parse_mode=ParseMode.HTML
        )

    except FloodWait as e:

        await asyncio.sleep(
            e.value
        )

        try:

            await app.send_message(
                OWNER_ID,
                logger_text,
                parse_mode=ParseMode.HTML
            )

        except Exception as retry_error:

            log.warning(
                "Start logger retry failed: %s",
                retry_error
            )

    except Exception as e:

        log.warning(
            "Start logger error: %s",
            e
        )


# ============================================================
#                           START
# ============================================================

@app.on_message(
    filters.command("start")
)
async def start_cmd(
    _,
    message: Message
):

    if not message.from_user:
        return

    save_message_user(message)

    stat_inc("starts")

    bot = await app.get_me()

    # --------------------------------------------------------
    # LOG EVERY START TO OWNER
    # --------------------------------------------------------

    await send_start_logger(
        message.from_user,
        bot
    )

    text = start_text(
        message.from_user,
        bot
    )

    # --------------------------------------------------------
    # START IMAGE
    # --------------------------------------------------------

    if START_IMAGE:

        try:

            await message.reply_photo(
                photo=START_IMAGE,
                caption=text,
                reply_markup=start_buttons(),
                parse_mode=ParseMode.HTML
            )

            return

        except Exception as e:

            log.warning(
                "Start image failed: %s",
                e
            )

    await message.reply_text(
        text,
        reply_markup=start_buttons(),
        parse_mode=ParseMode.HTML
    )


# ============================================================
#                            HELP
# ============================================================

@app.on_message(
    filters.command("help")
)
async def help_cmd(
    _,
    message: Message
):

    save_message_user(message)

    await message.reply_text(
        HELP_TEXT,
        reply_markup=home_buttons(),
        parse_mode=ParseMode.HTML
    )


# ============================================================
#                          CALLBACKS
# ============================================================

@app.on_callback_query()
async def callbacks(
    _,
    query
):

    try:

        if query.data == "help":

            await query.message.edit_text(
                HELP_TEXT,
                reply_markup=home_buttons(),
                parse_mode=ParseMode.HTML
            )

            await query.answer(
                "ʜᴇʟᴘ"
            )

            return

        if query.data == "home":

            bot = await app.get_me()

            text = start_text(
                query.from_user,
                bot
            )

            await query.message.edit_text(
                text,
                reply_markup=start_buttons(),
                parse_mode=ParseMode.HTML
            )

            await query.answer(
                "ʜᴏᴍᴇ"
            )

            return

        await query.answer()

    except Exception as e:

        log.warning(
            "Callback error: %s",
            e
        )


# ============================================================
#                           AUTH
# ============================================================

@app.on_message(
    filters.command("auth")
)
async def auth_cmd(
    _,
    message: Message
):

    if not is_group(message):

        return await message.reply_text(
            "❌ <b>ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ᴡᴏʀᴋs ᴏɴʟʏ ɪɴ ɢʀᴏᴜᴘs.</b>",
            parse_mode=ParseMode.HTML
        )

    if not await is_admin(message):

        return await message.reply_text(
            "❌ <b>ɢʀᴏᴜᴘ ᴏᴡɴᴇʀ / ᴀᴅᴍɪɴ ᴏɴʟʏ.</b>",
            parse_mode=ParseMode.HTML
        )

    uid = await resolve_user(message)

    if not uid:

        return await message.reply_text(
            "❌ <b>ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴜsᴇʀ ᴏʀ ᴜsᴇ:</b>\n"
            "<code>/auth USER_ID</code>",
            parse_mode=ParseMode.HTML
        )

    add_local(
        message.chat.id,
        uid
    )

    await message.reply_text(
        "╭━━━━━━━━━━━━━━━━━━━━╮\n"
        "       👑 <b>ʟᴏᴄᴀʟ ᴀᴜᴛʜ</b>\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"✅ ᴜsᴇʀ: <code>{uid}</code>\n"
        "✨ <b>ᴀᴜᴛʜᴏʀɪᴢᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ.</b>",
        parse_mode=ParseMode.HTML
    )


# ============================================================
#                          UNAUTH
# ============================================================

@app.on_message(
    filters.command("unauth")
)
async def unauth_cmd(
    _,
    message: Message
):

    if not is_group(message):

        return await message.reply_text(
            "❌ <b>ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ᴡᴏʀᴋs ᴏɴʟʏ ɪɴ ɢʀᴏᴜᴘs.</b>",
            parse_mode=ParseMode.HTML
        )

    if not await is_admin(message):

        return await message.reply_text(
            "❌ <b>ɢʀᴏᴜᴘ ᴏᴡɴᴇʀ / ᴀᴅᴍɪɴ ᴏɴʟʏ.</b>",
            parse_mode=ParseMode.HTML
        )

    uid = await resolve_user(message)

    if not uid:

        return await message.reply_text(
            "❌ <b>ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴜsᴇʀ ᴏʀ ᴜsᴇ:</b>\n"
            "<code>/unauth USER_ID</code>",
            parse_mode=ParseMode.HTML
        )

    removed = remove_local(
        message.chat.id,
        uid
    )

    if removed:

        text = (
            f"✅ <b>ᴀᴜᴛʜ ʀᴇᴍᴏᴠᴇᴅ:</b>\n"
            f"<code>{uid}</code>"
        )

    else:

        text = (
            f"ℹ️ <b>ᴜsᴇʀ ᴡᴀs ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ:</b>\n"
            f"<code>{uid}</code>"
        )

    await message.reply_text(
        text,
        parse_mode=ParseMode.HTML
    )


# ============================================================
#                        AUTH USERS
# ============================================================

@app.on_message(
    filters.command("authusers")
)
async def authusers_cmd(
    _,
    message: Message
):

    if not is_group(message):

        return await message.reply_text(
            "❌ <b>ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ᴡᴏʀᴋs ᴏɴʟʏ ɪɴ ɢʀᴏᴜᴘs.</b>",
            parse_mode=ParseMode.HTML
        )

    if not await is_admin(message):

        return await message.reply_text(
            "❌ <b>ɢʀᴏᴜᴘ ᴏᴡɴᴇʀ / ᴀᴅᴍɪɴ ᴏɴʟʏ.</b>",
            parse_mode=ParseMode.HTML
        )

    users = list_local(
        message.chat.id
    )

    if not users:

        return await message.reply_text(
            "📭 <b>ɴᴏ ʟᴏᴄᴀʟ ᴀᴜᴛʜ ᴜsᴇʀs.</b>",
            parse_mode=ParseMode.HTML
        )

    text = (
        "╭━━━━━━━━━━━━━━━━━━━━╮\n"
        "       👑 <b>ʟᴏᴄᴀʟ ᴀᴜᴛʜ</b>\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
    )

    text += "\n".join(
        f"➤ <code>{uid}</code>"
        for uid in users
    )

    await message.reply_text(
        text,
        parse_mode=ParseMode.HTML
    )


# ============================================================
#                    CLEAR LOCAL AUTH
# ============================================================

@app.on_message(
    filters.command("clearauthusers")
)
async def clear_auth_cmd(
    _,
    message: Message
):

    if not is_group(message):

        return await message.reply_text(
            "❌ <b>ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ᴡᴏʀᴋs ᴏɴʟʏ ɪɴ ɢʀᴏᴜᴘs.</b>",
            parse_mode=ParseMode.HTML
        )

    if not await is_admin(message):

        return await message.reply_text(
            "❌ <b>ɢʀᴏᴜᴘ ᴏᴡɴᴇʀ / ᴀᴅᴍɪɴ ᴏɴʟʏ.</b>",
            parse_mode=ParseMode.HTML
        )

    count = clear_local(
        message.chat.id
    )

    await message.reply_text(
        f"🧹 <b>ᴄʟᴇᴀʀᴇᴅ {count} ʟᴏᴄᴀʟ ᴀᴜᴛʜ ᴜsᴇʀ(s).</b>",
        parse_mode=ParseMode.HTML
    )


# ============================================================
#                       GLOBAL AUTH
# ============================================================

@app.on_message(
    filters.command("gauth")
)
async def gauth_cmd(
    _,
    message: Message
):

    if not await is_owner(message):

        return await message.reply_text(
            "❌ <b>ʙᴏᴛ ᴏᴡɴᴇʀ ᴏɴʟʏ.</b>",
            parse_mode=ParseMode.HTML
        )

    uid = await resolve_user(message)

    if not uid:

        return await message.reply_text(
            "❌ <b>ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴜsᴇʀ ᴏʀ ᴜsᴇ:</b>\n"
            "<code>/gauth USER_ID</code>",
            parse_mode=ParseMode.HTML
        )

    add_global(uid)

    await message.reply_text(
        f"🌐 <b>ɢʟᴏʙᴀʟ ᴀᴜᴛʜ ᴀᴅᴅᴇᴅ:</b>\n"
        f"<code>{uid}</code>",
        parse_mode=ParseMode.HTML
    )


@app.on_message(
    filters.command("gunauth")
)
async def gunauth_cmd(
    _,
    message: Message
):

    if not await is_owner(message):

        return await message.reply_text(
            "❌ <b>ʙᴏᴛ ᴏᴡɴᴇʀ ᴏɴʟʏ.</b>",
            parse_mode=ParseMode.HTML
        )

    uid = await resolve_user(message)

    if not uid:

        return await message.reply_text(
            "❌ <b>ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴜsᴇʀ ᴏʀ ᴜsᴇ:</b>\n"
            "<code>/gunauth USER_ID</code>",
            parse_mode=ParseMode.HTML
        )

    removed = remove_global(uid)

    text = (
        f"✅ <b>ɢʟᴏʙᴀʟ ᴀᴜᴛʜ ʀᴇᴍᴏᴠᴇᴅ:</b>\n"
        f"<code>{uid}</code>"
        if removed
        else
        "ℹ️ <b>ᴜsᴇʀ ᴡᴀs ɴᴏᴛ ɢʟᴏʙᴀʟʟʏ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ.</b>"
    )

    await message.reply_text(
        text,
        parse_mode=ParseMode.HTML
    )


@app.on_message(
    filters.command("gusers")
)
async def gusers_cmd(
    _,
    message: Message
):

    if not await is_owner(message):

        return await message.reply_text(
            "❌ <b>ʙᴏᴛ ᴏᴡɴᴇʀ ᴏɴʟʏ.</b>",
            parse_mode=ParseMode.HTML
        )

    users = list_global()

    if not users:

        return await message.reply_text(
            "📭 <b>ɴᴏ ɢʟᴏʙᴀʟ ᴀᴜᴛʜ ᴜsᴇʀs.</b>",
            parse_mode=ParseMode.HTML
        )

    text = (
        "🌐 <b>ɢʟᴏʙᴀʟ ᴀᴜᴛʜ ᴜsᴇʀs</b>\n\n"
    )

    text += "\n".join(
        f"➤ <code>{uid}</code>"
        for uid in users
    )

    await message.reply_text(
        text,
        parse_mode=ParseMode.HTML
    )


@app.on_message(
    filters.command("cleargusers")
)
async def clear_global_cmd(
    _,
    message: Message
):

    if not await is_owner(message):

        return await message.reply_text(
            "❌ <b>ʙᴏᴛ ᴏᴡɴᴇʀ ᴏɴʟʏ.</b>",
            parse_mode=ParseMode.HTML
        )

    count = clear_global()

    await message.reply_text(
        f"🧹 <b>ᴄʟᴇᴀʀᴇᴅ {count} ɢʟᴏʙᴀʟ ᴀᴜᴛʜ ᴜsᴇʀ(s).</b>",
        parse_mode=ParseMode.HTML
    )


# ============================================================
#                       ADMIN EDIT
# ============================================================

@app.on_message(
    filters.command("adminedit")
)
async def adminedit_cmd(
    _,
    message: Message
):

    if not is_group(message):

        return await message.reply_text(
            "❌ <b>ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ᴡᴏʀᴋs ᴏɴʟʏ ɪɴ ɢʀᴏᴜᴘs.</b>",
            parse_mode=ParseMode.HTML
        )

    if not await is_admin(message):

        return await message.reply_text(
            "❌ <b>ɢʀᴏᴜᴘ ᴏᴡɴᴇʀ / ᴀᴅᴍɪɴ ᴏɴʟʏ.</b>",
            parse_mode=ParseMode.HTML
        )

    parts = (
        message.text or ""
    ).split()

    if (
        len(parts) < 2
        or parts[1].lower()
        not in ("on", "off")
    ):

        current = (
            "🟢 ᴏɴ"
            if get_setting(message.chat.id)
            else "🔴 ᴏғғ"
        )

        return await message.reply_text(
            "🛡️ <b>ᴀᴅᴍɪɴ ᴇᴅɪᴛ ɢᴜᴀʀᴅɪᴀɴ</b>\n\n"
            f"ᴄᴜʀʀᴇɴᴛ: <b>{current}</b>\n\n"
            "<code>/adminedit on</code>\n"
            "<code>/adminedit off</code>",
            parse_mode=ParseMode.HTML
        )

    enabled = (
        parts[1].lower() == "on"
    )

    set_setting(
        message.chat.id,
        enabled
    )

    await message.reply_text(
        "🛡️ <b>ᴀᴅᴍɪɴ ᴇᴅɪᴛ ɢᴜᴀʀᴅɪᴀɴ</b>\n\n"
        f"sᴛᴀᴛᴜs: "
        f"<b>{'🟢 ᴏɴ' if enabled else '🔴 ᴏғғ'}</b>",
        parse_mode=ParseMode.HTML
    )


# ============================================================
#                       EDIT GUARDIAN
# ============================================================

# IMPORTANT:
# filters.group covers GROUP + SUPERGROUP.
# filters.supergroup does NOT exist in Pyrogram.

@app.on_edited_message(
    filters.group
)
async def edited_guard(
    _,
    message: Message
):

    if not message.from_user:
        return

    if message.from_user.is_bot:
        return

    uid = message.from_user.id

    if local_authed(
        message.chat.id,
        uid
    ):
        return

    if global_authed(uid):
        return

    try:

        member = await app.get_chat_member(
            message.chat.id,
            uid
        )

        status = member.status

    except RPCError:

        status = None

    if status in (
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER
    ):

        if not get_setting(
            message.chat.id
        ):
            return

    await delete_quietly(
        message
    )


# ============================================================
#                         BROADCAST
# ============================================================

@app.on_message(
    filters.command("broadcast")
)
async def broadcast_cmd(
    _,
    message: Message
):

    if not await is_owner(message):

        return await message.reply_text(
            "❌ <b>ʙᴏᴛ ᴏᴡɴᴇʀ ᴏɴʟʏ.</b>",
            parse_mode=ParseMode.HTML
        )

    users = all_user_ids()

    if not users:

        return await message.reply_text(
            "📭 <b>ɴᴏ sᴀᴠᴇᴅ ᴜsᴇʀs.</b>",
            parse_mode=ParseMode.HTML
        )

    # --------------------------------------------------------
    # CHECK MESSAGE
    # --------------------------------------------------------

    if not message.reply_to_message:

        parts = (
            message.text or ""
        ).split(
            maxsplit=1
        )

        if len(parts) < 2:

            return await message.reply_text(
                "📢 <b>ʙʀᴏᴀᴅᴄᴀsᴛ ᴜsᴀɢᴇ:</b>\n\n"
                "<code>/broadcast Hello ❤️</code>\n\n"
                "ᴏʀ ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴍᴇssᴀɢᴇ:\n"
                "<code>/broadcast</code>",
                parse_mode=ParseMode.HTML
            )

        broadcast_text = parts[1].strip()

        if not broadcast_text:

            return await message.reply_text(
                "❌ <b>ʙʀᴏᴀᴅᴄᴀsᴛ ᴍᴇssᴀɢᴇ ᴇᴍᴘᴛʏ.</b>",
                parse_mode=ParseMode.HTML
            )

    progress = await message.reply_text(
        "📢 <b>ʙʀᴏᴀᴅᴄᴀsᴛ sᴛᴀʀᴛᴇᴅ...</b>\n\n"
        f"👥 ᴜsᴇʀs: <code>{len(users)}</code>\n"
        "⏳ <b>ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...</b>",
        parse_mode=ParseMode.HTML
    )

    sent = 0
    failed = 0
    removed = 0

    for uid in users:

        try:

            if message.reply_to_message:

                await message.reply_to_message.copy(
                    chat_id=uid
                )

            else:

                await app.send_message(
                    uid,
                    broadcast_text
                )

            sent += 1

            await asyncio.sleep(
                0.05
            )

        except FloodWait as e:

            await asyncio.sleep(
                e.value
            )

            try:

                if message.reply_to_message:

                    await message.reply_to_message.copy(
                        chat_id=uid
                    )

                else:

                    await app.send_message(
                        uid,
                        broadcast_text
                    )

                sent += 1

            except Exception:

                failed += 1

        except RPCError as e:

            failed += 1

            error = str(e).lower()

            if any(
                x in error
                for x in (
                    "blocked",
                    "deactivated",
                    "chat not found"
                )
            ):

                removed += 1

                remove_user(uid)

        except Exception:

            failed += 1

    await progress.edit_text(
        "╭━━━━━━━━━━━━━━━━━━━━╮\n"
        "       📢 <b>ʙʀᴏᴀᴅᴄᴀsᴛ</b>\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"👥 ᴛᴏᴛᴀʟ: <code>{len(users)}</code>\n"
        f"✅ sᴇɴᴛ: <code>{sent}</code>\n"
        f"❌ ғᴀɪʟᴇᴅ: <code>{failed}</code>\n"
        f"🚫 ʀᴇᴍᴏᴠᴇᴅ: <code>{removed}</code>\n\n"
        "✨ <b>ʙʀᴏᴀᴅᴄᴀsᴛ ᴄᴏᴍᴘʟᴇᴛᴇᴅ.</b>",
        parse_mode=ParseMode.HTML
    )


# ============================================================
#                    BROADCAST STATS
# ============================================================

@app.on_message(
    filters.command("broadcast_stats")
)
async def broadcast_stats_cmd(
    _,
    message: Message
):

    if not await is_owner(message):

        return await message.reply_text(
            "❌ <b>ʙᴏᴛ ᴏᴡɴᴇʀ ᴏɴʟʏ.</b>",
            parse_mode=ParseMode.HTML
        )

    await message.reply_text(
        "╭━━━━━━━━━━━━━━━━━━━━╮\n"
        "       📢 <b>ʙʀᴏᴀᴅᴄᴀsᴛ sᴛᴀᴛs</b>\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"👥 sᴀᴠᴇᴅ ᴜsᴇʀs: "
        f"<code>{user_count()}</code>\n"
        f"▶️ sᴛᴀʀᴛs: "
        f"<code>{get_stat('starts')}</code>\n"
        f"🗑️ ᴅᴇʟᴇᴛᴇᴅ ᴇᴅɪᴛs: "
        f"<code>{get_stat('deleted_edits')}</code>",
        parse_mode=ParseMode.HTML
    )


# ============================================================
#                           STATS
# ============================================================

@app.on_message(
    filters.command("stats")
)
async def stats_cmd(
    _,
    message: Message
):

    if not await is_admin(message):

        return await message.reply_text(
            "❌ <b>ᴀᴅᴍɪɴ / ᴏᴡɴᴇʀ ᴏɴʟʏ.</b>",
            parse_mode=ParseMode.HTML
        )

    text = (
        "╭━━━━━━━━━━━━━━━━━━━━╮\n"
        "        📊 <b>ᴋɪʀᴛɪ sᴛᴀᴛs</b>\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"▶️ sᴛᴀʀᴛs: "
        f"<code>{get_stat('starts')}</code>\n"
        f"🗑️ ᴅᴇʟᴇᴛᴇᴅ ᴇᴅɪᴛs: "
        f"<code>{get_stat('deleted_edits')}</code>\n"
        f"👥 sᴀᴠᴇᴅ ᴜsᴇʀs: "
        f"<code>{user_count()}</code>"
    )

    if is_group(message):

        text += (
            "\n🛡️ ᴀᴅᴍɪɴ ᴇᴅɪᴛ: "
            f"<b>{'🟢 ᴏɴ' if get_setting(message.chat.id) else '🔴 ᴏғғ'}</b>"
        )

    await message.reply_text(
        text,
        parse_mode=ParseMode.HTML
    )


# ============================================================
#                             ID
# ============================================================

@app.on_message(
    filters.private & filters.command("id")
)
async def id_cmd(
    _,
    message: Message
):

    save_message_user(message)

    if not message.from_user:
        return

    await message.reply_text(
        "🆔 <b>ʏᴏᴜʀ ᴛᴇʟᴇɢʀᴀᴍ ɪᴅ</b>\n\n"
        f"<code>{message.from_user.id}</code>",
        parse_mode=ParseMode.HTML
    )


# ============================================================
#                          STARTUP
# ============================================================

if __name__ == "__main__":

    init_database()

    log.info(
        "======================================"
    )

    log.info(
        "KIRTI GUARDIAN BOT STARTING"
    )

    log.info(
        "Database: %s",
        "MongoDB" if USE_MONGO else "SQLite"
    )

    log.info(
        "Start logger: ON"
    )

    log.info(
        "Owner button: %s",
        "ON" if OWNER_USERNAME else "OFF"
    )

    log.info(
        "Support button: %s",
        "ON" if SUPPORT_USERNAME else "OFF"
    )

    log.info(
        "======================================"
    )

    app.run()
