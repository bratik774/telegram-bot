import time
from typing import Optional
from db import get_db
from config import REF_LVL1_PCT, REF_LVL2_PCT, REF_LVL3_PCT


def ensure_user(user_id: int, username: str | None, first_name: str | None):
    now = int(time.time())
    with get_db() as db:
        db.execute(
            "INSERT OR IGNORE INTO users(user_id, username, first_name, created_at) "
            "VALUES (?,?,?,?)",
            (user_id, username, first_name, now),
        )
        db.execute(
            "INSERT OR IGNORE INTO balances(user_id, tickets, ref_earn_stars, total_spent_stars) "
            "VALUES (?,?,?,?)",
            (user_id, 0, 0, 0),
        )
        db.execute(
            "INSERT OR IGNORE INTO referrals(user_id, ref1, ref2, ref3) "
            "VALUES (?,?,?,?)",
            (user_id, None, None, None),
        )


def set_referrer_chain(new_user_id: int, referrer_id: Optional[int]):
    """
    Викликається ОДИН раз при першому /start з реф-кодом
    """
    if not referrer_id or referrer_id == new_user_id:
        return

    with get_db() as db:
        row = db.execute(
            "SELECT ref1 FROM referrals WHERE user_id=?",
            (new_user_id,)
        ).fetchone()

        if row and row["ref1"] is not None:
            return  # реф уже встановлений

        ref_row = db.execute(
            "SELECT ref1, ref2 FROM referrals WHERE user_id=?",
            (referrer_id,)
        ).fetchone()

        ref1 = referrer_id
        ref2 = ref_row["ref1"] if ref_row else None
        ref3 = ref_row["ref2"] if ref_row else None

        db.execute(
            "UPDATE referrals SET ref1=?, ref2=?, ref3=? WHERE user_id=?",
            (ref1, ref2, ref3, new_user_id),
        )


def add_spent(user_id: int, stars: float):
    with get_db() as db:
        db.execute(
            "UPDATE balances SET total_spent_stars = total_spent_stars + ? WHERE user_id=?",
            (stars, user_id),
        )


def credit_ref_earnings(user_id: int, stars: float):
    with get_db() as db:
        db.execute(
            "UPDATE balances SET ref_earn_stars = ref_earn_stars + ? WHERE user_id=?",
            (stars, user_id),
        )


def process_ref_commissions(payer_user_id: int, paid_stars: float) -> dict:
    """
    Нарахування реф-бонусів (3 рівні)
    Викликається ТІЛЬКИ після успішної оплати
    """
    with get_db() as db:
        chain = db.execute(
            "SELECT ref1, ref2, ref3 FROM referrals WHERE user_id=?",
            (payer_user_id,),
        ).fetchone()

    payouts = {}
    if not chain:
        return payouts

    levels = [
        ("ref1", REF_LVL1_PCT),
        ("ref2", REF_LVL2_PCT),
        ("ref3", REF_LVL3_PCT),
    ]

    for key, pct in levels:
        boss_id = chain[key]
        if boss_id:
            amount = round(paid_stars * pct, 4)
            if amount > 0:
                credit_ref_earnings(int(boss_id), amount)
                payouts[int(boss_id)] = amount

    return payouts
