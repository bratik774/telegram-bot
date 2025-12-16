import time
import random
from db import get_db
from modules.tickets import get_tickets, add_tickets


def ensure_round_open() -> int:
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM lottery_round WHERE status='open' ORDER BY id DESC LIMIT 1"
        ).fetchone()

        if row:
            return int(row["id"])

        now = int(time.time())
        cur = db.execute(
            "INSERT INTO lottery_round(status, jackpot_tickets, created_at) VALUES (?,?,?)",
            ("open", 0, now)
        )
        return int(cur.lastrowid)


def join_lottery(user_id: int, tickets: int) -> tuple[bool, str]:
    if tickets <= 0:
        return False, "❌ Кількість білетів має бути більше 0"

    have = get_tickets(user_id)
    if have < tickets:
        return False, f"❌ Недостатньо білетів. У тебе {have}"

    round_id = ensure_round_open()
    now = int(time.time())

    with get_db() as db:
        db.execute(
            "UPDATE balances SET tickets = tickets - ? WHERE user_id=?",
            (tickets, user_id)
        )
        db.execute(
            "INSERT INTO lottery_entries(round_id, user_id, tickets, created_at) VALUES (?,?,?,?)",
            (round_id, user_id, tickets, now)
        )
        db.execute(
            "UPDATE lottery_round SET jackpot_tickets = jackpot_tickets + ? WHERE id=?",
            (tickets, round_id)
        )

    return True, f"✅ Ти зайшов у лотерею #{round_id} з {tickets} білетами"


def draw_winner() -> tuple[bool, str]:
    with get_db() as db:
        round_row = db.execute(
            "SELECT id, jackpot_tickets FROM lottery_round WHERE status='open' ORDER BY id DESC LIMIT 1"
        ).fetchone()

        if not round_row:
            return False, "❌ Немає активного раунду"

        round_id = int(round_row["id"])
        jackpot = int(round_row["jackpot_tickets"])

        entries = db.execute(
            "SELECT user_id, tickets FROM lottery_entries WHERE round_id=?",
            (round_id,)
        ).fetchall()

        if not entries or jackpot <= 0:
            return False, "❌ У цьому раунді немає ставок"

        pool = []
        for e in entries:
            pool.extend([int(e["user_id"])] * int(e["tickets"]))

        winner = random.choice(pool)
        now = int(time.time())

        db.execute(
            "UPDATE lottery_round SET status='finished', closed_at=? WHERE id=?",
            (now, round_id)
        )

    add_tickets(winner, jackpot, apply_vip=False)
    return True, f"🏆 Переможець лотереї #{round_id}: {winner}\n🎁 Джекпот: {jackpot} білетів"
