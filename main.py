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
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()  # e.g. "123,456"
ADMIN_IDS = set()
if ADMIN_IDS_RAW:
    for part in ADMIN_IDS_RAW.replace(" ", "").split(","):
        if part.isdigit():
            ADMIN_IDS.add(int(part))

# If you want fallback (NOT recommended on Railway), uncomment and set:
# if not ADMIN_IDS: ADMIN_IDS = {123456789}

JACKPOT_PERCENT = float(os.getenv("JACKPOT_PERCENT", "0.15"))
DRAW_INTERVAL_HOURS = int(os.getenv("DRAW_INTERVAL_HOURS", "24"))

# =========================
# DB (SQLite)
# =========================
DB_PATH = os.getenv("DB_PATH", "bot.db")

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row


def now():
    return datetime.utcnow().isoformat(timespec="seconds")


def init_db():
    """
    IMPORTANT FIX:
    - jackpot needs a PRIMARY KEY so INSERT OR IGNORE works.
    - system needs PRIMARY KEY too (key).
    """
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
        tickets INTEGER NOT NULL,
        price REAL NOT NULL,
        active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS ref_offers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        url TEXT NOT NULL,
        reward_type TEXT NOT NULL,  -- stars | tickets
        reward INTEGER NOT NULL,
        active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS jackpot (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        amount REAL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS winners (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        prize INTEGER,
        created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS system (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """)
    # Seed singleton rows safely
    db.execute("INSERT OR IGNORE INTO jackpot(id, amount) VALUES(1, 0)")
    db.execute("INSERT OR IGNORE INTO system(key, value) VALUES('last_draw', '0')")
    db.commit()


# =========================
# TEXTS (multi-language)
# =========================
TEXT = {
    "en": {
        "welcome": "⭐ Welcome!\n🎟 1 Ticket = $1 value\n\nBuy tickets, earn rewards & win Stars 👇",
        "lang_set": "✅ Language updated",
        "shop_title": "🛒 Ticket Shop\nAuto delivery",
        "shop_empty": "🛒 Shop is empty.\nAsk admin to add packs.\n(Admin: /seed)",
        "offers_empty": "No offers right now.",
        "offer_done": "🎉 Reward added!",
        "pack_unavailable": "❌ Pack unavailable",
        "purchased": "✅ Purchased!\n+{n} tickets 🎟",
        "lottery": "🎰 Lottery",
        "lottery_text": "🎟 Tickets: {t}\n💰 Jackpot: ${j}\n⏱ Next draw in: {h}h",
        "not_admin": "❌ Admin only",
        "seed_done": "✅ Seed done: packs 1/$1, 5/$4, 10/$8",
        "offer_added": "✅ Offer added",
        "pack_added": "✅ Ticket pack added",
        "help_admin": (
            "Admin commands:\n"
            "/seed\n"
            "/add_pack <tickets> <price>\n"
            "/add_offer Title | url | stars/tickets | amount\n"
        ),
    },
    "ua": {
        "welcome": "⭐ Ласкаво просимо!\n🎟 1 квиток = $1\n\nКупуй квитки, заробляй та вигравай ⭐ 👇",
        "lang_set": "✅ Мову змінено",
        "shop_title": "🛒 Магазин квитків\nАвтоматична доставка",
        "shop_empty": "🛒 Магазин порожній.\nПопроси адміна додати пакети.\n(Адмін: /seed)",
        "offers_empty": "Наразі немає завдань.",
        "offer_done": "🎉 Нагороду зараховано!",
        "pack_unavailable": "❌ Пакет недоступний",
        "purchased": "✅ Куплено!\n+{n} квитків 🎟",
        "lottery": "🎰 Лотерея",
        "lottery_text": "🎟 Квитки: {t}\n💰 Джекпот: ${j}\n⏱ До розіграшу: {h} год",
        "not_admin": "❌ Тільки для адміна",
        "seed_done": "✅ Додано пакети: 1/$1, 5/$4, 10/$8",
        "offer_added": "✅ Оффер додано",
        "pack_added": "✅ Пакет додано",
        "help_admin": (
            "Команди адміна:\n"
            "/seed\n"
            "/add_pack <квитки> <ціна>\n"
            "/add_offer Назва | url | stars/tickets | сума\n"
        ),
    }
}


def get_lang(uid: int) -> str:
    row = db.execute("SELECT lang FROM users WHERE user_id=?", (uid,)).fetchone()
    if row and row["lang"] in TEXT:
        return row["lang"]
    return "en"


def t(uid: int, key: str, **kw) -> str:
    lang = get_lang(uid)
    return TEXT[lang][key].format(**kw)


# =========================
# Helpers
# =========================
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def ensure_user(uid: int):
    db.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (uid,))
    db.commit()


def vip_mult(uid: int) -> int:
    row = db.execute("SELECT vip_until FROM users WHERE user_id=?", (uid,)).fetchone()
    if not row or not row["vip_until"]:
        return 1
    return 2 if row["vip_until"] > now() else 1


# =========================
# UI
# =========================
def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇺🇸 EN", callback_data="lang:en"),
            InlineKeyboardButton("🇺🇦 UA", callback_data="lang:ua"),
        ],
        [InlineKeyboardButton("🎟 Buy Tickets", callback_data="shop")],
        [InlineKeyboardButton("🔥 Earn Rewards", callback_data="offers")],
        [InlineKeyboardButton("🎰 Lottery", callback_data="lottery")],
    ])


# =========================
# Handlers
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    await update.message.reply_text(t(uid, "welcome"), reply_markup=main_menu())


async def set_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    ensure_user(uid)

    lang = q.data.split(":")[1]
    if lang not in TEXT:
        lang = "en"

    db.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, uid))
    db.commit()

    await q.edit_message_text(t(uid, "lang_set"), reply_markup=main_menu())


async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    ensure_user(uid)

    packs = db.execute("SELECT * FROM ticket_packs WHERE active=1 ORDER BY tickets").fetchall()
    if not packs:
        await q.edit_message_text(t(uid, "shop_empty"), reply_markup=main_menu())
        return

    kb = [[InlineKeyboardButton(f"🎟 {p['tickets']} — ${p['price']}", callback_data=f"buy:{p['id']}")]
          for p in packs]
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])

    await q.edit_message_text(t(uid, "shop_title"), reply_markup=InlineKeyboardMarkup(kb))


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    IMPORTANT:
    This is auto-delivery logic.
    Real payments (Telegram Stars / Stripe) can be connected later,
    but logic is ready and stable.
    """
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    ensure_user(uid)

    pack_id = int(q.data.split(":")[1])
    pack = db.execute("SELECT * FROM ticket_packs WHERE id=? AND active=1", (pack_id,)).fetchone()
    if not pack:
        await q.edit_message_text(t(uid, "pack_unavailable"), reply_markup=main_menu())
        return

    mult = vip_mult(uid)
    tickets = int(pack["tickets"]) * mult

    # Add tickets + jackpot growth
    db.execute("UPDATE users SET tickets=tickets+? WHERE user_id=?", (tickets, uid))
    db.execute("UPDATE jackpot SET amount = amount + ? WHERE id=1", (float(pack["price"]) * JACKPOT_PERCENT,))
    db.commit()

    await q.edit_message_text(t(uid, "purchased", n=tickets), reply_markup=main_menu())


async def offers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    ensure_user(uid)

    offer = db.execute("SELECT * FROM ref_offers WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone()
    if not offer:
        await q.edit_message_text(t(uid, "offers_empty"), reply_markup=main_menu())
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I’ve completed", callback_data=f"done:{offer['id']}")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back")]
    ])

    await q.edit_message_text(
        f"🔥 {offer['title']}\n{offer['url']}\nReward: +{offer['reward']} {offer['reward_type']}",
        reply_markup=kb
    )


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    ensure_user(uid)

    oid = int(q.data.split(":")[1])
    offer = db.execute("SELECT * FROM ref_offers WHERE id=? AND active=1", (oid,)).fetchone()
    if not offer:
        await q.edit_message_text("❌ Offer expired", reply_markup=main_menu())
        return

    mult = vip_mult(uid)
    reward = int(offer["reward"]) * mult

    if offer["reward_type"] == "tickets":
        db.execute("UPDATE users SET tickets=tickets+? WHERE user_id=?", (reward, uid))
    else:
        db.execute("UPDATE users SET stars=stars+? WHERE user_id=?", (reward, uid))

    db.commit()
    await q.edit_message_text(t(uid, "offer_done"), reply_markup=main_menu())


async def lottery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    ensure_user(uid)

    user = db.execute("SELECT tickets FROM users WHERE user_id=?", (uid,)).fetchone()
    jackpot = db.execute("SELECT amount FROM jackpot WHERE id=1").fetchone()["amount"]

    last = int(db.execute("SELECT value FROM system WHERE key='last_draw'").fetchone()["value"])
    remain = max(0, DRAW_INTERVAL_HOURS * 3600 - (int(time.time()) - last))

    await q.edit_message_text(
        f"{t(uid, 'lottery')}\n\n" + t(uid, "lottery_text", t=user["tickets"], j=int(jackpot), h=remain // 3600),
        reply_markup=main_menu()
    )


async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    ensure_user(uid)
    await q.edit_message_text(t(uid, "welcome"), reply_markup=main_menu())


# =========================
# Admin commands
# =========================
async def seed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    if not is_admin(uid):
        await update.message.reply_text(t(uid, "not_admin"))
        return

    # insert default packs if empty
    existing = db.execute("SELECT COUNT(*) c FROM ticket_packs").fetchone()["c"]
    if existing == 0:
        db.execute("INSERT INTO ticket_packs(tickets, price, active) VALUES(1, 1.0, 1)")
        db.execute("INSERT INTO ticket_packs(tickets, price, active) VALUES(5, 4.0, 1)")
        db.execute("INSERT INTO ticket_packs(tickets, price, active) VALUES(10, 8.0, 1)")
        db.commit()

    await update.message.reply_text(t(uid, "seed_done"))


async def add_pack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    if not is_admin(uid):
        await update.message.reply_text(t(uid, "not_admin"))
        return

    # /add_pack 5 4
    parts = update.message.text.strip().split()
    if len(parts) != 3 or (not parts[1].isdigit()):
        await update.message.reply_text("Usage: /add_pack <tickets:int> <price:float>")
        return

    tickets = int(parts[1])
    price = float(parts[2])
    db.execute("INSERT INTO ticket_packs(tickets, price, active) VALUES(?,?,1)", (tickets, price))
    db.commit()
    await update.message.reply_text(t(uid, "pack_added"))


async def add_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    if not is_admin(uid):
        await update.message.reply_text(t(uid, "not_admin"))
        return

    # /add_offer Title | url | stars/tickets | 3
    raw = update.message.text.split(" ", 1)
    if len(raw) < 2:
        await update.message.reply_text("Usage: /add_offer Title | url | stars/tickets | amount")
        return

    data = raw[1]
    parts = [p.strip() for p in data.split("|")]
    if len(parts) != 4:
        await update.message.reply_text("Usage: /add_offer Title | url | stars/tickets | amount")
        return

    title, url, rtype, amount = parts
    rtype = rtype.lower()
    if rtype not in ("stars", "tickets"):
        await update.message.reply_text("reward_type must be 'stars' or 'tickets'")
        return
    if not amount.isdigit():
        await update.message.reply_text("amount must be integer")
        return

    db.execute(
        "INSERT INTO ref_offers(title, url, reward_type, reward, active) VALUES(?,?,?,?,1)",
        (title, url, rtype, int(amount))
    )
    db.commit()
    await update.message.reply_text(t(uid, "offer_added"))


async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    if not is_admin(uid):
        await update.message.reply_text(t(uid, "not_admin"))
        return
    await update.message.reply_text(t(uid, "help_admin"))


# =========================
# Run
# =========================
def main():
    if not TOKEN:
        # Railway Logs will show this clearly
        raise RuntimeError("TOKEN is empty. Set Railway Variable TOKEN=...")

    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("seed", seed))
    app.add_handler(CommandHandler("add_pack", add_pack))
    app.add_handler(CommandHandler("add_offer", add_offer))
    app.add_handler(CommandHandler("admin_help", admin_help))

    app.add_handler(CallbackQueryHandler(set_lang, pattern=r"^lang:"))
    app.add_handler(CallbackQueryHandler(shop, pattern=r"^shop$"))
    app.add_handler(CallbackQueryHandler(offers, pattern=r"^offers$"))
    app.add_handler(CallbackQueryHandler(lottery, pattern=r"^lottery$"))
    app.add_handler(CallbackQueryHandler(back, pattern=r"^back$"))
    app.add_handler(CallbackQueryHandler(buy, pattern=r"^buy:\d+$"))
    app.add_handler(CallbackQueryHandler(done, pattern=r"^done:\d+$"))

    app.run_polling()


if __name__ == "__main__":
    main()

