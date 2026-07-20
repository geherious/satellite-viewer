import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not set in .env or environment!")

SPACETRACK_IDENTITY = os.getenv("SPACETRACK_IDENTITY")
if not SPACETRACK_IDENTITY:
    raise ValueError("SPACETRACK_IDENTITY not set in .env or environment!")

SPACETRACK_PASSWORD = os.getenv("SPACETRACK_PASSWORD")
if not SPACETRACK_PASSWORD:
    raise ValueError("SPACETRACK_PASSWORD not set in .env or environment!")

ALLOWED_PHONES_STR = os.getenv("ALLOWED_PHONES")
if not ALLOWED_PHONES_STR:
    raise ValueError("ALLOWED_PHONES not set in .env or environment!")
ALLOWED_PHONES = [phone.strip() for phone in ALLOWED_PHONES_STR.split(",") if phone.strip()]

SMA_DB_PATH = os.getenv("SMA_DB_PATH", "./sma_bot.db")
