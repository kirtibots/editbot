# Purvi Guardian Bot

Telegram **Edit Guardian** bot based on the command layout shown in the reference screenshot.

## Features
- `/start` with a start image (set `START_IMAGE`)
- `/help`
- Local authorization: `/auth`, `/unauth`, `/authusers`, `/clearauthusers`
- Global authorization: `/gauth`, `/gunauth`, `/gusers`, `/cleargusers`
- `/adminedit on|off` — controls deletion of admin/owner edits
- `/stats`
- SQLite database; no MongoDB required
- Inline Help/Status buttons
- FloodWait/RPCError handling
- Works with Pyrogram 2.x

## Setup
1. Install Python 3.10+.
2. `pip install -r requirements.txt`
3. Set environment variables from `.env.example`.
4. Run: `python bot.py`

## Telegram permissions
Add the bot to your group and make it an administrator with **Delete Messages** permission.

## Important behavior
- `/adminedit on` deletes edited messages from admins/owners as well as normal members.
- `/adminedit off` ignores edits made by admins/owners but still deletes edited messages from normal members.
- Authorized local/global users are exempt from edit deletion.
- Default is OFF for admin edits, matching the reference help screen.

For username targets, use `/auth @username`; for the most reliable method, reply to the user's message and send `/auth`.
