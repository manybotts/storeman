#!/usr/bin/env python3
import os
import logging
import time
from telegram import Bot
from telegram.error import RetryAfter, TelegramError

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS.split(",") if x.strip()]
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME")
if HEROKU_APP_NAME:
    BASE_URL = f"https://{HEROKU_APP_NAME}.herokuapp.com"
else:
    BASE_URL = os.environ.get("BASE_URL")
WEBHOOK_URL = f"{BASE_URL}/webhook"

bot = Bot(BOT_TOKEN)

def notify_admins(message_text):
    for admin in ADMIN_IDS:
        try:
            bot.send_message(chat_id=admin, text=message_text)
        except Exception as e:
            logger.error("Failed to notify admin %s: %s", admin, e)

def set_webhook():
    try:
        current = bot.get_webhook_info().url
        if current == WEBHOOK_URL:
            logger.info("Webhook already set to %s", WEBHOOK_URL)
            notify_admins(f"Deployment succeeded: Webhook already set to {WEBHOOK_URL}")
        else:
            logger.info("Setting webhook to %s (current: %s)", WEBHOOK_URL, current)
            bot.delete_webhook()
            bot.set_webhook(url=WEBHOOK_URL)
            logger.info("Webhook successfully set to %s", WEBHOOK_URL)
            notify_admins(f"Deployment succeeded: Webhook set to {WEBHOOK_URL}")
    except RetryAfter as e:
        logger.error("Flood control exceeded, retrying in %s seconds", e.retry_after)
        time.sleep(e.retry_after)
        set_webhook()
    except TelegramError as e:
        logger.error("Telegram error setting webhook: %s", e)
        notify_admins(f"Deployment error: {e}")
    except Exception as e:
        logger.error("Unexpected error setting webhook: %s", e)
        notify_admins(f"Deployment error: {e}")

if __name__ == "__main__":
    set_webhook()
