import logging
import time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (

from modules.ref_tasks import add_ref_task, get_active_tasks, complete_task

    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import (
    BOT_TOKEN, ADMIN_IDS,
    VIP_PRICE_STARS, PAYMENT_UAH_URL, PAYMENT_USD_URL,
    ADS_AUTOPOST_EVERY_MIN, ADS_CHANNEL_ID,
    STARS_PROVIDER_TOKEN,
)
from locales import LANGS
from db import init_db, get_or_create_user, get_user, top_tickets
from modules.language import lang_keyboard, apply_lang_choice
from modules.vip import is_vip, activate_vip, vip_until_ts
from modules.lottery import get_current_cycle, time_left_str, join_lottery, close_cycle_and_start_new
from modules.ads import create_order, set_status, list_pending_review, pick_next_approved
from modules.donations import register_donation, get_top

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("bot")


def t(lang: str, key: str) -> str:
    return LANGS.get(lang, LANGS["ua"]).get(key, key)

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def main_menu(lang: str):
    # кнопки як у твоєму прикладі (краще/повніше)
    return ReplyKeyboardMarkup(
        [
            [t(lang, "earn")],
            [t(lang, "ref"), t(lang, "ads")],
            [t(lang, "lottery")],
            [t(lang, "balance")],
            [t(lang, "donate"), t(lang, "donate_top")],
            [t(lang, "lang"), t(lang, "support")],
        ],
        resize_keyboard=True
    )


async def cmd_add_ref_task(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return
    text = " ".join(context.args)
    if "|" not in text:
        await update.message.reply_text("Формат: /add_task Назва | https://link")
        return

    title, link = [x.strip() for x in text.split("|", 1)]
    add_ref_task(title, link)
    await update.message.reply_text("✅ Реф-завдання додано")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user = get_or_create_user(u.id, u.username, u.first_name)
    lang = user.get("lang", "ua")

    # optional referral param: /start <refid>
    if context.args:
        # Тут можна підключити твою referrals.py, якщо вона є
        pass

    await update.message.reply_text(
        f"{t(lang,'menu_title')}\n\n"
        f"👤 {t(lang,'your_id')}: {u.id}\n"
        f"🎟 {t(lang,'tickets')}: {user.get('tickets',0)}\n"
        f"{t(lang,'vip')}: {t(lang,'vip_active') if is_vip(u.id) else t(lang,'vip_inactive')}",
        reply_markup=main_menu(lang)
    )

async def cmd_task_done(update, context):
    uid = update.effective_user.id
    if not context.args:
        return

    task_id = int(context.args[0])
    ok = complete_task(uid, task_id)

    if ok:
        await update.message.reply_text("⭐ Завдання виконано! +1 зірочка")
    else:
        await update.message.reply_text("❌ Уже виконано або помилка")

async def cmd_tasks(update, context):
    user = get_user(update.effective_user.id)
    lang = user.get("lang", "ua")

    tasks = get_active_tasks()
    if not tasks:
        await update.message.reply_text("Немає доступних завдань")
        return

    text = "📋 Завдання:\n\n"
    for t in tasks:
        text += f"🔗 {t['title']}\n{t['link']}\n/task_done {t['id']}\n\n"

    await update.message.reply_text(text)

    async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user = get_user(u.id) or {}
    lang = user.get("lang", "ua")
    vip_txt = t(lang, "vip_active") if is_vip(u.id) else t(lang, "vip_inactive")
    until = vip_until_ts(u.id)
    until_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(until)) if until else "—"

    await update.message.reply_text(
        f"🎟 {t(lang,'tickets')}: {user.get('tickets',0)}\n"
        f"{t(lang,'vip')}: {vip_txt}\n"
        f"⏳ VIP until: {until_str}"
    )


async def cmd_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user = get_user(u.id) or {}
    lang = user.get("lang", "ua")
    await update.message.reply_text(t(lang, "choose_lang"), reply_markup=lang_keyboard())


async def cb_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    _, lang = q.data.split(":", 1)
    lang = apply_lang_choice(uid, lang)
    await q.edit_message_text(f"✅ OK: {lang}")
    await context.bot.send_message(chat_id=uid, text=t(lang, "menu_title"), reply_markup=main_menu(lang))


async def show_lottery(update: Update, lang: str):
    cycle = get_current_cycle()
    left = time_left_str(cycle["ends_at"]) if cycle else "—"
    tops = top_tickets(5)
    text = f"{t(lang,'lottery')}\n\n{t(lang,'lottery_left')}: {left}\n\n{t(lang,'lottery_top')}:\n"
    for i, row in enumerate(tops, 1):
        text += f"{i}. ID {row['user_id']} — {row['tickets']} 🎟\n"
    text += f"\n{t(lang,'lottery_join_hint')}"
    await update.message.reply_text(text)


async def cmd_lottery_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user = get_user(u.id) or {}
    lang = user.get("lang", "ua")
    if not context.args:
        await update.message.reply_text(t(lang, "lottery_join_hint"))
        return
    try:
        n = int(context.args[0])
    except ValueError:
        await update.message.reply_text(t(lang, "lottery_join_hint"))
        return

    if user.get("tickets", 0) <= 0:
        await update.message.reply_text(t(lang, "need_tickets"))
        return

    cycle = get_current_cycle()
    if not cycle:
        await update.message.reply_text("Lottery not ready")
        return

    join_lottery(cycle["id"], u.id, max(1, n))
    await update.message.reply_text("✅ Joined")


async def vip_menu(update: Update, lang: str):
    # Stars invoice (optional)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{t(lang,'vip_buy')} — {VIP_PRICE_STARS} ⭐", callback_data="vip:buy")],
    ])
    await update.message.reply_text(
        f"👑 VIP\n"
        f"• +250 🎟\n"
        f"• x2 multiplier\n"
        f"• 30 days\n",
        reply_markup=kb
    )


async def cb_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    user = get_user(uid) or {}
    lang = user.get("lang", "ua")

    # Якщо не налаштовані Stars інвойси — показуємо інструкцію
    if not STARS_PROVIDER_TOKEN:
        await q.edit_message_text(
            "⚠️ Stars auto-pay ще не підключено.\n"
            "Зараз варіант: напиши в підтримку /support і адмін активує VIP вручну."
        )
        return

    # Тут місце для Telegram invoice на Stars (XTR).
    # Реалізація інвойсу залежить від того, як саме ти підключиш Stars payments.
    # Щоб не зламати бота, зараз робимо “safe stub”:
    activate_vip(uid)
    await q.edit_message_text("✅ VIP activated (stub).")


async def donate_menu(update: Update, lang: str):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Donate Stars", callback_data="don:stars")],
        [InlineKeyboardButton("₴ Donate UAH", url=PAYMENT_UAH_URL or "https://example.com")],
        [InlineKeyboardButton("$ Donate USD", url=PAYMENT_USD_URL or "https://example.com")],
        [InlineKeyboardButton(t(lang, "donate_top"), callback_data="don:top")],
    ])
    await update.message.reply_text("💰 Донати:", reply_markup=kb)


async def cb_donate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    user = get_user(uid) or {}
    lang = user.get("lang", "ua")

    if q.data == "don:top":
        tops = get_top(10)
        text = f"{t(lang,'donate_top')}:\n"
        for i, r in enumerate(tops, 1):
            text += f"{i}. ID {r['user_id']} — total {r['donated_total']:.2f} (⭐{r['donated_xtr']} ₴{r['donated_uah']:.2f} ${r['donated_usd']:.2f})\n"
        await q.edit_message_text(text)
        return

    if q.data == "don:stars":
        if not STARS_PROVIDER_TOKEN:
            await q.edit_message_text("⚠️ Stars auto-donate ще не підключено. Поки що донат через підтримку.")
            return
        # safe stub donate 1 star
        register_donation(uid, 1, "XTR")
        await q.edit_message_text("✅ Donated 1 ⭐ (stub).")
        return


async def ads_menu(update: Update, lang: str):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "ad_buy"), callback_data="ads:buy")],
        [InlineKeyboardButton(t(lang, "ad_status"), callback_data="ads:status")],
    ])
    await update.message.reply_text(t(lang, "ads"), reply_markup=kb)


async def cb_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    user = get_user(uid) or {}
    lang = user.get("lang", "ua")

    if q.data == "ads:buy":
        await q.edit_message_text("Надішли одним повідомленням текст реклами.\nФормат:\nTEXT | https://link\n\nПісля цього дам лінк на оплату.")
        context.user_data["ads_waiting_text"] = True
        return

    if q.data == "ads:status":
        await q.edit_message_text("📌 Статус: якщо оплатив — чекай модерацію.")
        return


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user = get_user(u.id) or {}
    lang = user.get("lang", "ua")
    text = (update.message.text or "").strip()

    # menu routing by button titles
    if text == t(lang, "lang"):
        await cmd_language(update, context); return
    if text == t(lang, "balance"):
        await cmd_balance(update, context); return
    if text == t(lang, "lottery"):
        await show_lottery(update, lang); return
    if text == t(lang, "donate"):
        await donate_menu(update, lang); return
    if text == t(lang, "ads"):
        await ads_menu(update, lang); return
    if text == t(lang, "earn"):
        await update.message.reply_text("⭐ Тут підключиш оффери/посилання. (плейсхолдер)"); return
    if text == t(lang, "ref"):
        await update.message.reply_text("👥 Рефералка (плейсхолдер)"); return
    if text == t(lang, "support"):
        await update.message.reply_text("🆘 Підтримка: напиши @your_support"); return

    # ads flow
    if context.user_data.get("ads_waiting_text"):
        context.user_data["ads_waiting_text"] = False
        parts = [p.strip() for p in text.split("|", 1)]
        ad_text = parts[0]
        ad_link = parts[1] if len(parts) > 1 else ""

        # Example pricing:
        price = 10.0
        currency = "USD"
        order_id = create_order(u.id, ad_text, ad_link, price, currency)

        pay_link = PAYMENT_USD_URL or "https://example.com"
        set_status(order_id, "pending_review")  # if you want payment-gated: keep pending_payment
        await update.message.reply_text(
            f"🧾 Order #{order_id}\n"
            f"Сума: {price} {currency}\n"
            f"Оплата: {pay_link}\n"
            f"Після оплати — чекай модерацію."
        )
        # notify admins
        for aid in ADMIN_IDS:
            try:
                await context.bot.send_message(aid, f"📣 New ad order #{order_id}\nText: {ad_text}\nLink: {ad_link}\nApprove: /ad_approve {order_id}  Reject: /ad_reject {order_id}")
            except:
                pass
        return


# -------- Admin commands for ads --------
async def ad_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    if not context.args:
        await update.message.reply_text("Usage: /ad_approve <id>"); return
    oid = int(context.args[0])
    set_status(oid, "approved")
    await update.message.reply_text(f"✅ approved #{oid}")

async def ad_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    if not context.args:
        await update.message.reply_text("Usage: /ad_reject <id>"); return
    oid = int(context.args[0])
    set_status(oid, "rejected")
    await update.message.reply_text(f"❌ rejected #{oid}")


# -------- Jobs: lottery autoclose + ads autopost --------
async def job_lottery_check(context: ContextTypes.DEFAULT_TYPE):
    cycle = get_current_cycle()
    if not cycle:
        return
    if int(time.time()) >= int(cycle["ends_at"]) and int(cycle["closed"]) == 0:
        closed_cycle, winner = close_cycle_and_start_new()
        if not closed_cycle:
            return
        # announce to all users (simple: only to admins here; full broadcast requires user list scan)
        for aid in ADMIN_IDS:
            await context.bot.send_message(aid, f"🎟 Lottery ended. Winner: {winner or 'no one'}")

if user.get("donated_xtr", 0) >= 50:
    text += "\n💸 Вивід доступний"
else:
    text += "\n⛔ Вивід від 50 ⭐"

async def job_ads_autopost(context: ContextTypes.DEFAULT_TYPE):
    if not ADS_CHANNEL_ID:
        return
    ad = pick_next_approved()
    if not ad:
        return
    text = ad["text"]
    link = ad["link"]
    msg = text + (f"\n{link}" if link else "")
    try:
        await context.bot.send_message(chat_id=int(ADS_CHANNEL_ID), text=msg)
        set_status(ad["id"], "posted")
    except Exception as e:
        log.warning(f"ads autopost failed: {e}")


def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("lottery_join", cmd_lottery_join))
    app.add_handler(CommandHandler("ad_approve", ad_approve))
    app.add_handler(CommandHandler("ad_reject", ad_reject))

    app.add_handler(CallbackQueryHandler(cb_language, pattern=r"^lang:"))
    app.add_handler(CallbackQueryHandler(cb_vip, pattern=r"^vip:"))
    app.add_handler(CallbackQueryHandler(cb_donate, pattern=r"^don:"))
    app.add_handler(CallbackQueryHandler(cb_ads, pattern=r"^ads:"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    # Jobs
    app.job_queue.run_repeating(job_lottery_check, interval=60, first=10)
    app.job_queue.run_repeating(job_ads_autopost, interval=ADS_AUTOPOST_EVERY_MIN * 60, first=30)

    app.run_polling(allowed_updates=None)

app.add_handler(CommandHandler("add_task", cmd_add_ref_task))
app.add_handler(CommandHandler("tasks", cmd_tasks))
app.add_handler(CommandHandler("task_done", cmd_task_done))


if __name__ == "__main__":
    main()

