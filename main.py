import re
import io
import os
import tempfile
import requests
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ================== CONFIGURATION ==================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set in .env or environment!")

ALLOWED_PHONES_STR = os.getenv("ALLOWED_PHONES")
if not ALLOWED_PHONES_STR:
    raise ValueError("ALLOWED_PHONES not set in .env or environment!")
# Parse comma-separated list, trimming spaces and ignoring empty entries
ALLOWED_PHONES = [phone.strip() for phone in ALLOWED_PHONES_STR.split(",") if phone.strip()]

# URL pattern for the orbit data page (adjust if necessary)
URL_PATTERN = "https://celestrak.org/NORAD/elements/graph-orbit-data.php?CATNR={sat_id}"

# ================== GLOBAL AUTHORIZATION ==================
authorized_users = set()   # stores chat_ids of authorized users

# ================== DATA FETCHING & PDF GENERATION ==================
def fetch_sma_data(sat_id):
    """Return (sat_name, DataFrame with Date & SMA) or (None, None)."""
    url = URL_PATTERN.format(sat_id=sat_id)
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print(f"  Error fetching {sat_id}: {e}")
        return None, None

    match = re.search(r'var plotData = "(.*?)";', html, re.DOTALL)
    if not match:
        return None, None

    csv_raw = match.group(1)
    csv_clean = csv_raw.replace('|', '\n')
    try:
        df = pd.read_csv(io.StringIO(csv_clean))
    except Exception:
        return None, None

    if 'Date' not in df.columns or 'SMA' not in df.columns:
        return None, None

    df['Date'] = pd.to_datetime(df['Date'])

    # Extract satellite name
    soup = BeautifulSoup(html, 'html.parser')
    title_tag = soup.find('title')
    sat_name = f"Satellite {sat_id}"
    if title_tag:
        sat_name = title_tag.text.strip()
    title_match = re.search(r'text:\s*"<b>Orbit Data \[GP\]<br>(.*?)<\/b>"', html)
    if title_match:
        sat_name = title_match.group(1)

    return sat_name, df[['Date', 'SMA']]


def generate_pdf(sat_ids, pdf_filename="satellite_plots.pdf"):
    tmp_path = os.path.join(tempfile.gettempdir(), pdf_filename)
    pdf = PdfPages(tmp_path)
    successful = 0

    for sid in sat_ids:
        name, df = fetch_sma_data(sid)
        if df is None or df.empty:
            continue

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(df['Date'], df['SMA'], linewidth=2, color='black')
        ax.set_title(f"{name}\nSMA over Time", fontsize=14)
        ax.set_xlabel("Date (UTC)")
        ax.set_ylabel("Semi-Major Axis (km)")

        # Move y-axis to the right
        ax.yaxis.tick_right()
        ax.yaxis.set_label_position("right")

        ax.grid(True, linestyle='--', alpha=0.7)
        plt.tight_layout()
        pdf.savefig()
        plt.close()
        successful += 1

    pdf.close()
    if successful == 0:
        os.remove(tmp_path)
        return None
    return tmp_path

# ================== BOT HANDLERS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask for phone number to verify."""
    button = KeyboardButton("Share phone number", request_contact=True)
    reply_markup = ReplyKeyboardMarkup([[button]], one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text(
        "Welcome! To use this bot, please share your phone number for verification.",
        reply_markup=reply_markup
    )

async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify the contact phone number against the allowed list."""
    contact = update.message.contact
    phone = contact.phone_number

    # Normalize the received number: remove spaces, dashes, parentheses, plus sign
    def clean_number(num):
        return re.sub(r'[\s\-\(\)]', '', num).lstrip('+')

    cleaned_phone = clean_number(phone)

    # Check against any allowed number
    allowed = any(cleaned_phone == clean_number(allowed) for allowed in ALLOWED_PHONES)

    if allowed:
        authorized_users.add(update.effective_chat.id)
        await update.message.reply_text(
            "✅ Authorization successful!\n\n"
            "Send me satellite IDs and an optional filename.\n"
            "Example: `68360 68361 results.pdf`",
            reply_markup=None
        )
    else:
        await update.message.reply_text("❌ Unauthorized phone number. Access denied.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parse satellite IDs and filename, generate PDF, and send it."""
    chat_id = update.effective_chat.id
    if chat_id not in authorized_users:
        await update.message.reply_text("You are not authorized. Use /start to verify.")
        return

    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("Please send satellite IDs and an optional filename.")
        return

    # Extract all integers as satellite IDs
    id_tokens = re.findall(r'\b\d+\b', text)
    sat_ids = [int(t) for t in id_tokens]

    # Extract a filename ending with .pdf (case-insensitive)
    filename_match = re.search(r'\b([\w\-]+\.pdf)\b', text, re.IGNORECASE)
    pdf_filename = filename_match.group(1) if filename_match else "satellite_plots.pdf"

    if not sat_ids:
        await update.message.reply_text("No satellite IDs found. Please send numbers like `68360 68361 results.pdf`.")
        return

    await update.message.reply_text(f"⏳ Processing {len(sat_ids)} satellite(s)... This may take a moment.")

    pdf_path = generate_pdf(sat_ids, pdf_filename)
    if pdf_path is None:
        await update.message.reply_text("⚠️ Could not retrieve data for any of the provided IDs.")
        return

    with open(pdf_path, 'rb') as f:
        await update.message.reply_document(document=f, filename=pdf_filename)
    os.remove(pdf_path)
    await update.message.reply_text("✅ Done! Send me another set of IDs or /start to restart.")

# ================== MAIN ==================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, contact_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()