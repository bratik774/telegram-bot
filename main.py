import logging
import os
import time
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)

from config import BOT_TOKEN, ADS_AUTOPOST_EVERY_MIN, TICKET_PRICE_STARS, VIP_DAYS_DEFAULT
from db import init_db
from modules.referrals import ensure_user, set_referrer_chain, add_spent, process_ref_commissions
from modules.vip import is_vip, add_vip, vip_until_ts
from modules.tickets import add_tickets, get_tickets
from modules.ads import ADS_PRICE_TEXT, create_ad, list_pending_ads, set_ad_status, pick_next_ad_to_post, mark_posted, is_admin
from modules.lottery import join_lottery, draw_winner

# ----------------- logging -----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("bot")

# ----------------- anti-flood -----------------
_user_last = {}
def anti_flood(user_id: int, delay: float = 1.2) -> bool:
    now = time.time()
    last = _user_last.get(user_id, 0)
    if now - last < delay:
        return False
    _user_last[user_id] = now
    return True

# ----------------- helpers -----------------
def main_menu() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("⭐ Купити білети", callback_data="buy")],
        [InlineKeyboardButton("🎟 Мої білети", callback_data="my_tickets"),
         InlineKeyboardButton("👑 VIP", callback_data="vip")],
        [InlineKeyboardButton("🔗 Рефералка", callback_data="ref")],
        [InlineKeyboardButton("🎰 Лотерея", callback_data="lottery")],
        [InlineKeyboardButton("📣 Реклама", callback_data="ads")],
        [InlineKeyboardButton("🆘 Підтримка", callback_data="support")],
    ]
    return InlineKeyboardMarkup(kb)

def ref_link(username_or_id: str) -> str:
    # якщо є username — можна красиво. якщо ні — працюємо через id
    return f"https://t.me/{username_or_id}?start="

def parse_start_ref(args: list[str]) -> Optional[int]:
    # очікуємо /start ref_123 або просто 123
    if not args:
        return None
    raw = args[0].strip()
    if raw.startswith("ref_"):
        raw = raw[4:]
    if raw.isdigit():
        return int(raw)
    return None

# ----------------- payments hook (важливо) -----------------
async def confirm_payment(
    payer_user_id: int,
    paid_stars: int,
    kind: str,
    context: ContextTypes.DEFAULT_TYPE,
):
    """
    ЄДИНА точка, де ми нараховуємо білети/VIP/реф.
    Викликається ТІЛЬКИ після факту успішної оплати Stars.
    kind: "tickets" або "vip"
    """
    ensure_user(payer_user_id, None, None)
    add_spent(payer_user_id, float(paid_stars))

    # VIP множник впливає на білети
    if kind == "tickets":
        # 1 Stars = 1 ticket (або як в тебе)
        base_tickets = paid_stars // TICKET_PRICE_STARS
        got = add_tickets(payer_user_id, int(base_tickets), apply_vip=True)
        await context.bot.send_message(
            chat_id=payer_user_id,
            text=f"✅ Оплата підтверджена.\n🎟 Нараховано білетів: {got}"
        )

    elif kind == "vip":
        until = add_vip(payer_user_id, VIP_DAYS_DEFAULT)
        await context.bot.send_message(
            chat_id=payer_user_id,
            text=f"👑 VIP активовано на {VIP_DAYS_DEFAULT} днів.\n⏳ Дійсний до: {time.strftime('%Y-%m-%d %H:%M', time.localtime(until))}"
        )

    # реф-комісії
    payouts = process_ref_commissions(payer_user_id, float(paid_stars))
    for boss_id, amount in payouts.items():
        await context.bot.send_message(
            chat_id=boss_id,
            text=f"💸 Реферальний бонус: +{amount} Stars (з оплати користувача {payer_user_id})"
        )

# ----------------- commands -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.username, user.first_name)

    # реф-ланцюг
    ref_id = parse_start_ref(context.args)
    set_referrer_chain(user.id, ref_id)

    await update.message.reply_text(
        "Привіт 👋\n\n"
        "Це платформа: ⭐ Stars / 🎟 білети / 👑 VIP / 🎰 лотереї / 📣 реклама.\n"
        "Обери дію нижче:",
        reply_markup=main_menu(),
    )

async def admin_pending_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return await update.message.reply_text("⛔️ Нема доступу.")

    rows = list_pending_ads()
    if not rows:
        return await update.message.reply_text("Немає pending-заявок.")

    text = "🧾 Pending реклама:\n\n"
    for r in rows[:20]:
        text += f"ID {r['id']} | owner {r['owner_id']}\n{r['text']}\nURL: {r['url']}\n\n"
    text += "✅ Схвалити: /ad_approve ID\n❌ Відхилити: /ad_reject ID"
    await update.message.reply_text(text)

async def ad_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return await update.message.reply_text("⛔️ Нема доступу.")
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text("Формат: /ad_approve 12")
    ad_id = int(context.args[0])
    set_ad_status(ad_id, "approved")
    await update.message.reply_text(f"✅ Ad {ad_id} approved.")

async def ad_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return await update.message.reply_text("⛔️ Нема доступу.")
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text("Формат: /ad_reject 12")
    ad_id = int(context.args[0])
    set_ad_status(ad_id, "rejected")
    await update.message.reply_text(f"❌ Ad {ad_id} rejected.")

# buy_ad flow via messages (simple state)
BUY_AD_STATE = {}

async def buy_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    BUY_AD_STATE[user.id] = {"step": 1}
    await update.message.reply_text(
        "📣 Створення заявки на рекламу.\n\n"
        "Надішли текст реклами одним повідомленням (до 1000 символів)."
    )

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not update.message or not update.message.text:
        return

    # антифлуд
    if not anti_flood(user.id):
        return

    # buy_ad wizard
    if user.id in BUY_AD_STATE:
        st = BUY_AD_STATE[user.id]
        step = st.get("step", 1)
        msg = update.message.text.strip()

        if step == 1:
            if len(msg) < 10:
                return await update.message.reply_text("Текст закороткий. Спробуй ще раз.")
            st["text"] = msg[:1000]
            st["step"] = 2
            return await update.message.reply_text("Тепер надішли URL (або напиши `-`, якщо без посилання).")

        if step == 2:
            url = None if msg == "-" else msg
            ad_id = create_ad(user.id, st["text"], url)
            BUY_AD_STATE.pop(user.id, None)
            await update.message.reply_text(f"✅ Заявка створена. ID: {ad_id}\nОчікуй модерацію.")
            return

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if not anti_flood(user.id):
        return

    data = query.data

    if data == "my_tickets":
        t = get_tickets(user.id)
        await query.edit_message_text(f"🎟 У тебе білетів: {t}", reply_markup=main_menu())

    elif data == "vip":
        if is_vip(user.id):
            until = vip_until_ts(user.id)
            await query.edit_message_text(
                f"👑 VIP активний.\n⏳ До: {time.strftime('%Y-%m-%d %H:%M', time.localtime(until))}",
                reply_markup=main_menu()
            )
        else:
            await query.edit_message_text(
                "👑 VIP дає x2 білети та бонуси.\n\n"
                "Щоб купити VIP: /buy_vip",
                reply_markup=main_menu()
            )

    elif data == "ref":
        # реф-код через user_id стабільний
        link = f"https://t.me/{context.bot.username}?start=ref_{user.id}"
        await query.edit_message_text(
            f"🔗 Твоя реф-силка (3 рівні):\n{link}",
            reply_markup=main_menu()
        )

    elif data == "ads":
        await query.edit_message_text(ADS_PRICE_TEXT, parse_mode="Markdown", reply_markup=main_menu())

    elif data == "support":
        await query.edit_message_text("🆘 Підтримка: напиши сюди свій питання одним повідомленням.", reply_markup=main_menu())

    elif data == "lottery":
        await query.edit_message_text(
            "🎰 Лотерея\n\n"
            "Щоб зайти: /lottery_join <кількість білетів>\n"
            "Приклад: /lottery_join 10",
            reply_markup=main_menu()
        )

    elif data == "buy":
        await query.edit_message_text(
            "⭐ Купівля білетів\n\n"
            "Оплата Stars має підтверджуватися реально.\n"
            "Після інтеграції платежу викликається confirm_payment(...)\n\n"
            "Тестово (симуляція адміном): /pay_test tickets <user_id> <stars>",
            reply_markup=main_menu()
        )

# VIP purchase command
async def buy_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👑 Купівля VIP\n\n"
        "Після реальної оплати Stars викликаємо confirm_payment(...)\n\n"
        "Тестово (симуляція адміном): /pay_test vip <user_id> <stars>"
    )

# lottery join
async def lottery_join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text("Формат: /lottery_join 10")
    n = int(context.args[0])
    ok, msg = join_lottery(user.id, n)
    await update.message.reply_text(msg)

# admin draw
async def lottery_draw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return await update.message.reply_text("⛔️ Нема доступу.")
    ok, msg = draw_winner()
    await update.message.reply_text(msg)

# TEST payment simulation (адміну)
async def pay_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return await update.message.reply_text("⛔️ Нема доступу.")
    if len(context.args) < 3:
        return await update.message.reply_text("Формат: /pay_test tickets|vip <user_id> <stars>")

    kind = context.args[0].strip()
    uid = int(context.args[1])
    stars = int(context.args[2])

    await confirm_payment(uid, stars, kind, context)
    await update.message.reply_text(f"✅ Симуляція оплати виконана: {kind} для {uid} ({stars} Stars)")

# ----------------- autopost ads job -----------------
async def autopost_ads_job(context: ContextTypes.DEFAULT_TYPE):
    ad = pick_next_ad_to_post()
    if not ad:
        return

    # тут ти вибираєш куди постити (канал/група/бот-чат)
    # для production: збережи CHANNEL_ID у Railway Variables і діставай через os.getenv
    channel_id = os.getenv("ADS_CHANNEL_ID")
    if not channel_id:
        return

    text = ad["text"]
    if ad.get("url"):
        text += f"\n\n👉 {ad['url']}"

    try:
        await context.bot.send_message(chat_id=channel_id, text=text)
        mark_posted(int(ad["id"]))
        log.info("Ad posted: %s", ad["id"])
    except Exception as e:
        log.exception("Failed to post ad: %s", e)

# ----------------- errors -----------------
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled error: %s", context.error)

# ----------------- build app -----------------
def build_app() -> Application:
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buy_ad", buy_ad))
    app.add_handler(CommandHandler("ads_pending", admin_pending_ads))
    app.add_handler(CommandHandler("ad_approve", ad_approve))
    app.add_handler(CommandHandler("ad_reject", ad_reject))

    app.add_handler(CommandHandler("buy_vip", buy_vip))
    app.add_handler(CommandHandler("lottery_join", lottery_join_cmd))
    app.add_handler(CommandHandler("lottery_draw", lottery_draw_cmd))

    # тестовий платіж (адмін)
    app.add_handler(CommandHandler("pay_test", pay_test))

    # callbacks + текст
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    # jobs
    app.job_queue.run_repeating(autopost_ads_job, interval=ADS_AUTOPOST_EVERY_MIN * 60, first=30)

    # error handler
    app.add_error_handler(on_error)

    return app

def main():
    app = build_app()
    log.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
