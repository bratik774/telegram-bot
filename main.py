import os
import sqlite3
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")

DB_PATH = "bot.db"


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TEXT,
            ref_by INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def upsert_user(user_id: int, username: str, first_name: str, ref_by: int = 0):
    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    exists = cur.fetchone() is not None

    if not exists:
        cur.execute(
            "INSERT INTO users(user_id, username, first_name, joined_at, ref_by) VALUES(?,?,?,?,?)",
            (user_id, username or "", first_name or "", datetime.utcnow().isoformat(), ref_by or 0)
        )
    else:
        cur.execute(
            "UPDATE users SET username=?, first_name=? WHERE user_id=?",
            (username or "", first_name or "", user_id)
        )

    conn.commit()
    conn.close()


def count_users() -> int:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    n = cur.fetchone()[0]
    conn.close()
    return n


def count_refs(user_id: int) -> int:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users WHERE ref_by=?", (user_id,))
    n = cur.fetchone()[0]
    conn.close()
    return n


def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Заробити зірочки", callback_data="earn")],
        [InlineKeyboardButton("👥 Рефералка", callback_data="ref")],
        [InlineKeyboardButton("📢 Реклама / Канали", callback_data="ads")],
        [InlineKeyboardButton("🆘 Підтримка", callback_data="support")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ref_by = 0

    # Рефералка: /start 123456789
    if context.args:
        try:
            ref_by = int(context.args[0])
        except:
            ref_by = 0

    # Не дозволяємо реф самому на себе
    if ref_by == user.id:
        ref_by = 0

    upsert_user(user.id, user.username, user.first_name, ref_by)

    text = (
        f"🤖 Бот онлайн!\n\n"
        f"Привіт, {user.first_name} 👋\n"
        f"Обери дію з меню нижче:"
    )

    await update.message.reply_text(text, reply_markup=main_menu())


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команди:\n"
        "/start — меню\n"
        "/help — допомога\n"
        "/profile — твій профіль\n"
        "/admin — адмін панель (тільки для власника)"
    )


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    refs = count_refs(user.id)
    link = f"https://t.me/{(context.bot.username or 'YOUR_BOT')}?start={user.id}"

    await update.message.reply_text(
        f"👤 Профіль\n\n"
        f"ID: {user.id}\n"
        f"Рефералів: {refs}\n\n"
        f"🔗 Твоя реф-силка:\n{link}"
    )


def is_admin(user_id: int) -> bool:
    return ADMIN_ID != 0 and user_id == ADMIN_ID


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Нема доступу.")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("📣 Розсилка (reply)", callback_data="admin_broadcast")],
    ])
    await update.message.reply_text("🛠 Адмін панель:", reply_markup=keyboard)


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "earn":
        await q.edit_message_text(
            "⭐ Заробити зірочки\n\n"
            "Тут буде механіка заробітку (канали/завдання/рефералка).\n"
            "Поки працює рефералка — натисни «👥 Рефералка».",
            reply_markup=main_menu()
        )

    elif q.data == "ref":
        user = q.from_user
        refs = count_refs(user.id)
        link = f"https://t.me/{(context.bot.username or 'YOUR_BOT')}?start={user.id}"
        await q.edit_message_text(
            f"👥 Рефералка\n\n"
            f"Твої реферали: {refs}\n\n"
            f"🔗 Запрошуй друзів цією силкою:\n{link}",
            reply_markup=main_menu()
        )

    elif q.data == "ads":
        await q.edit_message_text(
            "📢 Реклама / Канали\n\n"
            "1) Ти можеш продавати рекламу в боті\n"
            "2) Або додати список каналів для переходів\n\n"
            "Скажи мені: ти хочеш «продавати рекламу» чи «просто список каналів»?",
            reply_markup=main_menu()
        )

    elif q.data == "support":
        await q.edit_message_text(
            "🆘 Підтримка\n\n"
            "Напиши сюди свою проблему одним повідомленням.\n"
            "Якщо ти власник — можеш додати контакт/юзернейм підтримки в текст.",
            reply_markup=main_menu()
        )

    elif q.data == "admin_stats":
        if not is_admin(q.from_user.id):
            return
        await q.edit_message_text(
            f"📊 Статистика\n\n"
            f"Користувачів у боті: {count_users()}",
            reply_markup=main_menu()
        )

    elif q.data == "admin_broadcast":
        if not is_admin(q.from_user.id):
            return
        await q.edit_message_text(
            "📣 Розсилка\n\n"
            "Напиши команду так:\n"
            "/broadcast Текст повідомлення\n\n"
            "Або я можу зробити розсилку з картинками/кнопками — скажи.",
            reply_markup=main_menu()
        )


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Нема доступу.")
        return

    if not context.args:
        await update.message.reply_text("Приклад: /broadcast Привіт всім!")
        return

    text = " ".join(context.args)

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    users = [row[0] for row in cur.fetchall()]
    conn.close()

    sent = 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=text)
            sent += 1
        except:
            pass

    await update.message.reply_text(f"✅ Розсилка готова. Надіслано: {sent}/{len(users)}")


def ensure_token():
    if not BOT_TOKEN or ":" not in BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing or invalid. Set it in Railway Variables.")


def run():
    ensure_token()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CallbackQueryHandler(on_button))

    print("Bot is running...")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    run()

