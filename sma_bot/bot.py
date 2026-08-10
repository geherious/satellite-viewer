import re
import os
import logging
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from sma_bot.config import BOT_TOKEN, ALLOWED_PHONES
from sma_bot import db
from sma_bot.db import Satellite, SmaHistoryEntry
from sma_bot import spacetrack_client as stc
from sma_bot.plotting import generate_pdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

MAX_IDS = 50
PLOT_WINDOW_DAYS = 90
FRESHNESS_HOURS = 1

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


def _parse_iso(iso_str: str) -> datetime:
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _extract_entities(records: list[dict]) -> tuple[dict[int, Satellite], dict[int, list[SmaHistoryEntry]]]:
    sats: dict[int, Satellite] = {}
    points: dict[int, list[SmaHistoryEntry]] = {}
    for rec in records:
        nid = int(rec["NORAD_CAT_ID"])
        if nid not in sats:
            sats[nid] = Satellite(norad_cat_id=nid)
        name = rec.get("OBJECT_NAME")
        if name:
            sats[nid].object_name = name
        points.setdefault(nid, []).append(SmaHistoryEntry(
            epoch=_parse_iso(rec["EPOCH"]),
            semimajor_axis=float(rec["SEMIMAJOR_AXIS"]),
        ))
    return sats, points


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
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=PLOT_WINDOW_DAYS)
        one_hour_ago = now - timedelta(hours=FRESHNESS_HOURS)

        new_sats: list[int] = []
        sats_for_refresh: list[int] = []
        cached_sats: list[int] = []

        for nid in sat_ids:
            sat = db.get_satellite(nid)
            if sat is None:
                new_sats.append(nid)
            elif sat.last_fetch_at is None or sat.last_fetch_at < one_hour_ago:
                sats_for_refresh.append(nid)
            else:
                cached_sats.append(nid)

        parts = []
        if new_sats:
            parts.append(f"{len(new_sats)} new")
        if sats_for_refresh:
            parts.append(f"{len(sats_for_refresh)} refresh")
        if cached_sats:
            parts.append(f"{len(cached_sats)} cached")
        await update.message.reply_text(f"Processing {len(sat_ids)} satellite(s) ({', '.join(parts)})...")

        failed_ids: list[int] = []
        entities: dict[int, tuple[Satellite, list[SmaHistoryEntry]]] = {}

        if new_sats:
            records = stc.fetch_history(new_sats)
            sats, points = _extract_entities(records)
            for nid in new_sats:
                pts = points.get(nid, [])
                if pts:
                    sat = sats.get(nid, Satellite(norad_cat_id=nid))
                    sat.history_backfilled = True
                    sat.last_fetch_at = now
                    db.insert_satellite(sat)
                    db.insert_sma_points(nid, pts)
                else:
                    failed_ids.append(nid)
                    logger.warning("No history data for ID %d", nid)

        if sats_for_refresh:
            records = stc.fetch_current(sats_for_refresh)
            sats, points = _extract_entities(records)
            for nid in sats_for_refresh:
                pts = points.get(nid, [])
                if pts:
                    existing = db.get_satellite(nid) or Satellite(norad_cat_id=nid)
                    existing.last_fetch_at = now
                    if sats.get(nid) and sats[nid].object_name:
                        existing.object_name = sats[nid].object_name
                    db.insert_satellite(existing)
                    db.insert_sma_points(nid, pts)
                else:
                    failed_ids.append(nid)
                    logger.warning("No current data for ID %d", nid)

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

        if failed_ids:
            await update.message.reply_text(f"Note: no data found for IDs: {', '.join(str(i) for i in failed_ids)}")
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
    logger.info("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
