import time
from db import get_db
from config import VIP_MULTIPLIER, VIP_DAYS_DEFAULT


def is_vip(user_id: int) -> bool:
    now = int(time.time())
    with get_db() as db:
        row = db.execute(
            "SELECT vip_until FROM vip WHERE user_id=?",
            (user_id,)
        ).fetchone()

    return bool(row and row["vip_until"] and int(row["vip_until"]) > now)


def vip_until_ts(user_id: int) -> int:
    with get_db() as db:
        row = db.execute(
            "SELECT vip_until FROM vip WHERE user_id=?",
            (user_id,)
        ).fetchone()

    return int(row["vip_until"]) if row and row["vip_until"] else 0


def add_vip(user_id: int, days: int = VIP_DAYS_DEFAULT) -> int:
    """
    Додає або подовжує VIP
    """
    now = int(time.time())
    add_seconds = days * 86400

    current = vip_until_ts(user_id)
    new_until = max(now, current) + add_seconds

    with get_db() as db:
        db.execute(
            "INSERT INTO vip(user_id, vip_until) VALUES(?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET vip_until=excluded.vip_until",
            (user_id, new_until),
        )

    return new_until


def apply_vip_multiplier(user_id: int, base_amount: int) -> int:
    """
    Застосовує множник VIP (наприклад x2)
    """
    if is_vip(user_id):
        return int(base_amount * VIP_MULTIPLIER)
    return base_amount
