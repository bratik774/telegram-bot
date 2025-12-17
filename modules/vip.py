import time
from config import VIP_MULTIPLIER, VIP_DAYS_DEFAULT, VIP_TICKETS_BONUS
from db import get_user, get_db, add_tickets

def is_vip(user_id: int) -> bool:
    u = get_user(user_id)
    if not u:
        return False
    return int(u.get("vip_until", 0)) > int(time.time())

def vip_until_ts(user_id: int) -> int:
    u = get_user(user_id)
    return int(u.get("vip_until", 0)) if u else 0

def activate_vip(user_id: int, days: int = VIP_DAYS_DEFAULT):
    now = int(time.time())
    until = now + days * 86400
    with get_db() as db:
        db.execute("UPDATE users SET vip_until=? WHERE user_id=?", (until, user_id))
    add_tickets(user_id, VIP_TICKETS_BONUS)

def apply_vip_multiplier(user_id: int, base: int) -> int:
    return int(base * VIP_MULTIPLIER) if is_vip(user_id) else base

    
