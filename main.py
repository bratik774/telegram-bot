import logging
import os
import random

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# =========================
# CONFIG
# =========================
TOKEN = os.getenv("TOKEN")  # ОБОВʼЯЗКОВО
ADMIN_IDS = set()

raw_admins = os.getenv("ADMIN_IDS", "")
for x in raw_admins.replace(" ", "").split(","):
    if x.isdigit():
        ADMIN_IDS.add(int(x))

if not TOKEN:
    raise RuntimeError("❌ TOKEN not set in environment variables")

# =========================
# LOGGING
# =========================
logging.basicConfig(level=logging.INFO)

# =========================
# SIMPLE ADS STORAGE
# =========================
ADS = [
    "📣 Реклама\n\n🔥 Просування Telegram каналів\n💰 Оплата за результат\n👉 Пиши адміну",
    "📣 Реклама\n\n🚀 Купуй рекламу в боті\n🎯 Жива аудиторія\n👉 Звертайся до адміна",
    "📣 Реклама\n\n⭐ Telegram Stars\n🎟 Лотерея\n👉 Запусти рекламу тут",
]

# =========================
# HELPERS
# =========================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Earn", callback_data="earn")],
        [InlineKeyboardButton("👤 Profile", callback_data="profile")],
        [InlineKeyboardButton("🎟 Tickets", callback_data="tickets")],
        [InlineKeyboardButton("🎰 Lottery", callback_data="lottery")],
        [InlineKeyboardButton("📣 Ads", callback_data="ads")],
    ])

async def send_auto_ad(context, chat_id):
    ad = random.choice(ADS)
    await context.bot.send_message(chat_id, ad)

# =========================
# COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome!\n\n"
        "Earn ⭐ Telegram Stars & 🎟 Lottery Tickets\n"
        "🎟 1 Ticket = $1\n\n"
        "Choose an option 👇",
        reply_markup=main_keyboard()
    )

    # 🔥 автопоказ реклами
    await send_auto_ad(context, update.effective_chat.id)

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only")
        return

    await update.message.reply_text(
        "🛠 Admin Panel\n\n"
        "✔ Bot is running\n"
        "✔ Ads enabled\n"
        "✔ Lottery enabled\n\n"
        "Команди:\n"
        "/add_ad текст реклами"
    )

async def add_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    text = update.message.text.replace("/add_ad", "").strip()
    if not text:
        await update.message.reply_text("❌ Напиши текст реклами")
        return

    ADS.append("📣 Реклама\n\n" + text)
    await update.message.reply_text("✅ Рекламу додано")

# =========================
# CALLBACKS
# =========================
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "earn":
        await query.edit_message_text(
            "⭐ Earn\n\n"
            "🔹 Запрошуй друзів\n"
            "🔹 Виконуй оффери\n"
            "🔹 Отримуй білети"
        )

    elif query.data == "profile":
        await query.edit_message_text(
            "👤 Profile\n\n"
            "⭐ Stars: 0\n"
            "🎟 Tickets: 0\n"
            "👑 VIP: No"
        )

    elif query.data == "tickets":
        await query.edit_message_text(
            "🎟 Tickets Shop\n\n"
            "1 Ticket = $1\n"
            "Автозарахування після оплати"
        )

    elif query.data == "lottery":
        await query.edit_message_text(
            "🎰 Lottery\n\n"
            "💰 Jackpot росте\n"
            "⏱ Скоро розіграш"
        )

    elif query.data == "ads":
        await query.edit_message_text(
            "📣 Реклама в боті\n\n"
            "🔹 Закріплене повідомлення\n"
            "🔹 Автопоказ юзерам\n"
            "🔹 Оффери\n\n"
            "💰 Ціни:\n"
            "$10 / 24 години\n"
            "$0.01 / показ\n\n"
            "📩 Пиши адміну"
        )

# =========================
# START APP
# =========================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("add_ad", add_ad))
    app.add_handler(CallbackQueryHandler(callbacks))

    print("✅ Bot started with ADS")
    app.run_polling()

if __name__ == "__main__":
    main()

