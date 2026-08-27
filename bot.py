import os
import asyncio
import logging
import time

from pymongo import MongoClient
from pyrogram import Client, filters
from pyrogram.enums import ChatType, ChatMemberStatus
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from pyrogram.errors import RPCError, FloodWait


# ============================================================
#                    KIRTI GUARDIAN BOT
# ============================================================

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

MONGO_URI = os.getenv("MONGO_URI", "")
MONGO_DB_NAME = os.getenv(
    "MONGO_DB_NAME",
    "kirti_guardian"
)

START_IMAGE = os.getenv(
    "START_IMAGE",
    "start.jpg"
)

BOT_USERNAME = os.getenv(
    "BOT_USERNAME",
    "KirtiGuardianBot"
).lstrip("@")

OWNER_USERNAME = os.getenv(
    "OWNER_USERNAME",
    ""
).lstrip("@")

SUPPORT_USERNAME = os.getenv(
    "SUPPORT_USERNAME",
    ""
).lstrip("@")


# ============================================================
#                       CHECK CONFIG
# ============================================================

if not API_ID:
    raise RuntimeError("API_ID is missing.")

if not API_HASH:
    raise RuntimeError("API_HASH is missing.")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing.")

if not OWNER_ID:
    raise RuntimeError("OWNER_ID is missing.")

if not MONGO_URI:
    raise RuntimeError("MONGO_URI is missing.")


# ============================================================
#                         LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("KirtiGuardian")


# ============================================================
#                        PYROGRAM
# ============================================================

app = Client(
    "kirti_guardian_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="."
)


# ============================================================
#                         MONGODB
# ============================================================

mongo = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=10000
)

mongo.admin.command("ping")

db = mongo[MONGO_DB_NAME]

users_col = db["users"]
local_auth_col = db["local_auth"]
global_auth_col = db["global_auth"]
settings_col = db["settings"]
stats_col = db["stats"]


# ============================================================
#                          INDEXES
# ============================================================

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


# ============================================================
#                         STATISTICS
# ============================================================

def stat_inc(key, amount=1):

    stats_col.update_one(
        {"key": key},
        {
            "$inc": {
                "value": amount
            }
        },
        upsert=True
    )


def get_stat(key):

    data = stats_col.find_one(
        {"key": key}
    )

    if not data:
        return 0

    return int(
        data.get("value", 0)
    )


# ============================================================
#                         SAVE USER
# ============================================================

def save_user(user):

    if not user:
        return

    try:

        users_col.update_one(
            {
                "user_id": user.id
            },
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

    except Exception as e:

        log.warning(
            "User save error: %s",
            e
        )


def save_message_user(message):

    if (
        message
        and message.from_user
    ):
        save_user(
            message.from_user
        )


# ============================================================
#                         GROUP CHECK
# ============================================================

def is_group(message):

    if not message:
        return False

    if not message.chat:
        return False

    return message.chat.type in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    )


# ============================================================
#                         ADMIN CHECK
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

    except RPCError as e:

        log.warning(
            "Admin check error: %s",
            e
        )

        return False


async def owner_only(message):

    return bool(
        message.from_user
        and message.from_user.id == OWNER_ID
    )


# ============================================================
#                          SETTINGS
# ============================================================

def get_setting(chat_id):

    data = settings_col.find_one(
        {
            "chat_id": chat_id
        }
    )

    if not data:
        return False

    return bool(
        data.get(
            "admin_edit",
            False
        )
    )


def set_setting(
    chat_id,
    enabled
):

    settings_col.update_one(
        {
            "chat_id": chat_id
        },
        {
            "$set": {
                "chat_id": chat_id,
                "admin_edit": bool(enabled)
            }
        },
        upsert=True
    )


# ============================================================
#                         LOCAL AUTH
# ============================================================

def local_authed(
    chat_id,
    user_id
):

    return (
        local_auth_col.find_one(
            {
                "chat_id": chat_id,
                "user_id": user_id
            }
        )
        is not None
    )


def add_local(
    chat_id,
    user_id
):

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


def remove_local(
    chat_id,
    user_id
):

    result = local_auth_col.delete_one(
        {
            "chat_id": chat_id,
            "user_id": user_id
        }
    )

    return result.deleted_count


def clear_local(chat_id):

    result = local_auth_col.delete_many(
        {
            "chat_id": chat_id
        }
    )

    return result.deleted_count


def list_local(chat_id):

    return [
        x["user_id"]
        for x in local_auth_col.find(
            {
                "chat_id": chat_id
            },
            {
                "_id": 0,
                "user_id": 1
            }
        ).sort(
            "user_id",
            1
        )
    ]


# ============================================================
#                         GLOBAL AUTH
# ============================================================

def global_authed(user_id):

    return (
        global_auth_col.find_one(
            {
                "user_id": user_id
            }
        )
        is not None
    )


def add_global(user_id):

    global_auth_col.update_one(
        {
            "user_id": user_id
        },
        {
            "$set": {
                "user_id": user_id
            }
        },
        upsert=True
    )


def remove_global(user_id):

    result = global_auth_col.delete_one(
        {
            "user_id": user_id
        }
    )

    return result.deleted_count


def clear_global():

    result = global_auth_col.delete_many({})

    return result.deleted_count


def list_global():

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


# ============================================================
#                         USER RESOLVER
# ============================================================

def target_user(message):

    if (
        message.reply_to_message
        and message.reply_to_message.from_user
    ):
        return (
            message.reply_to_message
            .from_user
            .id
        )

    parts = (
        message.text or ""
    ).split(
        maxsplit=1
    )

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

        user = await app.get_users(
            target
        )

        return user.id

    except RPCError:

        return None


# ============================================================
#                       DELETE EDIT
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

    except RPCError as e:

        log.debug(
            "Delete error: %s",
            e
        )

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
      🛡️ <b>Ҡɪʀᴛɪ Gᴜᴀʀᴅɪᴀɴ</b>
          <i>Bᴏᴛ V𝟸</i>
╰━━━━━━━━━━━━━━━━━━━━━━╯

👋 <b>Hᴇʟʟᴏ {user_mention} ❤️</b>

🤖 <b>Wᴇʟᴄᴏᴍᴇ Tᴏ
{bot_mention}</b>

🚨 <b>I Cᴀɴ Aᴜᴛᴏ-Dᴇʟᴇᴛᴇ
Eᴅɪᴛᴇᴅ Mᴇssᴀɢᴇs</b>

🛡️ <b>I'ʟʟ Kᴇᴇᴘ Yᴏᴜʀ
Gʀᴏᴜᴘ Cʟᴇᴀɴ & Sᴀғᴇ.</b>

⭐ <b>Aᴅᴅ Mᴇ Tᴏ Yᴏᴜʀ Gʀᴏᴜᴘ</b>

<b>Gɪᴠᴇ Mᴇ Dᴇʟᴇᴛᴇ
Mᴇssᴀɢᴇs Pᴇʀᴍɪssɪᴏɴ.</b>

━━━━━━━━━━━━━━━━━━━━━━

💎 <b>Pᴏᴡᴇʀᴇᴅ Bʏ {bot_mention}</b>
❤️ <i>Mᴀᴅᴇ Fᴏʀ Tᴇʟᴇɢʀᴀᴍ</i>
"""


# ============================================================
#                            HELP
# ============================================================

HELP_TEXT = """
╭━━━━━━━━━━━━━━━━━━━━━━╮
       📚 <b>Hᴇʟᴘ & Cᴏᴍᴍᴀɴᴅs</b>
╰━━━━━━━━━━━━━━━━━━━━━━╯

👑 <b>Lᴏᴄᴀʟ Aᴜᴛʜ</b>
<i>Gʀᴏᴜᴘ Oᴡɴᴇʀ / Aᴅᴍɪɴ</i>

➤ <code>/auth</code> — Aᴜᴛʜᴏʀɪᴢᴇ
➤ <code>/unauth</code> — Rᴇᴍᴏᴠᴇ
➤ <code>/authusers</code> — Lɪsᴛ
➤ <code>/clearauthusers</code> — Cʟᴇᴀʀ Aʟʟ

🌐 <b>Gʟᴏʙᴀʟ Aᴜᴛʜ</b>
<i>Bᴏᴛ Oᴡɴᴇʀ Oɴʟʏ</i>

➤ <code>/gauth</code> — Gʟᴏʙᴀʟ Aᴜᴛʜ
➤ <code>/gunauth</code> — Rᴇᴍᴏᴠᴇ
➤ <code>/gusers</code> — Lɪsᴛ
➤ <code>/cleargusers</code> — Cʟᴇᴀʀ Aʟʟ

📢 <b>Bʀᴏᴀᴅᴄᴀsᴛ</b>
<i>Bᴏᴛ Oᴡɴᴇʀ Oɴʟʏ</i>

➤ <code>/broadcast MESSAGE</code>

➤ Rᴇᴘʟʏ Tᴏ Aɴʏ Mᴇssᴀɢᴇ:
<code>/broadcast</code>

➤ <code>/broadcast_stats</code>

🛡️ <b>Eᴅɪᴛ Gᴜᴀʀᴅɪᴀɴ</b>

➤ <code>/adminedit on</code>
➤ <code>/adminedit off</code>

📊 <b>Oᴛʜᴇʀ</b>

➤ <code>/start</code>
➤ <code>/help</code>
➤ <code>/stats</code>
➤ <code>/id</code>

━━━━━━━━━━━━━━━━━━━━━━

⚡ <b>Gɪᴠᴇ Mᴇ Dᴇʟᴇᴛᴇ
Mᴇssᴀɢᴇs Pᴇʀᴍɪssɪᴏɴ</b>
"""


# ============================================================
#                           BUTTONS
# ============================================================

def start_buttons():

    buttons = []

    buttons.append(
        [
            InlineKeyboardButton(
                "✚ Aᴅᴅ Mᴇ Iɴ Yᴏᴜʀ Gʀᴏᴜᴘ ✚",
                url=(
                    f"https://t.me/"
                    f"{BOT_USERNAME}"
                    f"?startgroup=true"
                )
            )
        ]
    )

    owner_row = []

    if OWNER_USERNAME:

        owner_row.append(
            InlineKeyboardButton(
                "💬 Oᴡɴᴇʀ",
                url=(
                    f"https://t.me/"
                    f"{OWNER_USERNAME}"
                )
            )
        )

    if SUPPORT_USERNAME:

        owner_row.append(
            InlineKeyboardButton(
                "👨‍💼 Sᴜᴘᴘᴏʀᴛ",
                url=(
                    f"https://t.me/"
                    f"{SUPPORT_USERNAME}"
                )
            )
        )

    if owner_row:
        buttons.append(
            owner_row
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "📚 Hᴇʟᴘ & Cᴏᴍᴍᴀɴᴅs",
                callback_data="help"
            )
        ]
    )

    return InlineKeyboardMarkup(
        buttons
    )


def home_buttons():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🏠 Hᴏᴍᴇ",
                    callback_data="home"
                )
            ]
        ]
    )


# ============================================================
#                            START
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

    save_message_user(
        message
    )

    stat_inc(
        "starts"
    )

    bot = await app.get_me()

    text = start_text(
        message.from_user,
        bot
    )

    try:

        if START_IMAGE:

            await message.reply_photo(
                photo=START_IMAGE,
                caption=text,
                reply_markup=start_buttons()
            )

            return

    except Exception as e:

        log.warning(
            "Start image failed: %s",
            e
        )

    await message.reply_text(
        text,
        reply_markup=start_buttons()
    )


# ============================================================
#                             HELP
# ============================================================

@app.on_message(
    filters.command("help")
)
async def help_cmd(
    _,
    message: Message
):

    save_message_user(
        message
    )

    await message.reply_text(
        HELP_TEXT,
        reply_markup=home_buttons(),
        disable_web_page_preview=True
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
                reply_markup=home_buttons()
            )

            await query.answer()

            return

        if query.data == "home":

            bot = await app.get_me()

            text = start_text(
                query.from_user,
                bot
            )

            await query.message.edit_text(
                text,
                reply_markup=start_buttons()
            )

            await query.answer()

            return

        await query.answer()

    except Exception as e:

        log.warning(
            "Callback error: %s",
            e
        )


# ============================================================
#                             AUTH
# ============================================================

@app.on_message(
    filters.command("auth")
)
async def auth_cmd(
    _,
    message: Message
):

    save_message_user(
        message
    )

    if not is_group(message):

        return await message.reply_text(
            "❌ <b>Tʜɪs Cᴏᴍᴍᴀɴᴅ Wᴏʀᴋs Oɴʟʏ Iɴ Gʀᴏᴜᴘs.</b>"
        )

    if not await is_admin(message):

        return await message.reply_text(
            "❌ <b>Gʀᴏᴜᴘ Oᴡɴᴇʀ / Aᴅᴍɪɴ Oɴʟʏ.</b>"
        )

    uid = await resolve_user(
        message
    )

    if not uid:

        return await message.reply_text(
            "❌ <b>Rᴇᴘʟʏ Tᴏ A Usᴇʀ Oʀ Usᴇ:</b>\n"
            "<code>/auth USER_ID</code>"
        )

    add_local(
        message.chat.id,
        uid
    )

    await message.reply_text(
        "╭━━━━━━━━━━━━━━━━━━━━╮\n"
        "       👑 <b>Lᴏᴄᴀʟ Aᴜᴛʜ</b>\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"✅ Usᴇʀ <code>{uid}</code>\n"
        "<b>Aᴜᴛʜᴏʀɪᴢᴇᴅ Sᴜᴄᴄᴇssғᴜʟʟʏ.</b>"
    )


# ============================================================
#                           UNAUTH
# ============================================================

@app.on_message(
    filters.command("unauth")
)
async def unauth_cmd(
    _,
    message: Message
):

    save_message_user(
        message
    )

    if not is_group(message):

        return await message.reply_text(
            "❌ <b>Tʜɪs Cᴏᴍᴍᴀɴᴅ Wᴏʀᴋs Oɴʟʏ Iɴ Gʀᴏᴜᴘs.</b>"
        )

    if not await is_admin(message):

        return await message.reply_text(
            "❌ <b>Gʀᴏᴜᴘ Oᴡɴᴇʀ / Aᴅᴍɪɴ Oɴʟʏ.</b>"
        )

    uid = await resolve_user(
        message
    )

    if not uid:

        return await message.reply_text(
            "❌ Rᴇᴘʟʏ Tᴏ A Usᴇʀ Oʀ Usᴇ:\n"
            "<code>/unauth USER_ID</code>"
        )

    removed = remove_local(
        message.chat.id,
        uid
    )

    await message.reply_text(
        (
            f"✅ Aᴜᴛʜ Rᴇᴍᴏᴠᴇᴅ Fʀᴏᴍ "
            f"<code>{uid}</code>."
            if removed
            else
            f"ℹ️ Usᴇʀ <code>{uid}</code> "
            "Wᴀs Nᴏᴛ Aᴜᴛʜᴏʀɪᴢᴇᴅ."
        )
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

    save_message_user(
        message
    )

    if not is_group(message):

        return await message.reply_text(
            "❌ <b>Tʜɪs Cᴏᴍᴍᴀɴᴅ Wᴏʀᴋs Oɴʟʏ Iɴ Gʀᴏᴜᴘs.</b>"
        )

    if not await is_admin(message):

        return await message.reply_text(
            "❌ <b>Gʀᴏᴜᴘ Oᴡɴᴇʀ / Aᴅᴍɪɴ Oɴʟʏ.</b>"
        )

    users = list_local(
        message.chat.id
    )

    if not users:

        return await message.reply_text(
            "📭 <b>Nᴏ Lᴏᴄᴀʟ Aᴜᴛʜ Usᴇʀs.</b>"
        )

    text = (
        "╭━━━━━━━━━━━━━━━━━━━━╮\n"
        "       👑 <b>Lᴏᴄᴀʟ Aᴜᴛʜ</b>\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
    )

    text += "\n".join(
        f"➤ <code>{uid}</code>"
        for uid in users
    )

    await message.reply_text(
        text
    )


# ============================================================
#                     CLEAR LOCAL AUTH
# ============================================================

@app.on_message(
    filters.command("clearauthusers")
)
async def clearauthusers_cmd(
    _,
    message: Message
):

    save_message_user(
        message
    )

    if not is_group(message):

        return await message.reply_text(
            "❌ <b>Tʜɪs Cᴏᴍᴍᴀɴᴅ Wᴏʀᴋs Oɴʟʏ Iɴ Gʀᴏᴜᴘs.</b>"
        )

    if not await is_admin(message):

        return await message.reply_text(
            "❌ <b>Gʀᴏᴜᴘ Oᴡɴᴇʀ / Aᴅᴍɪɴ Oɴʟʏ.</b>"
        )

    count = clear_local(
        message.chat.id
    )

    await message.reply_text(
        f"🧹 <b>Cʟᴇᴀʀᴇᴅ {count} Lᴏᴄᴀʟ Aᴜᴛʜ Usᴇʀ(s).</b>"
    )


# ============================================================
#                         GLOBAL AUTH
# ============================================================

@app.on_message(
    filters.command("gauth")
)
async def gauth_cmd(
    _,
    message: Message
):

    save_message_user(
        message
    )

    if not await owner_only(message):

        return await message.reply_text(
            "❌ <b>Bᴏᴛ Oᴡɴᴇʀ Oɴʟʏ.</b>"
        )

    uid = await resolve_user(
        message
    )

    if not uid:

        return await message.reply_text(
            "❌ Rᴇᴘʟʏ Tᴏ A Usᴇʀ Oʀ Usᴇ:\n"
            "<code>/gauth USER_ID</code>"
        )

    add_global(
        uid
    )

    await message.reply_text(
        f"🌐 Usᴇʀ <code>{uid}</code>\n"
        "<b>Gʟᴏʙᴀʟʟʏ Aᴜᴛʜᴏʀɪᴢᴇᴅ.</b>"
    )


# ============================================================
#                       GLOBAL UNAUTH
# ============================================================

@app.on_message(
    filters.command("gunauth")
)
async def gunauth_cmd(
    _,
    message: Message
):

    save_message_user(
        message
    )

    if not await owner_only(message):

        return await message.reply_text(
            "❌ <b>Bᴏᴛ Oᴡɴᴇʀ Oɴʟʏ.</b>"
        )

    uid = await resolve_user(
        message
    )

    if not uid:

        return await message.reply_text(
            "❌ Rᴇᴘʟʏ Tᴏ A Usᴇʀ Oʀ Usᴇ:\n"
            "<code>/gunauth USER_ID</code>"
        )

    removed = remove_global(
        uid
    )

    await message.reply_text(
        (
            f"✅ Gʟᴏʙᴀʟ Aᴜᴛʜ Rᴇᴍᴏᴠᴇᴅ: "
            f"<code>{uid}</code>"
            if removed
            else
            f"ℹ️ Usᴇʀ <code>{uid}</code> Wᴀs Nᴏᴛ Gʟᴏʙᴀʟʟʏ Aᴜᴛʜᴏʀɪᴢᴇᴅ."
        )
    )


# ============================================================
#                         GLOBAL USERS
# ============================================================

@app.on_message(
    filters.command("gusers")
)
async def gusers_cmd(
    _,
    message: Message
):

    save_message_user(
        message
    )

    if not await owner_only(message):

        return await message.reply_text(
            "❌ <b>Bᴏᴛ Oᴡɴᴇʀ Oɴʟʏ.</b>"
        )

    users = list_global()

    if not users:

        return await message.reply_text(
            "📭 <b>Nᴏ Gʟᴏʙᴀʟ Aᴜᴛʜ Usᴇʀs.</b>"
        )

    text = (
        "╭━━━━━━━━━━━━━━━━━━━━╮\n"
        "       🌐 <b>Gʟᴏʙᴀʟ Aᴜᴛʜ</b>\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
    )

    text += "\n".join(
        f"➤ <code>{uid}</code>"
        for uid in users
    )

    await message.reply_text(
        text
    )


# ============================================================
#                     CLEAR GLOBAL AUTH
# ============================================================

@app.on_message(
    filters.command("cleargusers")
)
async def cleargusers_cmd(
    _,
    message: Message
):

    save_message_user(
        message
    )

    if not await owner_only(message):

        return await message.reply_text(
            "❌ <b>Bᴏᴛ Oᴡɴᴇʀ Oɴʟʏ.</b>"
        )

    count = clear_global()

    await message.reply_text(
        f"🧹 <b>Cʟᴇᴀʀᴇᴅ {count} Gʟᴏʙᴀʟ Aᴜᴛʜ Usᴇʀ(s).</b>"
    )


# ============================================================
#                       ADMIN EDIT MODE
# ============================================================

@app.on_message(
    filters.command("adminedit")
)
async def adminedit_cmd(
    _,
    message: Message
):

    save_message_user(
        message
    )

    if not is_group(message):

        return await message.reply_text(
            "❌ <b>Tʜɪs Cᴏᴍᴍᴀɴᴅ Wᴏʀᴋs Oɴʟʏ Iɴ Gʀᴏᴜᴘs.</b>"
        )

    if not await is_admin(message):

        return await message.reply_text(
            "❌ <b>Gʀᴏᴜᴘ Oᴡɴᴇʀ / Aᴅᴍɪɴ Oɴʟʏ.</b>"
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
            "🟢 Oɴ"
            if get_setting(
                message.chat.id
            )
            else "🔴 Oғғ"
        )

        return await message.reply_text(
            "🛡️ <b>Aᴅᴍɪɴ Eᴅɪᴛ Dᴇʟᴇᴛᴇ</b>\n\n"
            f"Cᴜʀʀᴇɴᴛ: <b>{current}</b>\n\n"
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
        "🛡️ <b>Aᴅᴍɪɴ Eᴅɪᴛ Dᴇʟᴇᴛᴇ</b>\n\n"
        f"Sᴛᴀᴛᴜs: <b>{'🟢 Oɴ' if enabled else '🔴 Oғғ'}</b>"
    )


# ============================================================
#                       EDIT GUARDIAN
# ============================================================

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

    save_user(
        message.from_user
    )

    # Local auth users are protected
    if local_authed(
        message.chat.id,
        uid
    ):
        return

    # Global auth users are protected
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

    # Admin / owner
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

        return

    # Normal members
    await delete_quietly(
        message
    )


# ============================================================
#                         BROADCAST COPY
# ============================================================

async def broadcast_copy(
    source_message
):

    users = users_col.find(
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

    total = 0
    success = 0
    failed = 0
    removed = 0

    for item in users:

        user_id = item.get(
            "user_id"
        )

        if not user_id:
            continue

        total += 1

        try:

            await source_message.copy(
                chat_id=user_id
            )

            success += 1

            await asyncio.sleep(
                0.05
            )

        except FloodWait as e:

            await asyncio.sleep(
                e.value
            )

            try:

                await source_message.copy(
                    chat_id=user_id
                )

                success += 1

            except Exception:

                failed += 1

        except RPCError as e:

            failed += 1

            error = str(
                e
            ).lower()

            if (
                "blocked" in error
                or "deactivated" in error
                or "chat not found" in error
            ):

                removed += 1

                try:

                    users_col.delete_one(
                        {
                            "user_id": user_id
                        }
                    )

                except Exception:
                    pass

        except Exception as e:

            failed += 1

            log.debug(
                "Broadcast error: %s",
                e
            )

    return (
        total,
        success,
        failed,
        removed
    )


# ============================================================
#                          BROADCAST
# ============================================================

@app.on_message(
    filters.command("broadcast")
)
async def broadcast_cmd(
    _,
    message: Message
):

    save_message_user(
        message
    )

    if not await owner_only(message):

        return await message.reply_text(
            "❌ <b>Bᴏᴛ Oᴡɴᴇʀ Oɴʟʏ.</b>"
        )

    # --------------------------------------------------------
    # REPLY BROADCAST
    # --------------------------------------------------------

    if message.reply_to_message:

        progress = await message.reply_text(
            "📢 <b>Bʀᴏᴀᴅᴄᴀsᴛ Sᴛᴧʀᴛ𝛆ɗ...</b>\n\n"
            "⏳ Pʟᴇᴀsᴇ Wᴀɪᴛ..."
        )

        (
            total,
            success,
            failed,
            removed
        ) = await broadcast_copy(
            message.reply_to_message
        )

        await progress.edit_text(
            "╭━━━━━━━━━━━━━━━━━━━━╮\n"
            "       📢 <b>Bʀᴏᴀᴅᴄᴀsᴛ</b>\n"
            "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
            f"👥 Tᴏᴛᴀʟ: <code>{total}</code>\n"
            f"✅ Sᴇɴᴛ: <code>{success}</code>\n"
            f"❌ Fᴀɪʟᴇᴅ: <code>{failed}</code>\n"
            f"🚫 Rᴇᴍᴏᴠᴇᴅ: <code>{removed}</code>\n\n"
            "✨ <b>Bʀᴏᴀᴅᴄᴀsᴛ Cᴏᴍᴘʟᴇᴛ𝛆ɗ.</b>"
        )

        return

    # --------------------------------------------------------
    # TEXT BROADCAST
    # --------------------------------------------------------

    parts = (
        message.text or ""
    ).split(
        maxsplit=1
    )

    if len(parts) < 2:

        return await message.reply_text(
            "📢 <b>Bʀᴏᴀᴅᴄᴀsᴛ Uѕᴧɢ𝛆</b>\n\n"
            "Tᴇxᴛ:\n"
            "<code>/broadcast Hello ❤️</code>\n\n"
            "Oʀ Rᴇᴘʟʏ Tᴏ Aɴʏ Mᴇssᴀɢᴇ:\n"
            "<code>/broadcast</code>"
        )

    text = parts[1].strip()

    if not text:

        return await message.reply_text(
            "❌ <b>Bʀᴏᴀᴅᴄᴀsᴛ Mᴇssᴀɢᴇ Is Eᴍᴘᴛʏ.</b>"
        )

    progress = await message.reply_text(
        "📢 <b>Bʀᴏᴀᴅᴄᴀsᴛ Sᴛᴧʀᴛ𝛆ɗ...</b>\n\n"
        "⏳ Pʟᴇᴀsᴇ Wᴀɪᴛ..."
    )

    users = users_col.find(
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

    total = 0
    success = 0
    failed = 0
    removed = 0

    for item in users:

        user_id = item.get(
            "user_id"
        )

        if not user_id:
            continue

        total += 1

        try:

            await app.send_message(
                chat_id=user_id,
                text=text
            )

            success += 1

            await asyncio.sleep(
                0.05
            )

        except FloodWait as e:

            await asyncio.sleep(
                e.value
            )

            try:

                await app.send_message(
                    chat_id=user_id,
                    text=text
                )

                success += 1

            except Exception:

                failed += 1

        except RPCError as e:

            failed += 1

            error = str(
                e
            ).lower()

            if (
                "blocked" in error
                or "deactivated" in error
                or "chat not found" in error
            ):

                removed += 1

                try:

                    users_col.delete_one(
                        {
                            "user_id": user_id
                        }
                    )

                except Exception:
                    pass

        except Exception:

            failed += 1

    await progress.edit_text(
        "╭━━━━━━━━━━━━━━━━━━━━╮\n"
        "       📢 <b>Bʀᴏᴀᴅᴄᴀsᴛ</b>\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"👥 Tᴏᴛᴀʟ: <code>{total}</code>\n"
        f"✅ Sᴇɴᴛ: <code>{success}</code>\n"
        f"❌ Fᴀɪʟᴇᴅ: <code>{failed}</code>\n"
        f"🚫 Rᴇᴍᴏᴠᴇᴅ: <code>{removed}</code>\n\n"
        "✨ <b>Bʀᴏᴀᴅᴄᴀsᴛ Cᴏᴍᴘʟᴇᴛ𝛆ɗ.</b>"
    )


# ============================================================
#                      BROADCAST STATS
# ============================================================

@app.on_message(
    filters.command("broadcast_stats")
)
async def broadcast_stats_cmd(
    _,
    message: Message
):

    if not await owner_only(message):

        return await message.reply_text(
            "❌ <b>Bᴏᴛ Oᴡɴᴇʀ Oɴʟʏ.</b>"
        )

    total = users_col.count_documents(
        {
            "is_bot": {
                "$ne": True
            }
        }
    )

    await message.reply_text(
        "╭━━━━━━━━━━━━━━━━━━━━╮\n"
        "     📢 <b>Bʀᴏᴀᴅᴄᴀsᴛ Sᴛᴀᴛs</b>\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"👥 Sᴀᴠᴇᴅ Usᴇʀs: <code>{total}</code>\n"
        f"▶️ Sᴛᴀʀᴛs: <code>{get_stat('starts')}</code>\n"
        f"🗑️ Dᴇʟᴇᴛᴇᴅ Eᴅɪᴛs: "
        f"<code>{get_stat('deleted_edits')}</code>"
    )


# ============================================================
#                            STATS
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
            "❌ <b>Aᴅᴍɪɴ / Oᴡɴᴇʀ Oɴʟʏ.</b>"
        )

    total_users = users_col.count_documents(
        {
            "is_bot": {
                "$ne": True
            }
        }
    )

    text = (
        "╭━━━━━━━━━━━━━━━━━━━━╮\n"
        "        📊 <b>Kɪʀᴛɪ Sᴛᴀᴛs</b>\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"▶️ Sᴛᴀʀᴛs: "
        f"<code>{get_stat('starts')}</code>\n"
        f"🗑️ Dᴇʟᴇᴛᴇᴅ Eᴅɪᴛs: "
        f"<code>{get_stat('deleted_edits')}</code>\n"
        f"👥 Sᴀᴠᴇᴅ Usᴇʀs: "
        f"<code>{total_users}</code>\n"
    )

    if is_group(message):

        enabled = get_setting(
            message.chat.id
        )

        text += (
            f"🛡️ Aᴅᴍɪɴ Eᴅɪᴛ: "
            f"<b>{'🟢 Oɴ' if enabled else '🔴 Oғғ'}</b>"
        )

    await message.reply_text(
        text
    )


# ============================================================
#                              ID
# ============================================================

@app.on_message(
    filters.private & filters.command("id")
)
async def id_cmd(
    _,
    message: Message
):

    save_message_user(
        message
    )

    if not message.from_user:
        return

    await message.reply_text(
        "🆔 <b>Yᴏᴜʀ Tᴇʟᴇɢʀᴀᴍ ID</b>\n\n"
        f"<code>{message.from_user.id}</code>"
    )


# ============================================================
#                            STARTUP
# ============================================================

if __name__ == "__main__":

    log.info(
        "======================================"
    )

    log.info(
        "KIRTI GUARDIAN BOT STARTING"
    )

    log.info(
        "MongoDB: CONNECTED"
    )

    log.info(
        "Broadcast: ENABLED"
    )

    log.info(
        "Owner/Admin system: ENABLED"
    )

    log.info(
        "Edit Guardian: ENABLED"
    )

    log.info(
        "Status system: REMOVED"
    )

    log.info(
        "======================================"
    )

    app.run()
