from db import get_db
from modules.vip import apply_vip_multiplier


def add_tickets(user_id: int, amount: int, apply_vip: bool = True) -> int:
    """
    Нараховує білети користувачу
    Якщо apply_vip=True — застосовується VIP множник
    """
    if amount <= 0:
        return 0

    final_amount = (
        apply_vip_multiplier(user_id, amount)
        if apply_vip else amount
    )

    with get_db() as db:
        db.execute(
            "UPDATE balances SET tickets = tickets + ? WHERE user_id=?",
            (final_amount, user_id),
        )

    return final_amount


def get_tickets(user_id: int) -> int:
    """
    Повертає кількість білетів користувача
    """
    with get_db() as db:
        row = db.execute(
            "SELECT tickets FROM balances WHERE user_id=?",
            (user_id,),
        ).fetchone()

    return int(row["tickets"]) if row else 0
