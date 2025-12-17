import os

# === Telegram Bot Token ===
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN missing or invalid. "
        "Set BOT_TOKEN in Railway → Variables"
    )

# === Admin IDs ===
# Railway Variable: ADMIN_IDS=123456789,987654321
ADMIN_IDS = []

_admins = os.getenv("ADMIN_IDS", "")
if _admins:
    ADMIN_IDS = [
        int(x.strip())
        for x in _admins.split(",")
        if x.strip().isdigit()
    ]
# === Ads autopost ===
ADS_AUTOPOST_EVERY_MIN = int(
    os.getenv("ADS_AUTOPOST_EVERY_MIN", "180")
)

# === Economy ===
TICKET_PRICE_STARS = int(
    os.getenv("TICKET_PRICE_STARS", "1")
)

VIP_DAYS_DEFAULT = int(
    os.getenv("VIP_DAYS_DEFAULT", "30")
)
# === Database ===
DB_PATH = os.getenv("DB_PATH", "bot.sqlite3")
# === Referral percentages ===
REF_LVL1_PCT = float(os.getenv("REF_LVL1_PCT", "0.10"))  # 10%
REF_LVL2_PCT = float(os.getenv("REF_LVL2_PCT", "0.05"))  # 5%
REF_LVL3_PCT = float(os.getenv("REF_LVL3_PCT", "0.02"))  # 2%
# === VIP ===
VIP_MULTIPLIER = float(os.getenv("VIP_MULTIPLIER", "2.0"))
