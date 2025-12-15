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
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB_PATH = "bot.db"


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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        url TEXT NOT NULL,
        reward REAL NOT NULL DEFAULT 1,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS task_claims (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        task_id INTEGER,
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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS donations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        stars INTEGER,
        created_at INTEGER
    )
    """)

    conn.commit()
    conn.close()


def get_user(user_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, first_name, balance, referred_by FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


def upsert_user(user_id: int, username: str, first_name: str, referred_by: int | None = None):
    now = int(time.time())
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    exists = cur.fetchone()

    if exists:
        cur.execute(
            "UPDATE users SET username=?, first_name=? WHERE user_id=?",
            (username, first_name, user_id)
        )
    else:
        cur.execute(
            "INSERT INTO users(user_id, username, first_name, balance, referred_by, created_at) VALUES(?,?,?,?,?,?)",
            (user_id, username, first_name, 0, referred_by, now)
        )

    conn.commit()
    conn.close()


def add_balance(user_id: int, amount: float):
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = COALESCE(balance,0) + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()


def set_balance(user_id: int, amount: float):
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance=? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()


# =========================
# Referral logic (3 levels)
# =========================
REF_REWARDS = {1: 5.0, 2: 3.0, 3: 2.0}
NEW_USER_BONUS = 3.0  # бонус новому, який зайшов по реф-ссилці


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
    """
    1 рівень: inviter_id
    2 рівень: хто запросив inviter_id
    3 рівень: хто запросив 2 рівень
    """
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
        reward = REF_REWARDS.get(level, 0)
        if reward > 0:
            cur.execute("UPDATE users SET balance = COALESCE(balance,0) + ? WHERE user_id=?", (reward, inviter))
    conn.commit()
    conn.close()


# =========================
# UI
# =========================
def main_menu():
    kb = [
        [InlineKeyboardButton("⭐ Заробити зірочки", callback_data="earn")],
        [InlineKeyboardButton("👥 Рефералка", callback_data="ref")],
        [InlineKeyboardButton("📣 Реклама / Канали", callback_data="ads")],
        [InlineKeyboardButton("🎟 Тижневий розіграш", callback_data="lottery")],
        [InlineKeyboardButton("🎁 Бонуси / Баланс", callback_data="bonus")],
        [InlineKeyboardButton("🆘 Підтримка", callback_data="support")],
    ]
    return InlineKeyboardMarkup(kb)


def back_btn(where="menu"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=where)]])


# =========================
# Tasks
# =========================
def list_tasks():
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, title, url, reward FROM tasks WHERE is_active=1 ORDER BY id DESC LIMIT 20")
    rows = cur.fetchall()
    conn.close()
    return rows


def has_claim(user_id: int, task_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT status FROM task_claims WHERE user_id=? AND task_id=? ORDER BY id DESC LIMIT 1", (user_id, task_id))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


# =========================
# Lottery
# =========================
LOTTERY_PRIZES = [
    (1, 300.0),
    (2, 100.0),
    (3, 50.0),
]
# 4-20: 5
for p in range(4, 21):
    LOTTERY_PRIZES.append((p, 5.0))
# 21-40: 2.5
for p in range(21, 41):
    LOTTERY_PRIZES.append((p, 2.5))
# 41-50: 1
for p in range(41, 51):
    LOTTERY_PRIZES.append((p, 1.0))


def get_active_lottery():
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, is_active, started_at, ends_at FROM lottery WHERE is_active=1 ORDER BY id DESC LIMIT 1")
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
    cur.execute(
        "INSERT INTO lottery_tickets(lottery_id, user_id, count, created_at) VALUES(?,?,?,?)",
        (lottery_id, user_id, count, int(time.time()))
    )
    conn.commit()
    conn.close()


def tickets_pool(lottery_id: int):
    """
    повертає список user_id з повтореннями = кількості білетів
    """
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
# Handlers
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    inviter_id = None
    if args:
        # /start <ref_id>
        try:
            inviter_id = int(args[0])
            if inviter_id == user.id:
                inviter_id = None
        except:
            inviter_id = None

    # create / update user
    existed = get_user(user.id)
    if not existed:
        upsert_user(user.id, user.username or "", user.first_name or "", inviter_id)
        # referral only for new users
        if inviter_id and not already_recorded_ref(user.id):
            # bonus to new user
            add_balance(user.id, NEW_USER_BONUS)
            # record chain rewards
            record_referral_chain(user.id, inviter_id)
    else:
        upsert_user(user.id, user.username or "", user.first_name or "", existed[4])

    await update.message.reply_text("🤖 Бот онлайн! Обери дію:", reply_markup=main_menu())


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data = q.data
    uid = q.from_user.id

    if data == "menu":
        await q.edit_message_text("Головне меню:", reply_markup=main_menu())
        return

    if data == "earn":
        tasks = list_tasks()
        if not tasks:
            text = "⭐ Тут будуть завдання (канали/додатки/рефералки).\nПоки що завдань немає — адмін додасть."
            await q.edit_message_text(text, reply_markup=back_btn("menu"))
            return

        kb = []
        for tid, title, url, reward in tasks:
            status = has_claim(uid, tid)
            label = f"{title}  (+{reward}⭐)"
            if status == "approved":
                label += " ✅"
            elif status == "pending":
                label += " ⏳"
            kb.append([InlineKeyboardButton(label, url=url)])
            kb.append([InlineKeyboardButton("✅ Я виконав — нарахуйте", callback_data=f"claim:{tid}")])

        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="menu")])
        await q.edit_message_text("⭐ Завдання:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("claim:"):
        tid = int(data.split(":")[1])
        status = has_claim(uid, tid)
        if status in ("pending", "approved"):
            await q.answer("Вже є заявка / вже зараховано.", show_alert=True)
            return

        conn = db()
        cur = conn.cursor()
        cur.execute("INSERT INTO task_claims(user_id, task_id, status, created_at) VALUES(?,?,?,?)",
                    (uid, tid, "pending", int(time.time())))
        conn.commit()
        conn.close()

        # notify admin
        if ADMIN_ID:
            await context.bot.send_message(
                ADMIN_ID,
                f"📝 Заявка на завдання\nUser: {uid}\nTask ID: {tid}\n\nПідтвердити:\n/approve_task {uid} {tid}\nВідхилити:\n/decline_task {uid} {tid}"
            )

        await q.answer("Заявка відправлена адміну ✅", show_alert=True)
        return

    if data == "ref":
        me = get_user(uid)
        if not me:
            await q.edit_message_text("Натисни /start", reply_markup=back_btn("menu"))
            return
        ref_link = f"https://t.me/{context.bot.username}?start={uid}"
        text = (
            "👥 Рефералка (3 рівні)\n"
            f"Твоє посилання:\n`{ref_link}`\n\n"
            "Нарахування:\n"
            "1 рівень: +5⭐\n"
            "2 рівень: +3⭐\n"
            "3 рівень: +2⭐\n\n"
            "Новий користувач по твоїй силці отримує +3⭐ бонусом."
        )
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_btn("menu"))
        return

    if data == "bonus":
        me = get_user(uid)
        bal = me[3] if me else 0
        text = f"🎁 Твої бонуси\nБаланс: **{bal}⭐**\n\nВивід можливий від **50⭐** (вручну через адміна)."
        kb = [
            [InlineKeyboardButton("💸 Запросити вивід (50⭐)", callback_data="withdraw")],
            [InlineKeyboardButton("💎 Донат ⭐ (Stars)", callback_data="donate_stars")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu")],
        ]
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "withdraw":
        me = get_user(uid)
        bal = float(me[3]) if me else 0
        if bal < 50:
            await q.answer("Мінімум для виводу: 50⭐", show_alert=True)
            return

        conn = db()
        cur = conn.cursor()
        cur.execute("INSERT INTO withdraw_requests(user_id, amount, status, created_at) VALUES(?,?,?,?)",
                    (uid, 50.0, "pending", int(time.time())))
        conn.commit()
        conn.close()

        if ADMIN_ID:
            await context.bot.send_message(
                ADMIN_ID,
                f"💸 Запит на вивід\nUser: {uid}\nСума: 50⭐\n\nПідтвердити: /approve_withdraw {uid}\nВідхилити: /decline_withdraw {uid}"
            )
        await q.answer("Запит на вивід відправлено адміну ✅", show_alert=True)
        return

    if data == "donate_stars":
        # invoice for Telegram Stars (XTR)
        # Users choose amount by buttons:
        kb = [
            [InlineKeyboardButton("⭐ Донат 50", callback_data="buy:50")],
            [InlineKeyboardButton("⭐ Донат 100", callback_data="buy:100")],
            [InlineKeyboardButton("⭐ Донат 300", callback_data="buy:300")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="bonus")],
        ]
        await q.edit_message_text("💎 Донат через Telegram Stars:\nОбери суму:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("buy:"):
        stars = int(data.split(":")[1])
        prices = [LabeledPrice(label=f"Donation {stars} Stars", amount=stars)]
        await context.bot.send_invoice(
            chat_id=uid,
            title="Донат ⭐",
            description=f"Донат {stars} Stars",
            payload=f"donate:{uid}:{stars}",
            provider_token="",   # IMPORTANT for Stars
            currency="XTR",
            prices=prices,
        )
        await q.answer("Відправив рахунок ✅", show_alert=True)
        return

    if data == "ads":
        text = (
            "📣 Реклама / Канали\n"
            "Тут можна подати заявку на рекламу.\n\n"
            "Натисни кнопку нижче і пришли:\n"
            "1) Посилання на канал/чат\n"
            "2) Текст реклами\n"
            "3) Контакт для звʼязку\n"
        )
        kb = [
            [InlineKeyboardButton("✍️ Подати заявку на рекламу", callback_data="ads_apply")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu")],
        ]
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "ads_apply":
        context.user_data["ads_wait"] = True
        await q.edit_message_text("Ок ✅\nНадішли одним повідомленням:\n`посилання | текст | контакт`", parse_mode=ParseMode.MARKDOWN, reply_markup=back_btn("menu"))
        return

    if data == "lottery":
        lot = get_active_lottery()
        if not lot:
            text = (
                "🎟 Тижневий розіграш\n"
                "Зараз розіграш **не активний**.\n\n"
                "Коли адмін увімкне — тут зʼявиться покупка білетів."
            )
            await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_btn("menu"))
            return

        lottery_id = lot[0]
        total = get_total_tickets(lottery_id)
        text = (
            "🎟 Тижневий розіграш АКТИВНИЙ!\n"
            f"Всього білетів: **{total}/1000**\n\n"
            "Білет: **10 грн** (вручну) або Stars-пакети.\n"
            "Для покупки за реальні гроші — натисни кнопку і напиши адміну."
        )
        kb = [
            [InlineKeyboardButton("💰 Купити білети (вручну)", callback_data="lottery_manual")],
            [InlineKeyboardButton("⭐ Купити за Stars", callback_data="lottery_stars")],
            [InlineKeyboardButton("🏆 Призи", callback_data="lottery_prizes")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu")],
        ]
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "lottery_prizes":
        prize_text = "🏆 Призи:\n" + "\n".join([f"{p} місце — {r}⭐" for p, r in LOTTERY_PRIZES[:12]]) + "\n...\n(всього 50 переможців)"
        await q.edit_message_text(prize_text, reply_markup=back_btn("lottery"))
        return

    if data == "lottery_manual":
        await q.edit_message_text(
            "💰 Купівля білетів вручну:\nНапиши адміну скільки білетів хочеш.\nПісля оплати адмін нарахує командою.\n\n(Адмін: /add_tickets user_id count)",
            reply_markup=back_btn("lottery")
        )
        return

    if data == "lottery_stars":
        kb = [
            [InlineKeyboardButton("⭐ 10 Stars = 1 білет", callback_data="ltbuy:10:1")],
            [InlineKeyboardButton("⭐ 50 Stars = 6 білетів", callback_data="ltbuy:50:6")],
            [InlineKeyboardButton("⭐ 100 Stars = 13 білетів", callback_data="ltbuy:100:13")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="lottery")],
        ]
        await q.edit_message_text("⭐ Купівля білетів за Stars (пакети):", reply_markup=InlineKeyboardMarkup(kb))
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
        await q.answer("Відправив рахунок ✅", show_alert=True)
        return

    if data == "support":
        await q.edit_message_text("🆘 Підтримка\nНапиши сюди проблему — або адміну.", reply_markup=back_btn("menu"))
        return


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt = update.message.text.strip()

    # ADS apply flow
    if context.user_data.get("ads_wait"):
        context.user_data["ads_wait"] = False
        parts = [p.strip() for p in txt.split("|")]
        if len(parts) < 3:
            await update.message.reply_text("Формат не вірний. Надішли так:\n`посилання | текст | контакт`", parse_mode=ParseMode.MARKDOWN)
            return

        link, ad_text, contact = parts[0], parts[1], parts[2]
        conn = db()
        cur = conn.cursor()
        cur.execute("INSERT INTO ad_requests(user_id, text, contact, status, created_at) VALUES(?,?,?,?,?)",
                    (uid, f"{link}\n\n{ad_text}", contact, "pending", int(time.time())))
        conn.commit()
        conn.close()

        if ADMIN_ID:
            await context.bot.send_message(
                ADMIN_ID,
                f"📣 Заявка на рекламу\nUser: {uid}\nContact: {contact}\n\n{link}\n\n{ad_text}\n\nПідтвердити: /approve_ad {uid}\nВідхилити: /decline_ad {uid}"
            )

        await update.message.reply_text("Заявка відправлена ✅ Адмін відповість.")
        return

    # default
    await update.message.reply_text("Обери дію з меню:", reply_markup=main_menu())


# =========================
# Payments (Stars)
# =========================
async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.pre_checkout_query
    await q.answer(ok=True)


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    payload = update.message.successful_payment.invoice_payload

    if payload.startswith("donate:"):
        _, user_s, stars_s = payload.split(":")
        stars = int(stars_s)
        conn = db()
        cur = conn.cursor()
        cur.execute("INSERT INTO donations(user_id, stars, created_at) VALUES(?,?,?)", (uid, stars, int(time.time())))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"Дякую за донат 💎 +{stars} Stars ✅")
        return

    if payload.startswith("lottery:"):
        _, user_s, stars_s, tickets_s = payload.split(":")
        tickets = int(tickets_s)

        lot = get_active_lottery()
        if not lot:
            await update.message.reply_text("Розіграш зараз не активний 😕")
            return

        lottery_id = lot[0]
        total = get_total_tickets(lottery_id)
        if total + tickets > 1000:
            await update.message.reply_text("Ліміт 1000 білетів перевищено. Спробуй менше.")
            return

        add_tickets(lottery_id, uid, tickets)
        await update.message.reply_text(f"🎟 Куплено білетів: {tickets} ✅")
        return


# =========================
# Admin commands
# =========================
def is_admin(uid: int) -> bool:
    return ADMIN_ID and uid == ADMIN_ID


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "🛠 Адмін команди:\n"
        "/add_task title | url | reward\n"
        "/approve_task user_id task_id\n"
        "/decline_task user_id task_id\n"
        "/approve_withdraw user_id\n"
        "/decline_withdraw user_id\n"
        "/start_lottery days\n"
        "/end_lottery\n"
        "/add_tickets user_id count\n"
        "/draw_lottery\n"
    )


async def add_task_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    text = update.message.text.replace("/add_task", "", 1).strip()
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 3:
        await update.message.reply_text("Формат:\n/add_task Назва | https://... | 1")
        return
    title, url, reward_s = parts[0], parts[1], parts[2]
    reward = float(reward_s)
    conn = db()
    cur = conn.cursor()
    cur.execute("INSERT INTO tasks(title, url, reward, is_active, created_at) VALUES(?,?,?,?,?)",
                (title, url, reward, 1, int(time.time())))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ Завдання додано.")


async def approve_task_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        return
    uid = int(context.args[0])
    tid = int(context.args[1])

    # get reward
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT reward FROM tasks WHERE id=?", (tid,))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("Task не знайдено.")
        conn.close()
        return
    reward = float(row[0])

    # mark claim approved (latest pending)
    cur.execute("""
        UPDATE task_claims
        SET status='approved'
        WHERE id = (
            SELECT id FROM task_claims
            WHERE user_id=? AND task_id=? AND status='pending'
            ORDER BY id DESC LIMIT 1
        )
    """, (uid, tid))
    # pay
    cur.execute("UPDATE users SET balance = COALESCE(balance,0) + ? WHERE user_id=?", (reward, uid))
    conn.commit()
    conn.close()

    await context.bot.send_message(uid, f"✅ Завдання підтверджено. Нараховано +{reward}⭐")
    await update.message.reply_text("✅ OK")


async def decline_task_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        return
    uid = int(context.args[0])
    tid = int(context.args[1])

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE task_claims
        SET status='declined'
        WHERE id = (
            SELECT id FROM task_claims
            WHERE user_id=? AND task_id=? AND status='pending'
            ORDER BY id DESC LIMIT 1
        )
    """, (uid, tid))
    conn.commit()
    conn.close()
    await context.bot.send_message(uid, "❌ Завдання відхилено.")
    await update.message.reply_text("OK")


async def approve_withdraw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 1:
        return
    uid = int(context.args[0])

    # deduct 50
    me = get_user(uid)
    if not me:
        return
    bal = float(me[3])
    if bal < 50:
        await update.message.reply_text("В юзера менше 50⭐")
        return

    add_balance(uid, -50.0)

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

    await context.bot.send_message(uid, "✅ Вивід підтверджено. Напиши адміну для отримання грошей.")
    await update.message.reply_text("✅ OK")


async def decline_withdraw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 1:
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

    await context.bot.send_message(uid, "❌ Вивід відхилено.")
    await update.message.reply_text("OK")


async def start_lottery_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    days = int(context.args[0]) if context.args else 7
    now = int(time.time())
    ends = int((datetime.utcnow() + timedelta(days=days)).timestamp())

    conn = db()
    cur = conn.cursor()
    # disable old
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
    await context.bot.send_message(uid, f"🎟 Адмін нарахував білетів: {cnt} ✅")
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
    if len(pool) < 1:
        await update.message.reply_text("Немає білетів.")
        return

    # 50 unique winners
    winners = []
    used = set()
    attempts = 0
    while len(winners) < 50 and attempts < 20000 and len(used) < len(set(pool)):
        attempts += 1
        w = random.choice(pool)
        if w in used:
            continue
        used.add(w)
        winners.append(w)

    # pay prizes
    results_lines = ["🏆 Результати розіграшу:"]
    for (place, reward), user_id in zip(LOTTERY_PRIZES, winners):
        add_balance(user_id, reward)
        results_lines.append(f"{place}) {user_id} — +{reward}⭐")
        try:
            await context.bot.send_message(user_id, f"🎉 Ти виграв у розіграші!\nМісце: {place}\nНагорода: +{reward}⭐")
        except:
            pass

    # stop lottery
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE lottery SET is_active=0 WHERE id=?", (lottery_id,))
    conn.commit()
    conn.close()

    await update.message.reply_text("\n".join(results_lines))


# =========================
# Main
# =========================
def build_app():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Set it in Railway Variables.")

    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("add_task", add_task_cmd))
    app.add_handler(CommandHandler("approve_task", approve_task_cmd))
    app.add_handler(CommandHandler("decline_task", decline_task_cmd))
    app.add_handler(CommandHandler("approve_withdraw", approve_withdraw_cmd))
    app.add_handler(CommandHandler("decline_withdraw", decline_withdraw_cmd))
    app.add_handler(CommandHandler("start_lottery", start_lottery_cmd))
    app.add_handler(CommandHandler("end_lottery", end_lottery_cmd))
    app.add_handler(CommandHandler("add_tickets", add_tickets_cmd))
    app.add_handler(CommandHandler("draw_lottery", draw_lottery_cmd))

    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    return app


if __name__ == "__main__":
    application = build_app()
    application.run_polling()

