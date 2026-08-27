import os
import sqlite3
import logging
from contextlib import closing

from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from pyrogram.errors import RPCError, FloodWait


# ============================================================
# KIRTI GUARDIAN BOT [V2]
# EDITED MESSAGE PROTECTION BOT
# ============================================================

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# Start image
START_IMAGE = os.getenv("START_IMAGE", "").strip() or "start.jpg"

# Database
DB_PATH = os.getenv("DB_PATH", "guardian.db")

# Telegram usernames
BOT_USERNAME = os.getenv(
    "BOT_USERNAME",
    "KirtiGuardianBot"
).lstrip("@")

OWNER_USERNAME = os.getenv(
    "OWNER_USERNAME",
    "Kirti_Updates"
).lstrip("@")

SUPPORT_USERNAME = os.getenv(
    "SUPPORT_USERNAME",
    "Kirti_Updates"
).lstrip("@")


# ============================================================
# ENVIRONMENT CHECK
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
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

log = logging.getLogger("KirtiGuardianBot")


# ============================================================
# PYROGRAM CLIENT
# ============================================================

app = Client(
    "kirti_guardian_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="."
)


# ============================================================
# DATABASE
# ============================================================

def db():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30
    )

    conn.execute(
        "PRAGMA journal_mode=WAL"
    )

    return conn


def init_db():

    with closing(db()) as con:

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
                admin_edit INTEGER NOT NULL DEFAULT 0
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            )
        """)

        con.commit()


# ============================================================
# STATS DATABASE
# ============================================================

def stat_inc(key, amount=1):

    with closing(db()) as con:

        con.execute("""
            INSERT INTO stats(key, value)
            VALUES(?, ?)

            ON CONFLICT(key)
            DO UPDATE SET value = value + excluded.value
        """, (key, amount))

        con.commit()


def get_stats():

    with closing(db()) as con:

        rows = con.execute(
            "SELECT key, value FROM stats"
        ).fetchall()

    return dict(rows)


# ============================================================
# SETTINGS
# ============================================================

def get_setting(chat_id):

    with closing(db()) as con:

        row = con.execute(
            """
            SELECT admin_edit
            FROM settings
            WHERE chat_id=?
            """,
            (chat_id,)
        ).fetchone()

    return bool(row[0]) if row else False


def set_setting(chat_id, enabled):

    with closing(db()) as con:

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
# LOCAL AUTH
# ============================================================

def local_authed(chat_id, user_id):

    with closing(db()) as con:

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


def add_local(chat_id, user_id):

    with closing(db()) as con:

        con.execute(
            """
            INSERT OR IGNORE INTO local_auth(
                chat_id,
                user_id
            )
            VALUES(?, ?)
            """,
            (
                chat_id,
                user_id
            )
        )

        con.commit()


def remove_local(chat_id, user_id):

    with closing(db()) as con:

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

    with closing(db()) as con:

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

    with closing(db()) as con:

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
# GLOBAL AUTH
# ============================================================

def global_authed(user_id):

    with closing(db()) as con:

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

    with closing(db()) as con:

        con.execute(
            """
            INSERT OR IGNORE INTO global_auth(user_id)
            VALUES(?)
            """,
            (user_id,)
        )

        con.commit()


def remove_global(user_id):

    with closing(db()) as con:

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

    with closing(db()) as con:

        cur = con.execute(
            "DELETE FROM global_auth"
        )

        con.commit()

        return cur.rowcount


def list_global():

    with closing(db()) as con:

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
# HELPERS
# ============================================================

def is_group(message):

    return bool(
        message.chat
        and message.chat.type in (
            "group",
            "supergroup"
        )
    )


async def is_admin(message, user_id=None):

    if not message.from_user and user_id is None:
        return False

    user_id = user_id or message.from_user.id

    # Bot owner
    if user_id == OWNER_ID:
        return True

    # Only groups
    if not is_group(message):
        return False

    try:

        member = await app.get_chat_member(
            message.chat.id,
            user_id
        )

        return member.status in (
            "administrator",
            "owner"
        )

    except RPCError as e:

        log.warning(
            "Admin check failed: %s",
            e
        )

        return False


async def admin_only(message):

    return await is_admin(message)


async def owner_only(message):

    return bool(
        message.from_user
        and message.from_user.id == OWNER_ID
    )


# ============================================================
# TARGET USER
# ============================================================

def target_user(message):

    # Reply user
    if (
        message.reply_to_message
        and message.reply_to_message.from_user
    ):

        return message.reply_to_message.from_user.id

    # Command argument
    parts = (
        message.text or ""
    ).split(
        maxsplit=1
    )

    if len(parts) != 2:
        return None

    raw = parts[1].strip()

    # Numeric ID
    if raw.isdigit():
        return int(raw)

    # Username
    return raw.lstrip("@")


async def resolve_user(message):

    target = target_user(message)

    if target is None:
        return None

    # Already ID
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
# DELETE MESSAGE
# ============================================================

async def delete_quietly(message):

    try:

        await message.delete()

        stat_inc(
            "deleted_edits"
        )

        return True

    except FloodWait as e:

        await app.sleep(
            e.value
        )

    except RPCError as e:

        log.debug(
            "Delete RPC error: %s",
            e
        )

    except Exception as e:

        log.warning(
            "Delete error: %s",
            e
        )

    return False


# ============================================================
# START TEXT
# ============================================================

START_TEXT = """
╭━━━━━━━━━━━━━━━━━━━━━━╮
      🛡️ <b>𝐊𝐈𝐑𝐓𝐈 𝐆𝐔𝐀𝐑𝐃𝐈𝐀𝐍</b>
          <i>𝐁𝐎𝐓 [𝐕𝟐]</i>
╰━━━━━━━━━━━━━━━━━━━━━━╯

👋 <b>𝐖𝐄𝐋𝐂𝐎𝐌𝐄 — 𝐁𝐀𝐃𝐍𝐀𝐌 !! 🇨🇦</b>

🤖 <b>𝐈'𝐌 𝐊𝐈𝐑𝐓𝐈 𝐆𝐔𝐀𝐑𝐃𝐈𝐀𝐍</b>

🚨 <b>𝐈 𝐂𝐀𝐍 𝐀𝐔𝐓𝐎-𝐃𝐄𝐋𝐄𝐓𝐄</b>
<b>𝐄𝐃𝐈𝐓𝐄𝐃 𝐌𝐄𝐒𝐒𝐀𝐆𝐄𝐒</b>
<b>(𝐓𝐄𝐗𝐓 & 𝐌𝐄𝐃𝐈𝐀)</b>

🔔 <b>𝐌𝐄𝐌𝐁𝐄𝐑𝐒 𝐀𝐑𝐄 𝐍𝐎𝐓𝐈𝐅𝐈𝐄𝐃</b>
<b>𝐖𝐇𝐄𝐍 𝐀 𝐌𝐄𝐒𝐒𝐀𝐆𝐄 𝐈𝐒 𝐑𝐄𝐌𝐎𝐕𝐄𝐃.</b>

👍 <b>𝐓𝐄𝐋𝐄𝐆𝐑𝐀𝐌 𝐑𝐄𝐀𝐂𝐓𝐈𝐎𝐍 𝐄𝐃𝐈𝐓𝐒</b>
<b>𝐀𝐑𝐄 𝐈𝐆𝐍𝐎𝐑𝐄𝐃.</b>

🛡️ <b>𝐈'𝐋𝐋 𝐊𝐄𝐄𝐏 𝐘𝐎𝐔𝐑 𝐆𝐑𝐎𝐔𝐏</b>
<b>𝐂𝐋𝐄𝐀𝐍 & 𝐒𝐀𝐅𝐄.</b>

⭐ <b>𝐀𝐃𝐃 𝐌𝐄 𝐓𝐎 𝐘𝐎𝐔𝐑 𝐆𝐑𝐎𝐔𝐏</b>
<b>𝐀𝐍𝐃 𝐆𝐈𝐕𝐄 𝐌𝐄 𝐃𝐄𝐋𝐄𝐓𝐄 𝐌𝐄𝐒𝐒𝐀𝐆𝐄𝐒</b>
<b>𝐏𝐄𝐑𝐌𝐈𝐒𝐒𝐈𝐎𝐍.</b>

━━━━━━━━━━━━━━━━━━━━━━

💎 <b>𝐏𝐎𝐖𝐄𝐑𝐄𝐃 𝐁𝐘 𝐊𝐈𝐑𝐓𝐈 𝐁𝐎𝐓𝐒</b>
❤️ <i>𝐌𝐀𝐃𝐄 𝐅𝐎𝐑 𝐓𝐄𝐋𝐄𝐆𝐑𝐀𝐌</i>
"""


# ============================================================
# HELP TEXT
# ============================================================

HELP_TEXT = """
╭━━━━━━━━━━━━━━━━━━━━━━╮
      📚 <b>𝐇𝐄𝐋𝐏 & 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒</b>
╰━━━━━━━━━━━━━━━━━━━━━━╯

👑 <b>𝐋𝐎𝐂𝐀𝐋 𝐀𝐔𝐓𝐇</b>
<i>𝐆𝐫𝐨𝐮𝐩 𝐎𝐰𝐧𝐞𝐫 / 𝐀𝐝𝐦𝐢𝐧 𝐎𝐧𝐥𝐲</i>

➤ <code>/auth</code> — 𝐀𝐮𝐭𝐡𝐨𝐫𝐢𝐳𝐞 𝐔𝐬𝐞𝐫
➤ <code>/unauth</code> — 𝐑𝐞𝐦𝐨𝐯𝐞 𝐀𝐮𝐭𝐡
➤ <code>/authusers</code> — 𝐀𝐮𝐭𝐡 𝐔𝐬𝐞𝐫𝐬
➤ <code>/clearauthusers</code> — 𝐂𝐥𝐞𝐚𝐫 𝐀𝐥𝐥

🌐 <b>𝐆𝐋𝐎𝐁𝐀𝐋 𝐀𝐔𝐓𝐇</b>
<i>𝐁𝐨𝐭 𝐎𝐰𝐧𝐞𝐫 𝐎𝐧𝐥𝐲</i>

➤ <code>/gauth</code> — 𝐆𝐥𝐨𝐛𝐚𝐥 𝐀𝐮𝐭𝐡
➤ <code>/gunauth</code> — 𝐑𝐞𝐦𝐨𝐯𝐞 𝐆𝐥𝐨𝐛𝐚𝐥
➤ <code>/gusers</code> — 𝐆𝐥𝐨𝐛𝐚𝐥 𝐔𝐬𝐞𝐫𝐬
➤ <code>/cleargusers</code> — 𝐂𝐥𝐞𝐚𝐫 𝐀𝐥𝐥

🛡️ <b>𝐄𝐃𝐈𝐓 𝐏𝐑𝐎𝐓𝐄𝐂𝐓𝐈𝐎𝐍</b>

➤ <code>/adminedit on</code>
   𝐄𝐧𝐚𝐛𝐥𝐞 𝐀𝐝𝐦𝐢𝐧 𝐄𝐝𝐢𝐭 𝐃𝐞𝐥𝐞𝐭𝐢𝐨𝐧

➤ <code>/adminedit off</code>
   𝐃𝐢𝐬𝐚𝐛𝐥𝐞 𝐀𝐝𝐦𝐢𝐧 𝐄𝐝𝐢𝐭 𝐃𝐞𝐥𝐞𝐭𝐢𝐨𝐧

📊 <b>𝐎𝐓𝐇𝐄𝐑</b>

➤ <code>/start</code> — 𝐒𝐭𝐚𝐫𝐭
➤ <code>/stats</code> — 𝐒𝐭𝐚𝐭𝐢𝐬𝐭𝐢𝐜𝐬
➤ <code>/id</code> — 𝐓𝐞𝐥𝐞𝐠𝐫𝐚𝐦 𝐈𝐃

━━━━━━━━━━━━━━━━━━━━━━

⚡ <b>𝐆𝐈𝐕𝐄 𝐌𝐄 𝐃𝐄𝐋𝐄𝐓𝐄 𝐌𝐄𝐒𝐒𝐀𝐆𝐄𝐒</b>
<b>𝐏𝐄𝐑𝐌𝐈𝐒𝐒𝐈𝐎𝐍 𝐓𝐎 𝐏𝐑𝐎𝐓𝐄𝐂𝐓 𝐘𝐎𝐔𝐑 𝐆𝐑𝐎𝐔𝐏.</b>
"""


# ============================================================
# START BUTTONS
# ============================================================

def start_buttons():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✚ 𝐀𝐃𝐃 𝐌𝐄 𝐈𝐍 𝐘𝐎𝐔𝐑 𝐆𝐑𝐎𝐔𝐏 ✚",
                    url=(
                        f"https://t.me/"
                        f"{BOT_USERNAME}"
                        f"?startgroup=true"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "💬 𝐎𝐖𝐍𝐄𝐑",
                    url=(
                        f"https://t.me/"
                        f"{OWNER_USERNAME}"
                    )
                ),
                InlineKeyboardButton(
                    "👨‍💼 𝐒𝐔𝐏𝐏𝐎𝐑𝐓",
                    url=(
                        f"https://t.me/"
                        f"{SUPPORT_USERNAME}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "📚 𝐇𝐄𝐋𝐏 & 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒",
                    callback_data="help"
                )
            ]
        ]
    )


# ============================================================
# HOME BUTTONS
# ============================================================

def home_buttons():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📚 𝐇𝐄𝐋𝐏",
                    callback_data="help"
                ),
                InlineKeyboardButton(
                    "🛡️ 𝐒𝐓𝐀𝐓𝐔𝐒",
                    callback_data="status"
                )
            ],
            [
                InlineKeyboardButton(
                    "✚ 𝐀𝐃𝐃 𝐌𝐄 𝐈𝐍 𝐘𝐎𝐔𝐑 𝐆𝐑𝐎𝐔𝐏 ✚",
                    url=(
                        f"https://t.me/"
                        f"{BOT_USERNAME}"
                        f"?startgroup=true"
                    )
                )
            ]
        ]
    )


# ============================================================
# START COMMAND
# ============================================================

@app.on_message(filters.command("start"))
async def start_cmd(_, message: Message):

    stat_inc("starts")

    buttons = start_buttons()

    if START_IMAGE:

        try:

            await message.reply_photo(
                photo=START_IMAGE,
                caption=START_TEXT,
                reply_markup=buttons
            )

            return

        except Exception as e:

            log.warning(
                "Start image failed: %s",
                e
            )

    await message.reply_text(
        START_TEXT,
        reply_markup=buttons
    )


# ============================================================
# HELP COMMAND
# ============================================================

@app.on_message(filters.command("help"))
async def help_cmd(_, message: Message):

    buttons = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🏠 𝐇𝐎𝐌𝐄",
                    callback_data="home"
                ),
                InlineKeyboardButton(
                    "🛡️ 𝐒𝐓𝐀𝐓𝐔𝐒",
                    callback_data="status"
                )
            ]
        ]
    )

    await message.reply_text(
        HELP_TEXT,
        reply_markup=buttons,
        disable_web_page_preview=True
    )


# ============================================================
# CALLBACK BUTTONS
# ============================================================

@app.on_callback_query()
async def callbacks(_, query):

    try:

        # ----------------------------------------------------
        # HELP
        # ----------------------------------------------------

        if query.data == "help":

            buttons = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🏠 𝐇𝐎𝐌𝐄",
                            callback_data="home"
                        ),
                        InlineKeyboardButton(
                            "🛡️ 𝐒𝐓𝐀𝐓𝐔𝐒",
                            callback_data="status"
                        )
                    ]
                ]
            )

            # Start message is photo message
            if query.message.photo:

                await query.message.edit_caption(
                    caption=HELP_TEXT,
                    reply_markup=buttons
                )

            else:

                await query.message.edit_text(
                    HELP_TEXT,
                    reply_markup=buttons
                )

            await query.answer()

            return

        # ----------------------------------------------------
        # HOME
        # ----------------------------------------------------

        if query.data == "home":

            buttons = start_buttons()

            if query.message.photo:

                await query.message.edit_caption(
                    caption=START_TEXT,
                    reply_markup=buttons
                )

            else:

                await query.message.edit_text(
                    START_TEXT,
                    reply_markup=buttons
                )

            await query.answer()

            return

        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

        if query.data == "status":

            text = (
                "╭━━━━━━━━━━━━━━━━━━━━━━╮\n"
                "      🛡️ <b>𝐁𝐎𝐓 𝐒𝐓𝐀𝐓𝐔𝐒</b>\n"
                "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
                "🟢 <b>𝐁𝐎𝐓:</b> 𝐎𝐍𝐋𝐈𝐍𝐄\n"
                f"👑 <b>𝐎𝐖𝐍𝐄𝐑 𝐈𝐃:</b> "
                f"<code>{OWNER_ID}</code>\n"
            )

            if (
                query.message.chat
                and query.message.chat.type
                in (
                    "group",
                    "supergroup"
                )
            ):

                enabled = get_setting(
                    query.message.chat.id
                )

                text += (
                    "🛡️ <b>𝐀𝐃𝐌𝐈𝐍 𝐄𝐃𝐈𝐓:</b> "
                    f"<b>{'🟢 ON' if enabled else '🔴 OFF'}</b>"
                )

            else:

                text += (
                    "🛡️ <b>𝐄𝐃𝐈𝐓 𝐃𝐄𝐋𝐄𝐓𝐄:</b> "
                    "<b>𝐑𝐄𝐀𝐃𝐘</b>"
                )

            buttons = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🏠 𝐇𝐎𝐌𝐄",
                            callback_data="home"
                        ),
                        InlineKeyboardButton(
                            "📚 𝐇𝐄𝐋𝐏",
                            callback_data="help"
                        )
                    ]
                ]
            )

            if query.message.photo:

                await query.message.edit_caption(
                    caption=text,
                    reply_markup=buttons
                )

            else:

                await query.message.edit_text(
                    text,
                    reply_markup=buttons
                )

            await query.answer()

            return

        await query.answer()

    except Exception as e:

        log.warning(
            "Callback error: %s",
            e
        )

        try:
            await query.answer(
                "Something went wrong."
            )
        except Exception:
            pass


# ============================================================
# LOCAL AUTH
# ============================================================

@app.on_message(filters.command("auth"))
async def auth_cmd(_, message: Message):

    if not await admin_only(message):

        return await message.reply_text(
            "❌ <b>Admin / Owner Only.</b>"
        )

    if not is_group(message):

        return await message.reply_text(
            "❌ This command works only in groups."
        )

    uid = await resolve_user(message)

    if not uid:

        return await message.reply_text(
            "❌ Reply to a user or use:\n"
            "<code>/auth USER_ID</code>"
        )

    add_local(
        message.chat.id,
        uid
    )

    await message.reply_text(
        "╭━━━━━━━━━━━━━━━━━━━━╮\n"
        "      👑 <b>𝐋𝐎𝐂𝐀𝐋 𝐀𝐔𝐓𝐇</b>\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"✅ User <code>{uid}</code>\n"
        "has been authorized."
    )


# ============================================================
# LOCAL UNAUTH
# ============================================================

@app.on_message(filters.command("unauth"))
async def unauth_cmd(_, message: Message):

    if not await admin_only(message):

        return await message.reply_text(
            "❌ <b>Admin / Owner Only.</b>"
        )

    if not is_group(message):

        return await message.reply_text(
            "❌ This command works only in groups."
        )

    uid = await resolve_user(message)

    if not uid:

        return await message.reply_text(
            "❌ Reply to a user or use:\n"
            "<code>/unauth USER_ID</code>"
        )

    removed = remove_local(
        message.chat.id,
        uid
    )

    if removed:

        text = (
            f"✅ User <code>{uid}</code>\n"
            "local authorization removed."
        )

    else:

        text = (
            f"ℹ️ User <code>{uid}</code>\n"
            "was not locally authorized."
        )

    await message.reply_text(text)


# ============================================================
# AUTH USERS
# ============================================================

@app.on_message(filters.command("authusers"))
async def authusers_cmd(_, message: Message):

    if not await admin_only(message):

        return await message.reply_text(
            "❌ <b>Admin / Owner Only.</b>"
        )

    if not is_group(message):

        return await message.reply_text(
            "❌ This command works only in groups."
        )

    users = list_local(
        message.chat.id
    )

    if not users:

        return await message.reply_text(
            "📭 <b>No local authorized users.</b>"
        )

    text = (
        "╭━━━━━━━━━━━━━━━━━━━━╮\n"
        "      👑 <b>𝐋𝐎𝐂𝐀𝐋 𝐀𝐔𝐓𝐇</b>\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
    )

    text += "\n".join(
        f"➤ <code>{uid}</code>"
        for uid in users
    )

    await message.reply_text(text)


# ============================================================
# CLEAR LOCAL AUTH
# ============================================================

@app.on_message(filters.command("clearauthusers"))
async def clearauthusers_cmd(_, message: Message):

    if not await admin_only(message):

        return await message.reply_text(
            "❌ <b>Admin / Owner Only.</b>"
        )

    if not is_group(message):

        return await message.reply_text(
            "❌ This command works only in groups."
        )

    count = clear_local(
        message.chat.id
    )

    await message.reply_text(
        f"🧹 Cleared <b>{count}</b> "
        "local authorized user(s)."
    )


# ============================================================
# GLOBAL AUTH
# ============================================================

@app.on_message(filters.command("gauth"))
async def gauth_cmd(_, message: Message):

    if not await owner_only(message):

        return await message.reply_text(
            "❌ <b>Bot Owner Only.</b>"
        )

    uid = await resolve_user(message)

    if not uid:

        return await message.reply_text(
            "❌ Reply to a user or use:\n"
            "<code>/gauth USER_ID</code>"
        )

    add_global(uid)

    await message.reply_text(
        f"🌐 User <code>{uid}</code>\n"
        "has been globally authorized."
    )


# ============================================================
# GLOBAL UNAUTH
# ============================================================

@app.on_message(filters.command("gunauth"))
async def gunauth_cmd(_, message: Message):

    if not await owner_only(message):

        return await message.reply_text(
            "❌ <b>Bot Owner Only.</b>"
        )

    uid = await resolve_user(message)

    if not uid:

        return await message.reply_text(
            "❌ Reply to a user or use:\n"
            "<code>/gunauth USER_ID</code>"
        )

    removed = remove_global(
        uid
    )

    if removed:

        text = (
            f"✅ Global authorization removed "
            f"from <code>{uid}</code>."
        )

    else:

        text = (
            f"ℹ️ User <code>{uid}</code> "
            "was not globally authorized."
        )

    await message.reply_text(text)


# ============================================================
# GLOBAL USERS
# ============================================================

@app.on_message(filters.command("gusers"))
async def gusers_cmd(_, message: Message):

    if not await owner_only(message):

        return await message.reply_text(
            "❌ <b>Bot Owner Only.</b>"
        )

    users = list_global()

    if not users:

        return await message.reply_text(
            "📭 <b>No global authorized users.</b>"
        )

    text = (
        "╭━━━━━━━━━━━━━━━━━━━━╮\n"
        "      🌐 <b>𝐆𝐋𝐎𝐁𝐀𝐋 𝐀𝐔𝐓𝐇</b>\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
    )

    text += "\n".join(
        f"➤ <code>{uid}</code>"
        for uid in users
    )

    await message.reply_text(text)


# ============================================================
# CLEAR GLOBAL USERS
# ============================================================

@app.on_message(filters.command("cleargusers"))
async def cleargusers_cmd(_, message: Message):

    if not await owner_only(message):

        return await message.reply_text(
            "❌ <b>Bot Owner Only.</b>"
        )

    count = clear_global()

    await message.reply_text(
        f"🧹 Cleared <b>{count}</b> "
        "global authorized user(s)."
    )


# ============================================================
# ADMIN EDIT
# ============================================================

@app.on_message(filters.command("adminedit"))
async def adminedit_cmd(_, message: Message):

    if not await admin_only(message):

        return await message.reply_text(
            "❌ <b>Admin / Owner Only.</b>"
        )

    if not is_group(message):

        return await message.reply_text(
            "❌ This command works only in groups."
        )

    parts = (
        message.text or ""
    ).split()

    if (
        len(parts) < 2
        or parts[1].lower()
        not in (
            "on",
            "off"
        )
    ):

        current = (
            "🟢 ON"
            if get_setting(message.chat.id)
            else "🔴 OFF"
        )

        return await message.reply_text(
            "🛡️ <b>𝐀𝐃𝐌𝐈𝐍 𝐄𝐃𝐈𝐓 𝐃𝐄𝐋𝐄𝐓𝐄</b>\n\n"
            f"Current: <b>{current}</b>\n\n"
            "Use:\n"
            "<code>/adminedit on</code>\n"
            "<code>/adminedit off</code>"
        )

    enabled = (
        parts[1].lower()
        == "on"
    )

    set_setting(
        message.chat.id,
        enabled
    )

    await message.reply_text(
        "🛡️ <b>𝐀𝐃𝐌𝐈𝐍 𝐄𝐃𝐈𝐓 𝐃𝐄𝐋𝐄𝐓𝐄</b>\n\n"
        f"Status: <b>{'🟢 ON' if enabled else '🔴 OFF'}</b>"
    )


# ============================================================
# EDITED MESSAGE GUARD
# ============================================================
#
# IMPORTANT:
# filters.supergroup DOES NOT EXIST.
#
# filters.group handles:
#   • Normal Groups
#   • Supergroups
#
# ============================================================

@app.on_edited_message(filters.group)
async def edited_guard(_, message: Message):

    if not message.from_user:
        return

    uid = message.from_user.id

    # Ignore bot messages
    if message.from_user.is_bot:
        return

    # --------------------------------------------------------
    # LOCAL AUTH
    # --------------------------------------------------------

    if local_authed(
        message.chat.id,
        uid
    ):
        return

    # --------------------------------------------------------
    # GLOBAL AUTH
    # --------------------------------------------------------

    if global_authed(uid):
        return

    # --------------------------------------------------------
    # GET MEMBER STATUS
    # --------------------------------------------------------

    try:

        member = await app.get_chat_member(
            message.chat.id,
            uid
        )

        status = member.status

    except RPCError as e:

        log.debug(
            "Member check failed: %s",
            e
        )

        status = None

    # --------------------------------------------------------
    # ADMIN / OWNER
    # --------------------------------------------------------

    if status in (
        "administrator",
        "owner"
    ):

        # Admin edits are ignored by default.
        if not get_setting(
            message.chat.id
        ):
            return

        await delete_quietly(
            message
        )

        return

    # --------------------------------------------------------
    # NORMAL MEMBER
    # --------------------------------------------------------

    await delete_quietly(
        message
    )


# ============================================================
# STATS
# ============================================================

@app.on_message(filters.command("stats"))
async def stats_cmd(_, message: Message):

    if not (
        await owner_only(message)
        or await admin_only(message)
    ):

        return await message.reply_text(
            "❌ <b>Admin / Owner Only.</b>"
        )

    rows = get_stats()

    starts = rows.get(
        "starts",
        0
    )

    deleted = rows.get(
        "deleted_edits",
        0
    )

    text = (
        "╭━━━━━━━━━━━━━━━━━━━━╮\n"
        "      📊 <b>𝐊𝐈𝐑𝐓𝐈 𝐒𝐓𝐀𝐓𝐒</b>\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"▶️ <b>𝐒𝐓𝐀𝐑𝐓𝐒:</b> "
        f"<code>{starts}</code>\n"
        f"🗑️ <b>𝐃𝐄𝐋𝐄𝐓𝐄𝐃 𝐄𝐃𝐈𝐓𝐒:</b> "
        f"<code>{deleted}</code>\n"
    )

    if is_group(message):

        enabled = get_setting(
            message.chat.id
        )

        text += (
            "🛡️ <b>𝐀𝐃𝐌𝐈𝐍 𝐄𝐃𝐈𝐓:</b> "
            f"<b>{'🟢 ON' if enabled else '🔴 OFF'}</b>"
        )

    await message.reply_text(text)


# ============================================================
# ID COMMAND
# ============================================================

@app.on_message(
    filters.private & filters.command("id")
)
async def id_cmd(_, message: Message):

    if not message.from_user:
        return

    await message.reply_text(
        "🆔 <b>𝐘𝐎𝐔𝐑 𝐓𝐄𝐋𝐄𝐆𝐑𝐀𝐌 𝐈𝐃</b>\n\n"
        f"<code>{message.from_user.id}</code>"
    )


# ============================================================
# ERROR LOGGER
# ============================================================

@app.on_disconnect()
async def disconnected():

    log.warning(
        "Telegram connection disconnected."
    )


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":

    init_db()

    log.info(
        "=========================================="
    )

    log.info(
        "KIRTI GUARDIAN BOT [V2] STARTING..."
    )

    log.info(
        "Edited message protection enabled."
    )

    log.info(
        "=========================================="
    )

    app.run()
