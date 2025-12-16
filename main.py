import os
import sqlite3
import random
import time
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")

DB_PATH = "bot.db"

# ====== Налаштування винагород ======
REF_REWARDS = {1: 5.0, 2: 3.0, 3: 2.0}         # 3 рівні
TASK_DEFAULT_REWARD = 1.0                      # за завдання (по 1⭐)
MIN_WITHDRAW = 50.0                            # вивід від 50⭐

# VIP: дає множник нагород
VIP_MULT = 2.0
VIP_PRICE_STARS = 100  # ціна VIP в Stars (можеш змінити)

# Лотерея: призи
LOTTERY_PRIZES = [(1, 300.0), (2, 100.0), (3, 50.0)]
for p in range(4, 21):
    LOTTERY_PRIZES.append((p, 5.0))
for p in range(21, 41):
    LOTTERY_PRIZES.append((p, 2.5))
for p in range(41, 51):
    LOTTERY_PRIZES.append((p, 1.0))


# =========================
# DB
# =========================
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        balance REAL DEFAULT 0,
        referred_by INTEGER,
        is_vip INTEGER DEFAULT 0,
        created_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inviter_id INTEGER,
        invited_id INTEGER,
        level INTEGER,
        created_at INTEGER
    )
    """)

    # Твої реф-силки / партнерки (адмін додає)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS partner_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        url TEXT NOT NULL,
        reward REAL NOT NULL DEFAULT 1,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at INTEGER
    )
    """)

    # Заявки на нарахування за партнер-лінк (бо бот не може довести "перехід" сам)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS partner_claims (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        link_id INTEGER,
        status TEXT, -- pending/approved/declined
        created_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS withdraw_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        status TEXT, -- pending/approved/declined
        created_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ad_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        text TEXT,
        contact TEXT,
        status TEXT, -- pending/approved/declined
        created_at INTEGER
    )
    """)

    # Лотерея
    cur.execute("""
    CREATE TABLE IF NOT EXISTS lottery (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        is_active INTEGER DEFAULT 0,
        started_at INTEGER,
        ends_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS lottery_tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lottery_id INTEGER,
        user_id INTEGER,
        count INTEGER,
        created_at INTEGER
    )
    """)

    # Донати Stars
    cur.execute("""
    CREATE TABLE IF NOT EXISTS donations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        stars INTEGER,
        purpose TEXT, -- donate/vip/lottery
        created_at INTEGER
    )
    """)

    # Налаштування авто-розсилки партнер-лінків
    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    conn.commit()
    conn.close()


def get_setting(key: str, default: str = "0") -> str:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else default


def set_setting(key: str, value: str):
    conn = db()
    cur = conn.cursor()
    cur.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()
    conn.close()


def upsert_user(user_id: int, username: str, first_name: str, referred_by: int | None = None):
    now = int(time.time())
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id, referred_by FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?", (username, first_name, user_id))
    else:
        cur.execute(
            "INSERT INTO users(user_id, username, first_name, balance, referred_by, is_vip, created_at) VALUES(?,?,?,?,?,?,?)",
            (user_id, username, first_name, 0.0, referred_by, 0, now)
        )
    conn.commit()
    conn.close()


def get_user(user_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, first_name, balance, referred_by, is_vip FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


def add_balance(user_id: int, amount: float):
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = COALESCE(balance,0) + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()


def set_vip(user_id: int, on: bool):
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_vip=? WHERE user_id=?", (1 if on else 0, user_id))
    conn.commit()
    conn.close()


def is_admin(uid: int) -> bool:
    return ADMIN_ID and uid == ADMIN_ID


def vip_mult(uid: int) -> float:
    u = get_user(uid)
    if not u:
        return 1.0
    return VIP_MULT if int(u[5]) == 1 else 1.0


# =========================
# Referral logic (3 levels)
# =========================
def get_referred_by(user_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT referred_by FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def already_recorded_ref(invited_id: int) -> bool:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM referrals WHERE invited_id=? LIMIT 1", (invited_id,))
    row = cur.fetchone()
    conn.close()
    return bool(row)


def record_referral_chain(invited_id: int, inviter_id: int):
    now = int(time.time())
    chain = []
    current = inviter_id
    for level in (1, 2, 3):
        if not current:
            break
        chain.append((current, level))
        current = get_referred_by(current)

    conn = db()
    cur = conn.cursor()
    for inviter, level in chain:
        cur.execute(
            "INSERT INTO referrals(inviter_id, invited_id, level, created_at) VALUES(?,?,?,?)",
            (inviter, invited_id, level, now)
        )
        reward = float(REF_REWARDS.get(level, 0))
        if reward > 0:
            cur.execute("UPDATE users SET balance = COALESCE(balance,0) + ? WHERE user_id=?", (reward, inviter))
    conn.commit()
    conn.close()


# =========================
# Partner links (реф-силки)
# =========================
def list_partner_links():
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, title, url, reward FROM partner_links WHERE is_active=1 ORDER BY id DESC LIMIT 50")
    rows = cur.fetchall()
    conn.close()
    return rows


def get_partner_link(link_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, title, url, reward, is_active FROM partner_links WHERE id=?", (link_id,))
    row = cur.fetchone()
    conn.close()
    return row


def partner_claim_status(user_id: int, link_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT status FROM partner_claims WHERE user_id=? AND link_id=? ORDER BY id DESC LIMIT 1", (user_id, link_id))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def create_partner_claim(user_id: int, link_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("INSERT INTO partner_claims(user_id, link_id, status, created_at) VALUES(?,?,?,?)",
                (user_id, link_id, "pending", int(time.time())))
    conn.commit()
    conn.close()


# =========================
# Lottery
# =========================
def get_active_lottery():
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, started_at, ends_at FROM lottery WHERE is_active=1 ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return row


def get_total_tickets(lottery_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(count),0) FROM lottery_tickets WHERE lottery_id=?", (lottery_id,))
    total = cur.fetchone()[0]
    conn.close()
    return int(total)


def add_tickets(lottery_id: int, user_id: int, count: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("INSERT INTO lottery_tickets(lottery_id, user_id, count, created_at) VALUES(?,?,?,?)",
                (lottery_id, user_id, count, int(time.time())))
    conn.commit()
    conn.close()


def top_ticket_buyers(lottery_id: int, limit: int = 10):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, COALESCE(SUM(count),0) AS total
        FROM lottery_tickets
        WHERE lottery_id=?
        GROUP BY user_id
        ORDER BY total DESC
        LIMIT ?
    """, (lottery_id, limit))
    rows = cur.fetchall()
    conn.close()
    return rows


def tickets_pool(lottery_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id, count FROM lottery_tickets WHERE lottery_id=?", (lottery_id,))
    rows = cur.fetchall()
    conn.close()
    pool = []
    for uid, cnt in rows:
        pool.extend([uid] * int(cnt))
    return pool


# =========================
# UI
# =========================
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Заробити зірочки", callback_data="earn")],
        [InlineKeyboardButton("👥 Рефералка (3 рівні)", callback_data="ref")],
        [InlineKeyboardButton("🎟 Тижневий розіграш", callback_data="lottery")],
        [InlineKeyboardButton("🏆 Топ по білетах", callback_data="top_tickets")],
        [InlineKeyboardButton("💎 VIP", callback_data="vip")],
        [InlineKeyboardButton("📣 Реклама / Канали", callback_data="ads")],
        [InlineKeyboardButton("🎁 Бонуси / Баланс", callback_data="bonus")],
        [InlineKeyboardButton("🆘 Підтримка", callback_data="support")],
    ])


def back_btn(where="menu"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=where)]])


# =========================
# Auto push (розсилка партнер-лінків)
# =========================
async def autopush_job(context: ContextTypes.DEFAULT_TYPE):
    # якщо вимкнено — нічого не робимо
    if get_setting("autopush_enabled", "0") != "1":
        return

    links = list_partner_links()
    if not links:
        return

    link = random.choice(links)
    link_id, title, url, reward = link

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    users = [r[0] for r in cur.fetchall()]
    conn.close()

    text = (
        f"⭐ Нове завдання!\n\n"
        f"**{title}**\n"
        f"Нагорода: **+{reward}⭐**\n\n"
        f"Перейди за посиланням 👇"
    )

    sent = 0
    for uid in users:
        try:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Відкрити", url=url)],
                [InlineKeyboardButton("✅ Я виконав — нарахуйте", callback_data=f"pclaim:{link_id}")],
            ])
            await context.bot.send_message(uid, text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
            sent += 1
        except:
            pass

    if ADMIN_ID:
        try:
            await context.bot.send_message(ADMIN_ID, f"📨 AutoPush відправив завдання {link_id} → {sent}/{len(users)}")
        except:
            pass


# =========================
# Handlers
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    inviter_id = None
    if context.args:
        try:
            inviter_id = int(context.args[0])
            if inviter_id == user.id:
                inviter_id = None
        except:
            inviter_id = None

    existed = get_user(user.id)
    if not existed:
        upsert_user(user.id, user.username or "", user.first_name or "", inviter_id)
        # рефералка тільки для нового
        if inviter_id and not already_recorded_ref(user.id):
            record_referral_chain(user.id, inviter_id)
    else:
        upsert_user(user.id, user.username or "", user.first_name or "", existed[4])

    await update.message.reply_text("🤖 Бот онлайн! Обери дію:", reply_markup=main_menu())


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data

    if data == "menu":
        await q.edit_message_text("Головне меню:", reply_markup=main_menu())
        return

    if data == "earn":
        links = list_partner_links()
        if not links:
            await q.edit_message_text("⭐ Завдань ще нема. Адмін додасть реф-силки.", reply_markup=back_btn("menu"))
            return

        kb = []
        for link_id, title, url, reward in links[:10]:
            status = partner_claim_status(uid, link_id)
            mult = vip_mult(uid)
            effective = reward * mult
            label = f"{title}  (+{effective}⭐)"
            if status == "approved":
                label += " ✅"
            elif status == "pending":
                label += " ⏳"
            kb.append([InlineKeyboardButton(label, url=url)])
            kb.append([InlineKeyboardButton("✅ Я виконав — нарахуйте", callback_data=f"pclaim:{link_id}")])

        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="menu")])
        await q.edit_message_text("⭐ Завдання (реф-силки):", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("pclaim:"):
        link_id = int(data.split(":")[1])
        st = partner_claim_status(uid, link_id)
        if st in ("pending", "approved"):
            await q.answer("Вже є заявка / вже зараховано.", show_alert=True)
            return

        link = get_partner_link(link_id)
        if not link or int(link[4]) != 1:
            await q.answer("Лінк не активний.", show_alert=True)
            return

        create_partner_claim(uid, link_id)

        if ADMIN_ID:
            await context.bot.send_message(
                ADMIN_ID,
                f"📝 Заявка на завдання\nUser: {uid}\nLink ID: {link_id}\n\n"
                f"✅ /approve_link {uid} {link_id}\n"
                f"❌ /decline_link {uid} {link_id}"
            )

        await q.answer("Заявка відправлена адміну ✅", show_alert=True)
        return

    if data == "ref":
        ref_link = f"https://t.me/{context.bot.username}?start={uid}"
        txt = (
            "👥 Рефералка (3 рівні)\n\n"
            f"Твоя силка:\n`{ref_link}`\n\n"
            "Нарахування:\n"
            "1 рівень: +5⭐\n"
            "2 рівень: +3⭐\n"
            "3 рівень: +2⭐\n"
        )
        await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=back_btn("menu"))
        return

    if data == "bonus":
        u = get_user(uid)
        bal = float(u[3]) if u else 0.0
        vip = "✅ VIP" if u and int(u[5]) == 1 else "❌ не VIP"
        txt = f"🎁 Баланс: **{bal}⭐**\nVIP: **{vip}**\n\nВивід від **{MIN_WITHDRAW}⭐**."
        kb = [
            [InlineKeyboardButton("💸 Запросити вивід (50⭐)", callback_data="withdraw")],
            [InlineKeyboardButton("💎 Донат ⭐ (Stars)", callback_data="donate_stars")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu")],
        ]
        await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "withdraw":
        u = get_user(uid)
        bal = float(u[3]) if u else 0.0
        if bal < MIN_WITHDRAW:
            await q.answer(f"Мінімум для виводу: {MIN_WITHDRAW}⭐", show_alert=True)
            return
        conn = db()
        cur = conn.cursor()
        cur.execute("INSERT INTO withdraw_requests(user_id, amount, status, created_at) VALUES(?,?,?,?)",
                    (uid, MIN_WITHDRAW, "pending", int(time.time())))
        conn.commit()
        conn.close()
        if ADMIN_ID:
            await context.bot.send_message(
                ADMIN_ID,
                f"💸 Запит на вивід\nUser: {uid}\nСума: {MIN_WITHDRAW}⭐\n\n✅ /approve_withdraw {uid}\n❌ /decline_withdraw {uid}"
            )
        await q.answer("Запит відправлено адміну ✅", show_alert=True)
        return

    if data == "donate_stars":
        kb = [
            [InlineKeyboardButton("⭐ Донат 50", callback_data="buy_donate:50")],
            [InlineKeyboardButton("⭐ Донат 100", callback_data="buy_donate:100")],
            [InlineKeyboardButton("⭐ Донат 300", callback_data="buy_donate:300")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="bonus")],
        ]
        await q.edit_message_text("💎 Донат через Telegram Stars — обери суму:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("buy_donate:"):
        stars = int(data.split(":")[1])
        prices = [LabeledPrice(label=f"Donation {stars} Stars", amount=stars)]
        await context.bot.send_invoice(
            chat_id=uid,
            title="Донат ⭐",
            description=f"Донат {stars} Stars",
            payload=f"donate:{uid}:{stars}",
            provider_token="",
            currency="XTR",
            prices=prices,
        )
        await q.answer("Рахунок відправлено ✅", show_alert=True)
        return

    if data == "vip":
        u = get_user(uid)
        is_v = (u and int(u[5]) == 1)
        if is_v:
            await q.edit_message_text("💎 VIP активний ✅\nТобі нарахування по завданнях і бонусах йдуть x2.", reply_markup=back_btn("menu"))
            return

        kb = [
            [InlineKeyboardButton(f"💎 Купити VIP за {VIP_PRICE_STARS} Stars", callback_data=f"buy_vip:{VIP_PRICE_STARS}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu")],
        ]
        await q.edit_message_text(
            f"💎 VIP\n\nVIP дає **x2 нагороди** за завдання.\nЦіна: **{VIP_PRICE_STARS} Stars**",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(kb),
        )
        return

    if data.startswith("buy_vip:"):
        stars = int(data.split(":")[1])
        prices = [LabeledPrice(label="VIP access", amount=stars)]
        await context.bot.send_invoice(
            chat_id=uid,
            title="VIP 💎",
            description="VIP дає x2 нагороди за завдання",
            payload=f"vip:{uid}:{stars}",
            provider_token="",
            currency="XTR",
            prices=prices,
        )
        await q.answer("Рахунок VIP відправлено ✅", show_alert=True)
        return

    if data == "ads":
        txt = (
            "📣 Реклама / Канали\n\n"
            "Подай заявку одним повідомленням у форматі:\n"
            "`посилання | текст | контакт`\n\n"
            "Натисни кнопку нижче."
        )
        kb = [
            [InlineKeyboardButton("✍️ Подати заявку", callback_data="ads_apply")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu")],
        ]
        await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "ads_apply":
        context.user_data["ads_wait"] = True
        await q.edit_message_text("Ок ✅ Надішли:\n`посилання | текст | контакт`", parse_mode=ParseMode.MARKDOWN, reply_markup=back_btn("menu"))
        return

    if data == "lottery":
        lot = get_active_lottery()
        if not lot:
            await q.edit_message_text("🎟 Розіграш зараз НЕ активний.", reply_markup=back_btn("menu"))
            return
        lottery_id = lot[0]
        total = get_total_tickets(lottery_id)
        txt = (
            "🎟 Розіграш АКТИВНИЙ!\n"
            f"Білетів: **{total}/1000**\n\n"
            "Покупка білетів:\n"
            "— вручну (реальні гроші)\n"
            "— або Stars (пакети)\n"
        )
        kb = [
            [InlineKeyboardButton("💰 Купити вручну", callback_data="lottery_manual")],
            [InlineKeyboardButton("⭐ Купити за Stars", callback_data="lottery_stars")],
            [InlineKeyboardButton("🏆 Призи", callback_data="lottery_prizes")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu")],
        ]
        await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "lottery_prizes":
        txt = "🏆 Призи:\n" + "\n".join([f"{p} місце — {r}⭐" for p, r in LOTTERY_PRIZES[:15]]) + "\n...\nВсього 50 переможців."
        await q.edit_message_text(txt, reply_markup=back_btn("lottery"))
        return

    if data == "lottery_manual":
        await q.edit_message_text(
            "💰 Купівля білетів вручну:\nНапиши адміну скільки білетів.\nАдмін нарахує /add_tickets user_id count",
            reply_markup=back_btn("lottery"),
        )
        return

    if data == "lottery_stars":
        kb = [
            [InlineKeyboardButton("⭐ 10 Stars = 1 білет", callback_data="ltbuy:10:1")],
            [InlineKeyboardButton("⭐ 50 Stars = 6 білетів", callback_data="ltbuy:50:6")],
            [InlineKeyboardButton("⭐ 100 Stars = 13 білетів", callback_data="ltbuy:100:13")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="lottery")],
        ]
        await q.edit_message_text("⭐ Пакети білетів за Stars:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("ltbuy:"):
        _, stars_s, tickets_s = data.split(":")
        stars = int(stars_s)
        tickets = int(tickets_s)
        prices = [LabeledPrice(label=f"Lottery pack: {tickets} tickets", amount=stars)]
        await context.bot.send_invoice(
            chat_id=uid,
            title="Білети на розіграш 🎟",
            description=f"{tickets} білетів за {stars} Stars",
            payload=f"lottery:{uid}:{stars}:{tickets}",
            provider_token="",
            currency="XTR",
            prices=prices,
        )
        await q.answer("Рахунок на білети відправлено ✅", show_alert=True)
        return

    if data == "top_tickets":
        lot = get_active_lottery()
        if not lot:
            await q.edit_message_text("🏆 Нема активної лотереї.", reply_markup=back_btn("menu"))
            return
        top = top_ticket_buyers(lot[0], 10)
        if not top:
            await q.edit_message_text("🏆 Поки ніхто не купував білети.", reply_markup=back_btn("menu"))
            return
        lines = ["🏆 Топ по білетах:"]
        for i, (u_id, total) in enumerate(top, start=1):
            lines.append(f"{i}) `{u_id}` — **{total}** білетів")
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=back_btn("menu"))
        return

    if data == "support":
        await q.edit_message_text("🆘 Підтримка: напиши адміну або опиши проблему тут.", reply_markup=back_btn("menu"))
        return


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt = update.message.text.strip()

    if context.user_data.get("ads_wait"):
        context.user_data["ads_wait"] = False
        parts = [p.strip() for p in txt.split("|")]
        if len(parts) < 3:
            await update.message.reply_text("Формат: `посилання | текст | контакт`", parse_mode=ParseMode.MARKDOWN)
            return
        link, ad_text, contact = parts[0], parts[1], parts[2]
        conn = db()
        cur = conn.cursor()
        cur.execute("INSERT INTO ad_requests(user_id, text, contact, status, created_at) VALUES(?,?,?,?,?)",
                    (uid, f"{link}\n\n{ad_text}", contact, "pending", int(time.time())))
        conn.commit()
        conn.close()
        if ADMIN_ID:
            await context.bot.send_message(ADMIN_ID, f"📣 Заявка на рекламу\nUser: {uid}\nContact: {contact}\n\n{link}\n\n{ad_text}")
        await update.message.reply_text("✅ Заявка на рекламу відправлена адміну.")
        return

    await update.message.reply_text("Обери дію з меню:", reply_markup=main_menu())


# =========================
# Payments (Stars)
# =========================
async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    payload = update.message.successful_payment.invoice_payload

    # donate
    if payload.startswith("donate:"):
        _, user_s, stars_s = payload.split(":")
        stars = int(stars_s)
        conn = db()
        cur = conn.cursor()
        cur.execute("INSERT INTO donations(user_id, stars, purpose, created_at) VALUES(?,?,?,?)",
                    (uid, stars, "donate", int(time.time())))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"Дякую за донат 💎 +{stars} Stars ✅")
        return

    # vip
    if payload.startswith("vip:"):
        _, user_s, stars_s = payload.split(":")
        stars = int(stars_s)
        conn = db()
        cur = conn.cursor()
        cur.execute("INSERT INTO donations(user_id, stars, purpose, created_at) VALUES(?,?,?,?)",
                    (uid, stars, "vip", int(time.time())))
        conn.commit()
        conn.close()
        set_vip(uid, True)
        await update.message.reply_text("💎 VIP активовано ✅ Тепер нагороди x2!")
        return

    # lottery tickets
    if payload.startswith("lottery:"):
        _, user_s, stars_s, tickets_s = payload.split(":")
        tickets = int(tickets_s)
        lot = get_active_lottery()
        if not lot:
            await update.message.reply_text("Розіграш не активний 😕")
            return
        lottery_id = lot[0]
        total = get_total_tickets(lottery_id)
        if total + tickets > 1000:
            await update.message.reply_text("Ліміт 1000 білетів перевищено. Спробуй менше.")
            return
        add_tickets(lottery_id, uid, tickets)
        conn = db()
        cur = conn.cursor()
        cur.execute("INSERT INTO donations(user_id, stars, purpose, created_at) VALUES(?,?,?,?)",
                    (uid, int(stars_s), "lottery", int(time.time())))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"🎟 Куплено білетів: {tickets} ✅")
        return


# =========================
# Admin commands
# =========================
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    auto = "ON ✅" if get_setting("autopush_enabled", "0") == "1" else "OFF ❌"
    await update.message.reply_text(
        "🛠 Адмін меню\n\n"
        "Реф-силки (партнерки):\n"
        "/add_link Назва | https://... | reward\n"
        "/links\n"
        "/autopush_on  (авто-розсилка)\n"
        "/autopush_off\n\n"
        "Підтвердження завдань:\n"
        "/approve_link user_id link_id\n"
        "/decline_link user_id link_id\n\n"
        "VIP:\n"
        "/vip_on user_id\n"
        "/vip_off user_id\n\n"
        "Лотерея:\n"
        "/start_lottery days\n"
        "/end_lottery\n"
        "/add_tickets user_id count\n"
        "/draw_lottery\n\n"
        f"AutoPush зараз: {auto}"
    )


async def add_link_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    text = update.message.text.replace("/add_link", "", 1).strip()
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 3:
        await update.message.reply_text("Формат:\n/add_link Назва | https://... | 1")
        return
    title, url, reward_s = parts[0], parts[1], parts[2]
    try:
        reward = float(reward_s)
    except:
        reward = TASK_DEFAULT_REWARD

    conn = db()
    cur = conn.cursor()
    cur.execute("INSERT INTO partner_links(title, url, reward, is_active, created_at) VALUES(?,?,?,?,?)",
                (title, url, reward, 1, int(time.time())))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ Реф-силка додана.")


async def links_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    links = list_partner_links()
    if not links:
        await update.message.reply_text("Нема активних лінків.")
        return
    lines = ["🔗 Активні реф-силки:"]
    for link_id, title, url, reward in links[:30]:
        lines.append(f"{link_id}) {title} (+{reward}⭐)\n{url}")
    await update.message.reply_text("\n\n".join(lines))


async def approve_link_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Формат: /approve_link user_id link_id")
        return
    uid = int(context.args[0])
    link_id = int(context.args[1])

    link = get_partner_link(link_id)
    if not link:
        await update.message.reply_text("Лінк не знайдено.")
        return

    reward = float(link[3]) * vip_mult(uid)

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE partner_claims
        SET status='approved'
        WHERE id = (
            SELECT id FROM partner_claims
            WHERE user_id=? AND link_id=? AND status='pending'
            ORDER BY id DESC LIMIT 1
        )
    """, (uid, link_id))
    conn.commit()
    conn.close()

    add_balance(uid, reward)
    try:
        await context.bot.send_message(uid, f"✅ Завдання підтверджено. Нараховано +{reward}⭐")
    except:
        pass
    await update.message.reply_text("✅ OK")


async def decline_link_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Формат: /decline_link user_id link_id")
        return
    uid = int(context.args[0])
    link_id = int(context.args[1])

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE partner_claims
        SET status='declined'
        WHERE id = (
            SELECT id FROM partner_claims
            WHERE user_id=? AND link_id=? AND status='pending'
            ORDER BY id DESC LIMIT 1
        )
    """, (uid, link_id))
    conn.commit()
    conn.close()

    try:
        await context.bot.send_message(uid, "❌ Завдання відхилено.")
    except:
        pass
    await update.message.reply_text("OK")


async def vip_on_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Формат: /vip_on user_id")
        return
    uid = int(context.args[0])
    set_vip(uid, True)
    await update.message.reply_text("✅ VIP ON")


async def vip_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Формат: /vip_off user_id")
        return
    uid = int(context.args[0])
    set_vip(uid, False)
    await update.message.reply_text("✅ VIP OFF")


async def autopush_on_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    set_setting("autopush_enabled", "1")
    await update.message.reply_text("✅ AutoPush ON")


async def autopush_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    set_setting("autopush_enabled", "0")
    await update.message.reply_text("✅ AutoPush OFF")


async def start_lottery_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    days = int(context.args[0]) if context.args else 7
    now = int(time.time())
    ends = int((datetime.utcnow() + timedelta(days=days)).timestamp())
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE lottery SET is_active=0 WHERE is_active=1")
    cur.execute("INSERT INTO lottery(is_active, started_at, ends_at) VALUES(?,?,?)", (1, now, ends))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ Лотерею запущено на {days} днів.")


async def end_lottery_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE lottery SET is_active=0 WHERE is_active=1")
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ Лотерею зупинено.")


async def add_tickets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Формат: /add_tickets user_id count")
        return
    uid = int(context.args[0])
    cnt = int(context.args[1])
    lot = get_active_lottery()
    if not lot:
        await update.message.reply_text("Лотерея не активна.")
        return
    lottery_id = lot[0]
    total = get_total_tickets(lottery_id)
    if total + cnt > 1000:
        await update.message.reply_text("Перевищить 1000 білетів.")
        return
    add_tickets(lottery_id, uid, cnt)
    try:
        await context.bot.send_message(uid, f"🎟 Адмін нарахував білетів: {cnt} ✅")
    except:
        pass
    await update.message.reply_text("OK")


async def draw_lottery_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    lot = get_active_lottery()
    if not lot:
        await update.message.reply_text("Лотерея не активна.")
        return
    lottery_id = lot[0]
    pool = tickets_pool(lottery_id)
    if not pool:
        await update.message.reply_text("Немає білетів.")
        return

    winners = []
    used = set()
    attempts = 0
    uniq = list(set(pool))
    if not uniq:
        await update.message.reply_text("Немає учасників.")
        return

    while len(winners) < 50 and attempts < 20000 and len(used) < len(uniq):
        attempts += 1
        w = random.choice(pool)
        if w in used:
            continue
        used.add(w)
        winners.append(w)

    results = ["🏆 Результати розіграшу:"]
    for (place, reward), user_id in zip(LOTTERY_PRIZES, winners):
        add_balance(user_id, reward)
        results.append(f"{place}) `{user_id}` — +{reward}⭐")
        try:
            await context.bot.send_message(user_id, f"🎉 Виграш!\nМісце: {place}\nНагорода: +{reward}⭐")
        except:
            pass

    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE lottery SET is_active=0 WHERE id=?", (lottery_id,))
    conn.commit()
    conn.close()

    await update.message.reply_text("\n".join(results), parse_mode=ParseMode.MARKDOWN)


# =========================
# Withdraw admin (простий)
# =========================
async def approve_withdraw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Формат: /approve_withdraw user_id")
        return
    uid = int(context.args[0])

    u = get_user(uid)
    if not u:
        return
    bal = float(u[3])
    if bal < MIN_WITHDRAW:
        await update.message.reply_text("В юзера менше 50⭐")
        return

    add_balance(uid, -MIN_WITHDRAW)

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE withdraw_requests
        SET status='approved'
        WHERE id = (
            SELECT id FROM withdraw_requests
            WHERE user_id=? AND status='pending'
            ORDER BY id DESC LIMIT 1
        )
    """, (uid,))
    conn.commit()
    conn.close()

    try:
        await context.bot.send_message(uid, "✅ Вивід підтверджено. Напиши адміну для отримання грошей.")
    except:
        pass
    await update.message.reply_text("✅ OK")


async def decline_withdraw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Формат: /decline_withdraw user_id")
        return
    uid = int(context.args[0])

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE withdraw_requests
        SET status='declined'
        WHERE id = (
            SELECT id FROM withdraw_requests
            WHERE user_id=? AND status='pending'
            ORDER BY id DESC LIMIT 1
        )
    """, (uid,))
    conn.commit()
    conn.close()

    try:
        await context.bot.send_message(uid, "❌ Вивід відхилено.")
    except:
        pass
    await update.message.reply_text("OK")


# =========================
# App
# =========================
def build_app():
    if not BOT_TOKEN or ":" not in BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN missing/invalid. Set it in Railway Variables.")
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # user handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    # admin handlers
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("add_link", add_link_cmd))
    app.add_handler(CommandHandler("links", links_cmd))
    app.add_handler(CommandHandler("approve_link", approve_link_cmd))
    app.add_handler(CommandHandler("decline_link", decline_link_cmd))
    app.add_handler(CommandHandler("vip_on", vip_on_cmd))
    app.add_handler(CommandHandler("vip_off", vip_off_cmd))
    app.add_handler(CommandHandler("autopush_on", autopush_on_cmd))
    app.add_handler(CommandHandler("autopush_off", autopush_off_cmd))
    app.add_handler(CommandHandler("start_lottery", start_lottery_cmd))
    app.add_handler(CommandHandler("end_lottery", end_lottery_cmd))
    app.add_handler(CommandHandler("add_tickets", add_tickets_cmd))
    app.add_handler(CommandHandler("draw_lottery", draw_lottery_cmd))
    app.add_handler(CommandHandler("approve_withdraw", approve_withdraw_cmd))
    app.add_handler(CommandHandler("decline_withdraw", decline_withdraw_cmd))

    # AUTO PUSH: кожні 6 годин (можеш змінити)
    # Вмикається/вимикається командами /autopush_on /autopush_off
    app.job_queue.run_repeating(autopush_job, interval=6 * 60 * 60, first=60)

    return app


if __name__ == "__main__":
    application = build_app()
    application.run_polling()
