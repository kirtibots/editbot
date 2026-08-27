import os
import sqlite3
import logging
from contextlib import closing

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import RPCError, FloodWait


# ============================================================
# PURVI GUARDIAN BOT
# Edited Message Protection Bot
# ============================================================

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

START_IMAGE = os.getenv("START_IMAGE", "").strip() or "start.jpg"
DB_PATH = os.getenv("DB_PATH", "guardian.db")


# ============================================================
# ENV CHECK
# ============================================================

if not API_ID or not API_HASH or not BOT_TOKEN or not OWNER_ID:
    raise RuntimeError(
        "Set API_ID, API_HASH, BOT_TOKEN and OWNER_ID environment variables."
    )


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

log = logging.getLogger("PurviGuardianBot")


# ============================================================
# PYROGRAM CLIENT
# ============================================================

app = Client(
    "purvi_guardian_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="."
)


# ============================================================
# DATABASE
# ============================================================

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
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


def stat_inc(key, amount=1):
    with closing(db()) as con:
        con.execute("""
            INSERT INTO stats(key, value)
            VALUES(?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value=value+excluded.value
        """, (key, amount))

        con.commit()


# ============================================================
# SETTINGS
# ============================================================

def get_setting(chat_id):
    with closing(db()) as con:
        row = con.execute(
            "SELECT admin_edit FROM settings WHERE chat_id=?",
            (chat_id,)
        ).fetchone()

    return bool(row[0]) if row else False


def set_setting(chat_id, enabled):
    with closing(db()) as con:
        con.execute("""
            INSERT INTO settings(chat_id, admin_edit)
            VALUES(?, ?)
            ON CONFLICT(chat_id)
            DO UPDATE SET admin_edit=excluded.admin_edit
        """, (chat_id, int(enabled)))

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
            WHERE chat_id=? AND user_id=?
            """,
            (chat_id, user_id)
        ).fetchone()

    return row is not None


def add_local(chat_id, user_id):
    with closing(db()) as con:
        con.execute(
            """
            INSERT OR IGNORE INTO local_auth(chat_id, user_id)
            VALUES(?, ?)
            """,
            (chat_id, user_id)
        )

        con.commit()


def remove_local(chat_id, user_id):
    with closing(db()) as con:
        cur = con.execute(
            """
            DELETE FROM local_auth
            WHERE chat_id=? AND user_id=?
            """,
            (chat_id, user_id)
        )

        con.commit()

        return cur.rowcount


def clear_local(chat_id):
    with closing(db()) as con:
        cur = con.execute(
            "DELETE FROM local_auth WHERE chat_id=?",
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

    return [row[0] for row in rows]


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
            "DELETE FROM global_auth WHERE user_id=?",
            (user_id,)
        )

        con.commit()

        return cur.rowcount


def clear_global():
    with closing(db()) as con:
        cur = con.execute("DELETE FROM global_auth")

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

    return [row[0] for row in rows]


# ============================================================
# HELPERS
# ============================================================

def is_group(message):
    return bool(
        message.chat
        and message.chat.type in ("group", "supergroup")
    )


async def is_admin(message, user_id=None):

    user_id = user_id or (
        message.from_user.id
        if message.from_user
        else 0
    )

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
            "administrator",
            "owner"
        )

    except RPCError:
        return False


async def owner_only(message):
    return bool(
        message.from_user
        and message.from_user.id == OWNER_ID
    )


async def admin_only(message):
    return await is_admin(message)


# ============================================================
# TARGET USER
# ============================================================

def target_user(message):

    # Reply target has priority.
    if (
        message.reply_to_message
        and message.reply_to_message.from_user
    ):
        return message.reply_to_message.from_user.id

    parts = (message.text or "").split(
        maxsplit=1
    )

    if len(parts) != 2:
        return None

    raw = parts[1].strip()

    if raw.isdigit():
        return int(raw)

    return raw.lstrip("@")


async def resolve_user(message):

    target = target_user(message)

    if target is None:
        return None

    if isinstance(target, int):
        return target

    try:
        user = await app.get_users(target)
        return user.id

    except RPCError:
        return None


# ============================================================
# DELETE HELPER
# ============================================================

async def delete_quietly(message):

    try:
        await message.delete()

        stat_inc("deleted_edits")

        return True

    except FloodWait as e:

        await app.sleep(e.value)

    except RPCError:
        pass

    except Exception as e:
        log.warning(
            "Delete failed: %s",
            e
        )

    return False


# ============================================================
# HELP
# ============================================================

HELP_TEXT = """
📚 <b>PURVI GUARDIAN BOT</b>

<b>👑 LOCAL AUTH — ADMIN ONLY</b>

• <code>/auth</code> — Authorize a user
• <code>/unauth</code> — Remove authorization
• <code>/authusers</code> — View authorized users
• <code>/clearauthusers</code> — Clear all local users

<b>🌐 GLOBAL AUTH — OWNER ONLY</b>

• <code>/gauth</code> — Global authorize
• <code>/gunauth</code> — Remove global authorization
• <code>/gusers</code> — View global users
• <code>/cleargusers</code> — Clear global users

<b>🛡️ EDIT DELETE — ADMIN ONLY</b>

• <code>/adminedit on</code> — Delete admin edits
• <code>/adminedit off</code> — Ignore admin edits

<b>📊 OTHER</b>

• <code>/start</code> — Bot status
• <code>/stats</code> — Bot statistics
• <code>/help</code> — Show help
• <code>/id</code> — Get your Telegram ID

<b>DEFAULT ADMIN EDIT:</b> 🔴 OFF

⚡ Add me to your group and give me
<b>Delete Messages</b> permission.
"""


# ============================================================
# START
# ============================================================

START_TEXT = """
<b>👋 Hello! I'm Purvi Guardian Bot.</b>

🛡️ I protect Telegram groups from edited messages.

<b>Features:</b>

• 🗑️ Delete edited messages
• 👑 Local authorization
• 🌐 Global authorization
• 🛡️ Admin edit protection
• 📊 Statistics
• 🔘 Inline buttons

<b>How to use:</b>

1. Add me to your group
2. Give me Delete Messages permission
3. Use <code>/help</code>

<b>Made for Telegram groups ❤️</b>
"""


@app.on_message(filters.command("start"))
async def start_cmd(_, message: Message):

    stat_inc("starts")

    buttons = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📚 Help",
                    callback_data="help"
                ),
                InlineKeyboardButton(
                    "🛡️ Status",
                    callback_data="status"
                )
            ],
            [
                InlineKeyboardButton(
                    "➕ Add Me To Group",
                    url="https://t.me/PurviGuardianBot?startgroup=true"
                )
            ]
        ]
    )

    if START_IMAGE:

        try:

            await message.reply_photo(
                START_IMAGE,
                caption=START_TEXT,
                reply_markup=buttons
            )

            return

        except Exception as e:

            log.warning(
                "START_IMAGE failed: %s",
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

    await message.reply_text(
        HELP_TEXT,
        disable_web_page_preview=True
    )


# ============================================================
# CALLBACK BUTTONS
# ============================================================

@app.on_callback_query()
async def callbacks(_, query):

    try:

        if query.data == "help":

            buttons = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🏠 Home",
                            callback_data="home"
                        ),
                        InlineKeyboardButton(
                            "🛡️ Status",
                            callback_data="status"
                        )
                    ]
                ]
            )

            await query.message.edit_text(
                HELP_TEXT,
                reply_markup=buttons
            )

        elif query.data == "status":

            text = (
                "<b>🛡️ PURVI GUARDIAN STATUS</b>\n\n"
                "🟢 Bot: Online\n"
                f"👑 Owner ID: <code>{OWNER_ID}</code>\n"
            )

            if (
                query.message.chat
                and query.message.chat.type
                in ("group", "supergroup")
            ):

                enabled = get_setting(
                    query.message.chat.id
                )

                text += (
                    "🛡️ Admin Edit Delete: "
                    f"<b>{'🟢 ON' if enabled else '🔴 OFF'}</b>"
                )

            buttons = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📚 Help",
                            callback_data="help"
                        ),
                        InlineKeyboardButton(
                            "🏠 Home",
                            callback_data="home"
                        )
                    ]
                ]
            )

            await query.message.edit_text(
                text,
                reply_markup=buttons
            )

        elif query.data == "home":

            buttons = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📚 Help",
                            callback_data="help"
                        ),
                        InlineKeyboardButton(
                            "🛡️ Status",
                            callback_data="status"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "➕ Add Me To Group",
                            url="https://t.me/PurviGuardianBot?startgroup=true"
                        )
                    ]
                ]
            )

            await query.message.edit_text(
                START_TEXT,
                reply_markup=buttons
            )

        await query.answer()

    except RPCError:
        pass

    except Exception as e:

        log.warning(
            "Callback error: %s",
            e
        )


# ============================================================
# LOCAL AUTH
# ============================================================

@app.on_message(filters.command("auth"))
async def auth_cmd(_, message: Message):

    if not await admin_only(message):

        return await message.reply_text(
            "❌ <b>Admin only.</b>"
        )

    if not is_group(message):

        return await message.reply_text(
            "❌ This command works only in groups."
        )

    uid = await resolve_user(message)

    if not uid:

        return await message.reply_text(
            "❌ Reply to a user or use "
            "<code>/auth USER_ID</code>."
        )

    add_local(
        message.chat.id,
        uid
    )

    await message.reply_text(
        f"✅ User <code>{uid}</code> "
        "authorized in this chat."
    )


# ============================================================
# UNAUTH
# ============================================================

@app.on_message(filters.command("unauth"))
async def unauth_cmd(_, message: Message):

    if not await admin_only(message):

        return await message.reply_text(
            "❌ <b>Admin only.</b>"
        )

    if not is_group(message):

        return await message.reply_text(
            "❌ This command works only in groups."
        )

    uid = await resolve_user(message)

    if not uid:

        return await message.reply_text(
            "❌ Reply to a user or use "
            "<code>/unauth USER_ID</code>."
        )

    removed = remove_local(
        message.chat.id,
        uid
    )

    if removed:

        text = (
            f"✅ Removed local authorization: "
            f"<code>{uid}</code>"
        )

    else:

        text = (
            f"ℹ️ User was not authorized: "
            f"<code>{uid}</code>"
        )

    await message.reply_text(text)


# ============================================================
# AUTH USERS
# ============================================================

@app.on_message(filters.command("authusers"))
async def authusers_cmd(_, message: Message):

    if not await admin_only(message):

        return await message.reply_text(
            "❌ <b>Admin only.</b>"
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
            "📭 No local authorized users."
        )

    text = (
        "👑 <b>LOCAL AUTH USERS</b>\n\n"
        + "\n".join(
            f"• <code>{uid}</code>"
            for uid in users
        )
    )

    await message.reply_text(text)


# ============================================================
# CLEAR LOCAL AUTH
# ============================================================

@app.on_message(filters.command("clearauthusers"))
async def clearauthusers_cmd(_, message: Message):

    if not await admin_only(message):

        return await message.reply_text(
            "❌ <b>Admin only.</b>"
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
        "local auth user(s)."
    )


# ============================================================
# GLOBAL AUTH
# ============================================================

@app.on_message(filters.command("gauth"))
async def gauth_cmd(_, message: Message):

    if not await owner_only(message):

        return await message.reply_text(
            "❌ <b>Owner only.</b>"
        )

    uid = await resolve_user(message)

    if not uid:

        return await message.reply_text(
            "❌ Reply to a user or use "
            "<code>/gauth USER_ID</code>."
        )

    add_global(uid)

    await message.reply_text(
        f"🌐 Global authorization added: "
        f"<code>{uid}</code>"
    )


# ============================================================
# GLOBAL UNAUTH
# ============================================================

@app.on_message(filters.command("gunauth"))
async def gunauth_cmd(_, message: Message):

    if not await owner_only(message):

        return await message.reply_text(
            "❌ <b>Owner only.</b>"
        )

    uid = await resolve_user(message)

    if not uid:

        return await message.reply_text(
            "❌ Reply to a user or use "
            "<code>/gunauth USER_ID</code>."
        )

    removed = remove_global(uid)

    if removed:

        text = (
            f"✅ Removed global authorization: "
            f"<code>{uid}</code>"
        )

    else:

        text = (
            f"ℹ️ User was not globally authorized: "
            f"<code>{uid}</code>"
        )

    await message.reply_text(text)


# ============================================================
# GLOBAL USERS
# ============================================================

@app.on_message(filters.command("gusers"))
async def gusers_cmd(_, message: Message):

    if not await owner_only(message):

        return await message.reply_text(
            "❌ <b>Owner only.</b>"
        )

    users = list_global()

    if not users:

        return await message.reply_text(
            "📭 No global authorized users."
        )

    text = (
        "🌐 <b>GLOBAL AUTH USERS</b>\n\n"
        + "\n".join(
            f"• <code>{uid}</code>"
            for uid in users
        )
    )

    await message.reply_text(text)


# ============================================================
# CLEAR GLOBAL USERS
# ============================================================

@app.on_message(filters.command("cleargusers"))
async def cleargusers_cmd(_, message: Message):

    if not await owner_only(message):

        return await message.reply_text(
            "❌ <b>Owner only.</b>"
        )

    count = clear_global()

    await message.reply_text(
        f"🧹 Cleared <b>{count}</b> "
        "global auth user(s)."
    )


# ============================================================
# ADMIN EDIT SETTING
# ============================================================

@app.on_message(filters.command("adminedit"))
async def adminedit_cmd(_, message: Message):

    if not await admin_only(message):

        return await message.reply_text(
            "❌ <b>Admin only.</b>"
        )

    if not is_group(message):

        return await message.reply_text(
            "❌ This command works only in groups."
        )

    parts = (message.text or "").split()

    if (
        len(parts) < 2
        or parts[1].lower() not in ("on", "off")
    ):

        current = (
            "ON"
            if get_setting(message.chat.id)
            else "OFF"
        )

        return await message.reply_text(
            f"🛡️ Admin Edit Delete: "
            f"<b>{current}</b>\n\n"
            "Use:\n"
            "<code>/adminedit on</code>\n"
            "<code>/adminedit off</code>"
        )

    enabled = (
        parts[1].lower() == "on"
    )

    set_setting(
        message.chat.id,
        enabled
    )

    await message.reply_text(
        "🛡️ Admin Edit Delete: "
        f"<b>{'🟢 ON' if enabled else '🔴 OFF'}</b>"
    )


# ============================================================
# EDITED MESSAGE GUARD
# ============================================================
#
# IMPORTANT:
# Pyrogram has filters.group.
# filters.supergroup DOES NOT EXIST.
#
# filters.group handles both groups and supergroups.
# ============================================================

@app.on_edited_message(filters.group)
async def edited_guard(_, message: Message):

    if not message.from_user:
        return

    uid = message.from_user.id

    # --------------------------------------------------------
    # Ignore bot's own edited messages
    # --------------------------------------------------------

    try:

        me = await app.get_me()

        if uid == me.id:
            return

    except RPCError:
        pass

    # --------------------------------------------------------
    # Authorized users are always exempt
    # --------------------------------------------------------

    if local_authed(
        message.chat.id,
        uid
    ):
        return

    if global_authed(uid):
        return

    # --------------------------------------------------------
    # Check Telegram member status
    # --------------------------------------------------------

    try:

        member = await app.get_chat_member(
            message.chat.id,
            uid
        )

        status = member.status

    except RPCError:

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

        await delete_quietly(message)

        return

    # --------------------------------------------------------
    # NORMAL MEMBERS
    # --------------------------------------------------------

    await delete_quietly(message)


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
            "❌ <b>Admin/Owner only.</b>"
        )

    with closing(db()) as con:

        rows = dict(
            con.execute(
                "SELECT key,value FROM stats"
            ).fetchall()
        )

    starts = rows.get(
        "starts",
        0
    )

    deleted = rows.get(
        "deleted_edits",
        0
    )

    text = (
        "<b>📊 PURVI GUARDIAN STATISTICS</b>\n\n"
        f"▶️ Starts: <code>{starts}</code>\n"
        f"🗑️ Deleted edits: <code>{deleted}</code>\n"
    )

    if is_group(message):

        enabled = get_setting(
            message.chat.id
        )

        text += (
            "🛡️ Admin Edit Delete: "
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
        f"🆔 Your Telegram ID: "
        f"<code>{message.from_user.id}</code>"
    )


# ============================================================
# STARTUP
# ============================================================

if __name__ == "__main__":

    init_db()

    log.info(
        "=========================================="
    )

    log.info(
        "Purvi Guardian Bot starting..."
    )

    log.info(
        "Edit protection: ENABLED"
    )

    log.info(
        "=========================================="
    )

    app.run()
