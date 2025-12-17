import os

def _must(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(f"{name} missing in Railway Variables")
    return v

BOT_TOKEN = _must("BOT_TOKEN")

# Admins: "123,456"
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

# DB
DB_PATH = os.getenv("DB_PATH", "bot.sqlite3")

# VIP
VIP_PRICE_STARS = int(os.getenv("VIP_PRICE_STARS", "50"))         # 50 ⭐
VIP_TICKETS_BONUS = int(os.getenv("VIP_TICKETS_BONUS", "250"))    # +250 tickets
VIP_MULTIPLIER = float(os.getenv("VIP_MULTIPLIER", "2.0"))        # x2
VIP_DAYS_DEFAULT = int(os.getenv("VIP_DAYS_DEFAULT", "30"))       # 30 days

# Referrals (%)
REF_LVL1_PCT = float(os.getenv("REF_LVL1_PCT", "0.10"))
REF_LVL2_PCT = float(os.getenv("REF_LVL2_PCT", "0.05"))
REF_LVL3_PCT = float(os.getenv("REF_LVL3_PCT", "0.02"))

# Lottery
LOTTERY_PERIOD_HOURS = int(os.getenv("LOTTERY_PERIOD_HOURS", "168"))  # 7 days
LOTTERY_PRIZE_TEXT = os.getenv("LOTTERY_PRIZE_TEXT", "🎁 Prize")

# Ads autopost
ADS_AUTOPOST_EVERY_MIN = int(os.getenv("ADS_AUTOPOST_EVERY_MIN", "180"))
ADS_CHANNEL_ID = os.getenv("ADS_CHANNEL_ID", "")  # e.g. "-1001234567890" (channel id). If empty: disabled.

# Payment links for UAH/USD (external provider)
PAYMENT_UAH_URL = os.getenv("PAYMENT_UAH_URL", "")
PAYMENT_USD_URL = os.getenv("PAYMENT_USD_URL", "")

# Telegram Stars invoices (optional)
# If empty -> Stars auto-pay disabled, bot will show “send stars manually / ask admin”.
STARS_PROVIDER_TOKEN = os.getenv("STARS_PROVIDER_TOKEN", "")
