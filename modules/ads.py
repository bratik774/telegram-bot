import time
from db import get_db

def create_order(user_id: int, text: str, link: str, price: float, currency: str):
    now = int(time.time())
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO ads_orders(user_id, text, link, price, currency, status, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (user_id, text, link, price, currency, "pending_payment", now),
        )
        return int(cur.lastrowid)

def set_status(order_id: int, status: str):
    with get_db() as db:
        db.execute("UPDATE ads_orders SET status=? WHERE id=?", (status, order_id))

def get_order(order_id: int):
    with get_db() as db:
        r = db.execute("SELECT * FROM ads_orders WHERE id=?", (order_id,)).fetchone()
        return dict(r) if r else None

def list_pending_review():
    with get_db() as db:
        rows = db.execute("SELECT * FROM ads_orders WHERE status='pending_review' ORDER BY created_at ASC").fetchall()
        return [dict(r) for r in rows]

def pick_next_approved():
    with get_db() as db:
        r = db.execute("SELECT * FROM ads_orders WHERE status='approved' ORDER BY created_at ASC LIMIT 1").fetchone()
        return dict(r) if r else None

