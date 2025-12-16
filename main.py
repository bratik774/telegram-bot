import sqlite3, time
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# ================== CONFIG ==================
TOKEN = "PASTE_BOT_TOKEN"
ADMIN_IDS = {123456789}

TICKET_PRICE_USD = 1
JACKPOT_PERCENT = 0.15
DRAW_INTERVAL_HOURS = 24

# ================== DB ==================
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
        amount REAL DEFAULT 0
    );
    INSERT OR IGNORE INTO jackpot(amount) VALUES(0);

    CREATE TABLE IF NOT EXISTS system (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    INSERT OR IGNORE INTO system(key,value) VALUES('last_draw','0');
    """)
    db.commit()

# ================== TEXTS ==================
TEXT = {
    "en": {
        "welcome": "⭐ Welcome!\n🎟 1 Ticket = $1 value\n\nBuy tickets, earn rewards & win Stars 👇",
        "shop": "🛒 Ticket Shop\nAuto delivery",
        "no_offers": "No offers right now.",
        "reward_added": "🎉 Reward added!",
        "purchased": "✅ Purchased!\n+{n} tickets 🎟",
        "lang_set": "✅ Language updated",
    },
    "ua": {
        "welcome": "⭐ Ласкаво просимо!\n🎟 1 квиток = $1\n\nКупуй квитки, заробляй та вигравай ⭐ 👇",
        "shop": "🛒 Магазин квитків\nАвтоматична доставка",
        "no_offers": "Наразі немає завдань.",
        "reward_added": "🎉 Нагороду зараховано!",
        "purchased": "✅ Куплено!\n+{n} квитків 🎟",
        "lang_set": "✅ Мову змінено",
    }
}

def t(uid, key, **kw):
    row = db.execute("SELECT lang FROM users WHERE user_id=?", (uid,)).fetchone()
    lang = row["lang"] if row and row["lang"] in TEXT else "en"
    return TEXT[lang][key].format(**kw)

# ================== HELPERS ==================
def is_admin(uid): return uid in ADMIN_IDS

def ensure_user(uid):
    db.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (uid,))
    db.commit()

def vip_mult(uid):
    row = db.execute("SELECT vip_until FROM users WHERE user_id=?", (uid,)).fetchone()
    return 2 if row and row["vip_until"] and row["vip_until"] > now() else 1

# ================== HANDLERS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇺🇸 EN", callback_data="lang:en"),
            InlineKeyboardButton("🇺🇦 UA", callback_data="lang:ua")
        ],
        [InlineKeyboardButton("🎟 Buy Tickets", callback_data="shop")],
        [InlineKeyboardButton("🔥 Earn Rewards", callback_data="offers")],
        [InlineKeyboardButton("🎰 Lottery", callback_data="lottery")]
    ])

    await update.message.reply_text(t(uid, "welcome"), reply_markup=kb)

async def set_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lang = q.data.split(":")[1]
    db.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, q.from_user.id))
    db.commit()
    await q.edit_message_text(t(q.from_user.id, "lang_set"))

async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    packs = db.execute("SELECT * FROM ticket_packs WHERE active=1").fetchall()

    kb = [[InlineKeyboardButton(
        f"🎟 {p['tickets']} — ${p['price']}",
        callback_data=f"buy:{p['id']}"
    )] for p in packs]

    await q.edit_message_text(t(q.from_user.id, "shop"), reply_markup=InlineKeyboardMarkup(kb))

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    pack_id = int(q.data.split(":")[1])

    pack = db.execute("SELECT * FROM ticket_packs WHERE id=? AND active=1", (pack_id,)).fetchone()
    if not pack: return

    tickets = pack["tickets"] * vip_mult(uid)
    db.execute("UPDATE users SET tickets=tickets+? WHERE user_id=?", (tickets, uid))
    db.execute("UPDATE jackpot SET amount = amount + ?", (pack["price"] * JACKPOT_PERCENT,))
    db.commit()

    await q.edit_message_text(t(uid, "purchased", n=tickets))

async def offers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id

    offer = db.execute("SELECT * FROM ref_offers WHERE active=1 LIMIT 1").fetchone()
    if not offer:
        await q.edit_message_text(t(uid, "no_offers")); return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I’ve completed", callback_data=f"done:{offer['id']}")]
    ])

    await q.edit_message_text(
        f"🔥 {offer['title']}\n{offer['url']}\nReward: +{offer['reward']} {offer['reward_type']}",
        reply_markup=kb
    )

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    oid = int(q.data.split(":")[1])

    offer = db.execute("SELECT * FROM ref_offers WHERE id=? AND active=1", (oid,)).fetchone()
    if not offer: return

    reward = offer["reward"] * vip_mult(uid)
    if offer["reward_type"] == "tickets":
        db.execute("UPDATE users SET tickets=tickets+? WHERE user_id=?", (reward, uid))
    else:
        db.execute("UPDATE users SET stars=stars+? WHERE user_id=?", (reward, uid))

    db.commit()
    await q.edit_message_text(t(uid, "reward_added"))

async def lottery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id

    user = db.execute("SELECT tickets FROM users WHERE user_id=?", (uid,)).fetchone()
    jackpot = db.execute("SELECT amount FROM jackpot").fetchone()["amount"]

    last = int(db.execute("SELECT value FROM system WHERE key='last_draw'").fetchone()["value"])
    remain = max(0, DRAW_INTERVAL_HOURS*3600 - (int(time.time()) - last))

    await q.edit_message_text(
        f"🎰 Lottery\n\n"
        f"🎟 Tickets: {user['tickets']}\n"
        f"💰 Jackpot: ${int(jackpot)}\n"
        f"⏱ Next draw in: {remain//3600}h"
    )

# ================== ADMIN ==================
async def add_pack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    _, t, p = update.message.text.split()
    db.execute("INSERT INTO ticket_packs(tickets,price) VALUES(?,?)", (int(t), float(p)))
    db.commit()
    await update.message.reply_text("✅ Ticket pack added")

async def add_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    _, data = update.message.text.split(" ", 1)
    title, url, rtype, reward = [x.strip() for x in data.split("|")]
    db.execute(
        "INSERT INTO ref_offers(title,url,reward_type,reward) VALUES(?,?,?,?)",
        (title, url, rtype, int(reward))
    )
    db.commit()
    await update.message.reply_text("✅ Offer added")

# ================== RUN ==================
def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add_pack", add_pack))
    app.add_handler(CommandHandler("add_offer", add_offer))

    app.add_handler(CallbackQueryHandler(set_lang, pattern="lang:"))
    app.add_handler(CallbackQueryHandler(shop, pattern="shop"))
    app.add_handler(CallbackQueryHandler(offers, pattern="offers"))
    app.add_handler(CallbackQueryHandler(lottery, pattern="lottery"))
    app.add_handler(CallbackQueryHandler(buy, pattern="buy:"))
    app.add_handler(CallbackQueryHandler(done, pattern="done:"))

    app.run_polling()

main()

