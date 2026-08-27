import os
import time
import asyncio
import logging
import sqlite3
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
#                    KIRTI GUARDIAN BOT V2
# ============================================================

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "8857291657"))

MONGO_URI = os.getenv("MONGO_URI", "").strip()
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "kirti_guardian").strip()

START_IMAGE = os.getenv(
    "START_IMAGE",
    "https://h.uguu.se/FekWWcsz.jpg"
).strip()

BOT_USERNAME = os.getenv(
    "BOT_USERNAME", "KirtiGuardianBot"
).strip().lstrip("@")

OWNER_USERNAME = os.getenv(
    "OWNER_USERNAME", "Only_badnam"
).strip().lstrip("@")

SUPPORT_USERNAME = os.getenv(
    "SUPPORT_USERNAME", "annu_updates"
).strip().lstrip("@")

SQLITE_DB = os.getenv("SQLITE_DB", "kirti_guardian.db")

for name, value in (
    ("API_ID", API_ID),
    ("API_HASH", API_HASH),
    ("BOT_TOKEN", BOT_TOKEN),
    ("OWNER_ID", OWNER_ID),
):
    if not value:
        raise RuntimeError(f"{name} is missing.")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("KirtiGuardian")

# ParseMode is set here, so do NOT use parse_mode="html".
app = Client(
    "kirti_guardian_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    parse_mode=ParseMode.HTML,
    workdir="."
)

# ============================================================
#                         DATABASE
# ============================================================

USE_MONGO = False
mongo = None
mongo_db = None
users_col = local_auth_col = global_auth_col = settings_col = stats_col = None

def sqlite_conn():
    con = sqlite3.connect(SQLITE_DB, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    return con

def init_sqlite():
    with closing(sqlite_conn()) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
            last_name TEXT, is_bot INTEGER DEFAULT 0, updated_at REAL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS local_auth (
            chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            PRIMARY KEY(chat_id, user_id))""")
        con.execute("""CREATE TABLE IF NOT EXISTS global_auth (
            user_id INTEGER PRIMARY KEY)""")
        con.execute("""CREATE TABLE IF NOT EXISTS settings (
            chat_id INTEGER PRIMARY KEY, admin_edit INTEGER DEFAULT 0)""")
        con.execute("""CREATE TABLE IF NOT EXISTS stats (
            key TEXT PRIMARY KEY, value INTEGER DEFAULT 0)""")
        con.commit()

def init_database():
    global USE_MONGO, mongo, mongo_db
    global users_col, local_auth_col, global_auth_col, settings_col, stats_col

    init_sqlite()

    if not MONGO_URI:
        log.warning("MONGO_URI not configured; using SQLite fallback.")
        return

    if not MONGO_AVAILABLE:
        log.warning("pymongo not installed; using SQLite fallback.")
        return

    try:
        mongo = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        mongo.admin.command("ping")
        mongo_db = mongo[MONGO_DB_NAME]

        users_col = mongo_db["users"]
        local_auth_col = mongo_db["local_auth"]
        global_auth_col = mongo_db["global_auth"]
        settings_col = mongo_db["settings"]
        stats_col = mongo_db["stats"]

        users_col.create_index("user_id", unique=True)
        local_auth_col.create_index(
            [("chat_id", 1), ("user_id", 1)], unique=True
        )
        global_auth_col.create_index("user_id", unique=True)
        settings_col.create_index("chat_id", unique=True)

        USE_MONGO = True
        log.info("MongoDB connected successfully.")
    except Exception as e:
        USE_MONGO = False
        log.warning("MongoDB unavailable: %s", e)
        log.warning("Using SQLite fallback.")

# ============================================================
#                         STATS
# ============================================================

def stat_inc(key, amount=1):
    if USE_MONGO:
        try:
            stats_col.update_one(
                {"key": key},
                {"$inc": {"value": amount}},
                upsert=True
            )
            return
        except Exception:
            pass
    with closing(sqlite_conn()) as con:
        con.execute("""INSERT INTO stats(key,value) VALUES(?,?)
            ON CONFLICT(key) DO UPDATE SET value=value+excluded.value""",
            (key, amount))
        con.commit()

def get_stat(key):
    if USE_MONGO:
        try:
            d = stats_col.find_one({"key": key})
            return int(d.get("value", 0)) if d else 0
        except Exception:
            pass
    with closing(sqlite_conn()) as con:
        row = con.execute(
            "SELECT value FROM stats WHERE key=?", (key,)
        ).fetchone()
    return int(row[0]) if row else 0

# ============================================================
#                           USERS
# ============================================================

def save_user(user):
    if not user:
        return
    data = {
        "user_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_bot": user.is_bot,
        "updated_at": time.time()
    }
    if USE_MONGO:
        try:
            users_col.update_one({"user_id": user.id}, {"$set": data}, upsert=True)
            return
        except Exception:
            pass
    with closing(sqlite_conn()) as con:
        con.execute("""INSERT INTO users
            (user_id,username,first_name,last_name,is_bot,updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username, first_name=excluded.first_name,
            last_name=excluded.last_name, is_bot=excluded.is_bot,
            updated_at=excluded.updated_at""",
            (user.id, user.username, user.first_name, user.last_name,
             int(user.is_bot), time.time()))
        con.commit()

def save_message_user(message):
    if message and message.from_user:
        save_user(message.from_user)

def all_user_ids():
    if USE_MONGO:
        try:
            return [x["user_id"] for x in users_col.find(
                {"is_bot": {"$ne": True}}, {"_id": 0, "user_id": 1}
            )]
        except Exception:
            pass
    with closing(sqlite_conn()) as con:
        rows = con.execute(
            "SELECT user_id FROM users WHERE is_bot=0"
        ).fetchall()
    return [x[0] for x in rows]

def user_count():
    return len(all_user_ids())

def remove_user(user_id):
    if USE_MONGO:
        try:
            users_col.delete_one({"user_id": user_id})
            return
        except Exception:
            pass
    with closing(sqlite_conn()) as con:
        con.execute("DELETE FROM users WHERE user_id=?", (user_id,))
        con.commit()

# ============================================================
#                      GROUP / ADMIN
# ============================================================

def is_group(message):
    return bool(
        message and message.chat and
        message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
    )

async def is_admin(message, user_id=None):
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
        member = await app.get_chat_member(message.chat.id, user_id)
        return member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER
        )
    except RPCError:
        return False

async def owner_only(message):
    return bool(message and message.from_user and
                message.from_user.id == OWNER_ID)

# ============================================================
#                         SETTINGS
# ============================================================

def get_setting(chat_id):
    if USE_MONGO:
        try:
            d = settings_col.find_one({"chat_id": chat_id})
            return bool(d.get("admin_edit", False)) if d else False
        except Exception:
            pass
    with closing(sqlite_conn()) as con:
        row = con.execute(
            "SELECT admin_edit FROM settings WHERE chat_id=?", (chat_id,)
        ).fetchone()
    return bool(row[0]) if row else False

def set_setting(chat_id, enabled):
    if USE_MONGO:
        try:
            settings_col.update_one(
                {"chat_id": chat_id},
                {"$set": {"chat_id": chat_id, "admin_edit": bool(enabled)}},
                upsert=True
            )
            return
        except Exception:
            pass
    with closing(sqlite_conn()) as con:
        con.execute("""INSERT INTO settings(chat_id,admin_edit) VALUES(?,?)
            ON CONFLICT(chat_id) DO UPDATE SET admin_edit=excluded.admin_edit""",
            (chat_id, int(enabled)))
        con.commit()

# ============================================================
#                       LOCAL AUTH
# ============================================================

def local_authed(chat_id, user_id):
    if USE_MONGO:
        try:
            return local_auth_col.find_one(
                {"chat_id": chat_id, "user_id": user_id}
            ) is not None
        except Exception:
            pass
    with closing(sqlite_conn()) as con:
        return con.execute("""SELECT 1 FROM local_auth
            WHERE chat_id=? AND user_id=?""",
            (chat_id, user_id)).fetchone() is not None

def add_local(chat_id, user_id):
    if USE_MONGO:
        try:
            local_auth_col.update_one(
                {"chat_id": chat_id, "user_id": user_id},
                {"$set": {"chat_id": chat_id, "user_id": user_id}},
                upsert=True
            )
            return
        except Exception:
            pass
    with closing(sqlite_conn()) as con:
        con.execute("INSERT OR IGNORE INTO local_auth(chat_id,user_id) VALUES(?,?)",
                    (chat_id, user_id))
        con.commit()

def remove_local(chat_id, user_id):
    if USE_MONGO:
        try:
            return local_auth_col.delete_one(
                {"chat_id": chat_id, "user_id": user_id}
            ).deleted_count
        except Exception:
            pass
    with closing(sqlite_conn()) as con:
        cur = con.execute(
            "DELETE FROM local_auth WHERE chat_id=? AND user_id=?",
            (chat_id, user_id))
        con.commit()
        return cur.rowcount

def clear_local(chat_id):
    if USE_MONGO:
        try:
            return local_auth_col.delete_many(
                {"chat_id": chat_id}
            ).deleted_count
        except Exception:
            pass
    with closing(sqlite_conn()) as con:
        cur = con.execute(
            "DELETE FROM local_auth WHERE chat_id=?", (chat_id,))
        con.commit()
        return cur.rowcount

def list_local(chat_id):
    if USE_MONGO:
        try:
            return [x["user_id"] for x in local_auth_col.find(
                {"chat_id": chat_id}, {"_id": 0, "user_id": 1}
            ).sort("user_id", 1)]
        except Exception:
            pass
    with closing(sqlite_conn()) as con:
        rows = con.execute(
            "SELECT user_id FROM local_auth WHERE chat_id=? ORDER BY user_id",
            (chat_id,)).fetchall()
    return [x[0] for x in rows]

# ============================================================
#                       GLOBAL AUTH
# ============================================================

def global_authed(user_id):
    if USE_MONGO:
        try:
            return global_auth_col.find_one({"user_id": user_id}) is not None
        except Exception:
            pass
    with closing(sqlite_conn()) as con:
        return con.execute(
            "SELECT 1 FROM global_auth WHERE user_id=?", (user_id,)
        ).fetchone() is not None

def add_global(user_id):
    if USE_MONGO:
        try:
            global_auth_col.update_one(
                {"user_id": user_id}, {"$set": {"user_id": user_id}}, upsert=True)
            return
        except Exception:
            pass
    with closing(sqlite_conn()) as con:
        con.execute("INSERT OR IGNORE INTO global_auth(user_id) VALUES(?)",
                    (user_id,))
        con.commit()

def remove_global(user_id):
    if USE_MONGO:
        try:
            return global_auth_col.delete_one({"user_id": user_id}).deleted_count
        except Exception:
            pass
    with closing(sqlite_conn()) as con:
        cur = con.execute("DELETE FROM global_auth WHERE user_id=?", (user_id,))
        con.commit()
        return cur.rowcount

def clear_global():
    if USE_MONGO:
        try:
            return global_auth_col.delete_many({}).deleted_count
        except Exception:
            pass
    with closing(sqlite_conn()) as con:
        cur = con.execute("DELETE FROM global_auth")
        con.commit()
        return cur.rowcount

def list_global():
    if USE_MONGO:
        try:
            return [x["user_id"] for x in global_auth_col.find(
                {}, {"_id": 0, "user_id": 1}).sort("user_id", 1)]
        except Exception:
            pass
    with closing(sqlite_conn()) as con:
        rows = con.execute(
            "SELECT user_id FROM global_auth ORDER BY user_id").fetchall()
    return [x[0] for x in rows]

# ============================================================
#                        USER RESOLVER
# ============================================================

def target_user(message):
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
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
        return (await app.get_users(target)).id
    except RPCError:
        return None

# ============================================================
#                         HELP TEXT
# ============================================================

HELP_TEXT = """
<b>📚 ʜᴇʟᴘ & ᴄᴏᴍᴍᴀɴᴅs ~</b>

<b>👑 ʟᴏᴄᴀʟ ᴀᴜᴛʜ ( ᴀᴅᴍɪɴ ᴏɴʟʏ )-</b>

<b>• <code>/auth</code> - ᴀᴜᴛʜᴏʀɪᴢᴇ ᴀ ᴜsᴇʀ</b>
<b>• <code>/unauth</code> - ʀᴇᴍᴏᴠᴇ ᴀᴜᴛʜ</b>
<b>• <code>/authusers</code> - ᴠɪᴇᴡ ᴀᴜᴛʜ ᴜsᴇʀs</b>
<b>• <code>/clearauthusers</code> - ᴄʟᴇᴀʀ ᴀʟʟ ᴀᴜᴛʜ ᴜsᴇʀs</b>

<b>🌐 ɢʟᴏʙᴀʟ ᴀᴜᴛʜ ( ᴏᴡɴᴇʀ ᴏɴʟʏ )-</b>

<b>• <code>/gauth</code> - ɢʟᴏʙᴀʟ ᴀᴜᴛʜ ᴜsᴇʀ</b>
<b>• <code>/gunauth</code> - ʀᴇᴍᴏᴠᴇ ɢʟᴏʙᴀʟ ᴀᴜᴛʜ</b>
<b>• <code>/gusers</code> - ᴠɪᴇᴡ ɢʟᴏʙᴀʟ ᴀᴜᴛʜ ᴜsᴇʀs</b>
<b>• <code>/cleargusers</code> - ᴄʟᴇᴀʀ ᴀʟʟ ɢʟᴏʙᴀʟ ᴀᴜᴛʜ ᴜsᴇʀs</b>

<b>🛡️ ᴇᴅɪᴛ ᴅᴇʟᴇᴛᴇ ( ᴀᴅᴍɪɴ ᴏɴʟʏ ) -</b>

<b>• <code>/adminedit on</code> - ᴅᴇʟᴇᴛᴇ ᴇᴅɪᴛs ғᴏʀ ᴀᴅᴍɪɴs</b>
<b>• <code>/adminedit off</code> - ɪɢɴᴏʀᴇ ᴀᴅᴍɪɴ ᴇᴅɪᴛs</b>
<b>• ᴅᴇғᴜʟᴛ : 🔴 ᴏғғ</b>

<b>📢 ʙʀᴏᴀᴅᴄᴀsᴛ ( ᴏᴡɴᴇʀ ᴏɴʟʏ )-</b>

<b>• <code>/broadcast MESSAGE</code></b>
<b>• ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴍᴇssᴀɢᴇ ᴛʜᴇɴ ᴜsᴇ <code>/broadcast</code></b>
<b>• <code>/broadcast_stats</code></b>

<b>📊 ᴏᴛʜᴇʀ -</b>

<b>• <code>/start</code> - ᴄʜᴇᴄᴋ ʙᴏᴛ ᴀʟɪᴠᴇ</b>
<b>• <code>/stats</code> - ᴄʜᴇᴄᴋ ʙᴏᴛ sᴛᴀᴛɪsᴛɪᴄs</b>
<b>• <code>/help</code> - ᴄʜᴇᴄᴋ ʙᴏᴛ ʜᴇʟᴘ</b>
<b>• <code>/id</code> - ʏᴏᴜʀ ᴛᴇʟᴇɢʀᴀᴍ ɪᴅ</b>

<b>⚡ ᴀᴅᴅ ᴍᴇ ɪɴ ʏᴏᴜʀ ɢʀᴏᴜᴘ ᴀɴᴅ ɢɪᴠᴇ ᴍᴇ
"ᴅᴇʟᴇᴛᴇ ᴍᴇssᴀɢᴇs" ᴘᴇʀᴍɪssɪᴏɴ.</b>

<b>✨ ᴋᴇᴇᴘ ʏᴏᴜʀ ɢʀᴏᴜᴘ ᴄʟᴇᴀɴ ᴀɴᴅ sᴀғᴇ
ʙʏ ᴅᴇᴛᴇᴄᴛɪɴɢ & ʀᴇᴍᴏᴠɪɴɢ ᴇᴅɪᴛᴇᴅ ᴍᴇssᴀɢᴇs ɪɴsᴛᴀɴᴛʟʏ.</b>
"""

# ============================================================
#                         START
# ============================================================

def start_text(user, bot):
    user_name = user.first_name or "User"
    bot_name = bot.first_name or "Edit Guardian Bot"

    user_mention = (
        f'<a href="tg://user?id={user.id}">{user_name}</a>'
    )

    # IMPORTANT: bot is NOT mentioned / linked.
    return f"""
<b>👋 ᴡᴇʟᴄᴏᴍᴇ {user_mention} 🇨🇦</b>

<b>ɪ'ᴍ {bot_name} [V2].</b>

<b>🚨 ɪ ᴄᴀɴ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ
ᴇᴅɪᴛᴇᴅ ᴍᴇssᴀɢᴇs
(ᴛᴇxᴛ & ᴍᴇᴅɪᴀ)</b>

<b>ᴀɴᴅ ɴᴏᴛɪғʏ ᴍᴇᴍʙᴇʀs
ᴡʜᴇɴ ᴀ ᴍᴇssᴀɢᴇ ɪs ʀᴇᴍᴏᴠᴇᴅ.</b>

<b>👍 ᴛᴇʟᴇɢʀᴀᴍ ʀᴇᴀᴄᴛɪᴏɴ
ᴇᴅɪᴛs ɪɢɴᴏʀᴇᴅ.</b>

<b>🛡️ ɪ'ʟʟ ᴋᴇᴇᴘ ʏᴏᴜʀ
ɢʀᴏᴜᴘ ᴄʟᴇᴀɴ & sᴀғᴇ.</b>

<b>⭐ ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ
ɢʀᴏᴜᴘ & ɢɪᴠᴇ ᴍᴇ
"ᴅᴇʟᴇᴛᴇ ᴍᴇssᴀɢᴇs"
ᴘᴇʀᴍɪssɪᴏɴ.</b>
"""

def start_buttons():
    rows = [[InlineKeyboardButton(
        "✚ ᴀᴅᴅ ᴍᴇ ɪɴ ʏᴏᴜʀ ɢʀᴏᴜᴘ ✚",
        url=f"https://t.me/{BOT_USERNAME}?startgroup=true"
    )]]

    contact_row = []
    if OWNER_USERNAME:
        contact_row.append(InlineKeyboardButton(
            "👑 ᴏᴡɴᴇʀ", url=f"https://t.me/{OWNER_USERNAME}"
        ))
    if SUPPORT_USERNAME:
        contact_row.append(InlineKeyboardButton(
            "🛠️ sᴜᴘᴘᴏʀᴛ", url=f"https://t.me/{SUPPORT_USERNAME}"
        ))
    if contact_row:
        rows.append(contact_row)

    rows.append([InlineKeyboardButton(
        "📚 ʜᴇʟᴘ & ᴄᴏᴍᴍᴀɴᴅs", callback_data="help"
    )])
    return InlineKeyboardMarkup(rows)

def home_buttons():
    rows = [[InlineKeyboardButton("🏠 ʜᴏᴍᴇ", callback_data="home")]]
    contact_row = []
    if OWNER_USERNAME:
        contact_row.append(InlineKeyboardButton(
            "👑 ᴏᴡɴᴇʀ", url=f"https://t.me/{OWNER_USERNAME}"
        ))
    if SUPPORT_USERNAME:
        contact_row.append(InlineKeyboardButton(
            "🛠️ sᴜᴘᴘᴏʀᴛ", url=f"https://t.me/{SUPPORT_USERNAME}"
        ))
    if contact_row:
        rows.append(contact_row)
    return InlineKeyboardMarkup(rows)

# ============================================================
#                       START LOGGER
# ============================================================

async def send_start_logger(user, bot):
    if not OWNER_ID:
        return
    username = f"@{user.username}" if user.username else "No Username"
    name = user.first_name or "Unknown"
    if user.last_name:
        name += f" {user.last_name}"

    text = (
        "<b>🔔 ɴᴇᴡ sᴛᴀʀᴛ</b>\n\n"
        f"👤 <b>ɴᴀᴍᴇ:</b> {name}\n"
        f"🔗 <b>ᴜsᴇʀɴᴀᴍᴇ:</b> {username}\n"
        f"🆔 <b>ɪᴅ:</b> <code>{user.id}</code>\n"
        f"🤖 <b>ʙᴏᴛ:</b> {bot.first_name or 'Kirti Guardian'}"
    )
    try:
        await app.send_message(OWNER_ID, text)
    except RPCError as e:
        log.warning("Start logger failed: %s", e)

# ============================================================
#                          START CMD
# ============================================================

@app.on_message(filters.command("start"))
async def start_cmd(_, message: Message):
    if not message.from_user:
        return

    save_message_user(message)
    stat_inc("starts")

    bot = await app.get_me()
    await send_start_logger(message.from_user, bot)

    text = start_text(message.from_user, bot)

    try:
        if START_IMAGE:
            await message.reply_photo(
                START_IMAGE,
                caption=text,
                reply_markup=start_buttons()
            )
            return
    except Exception as e:
        log.warning("Start image failed: %s", e)

    await message.reply_text(text, reply_markup=start_buttons())

# ============================================================
#                         HELP CALLBACK
# ============================================================

@app.on_message(filters.command("help"))
async def help_cmd(_, message: Message):
    save_message_user(message)
    await message.reply_text(HELP_TEXT, reply_markup=home_buttons())

@app.on_callback_query()
async def callbacks(_, query):
    try:
        if query.data == "help":
            await query.message.edit_text(
                HELP_TEXT, reply_markup=home_buttons()
            )
        elif query.data == "home":
            bot = await app.get_me()
            await query.message.edit_text(
                start_text(query.from_user, bot),
                reply_markup=start_buttons()
            )
        await query.answer()
    except Exception as e:
        log.warning("Callback error: %s", e)

# ============================================================
#                         AUTH COMMANDS
# ============================================================

@app.on_message(filters.command("auth"))
async def auth_cmd(_, message: Message):
    save_message_user(message)
    if not is_group(message):
        return await message.reply_text(
            "❌ <b>ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ᴡᴏʀᴋs ᴏɴʟʏ ɪɴ ɢʀᴏᴜᴘs.</b>"
        )
    if not await is_admin(message):
        return await message.reply_text(
            "❌ <b>ɢʀᴏᴜᴘ ᴏᴡɴᴇʀ / ᴀᴅᴍɪɴ ᴏɴʟʏ.</b>"
        )
    uid = await resolve_user(message)
    if not uid:
        return await message.reply_text(
            "❌ <b>ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴜsᴇʀ ᴏʀ ᴜsᴇ:</b> <code>/auth USER_ID</code>"
        )
    add_local(message.chat.id, uid)
    await message.reply_text(
        f"✅ <b>ᴜsᴇʀ <code>{uid}</code> ᴀᴜᴛʜᴏʀɪᴢᴇᴅ.</b>"
    )

@app.on_message(filters.command("unauth"))
async def unauth_cmd(_, message: Message):
    save_message_user(message)
    if not is_group(message):
        return await message.reply_text(
            "❌ <b>ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ᴡᴏʀᴋs ᴏɴʟʏ ɪɴ ɢʀᴏᴜᴘs.</b>"
        )
    if not await is_admin(message):
        return await message.reply_text(
            "❌ <b>ɢʀᴏᴜᴘ ᴏᴡɴᴇʀ / ᴀᴅᴍɪɴ ᴏɴʟʏ.</b>"
        )
    uid = await resolve_user(message)
    if not uid:
        return await message.reply_text(
            "❌ <b>ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴜsᴇʀ ᴏʀ ᴜsᴇ:</b> <code>/unauth USER_ID</code>"
        )
    removed = remove_local(message.chat.id, uid)
    await message.reply_text(
        f"✅ <b>ᴀᴜᴛʜ ʀᴇᴍᴏᴠᴇᴅ:</b> <code>{uid}</code>"
        if removed else f"ℹ️ <b>ᴜsᴇʀ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ:</b> <code>{uid}</code>"
    )

@app.on_message(filters.command("authusers"))
async def authusers_cmd(_, message: Message):
    if not is_group(message):
        return await message.reply_text(
            "❌ <b>ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ᴡᴏʀᴋs ᴏɴʟʏ ɪɴ ɢʀᴏᴜᴘs.</b>"
        )
    if not await is_admin(message):
        return await message.reply_text("❌ <b>ᴀᴅᴍɪɴ ᴏɴʟʏ.</b>")
    users = list_local(message.chat.id)
    if not users:
        return await message.reply_text("📭 <b>ɴᴏ ʟᴏᴄᴀʟ ᴀᴜᴛʜ ᴜsᴇʀs.</b>")
    await message.reply_text(
        "<b>👑 ʟᴏᴄᴀʟ ᴀᴜᴛʜ ᴜsᴇʀs</b>\n\n" +
        "\n".join(f"➤ <code>{u}</code>" for u in users)
    )

@app.on_message(filters.command("clearauthusers"))
async def clearauthusers_cmd(_, message: Message):
    if not is_group(message):
        return await message.reply_text(
            "❌ <b>ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ᴡᴏʀᴋs ᴏɴʟʏ ɪɴ ɢʀᴏᴜᴘs.</b>"
        )
    if not await is_admin(message):
        return await message.reply_text("❌ <b>ᴀᴅᴍɪɴ ᴏɴʟʏ.</b>")
    count = clear_local(message.chat.id)
    await message.reply_text(f"🧹 <b>ᴄʟᴇᴀʀᴇᴅ {count} ᴜsᴇʀ(s).</b>")

# ============================================================
#                      GLOBAL AUTH COMMANDS
# ============================================================

@app.on_message(filters.command("gauth"))
async def gauth_cmd(_, message: Message):
    if not await owner_only(message):
        return await message.reply_text("❌ <b>ᴏᴡɴᴇʀ ᴏɴʟʏ.</b>")
    uid = await resolve_user(message)
    if not uid:
        return await message.reply_text(
            "❌ <b>ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴜsᴇʀ ᴏʀ ᴜsᴇ:</b> <code>/gauth USER_ID</code>"
        )
    add_global(uid)
    await message.reply_text(f"🌐 <b>ɢʟᴏʙᴀʟ ᴀᴜᴛʜ ᴀᴅᴅᴇᴅ:</b> <code>{uid}</code>")

@app.on_message(filters.command("gunauth"))
async def gunauth_cmd(_, message: Message):
    if not await owner_only(message):
        return await message.reply_text("❌ <b>ᴏᴡɴᴇʀ ᴏɴʟʏ.</b>")
    uid = await resolve_user(message)
    if not uid:
        return await message.reply_text(
            "❌ <b>ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴜsᴇʀ ᴏʀ ᴜsᴇ:</b> <code>/gunauth USER_ID</code>"
        )
    removed = remove_global(uid)
    await message.reply_text(
        f"✅ <b>ɢʟᴏʙᴀʟ ᴀᴜᴛʜ ʀᴇᴍᴏᴠᴇᴅ:</b> <code>{uid}</code>"
        if removed else f"ℹ️ <b>ɴᴏᴛ ɢʟᴏʙᴀʟʟʏ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ.</b>"
    )

@app.on_message(filters.command("gusers"))
async def gusers_cmd(_, message: Message):
    if not await owner_only(message):
        return await message.reply_text("❌ <b>ᴏᴡɴᴇʀ ᴏɴʟʏ.</b>")
    users = list_global()
    if not users:
        return await message.reply_text("📭 <b>ɴᴏ ɢʟᴏʙᴀʟ ᴀᴜᴛʜ ᴜsᴇʀs.</b>")
    await message.reply_text(
        "<b>🌐 ɢʟᴏʙᴀʟ ᴀᴜᴛʜ ᴜsᴇʀs</b>\n\n" +
        "\n".join(f"➤ <code>{u}</code>" for u in users)
    )

@app.on_message(filters.command("cleargusers"))
async def cleargusers_cmd(_, message: Message):
    if not await owner_only(message):
        return await message.reply_text("❌ <b>ᴏᴡɴᴇʀ ᴏɴʟʏ.</b>")
    count = clear_global()
    await message.reply_text(f"🧹 <b>ᴄʟᴇᴀʀᴇᴅ {count} ɢʟᴏʙᴀʟ ᴜsᴇʀ(s).</b>")

# ============================================================
#                       ADMIN EDIT MODE
# ============================================================

@app.on_message(filters.command("adminedit"))
async def adminedit_cmd(_, message: Message):
    if not is_group(message):
        return await message.reply_text(
            "❌ <b>ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ᴡᴏʀᴋs ᴏɴʟʏ ɪɴ ɢʀᴏᴜᴘs.</b>"
        )
    if not await is_admin(message):
        return await message.reply_text("❌ <b>ᴀᴅᴍɪɴ ᴏɴʟʏ.</b>")

    parts = (message.text or "").split()
    if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
        current = "ON" if get_setting(message.chat.id) else "OFF"
        return await message.reply_text(
            f"🛡️ <b>ᴀᴅᴍɪɴ ᴇᴅɪᴛ ᴅᴇʟᴇᴛᴇ:</b> {current}\n\n"
            "<code>/adminedit on</code> or <code>/adminedit off</code>"
        )

    enabled = parts[1].lower() == "on"
    set_setting(message.chat.id, enabled)
    await message.reply_text(
        f"🛡️ <b>ᴀᴅᴍɪɴ ᴇᴅɪᴛ ᴅᴇʟᴇᴛᴇ:</b> "
        f"{'🟢 ON' if enabled else '🔴 OFF'}"
    )

# ============================================================
#                       EDIT GUARDIAN
# ============================================================

async def delete_quietly(message):
    try:
        await message.delete()
        stat_inc("deleted_edits")
        return True
    except FloodWait as e:
        await asyncio.sleep(e.value)
    except RPCError as e:
        log.debug("Delete error: %s", e)
    return False

@app.on_edited_message(filters.group)
async def edited_guard(_, message: Message):
    if not message.from_user or message.from_user.is_bot:
        return

    uid = message.from_user.id

    # Authorized users are always exempt.
    if local_authed(message.chat.id, uid) or global_authed(uid):
        return

    try:
        member = await app.get_chat_member(message.chat.id, uid)
        status = member.status
    except RPCError:
        status = None

    # Normal members: delete edited messages.
    # Admin/owner: delete only when /adminedit on.
    if status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        if not get_setting(message.chat.id):
            return

    deleted = await delete_quietly(message)

    if deleted:
        try:
            await app.send_message(
                message.chat.id,
                f"⚠️ <b>ᴇᴅɪᴛᴇᴅ ᴍᴇssᴀɢᴇ ʀᴇᴍᴏᴠᴇᴅ.</b>\n"
                f"👤 <a href='tg://user?id={uid}'>ᴜsᴇʀ</a>: "
                f"<code>{uid}</code>"
            )
        except RPCError:
            pass

# ============================================================
#                          BROADCAST
# ============================================================

async def broadcast_to_users(source_message=None, text=None):
    sent = failed = 0
    ids = all_user_ids()

    for uid in ids:
        try:
            if source_message:
                await source_message.copy(chat_id=uid)
            else:
                await app.send_message(uid, text)
            sent += 1
            await asyncio.sleep(0.05)
        except FloodWait as e:
            await asyncio.sleep(e.value)
            try:
                if source_message:
                    await source_message.copy(chat_id=uid)
                else:
                    await app.send_message(uid, text)
                sent += 1
            except Exception:
                failed += 1
        except RPCError:
            failed += 1
            remove_user(uid)

    stat_inc("broadcast_sent", sent)
    stat_inc("broadcast_failed", failed)
    return sent, failed, len(ids)

@app.on_message(filters.command("broadcast"))
async def broadcast_cmd(_, message: Message):
    if not await owner_only(message):
        return await message.reply_text("❌ <b>ᴏᴡɴᴇʀ ᴏɴʟʏ.</b>")

    source = message.reply_to_message
    text = None

    if not source:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            return await message.reply_text(
                "📢 <b>ᴜsᴇ:</b> <code>/broadcast MESSAGE</code>\n"
                "ᴏʀ ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴍᴇssᴀɢᴇ ᴡɪᴛʜ <code>/broadcast</code>"
            )
        text = parts[1]

    status_msg = await message.reply_text(
        "📢 <b>ʙʀᴏᴀᴅᴄᴀsᴛ sᴛᴀʀᴛᴇᴅ...</b>"
    )

    sent, failed, total = await broadcast_to_users(source, text)

    await status_msg.edit_text(
        "<b>📢 ʙʀᴏᴀᴅᴄᴀsᴛ ᴄᴏᴍᴘʟᴇᴛᴇ</b>\n\n"
        f"👥 <b>ᴛᴏᴛᴀʟ:</b> <code>{total}</code>\n"
        f"✅ <b>sᴇɴᴛ:</b> <code>{sent}</code>\n"
        f"❌ <b>ғᴀɪʟᴇᴅ:</b> <code>{failed}</code>"
    )

@app.on_message(filters.command("broadcast_stats"))
async def broadcast_stats_cmd(_, message: Message):
    if not await owner_only(message):
        return await message.reply_text("❌ <b>ᴏᴡɴᴇʀ ᴏɴʟʏ.</b>")
    await message.reply_text(
        "<b>📢 ʙʀᴏᴀᴅᴄᴀsᴛ sᴛᴀᴛs</b>\n\n"
        f"👥 <b>ᴜsᴇʀs:</b> <code>{user_count()}</code>\n"
        f"✅ <b>sᴇɴᴛ:</b> <code>{get_stat('broadcast_sent')}</code>\n"
        f"❌ <b>ғᴀɪʟᴇᴅ:</b> <code>{get_stat('broadcast_failed')}</code>"
    )

# ============================================================
#                           STATS / ID
# ============================================================

@app.on_message(filters.command("stats"))
async def stats_cmd(_, message: Message):
    if not (await owner_only(message) or await is_admin(message)):
        return await message.reply_text("❌ <b>ᴀᴅᴍɪɴ / ᴏᴡɴᴇʀ ᴏɴʟʏ.</b>")
    text = (
        "<b>📊 ʙᴏᴛ sᴛᴀᴛɪsᴛɪᴄs</b>\n\n"
        f"▶️ <b>sᴛᴀʀᴛs:</b> <code>{get_stat('starts')}</code>\n"
        f"🗑️ <b>ᴅᴇʟᴇᴛᴇᴅ ᴇᴅɪᴛs:</b> <code>{get_stat('deleted_edits')}</code>\n"
        f"👥 <b>ᴜsᴇʀs:</b> <code>{user_count()}</code>\n"
        f"📢 <b>ʙʀᴏᴀᴅᴄᴀsᴛ sᴇɴᴛ:</b> <code>{get_stat('broadcast_sent')}</code>\n"
        f"❌ <b>ʙʀᴏᴀᴅᴄᴀsᴛ ғᴀɪʟᴇᴅ:</b> <code>{get_stat('broadcast_failed')}</code>"
    )
    if is_group(message):
        text += (
            f"\n🛡️ <b>ᴀᴅᴍɪɴ ᴇᴅɪᴛ:</b> "
            f"{'🟢 ON' if get_setting(message.chat.id) else '🔴 OFF'}"
        )
    await message.reply_text(text)

@app.on_message(filters.private & filters.command("id"))
async def id_cmd(_, message: Message):
    if message.from_user:
        await message.reply_text(
            f"🆔 <b>ʏᴏᴜʀ ᴛᴇʟᴇɢʀᴀᴍ ɪᴅ:</b> <code>{message.from_user.id}</code>"
        )

# ============================================================
#                           STARTUP
# ============================================================

if __name__ == "__main__":
    init_database()
    log.info("Kirti Guardian Bot starting...")
    app.run()
