import logging
import time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import (
    BOT_TOKEN,
    ADMIN_IDS,
    VIP_PRICE_STARS,
    PAYMENT_USD_URL,
    ADS_AUTOPOST_EVERY_MIN,
    ADS_CHANNEL_ID,
)
from locales import LANGS
from db import init_db, get_or_create_user, get_user, top_tickets
from modules.language import lang_keyboard, apply_lang_choice
from modules.vip import is_vip, vip_until_ts
from modules.lottery import get_current_cycle, time_left_str, join_lottery, close_cycle_and_start_new
from modules.ads import create_order, set_status, pick_next_approved

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("bot")


def t(lang: str, key: str) -> str:
    return LANGS.get(lang, LANGS["ua"]).get(key, key)


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def main_menu(lang: str):
    return ReplyKeyboardMarkup(
        [
            [t(lang, "earn")],
            [t(lang, "ref"), t(lang, "ads")],
            [t(lang, "lottery")],
            [t(lang, "balance")],
            [t(lang, "donate")],
            [t(lang, "lang"), t(lang, "support")],
        ],
        resize_keyboard=True
    )


def fmt_vip_until(until_ts: int) -> str:
    if not until_ts:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(until_ts))


async def send_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user = get_user(u.id) or {}
    lang = user.get("lang", "ua")

    await update.message.reply_text(
        f"{t(lang,'menu_title')}\n\n"
        f"👤 {t(lang,'your_id')}: {u.id}\n"
        f"🎟 {t(lang,'tickets')}: {user.get('tickets',0)}\n"
        f"{t(lang,'vip')}: {t(lang,'vip_active') if is_vip(u.id) else t(lang,'vip_inactive')}",
        reply_markup=main_menu(lang),
    )


# ---------------- Commands ----------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user = get_or_create_user(u.id, u.username, u.first_name)
    lang = user.get("lang", "ua")

    # referral param (якщо потім треба буде) - поки без хаосу
    # /start <refid>
    # if context.args: ...

    await update.message.reply_text(
        f"{t(lang,'menu_title')}\n\n"
        f"👤 {t(lang,'your_id')}: {u.id}\n"
        f"🎟 {t(lang,'tickets')}: {user.get('tickets',0)}\n"
        f"{t(lang,'vip')}: {t(lang,'vip_active') if is_vip(u.id) else t(lang,'vip_inactive')}",
        reply_markup=main_menu(lang),
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_menu(update, context)


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user = get_user(u.id) or {}
    lang = user.get("lang", "ua")

    vip_txt = t(lang, "vip_active") if is_vip(u.id) else t(lang, "vip_inactive")
    until_str = fmt_vip_until(vip_until_ts(u.id))

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

    await q.edit_message_text("✅ OK")
    await context.bot.send_message(chat_id=uid, text=t(lang, "menu_title"), reply_markup=main_menu(lang))


# ---------------- Lottery ----------------
async def show_lottery(update: Update, lang: str):
    cycle = get_current_cycle()
    left = time_left_str(cycle["ends_at"]) if cycle else "—"

    tops = top_tickets(5)
    text = (
        f"🎟 {t(lang,'lottery')}\n\n"
        f"⏳ {t(lang,'lottery_left')}: {left}\n\n"
        f"🏆 {t(lang,'lottery_top')}:\n"
    )
    if not tops:
        text += "—\n"
    else:
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

    n = max(1, n)
    join_lottery(cycle["id"], u.id, n)
    await update.message.reply_text("✅ OK")


# ---------------- VIP (через підтримку) ----------------
async def vip_menu(update: Update, lang: str):
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"{t(lang,'vip_buy')} — {VIP_PRICE_STARS} ⭐", callback_data="vip:info")]]
    )
    await update.message.reply_text(
        "👑 VIP\n"
        f"💫 Ціна: {VIP_PRICE_STARS} ⭐\n"
        "🎟 +250 білетів\n"
        "🔥 Множник x2\n"
        "⏳ 30 днів\n\n"
        "Натисни кнопку нижче 👇",
        reply_markup=kb,
    )


async def cb_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    user = get_user(uid) or {}
    lang = user.get("lang", "ua")

    await q.edit_message_text(
        "👑 VIP\n\n"
        f"💫 Ціна: {VIP_PRICE_STARS} ⭐\n"
        "🎟 +250 білетів\n"
        "🔥 Множник x2\n"
        "⏳ 30 днів\n\n"
        "✅ Купівля зараз через адміністратора.\n"
        "Напиши в 🆘 Підтримка."
    )


# ---------------- Ads ----------------
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
        await q.edit_message_text(
            "📣 Надішли одним повідомленням текст реклами.\n\n"
            "Формат:\n"
            "TEXT | https://link\n\n"
            "Після цього я дам інструкцію по оплаті (через адміна/лінк)."
        )
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

    # menu routing
    if text == t(lang, "lang"):
        await cmd_language(update, context)
        return

    if text == t(lang, "balance"):
        await cmd_balance(update, context)
        return

    if text == t(lang, "lottery"):
        await show_lottery(update, lang)
        return

    if text == t(lang, "ads"):
        await ads_menu(update, lang)
        return

    if text == t(lang, "donate"):
        await update.message.reply_text(
            "💰 Донати приймаються через адміністратора.\n\n"
            "Напиши в 🆘 Підтримка."
        )
        return

    if text == t(lang, "support"):
        await update.message.reply_text("🆘 Підтримка: напиши @your_support")
        return

    if text == t(lang, "earn"):
        await update.message.reply_text("⭐ Тут будуть завдання/оффери (додамо далі).")
        return

    if text == t(lang, "ref"):
        await update.message.reply_text("👥 Рефералка (додамо далі без зламу).")
        return

    # ads flow
    if context.user_data.get("ads_waiting_text"):
        context.user_data["ads_waiting_text"] = False

        parts = [p.strip() for p in text.split("|", 1)]
        ad_text = parts[0]
        ad_link = parts[1] if len(parts) > 1 else ""

        # pricing example
        price = 10.0
        currency = "USD"
        order_id = create_order(u.id, ad_text, ad_link, price, currency)

        pay_link = PAYMENT_USD_URL or "Напиши в підтримку для оплати"
        set_status(order_id, "pending_review")

        await update.message.reply_text(
            f"🧾 Order #{order_id}\n"
            f"Сума: {price} {currency}\n"
            f"Оплата: {pay_link}\n"
            f"Після оплати — чекай модерацію."
        )

        # notify admins
        for aid in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    aid,
                    f"📣 New ad order #{order_id}\n"
                    f"User: {u.id}\n"
                    f"Text: {ad_text}\n"
                    f"Link: {ad_link}\n"
                    f"Approve: /ad_approve {order_id}\n"
                    f"Reject: /ad_reject {order_id}"
                )
            except Exception:
                pass
        return


# -------- Admin commands for ads --------
async def ad_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    if not context.args:
        await update.message.reply_text("Usage: /ad_approve <id>")
        return
    oid = int(context.args[0])
    set_status(oid, "approved")
    await update.message.reply_text(f"✅ approved #{oid}")


async def ad_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    if not context.args:
        await update.message.reply_text("Usage: /ad_reject <id>")
        return
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

        for aid in ADMIN_IDS:
            try:
                await context.bot.send_message(aid, f"🎟 Lottery ended. Winner: {winner or 'no one'}")
            except Exception:
                pass


async def job_ads_autopost(context: ContextTypes.DEFAULT_TYPE):
    if not ADS_CHANNEL_ID:
        return

    ad = pick_next_approved()
    if not ad:
        return

    msg = ad["text"] + (f"\n{ad['link']}" if ad.get("link") else "")
    try:
        await context.bot.send_message(chat_id=int(ADS_CHANNEL_ID), text=msg)
        set_status(ad["id"], "posted")
    except Exception as e:
        log.warning(f"ads autopost failed: {e}")


def main():
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("lottery_join", cmd_lottery_join))
    app.add_handler(CommandHandler("ad_approve", ad_approve))
    app.add_handler(CommandHandler("ad_reject", ad_reject))

    app.add_handler(CallbackQueryHandler(cb_language, pattern=r"^lang:"))
    app.add_handler(CallbackQueryHandler(cb_vip, pattern=r"^vip:"))
    app.add_handler(CallbackQueryHandler(cb_ads, pattern=r"^ads:"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.job_queue.run_repeating(job_lottery_check, interval=60, first=10)
    app.job_queue.run_repeating(job_ads_autopost, interval=ADS_AUTOPOST_EVERY_MIN * 60, first=30)

    app.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()

