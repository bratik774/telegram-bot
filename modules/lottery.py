import time
import random
from config import LOTTERY_PERIOD_HOURS
from db import get_db

def get_current_cycle():
    with get_db() as db:
        c = db.execute("SELECT * FROM lottery_cycles ORDER BY id DESC LIMIT 1").fetchone()
        return dict(c) if c else None

def time_left_str(ends_at: int) -> str:
    left = int(ends_at) - int(time.time())
    if left <= 0:
        return "00:00:00"
    h = left // 3600
    m = (left % 3600) // 60
    s = left % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def join_lottery(cycle_id: int, user_id: int, tickets: int):
    with get_db() as db:
        row = db.execute(
            "SELECT tickets FROM lottery_entries WHERE cycle_id=? AND user_id=?",
            (cycle_id, user_id),
        ).fetchone()
        if row:
            db.execute(
                "UPDATE lottery_entries SET tickets=tickets+? WHERE cycle_id=? AND user_id=?",
                (tickets, cycle_id, user_id),
            )
        else:
            db.execute(
                "INSERT INTO lottery_entries(cycle_id, user_id, tickets) VALUES (?,?,?)",
                (cycle_id, user_id, tickets),
            )

def pick_winner(cycle_id: int):
    with get_db() as db:
        rows = db.execute(
            "SELECT user_id, tickets FROM lottery_entries WHERE cycle_id=?",
            (cycle_id,),
        ).fetchall()
    pool = []
    for r in rows:
        pool.extend([int(r["user_id"])] * int(r["tickets"]))
    if not pool:
        return None
    return random.choice(pool)

def close_cycle_and_start_new():
    now = int(time.time())
    with get_db() as db:
        cycle = db.execute("SELECT * FROM lottery_cycles ORDER BY id DESC LIMIT 1").fetchone()
        if not cycle:
            db.execute("INSERT INTO lottery_cycles(ends_at, started_at, closed) VALUES (?,?,0)", (now + LOTTERY_PERIOD_HOURS * 3600, now))
            return None, None

        cycle = dict(cycle)
        if cycle["closed"] == 1:
            return None, None

        winner = pick_winner(cycle["id"])
        db.execute("UPDATE lottery_cycles SET winner_id=?, closed=1 WHERE id=?", (winner, cycle["id"]))
        db.execute("INSERT INTO lottery_cycles(ends_at, started_at, closed) VALUES (?,?,0)", (now + LOTTERY_PERIOD_HOURS * 3600, now))
        return cycle, winner

def distribute_rewards():
    with get_db() as db:
        rows = db.execute(
            "SELECT user_id, tickets FROM users ORDER BY tickets DESC LIMIT 50"
        ).fetchall()

    for i, r in enumerate(rows, 1):
        uid = r["user_id"]

        if i <= 5:
            reward = 300
        elif i <= 15:
            reward = 100
        else:
            reward = 50

        add_donation(uid, reward, "XTR")
