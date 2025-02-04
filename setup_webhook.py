#!/usr/bin/env python3
import os
import logging
import time
from telegram import Bot
from telegram.error import RetryAfter, TelegramError

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME")
if HEROKU_APP_NAME:
    BASE_URL = f"https://{HEROKU_APP_NAME}.herokuapp.com"
else:
    BASE_URL = os.environ.get("BASE_URL")
WEBHOOK_URL = f"{BASE_URL}/webhook"

bot = Bot(BOT_TOKEN)

def set_webhook():
    try:
        current_webhook = bot.get_webhook_info().url
        if current_webhook == WEBHOOK_URL:
            logger.info("Webhook already set to desired URL: %s", WEBHOOK_URL)
        else:
            logger.info("Current webhook: %s. Setting to desired URL: %s", current_webhook, WEBHOOK_URL)
            bot.delete_webhook()
            bot.set_webhook(url=WEBHOOK_URL)
            logger.info("Webhook successfully set to %s", WEBHOOK_URL)
    except RetryAfter as e:
        logger.error("Flood control exceeded. Retry in %s seconds", e.retry_after)
        time.sleep(e.retry_after)
        set_webhook()
    except TelegramError as e:
        logger.error("Telegram error while setting webhook: %s", e)

if __name__ == "__main__":
    set_webhook()
