import asyncio
import re
import os
import logging
from datetime import datetime, timezone, timedelta, time

from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from sma_bot.config import BOT_TOKEN, ALLOWED_PHONES
from sma_bot import db
from sma_bot.db import Satellite, SmaHistoryEntry
from sma_bot import spacetrack_client as stc
from sma_bot.service import SatelliteService, ActualizeStatus
from sma_bot.cron import actualize_all
from sma_bot.plotting import generate_pdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

MAX_IDS = 50
PLOT_WINDOW_DAYS = 90

authorized_users: set[int] = set()


def _parse_message(text: str) -> tuple[list[int], str]:
    id_tokens = re.findall(r"\b\d+\b", text)
    sat_ids = [int(t) for t in id_tokens]
    filename_match = re.search(r"\b([\w\-]+)\.pdf\b", text, re.IGNORECASE)
    pdf_name = filename_match.group(1) + ".pdf" if filename_match else "satellite_plots.pdf"
    return sat_ids, pdf_name


def _sanitize_filename(name: str) -> str:
    name = name.replace("/", "").replace("\\", "").replace("..", "")
    if not name.endswith(".pdf"):
        name += ".pdf"
    return name


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    button = KeyboardButton("Share phone number", request_contact=True)
    reply_markup = ReplyKeyboardMarkup([[button]], one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text(
        "Welcome! To use this bot, please share your phone number for verification.",
        reply_markup=reply_markup,
    )


async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    phone = contact.phone_number

    def clean_number(num: str) -> str:
        return re.sub(r"[\s\-\(\)]", "", num).lstrip("+")

    cleaned_phone = clean_number(phone)
    allowed = any(cleaned_phone == clean_number(p) for p in ALLOWED_PHONES)

    if allowed:
        authorized_users.add(update.effective_chat.id)
        await update.message.reply_text(
            "Authorization successful!\n\n"
            "Send me NORAD catalog IDs and an optional filename.\n"
            "Example: `25544,43013,48274 my_report.pdf`\n\n"
            f"Max {MAX_IDS} IDs per request.",
            reply_markup=None,
        )
    else:
        await update.message.reply_text("Unauthorized phone number. Access denied.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in authorized_users:
        await update.message.reply_text("You are not authorized. Use /start to verify.")
        return

    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("Please send NORAD IDs and an optional filename.")
        return

    sat_ids, pdf_name = _parse_message(text)
    if not sat_ids:
        await update.message.reply_text("No satellite IDs found. Send numbers like `25544,43013 results.pdf`.")
        return
    if len(sat_ids) > MAX_IDS:
        await update.message.reply_text(f"Too many IDs. Maximum is {MAX_IDS}.")
        return

    pdf_name = _sanitize_filename(pdf_name)

    try:
        await update.message.reply_text("Working on it...")
        service = SatelliteService(db, stc)
        results = await asyncio.get_event_loop().run_in_executor(None, service.actualize, sat_ids)

        counts = {s: 0 for s in ActualizeStatus}
        for r in results:
            counts[r.status] += 1
        parts = []
        if counts[ActualizeStatus.New]:
            parts.append(f"{counts[ActualizeStatus.New]} new")
        if counts[ActualizeStatus.Refreshed]:
            parts.append(f"{counts[ActualizeStatus.Refreshed]} refresh")
        if counts[ActualizeStatus.Cached]:
            parts.append(f"{counts[ActualizeStatus.Cached]} cached")
        await update.message.reply_text(f"Processed {len(sat_ids)} satellite(s) ({', '.join(parts)})...")

        cutoff = datetime.now(timezone.utc) - timedelta(days=PLOT_WINDOW_DAYS)
        entities: dict[int, tuple[Satellite, list[SmaHistoryEntry]]] = {}
        for nid in sat_ids:
            sat = db.get_satellite(nid)
            if sat:
                entities[nid] = (sat, db.get_sma_history([nid], since=cutoff)[nid])

        pdf_path = generate_pdf(entities, pdf_name, id_order=sat_ids)

        if pdf_path is None:
            await update.message.reply_text("Could not retrieve data for any of the provided IDs.")
            return

        with open(pdf_path, "rb") as f:
            await update.message.reply_document(document=f, filename=pdf_name)
        os.remove(pdf_path)

        not_found = [r.sat_id for r in results if r.status == ActualizeStatus.NotFound]
        if not_found:
            await update.message.reply_text(f"Note: no data found for IDs: {', '.join(str(i) for i in not_found)}")
        else:
            await update.message.reply_text("Done! Send another set of IDs or /start to restart.")

    except Exception as e:
        logger.exception("Error processing request")
        await update.message.reply_text(f"Something went wrong: {e}")


def main():
    db.init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, contact_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    jq = app.job_queue
    jq.run_daily(actualize_all, time=time(hour=00, minute=3), name="cron_00_03")
    jq.run_daily(actualize_all, time=time(hour=12, minute=3), name="cron_12_03")

    logger.info("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
