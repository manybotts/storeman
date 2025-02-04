#!/usr/bin/env python3
import os
import logging
import base64
import json
from datetime import datetime

import threading

from flask import Flask, request, redirect, abort, jsonify
from telegram import Bot, Update, InlineKeyboardMarkup, InlineKeyboardButton, ChatMember
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, CallbackQueryHandler, Filters
from pymongo import MongoClient

# ===== CONFIGURATION =====
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # Telegram bot token

ADMIN_IDS = os.environ.get("ADMIN_IDS", "")  # Comma-separated admin IDs (as integers)
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS.split(",") if x.strip()]

DUMP_CHANNEL = os.environ.get("DUMP_CHANNEL")
# Channel (ID or public username) where files are stored.

# Forced subscription channels (private channels; using channel IDs)
FORCE_SUB_CHANNEL1 = os.environ.get("FORCE_SUB_CHANNEL1")  # e.g., "-1001234567890"
FORCE_SUB_CHANNEL2 = os.environ.get("FORCE_SUB_CHANNEL2")  # e.g., "-1009876543210"

# Determine the base URL from Heroku’s app name or BASE_URL config var.
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME")
if HEROKU_APP_NAME:
    BASE_URL = f"https://{HEROKU_APP_NAME}.herokuapp.com"
else:
    BASE_URL = os.environ.get("BASE_URL")
if not BASE_URL:
    raise Exception("BASE_URL (or HEROKU_APP_NAME) must be set in config vars!")

# ===== DATABASE SETUP =====
MONGODB_URL = os.environ.get("MONGODB_URL")
if not MONGODB_URL:
    raise Exception("MONGODB_URL must be set in config vars!")
mongo_client = MongoClient(MONGODB_URL)
db = mongo_client.get_default_database()  # Or specify a database name, e.g. client['botdb']
users_collection = db["users"]

# ===== LOGGING SETUP =====
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== INITIALIZE FLASK & TELEGRAM BOT & DISPATCHER =====
app = Flask(__name__)
bot = Bot(BOT_TOKEN)
dispatcher = Dispatcher(bot, None, workers=4, use_context=True)

# ===== TOKEN UTILS (for file messages, if needed) =====
def encode_token(data: dict) -> str:
    json_str = json.dumps(data)
    return base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")

def decode_token(token: str) -> dict:
    try:
        json_str = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        return json.loads(json_str)
    except Exception as e:
        logger.error("Error decoding token: %s", e)
        return {}

def generate_token(file_type: str, msg_ids: list) -> str:
    data = {"t": file_type, "ids": msg_ids}
    return encode_token(data)

def parse_token(token: str):
    data = decode_token(token)
    if "t" in data and "ids" in data:
        return data["t"], data["ids"]
    return None, None

# ===== DATABASE FUNCTIONS =====
def register_user(user):
    """Store or update user info in MongoDB."""
    data = {
        "user_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "last_seen": datetime.utcnow()
    }
    users_collection.update_one({"user_id": user.id}, {"$set": data}, upsert=True)
    logger.info("Registered/updated user: %s", data)

# ===== SUBSCRIPTION CHECKS =====
def is_user_subscribed(user_id: int, channel: str) -> bool:
    try:
        member = bot.get_chat_member(chat_id=channel, user_id=user_id)
        if member.status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.CREATOR]:
            return True
    except Exception as e:
        logger.info("Subscription check: user %s not in channel %s: %s", user_id, channel, e)
    return False

def check_force_subscriptions(user_id: int) -> bool:
    return is_user_subscribed(user_id, FORCE_SUB_CHANNEL1) and is_user_subscribed(user_id, FORCE_SUB_CHANNEL2)

def join_button(channel_id: str) -> str:
    try:
        return bot.export_chat_invite_link(chat_id=channel_id)
    except Exception as e:
        logger.error("Failed to export invite link for channel %s: %s", channel_id, e)
        return "#"

# ===== HANDLERS =====
# For demonstration, we keep the handlers simple.
# In-memory storage for media groups (if needed in the future)
media_group_dict = {}

def start_command(update: Update, context):
    user = update.message.from_user
    register_user(user)
    logger.info("Received /start command from user %s", user.id)
    welcome_text = f"Welcome, {user.first_name}! Thank you for starting our bot."
    update.message.reply_text(welcome_text)

def help_command(update: Update, context):
    update.message.reply_text("Available commands:\n/start - Welcome message\n/help - This help text")

# (Additional file-handling commands can be added as needed.)
dispatcher.add_handler(CommandHandler("start", start_command))
dispatcher.add_handler(CommandHandler("help", help_command))

# ===== WEBHOOK ROUTES =====
@app.route("/webhook", methods=["POST"])
def webhook_route():
    try:
        update = Update.de_json(request.get_json(force=True), bot)
        logger.info("Received update: %s", update)
        dispatcher.process_update(update)
    except Exception as e:
        logger.error("Error processing update: %s", e)
    return "OK"

@app.route("/")
def index():
    return "Telegram File Dump Bot is running."

@app.route("/debug", methods=["GET"])
def debug_route():
    try:
        info = bot.get_webhook_info().to_dict()
        return jsonify(info)
    except Exception as e:
        logger.error("Error retrieving webhook info: %s", e)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # For local testing; in production, Gunicorn will serve the app.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
