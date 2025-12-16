import os
import sqlite3
import time
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# =========================
# CONFIG (Railway Variables)
# =========================
TOKEN = os.getenv("TOKEN", "").strip()
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()

ADMIN_IDS = set()
if ADMIN_IDS_RAW:
    for part in ADMIN_IDS_RAW.replace(" ", "").split(","):
        if part.isdigit():
            ADMIN_IDS.add(int(part))

JACKPOT_PERCENT = float(os.getenv("JACKPOT_PERCENT", "0.15"))
DRAW_INTERVAL_HOURS = int(os.getenv("DRAW_INTERVAL_HOURS", "24"))

# ===== ADMIN SECRET =====
ADMIN_SECRET = "ADMIN-8472"
ADMIN_SECRET_ENABLED = True  # ❗ після налаштування постав False

# =========================
# DB
# =========================
db = sqlite3.connect("bot.db", check_same_thread=False)
db.row_factory = sqlite3.Row


def now():
    return datetime.utcnow().isoformat(timespec="seconds")


def init_db():
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        stars INTEGER DEFAULT 0,
        tickets INTEGER DEFAULT 0,
        vip_until TEXT,
        lang TEXT DEFAULT 'en'
    );

    CREATE TABLE IF NOT EXISTS ticket_packs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tickets INTEGER,
        price REAL,
        active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS ref_offers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        url TEXT,
        reward_type TEXT,
        reward INTEGER,
        active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS jackpot (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        amount REAL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS system (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """)
    db.execute("INSERT OR IGNORE INTO jackpot(id, amount) VALUES(1, 0)")
    db.execute("INSERT OR IGNORE INTO system(key, value) VALUES('last_draw', '0')")
    db.commit()


# =========================
# TEXTS
# =========================
TEXT = {
    "en": {
        "welcome": "⭐ Welcome!\n🎟 1 Ticket = $1\n\nChoose action 👇",
        "lang_set": "✅ Language updated",
        "not_admin": "❌ Admin only",
        "seed_done": "✅ Ticket packs added",
    },
    "ua": {
        "welcome": "⭐ Ласкаво просимо!\n🎟 1 квиток = $1\n\nОбери дію 👇",
        "lang_set": "✅ Мову змінено",
        "not_admin": "❌ Тільки для адміна",
        "seed_done": "✅ Пакети додано",
    }
}


def get_lang(uid):
    row = db.execute("SELECT lang FROM users WHERE user_id=?", (uid,)).fetchone()
    return row["lang"] if row else "en"


def t(uid, key):
    return TEXT.get(get_lang(uid), TEXT["en"])[key]


# =========================
# HELPERS
# =========================
def ensure_user(uid):
    db.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (uid,))
    db.commit()


def is_admin(uid):
    return uid in ADMIN_IDS


# =========================
# HANDLERS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇺🇸 EN", callback_data="lang:en"),
            InlineKeyboardButton("🇺🇦 UA", callback_data="lang:ua")
        ],
        [InlineKeyboardButton("🎟 Buy Tickets", callback_data="shop")]
    ])

    await update.message.reply_text(t(uid, "welcome"), reply_markup=kb)


async def set_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    lang = q.data.split(":")[1]

    db.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, uid))
    db.commit()

    await q.edit_message_text(t(uid, "lang_set"))


# =========================
# ADMIN SECRET COMMAND
# =========================
async def claim_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_SECRET_ENABLED:
        await update.message.reply_text("❌ Admin claim disabled")
        return

    parts = update.message.text.split()
    if len(parts) != 2:
        await update.message.reply_text("Usage: /claim_admin SECRET")
        return

    if parts[1] != ADMIN_SECRET:
        await update.message.reply_text("❌ Wrong secret code")
        return

    uid = update.effective_user.id
    ADMIN_IDS.add(uid)

    await update.message.reply_text(
        f"✅ YOU ARE ADMIN NOW\n\n"
        f"Your Telegram ID:\n{uid}\n\n"
        f"Add it to Railway → Variables:\nADMIN_IDS={uid}\n"
        f"Then Redeploy"
    )


# =========================
# ADMIN COMMANDS
# =========================
async def seed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text(t(uid, "not_admin"))
        return

    db.execute("INSERT INTO ticket_packs(tickets, price) VALUES(1,1)")
    db.execute("INSERT INTO ticket_packs(tickets, price) VALUES(5,4)")
    db.execute("INSERT INTO ticket_packs(tickets, price) VALUES(10,8)")
    db.commit()

    await update.message.reply_text(t(uid, "seed_done"))


# =========================
# RUN
# =========================
def main():
    if not TOKEN:
        raise RuntimeError("TOKEN is empty")

    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("claim_admin", claim_admin))
    app.add_handler(CommandHandler("seed", seed))

    app.add_handler(CallbackQueryHandler(set_lang, pattern="lang:"))

    app.run_polling()


if __name__ == "__main__":
    main()

