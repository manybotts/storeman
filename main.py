#!/usr/bin/env python3
import os
import logging
import base64
import json
import threading

from flask import Flask, request, redirect, abort
from telegram import Bot, Update, InlineKeyboardMarkup, InlineKeyboardButton, ChatMember
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, CallbackQueryHandler, Filters

# ===== CONFIGURATION =====
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # Telegram bot token

ADMIN_IDS = os.environ.get("ADMIN_IDS", "")  # Comma-separated admin IDs (as integers)
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS.split(",") if x.strip()]

DUMP_CHANNEL = os.environ.get("DUMP_CHANNEL")  
# The channel (ID or public username) where files will be stored.

# For force subscriptions (private channels), we use channel IDs.
FORCE_SUB_CHANNEL1 = os.environ.get("FORCE_SUB_CHANNEL1")  # e.g., "-1001234567890"
FORCE_SUB_CHANNEL2 = os.environ.get("FORCE_SUB_CHANNEL2")  # e.g., "-1009876543210"

# Use Heroku's built-in domain via the HEROKU_APP_NAME variable.
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME")
if HEROKU_APP_NAME:
    BASE_URL = f"https://{HEROKU_APP_NAME}.herokuapp.com"
else:
    BASE_URL = os.environ.get("BASE_URL")  # fallback

# ===== LOGGING SETUP =====
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== INITIALIZE FLASK & TELEGRAM BOT =====
app = Flask(__name__)
bot = Bot(BOT_TOKEN)
dispatcher = Dispatcher(bot, None, workers=4, use_context=True)

# ===== UTILITY FUNCTIONS =====
def encode_token(data: dict) -> str:
    json_str = json.dumps(data)
    token_bytes = base64.urlsafe_b64encode(json_str.encode("utf-8"))
    return token_bytes.decode("utf-8")

def decode_token(token: str) -> dict:
    try:
        json_str = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        return json.loads(json_str)
    except Exception as e:
        logger.error("Token decode error: %s", e)
        return {}

def generate_token(file_type: str, msg_ids: list) -> str:
    data = {"t": file_type, "ids": msg_ids}
    return encode_token(data)

def parse_token(token: str):
    data = decode_token(token)
    if "t" in data and "ids" in data:
        return data["t"], data["ids"]
    return None, None

def is_user_subscribed(user_id: int, channel: str) -> bool:
    try:
        member = bot.get_chat_member(chat_id=channel, user_id=user_id)
        if member.status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.CREATOR]:
            return True
    except Exception as e:
        logger.info("User %s not in channel %s: %s", user_id, channel, e)
    return False

def check_force_subscriptions(user_id: int) -> bool:
    return is_user_subscribed(user_id, FORCE_SUB_CHANNEL1) and is_user_subscribed(user_id, FORCE_SUB_CHANNEL2)

def join_button(channel_id: str) -> str:
    try:
        invite_link = bot.export_chat_invite_link(chat_id=channel_id)
        return invite_link
    except Exception as e:
        logger.error("Could not export invite link for channel %s: %s", channel_id, e)
        return "#"

# ===== HANDLERS =====
# In-memory storage for media groups.
media_group_dict = {}  # key: media_group_id, value: list of messages

def process_file_messages(update: Update, context):
    message = update.message
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        message.reply_text("You are not authorized to upload files.")
        return

    # Single file
    if not message.media_group_id:
        copied = bot.copy_message(
            chat_id=DUMP_CHANNEL, from_chat_id=message.chat_id, message_id=message.message_id
        )
        token = generate_token("s", [copied.message_id])
        reply_text = f"Permanent link:\n{BASE_URL}/{token}"
        message.reply_text(reply_text)
    else:
        # Media group: collect messages briefly then process together.
        mgid = message.media_group_id
        if mgid not in media_group_dict:
            media_group_dict[mgid] = []
            threading.Timer(1.0, process_media_group, args=(mgid,)).start()
        media_group_dict[mgid].append(message)

def process_media_group(mgid):
    messages = media_group_dict.get(mgid, [])
    if not messages:
        return
    messages.sort(key=lambda m: m.message_id)
    dumped_ids = []
    for msg in messages:
        try:
            copied = bot.copy_message(
                chat_id=DUMP_CHANNEL, from_chat_id=msg.chat_id, message_id=msg.message_id
            )
            dumped_ids.append(copied.message_id)
        except Exception as e:
            logger.error("Error copying media group message: %s", e)
    file_type = "b" if len(dumped_ids) > 1 else "s"
    token = generate_token(file_type, dumped_ids)
    try:
        messages[-1].reply_text(f"Permanent link:\n{BASE_URL}/{token}")
    except Exception as e:
        logger.error("Error replying with permanent link: %s", e)
    media_group_dict.pop(mgid, None)

def start_command(update: Update, context):
    message = update.message
    args = context.args
    if not args:
        message.reply_text("Welcome! Please use a valid link to retrieve files.")
        return

    token = args[0]
    file_type, msg_ids = parse_token(token)
    if not file_type or not msg_ids:
        message.reply_text("Invalid or expired link.")
        return

    user_id = message.from_user.id
    if not check_force_subscriptions(user_id):
        kb = [
            [
                InlineKeyboardButton("Join Channel 1", url=join_button(FORCE_SUB_CHANNEL1)),
                InlineKeyboardButton("Join Channel 2", url=join_button(FORCE_SUB_CHANNEL2))
            ],
            [InlineKeyboardButton("Try Again", callback_data=f"retry:{token}")]
        ]
        message.reply_text("You must join the required channels before you can get the file(s).",
                           reply_markup=InlineKeyboardMarkup(kb))
        return

    for mid in msg_ids:
        try:
            bot.copy_message(
                chat_id=message.chat_id, from_chat_id=DUMP_CHANNEL, message_id=mid
            )
        except Exception as e:
            logger.error("Error sending file to user: %s", e)
            message.reply_text("An error occurred while sending the file.")

def callback_handler(update: Update, context):
    query = update.callback_query
    query.answer()
    data = query.data
    if data.startswith("retry:"):
        token = data.split("retry:")[1]
        file_type, msg_ids = parse_token(token)
        if not file_type or not msg_ids:
            query.edit_message_text("Invalid link.")
            return
        user_id = query.from_user.id
        if not check_force_subscriptions(user_id):
            query.edit_message_text("You still need to join the required channels.")
            return
        for mid in msg_ids:
            try:
                bot.copy_message(
                    chat_id=query.message.chat_id, from_chat_id=DUMP_CHANNEL, message_id=mid
                )
            except Exception as e:
                logger.error("Error sending file on retry: %s", e)
                query.message.reply_text("An error occurred while sending the file.")
        query.edit_message_text("Files sent. Enjoy!")

dispatcher.add_handler(MessageHandler(Filters.document | Filters.video | Filters.audio | Filters.photo, process_file_messages))
dispatcher.add_handler(CommandHandler("start", start_command, pass_args=True))
dispatcher.add_handler(CallbackQueryHandler(callback_handler))

# ===== WEBHOOK ROUTES =====
@app.route("/webhook", methods=["POST"])
def webhook_handler():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "OK"

@app.route("/<token>", methods=["GET"])
def permanent_link(token):
    try:
        bot_username = bot.get_me().username
        deep_link = f"https://t.me/{bot_username}?start={token}"
        return redirect(deep_link, code=302)
    except Exception as e:
        logger.error("Error in permanent link redirect: %s", e)
        abort(404)

@app.route("/")
def index():
    return "Telegram File Dump Bot is running."

if __name__ == "__main__":
    # This block is used when running locally.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
