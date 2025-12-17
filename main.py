import logging

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

from config import BOT_TOKEN
from db import init_db
from modules.referrals import ensure_user, set_referrer_chain
from modules.tickets import get_tickets
from modules.vip import is_vip
from modules.lottery import join_lottery, draw_winner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("bot")


# ---------------- /start ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    ensure_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    if context.args:
        try:
            ref_id = int(context.args[0])
            set_referrer_chain(user.id, ref_id)
        except ValueError:
            pass

    tickets = get_tickets(user.id)
    vip_status = "👑 VIP" if is_vip(user.id) else "—"

    await update.message.reply_text(
        f"⭐ Telegram Stars Bot\n\n"
        f"👤 ID: {user.id}\n"
        f"🎟 Білети: {tickets}\n"
        f"VIP: {vip_status}\n\n"
        f"/balance — баланс\n"
        f"/lottery_join <n> — участь у лотереї\n"
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    tickets = get_tickets(user.id)
    vip_status = "👑 VIP" if is_vip(user.id) else "—"

    await update.message.reply_text(
        f"🎟 Білети: {tickets}\nVIP: {vip_status}"
    )


async def lottery_join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Використання: /lottery_join 5")
        return

    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Кількість має бути числом")
        return

    ok, msg = join_lottery(update.effective_user.id, amount)
    await update.message.reply_text(msg)


async def lottery_draw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok, msg = draw_winner()
    await update.message.reply_text(msg)


# ---------------- ENTRYPOINT ----------------
def main():
    logger.info("Starting bot...")

    init_db()

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # 🔥 КРИТИЧНО ВАЖЛИВО
    application.bot.delete_webhook(drop_pending_updates=True)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("lottery_join", lottery_join_cmd))
    application.add_handler(CommandHandler("lottery_draw", lottery_draw_cmd))

    logger.info("Bot started, polling...")
    application.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()
