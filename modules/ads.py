import time
from db import get_db
from config import ADMIN_IDS


ADS_PRICE_TEXT = (
    "📣 Реклама\n\n"
    "Варіанти:\n"
    "• 1 пост / 24 год — $5\n"
    "• Закріплення — $10\n"
    "• Масовий пуш — $20\n\n"
    "Для заявки: /buy_ad"
)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def create_ad(owner_id: int, text: str, url: str | None, post_every_min: int = 720) -> int:
    now = int(time.time())
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO ads(owner_id, text, url, status, created_at, post_every_min) "
            "VALUES (?,?,?,?,?,?)",
            (owner_id, text, url, "pending", now, post_every_min),
        )
    return int(cur.lastrowid)


def list_pending_ads():
    with get_db() as db:
        rows = db.execute(
            "SELECT id, owner_id, text, url, created_at "
            "FROM ads WHERE status='pending' ORDER BY created_at ASC"
        ).fetchall()
    return rows


def set_ad_status(ad_id: int, status: str):
    now = int(time.time())
    with get_db() as db:
        db.execute(
            "UPDATE ads SET status=?, approved_at=? WHERE id=?",
            (status, now if status == "approved" else None, ad_id),
        )


def pick_next_ad_to_post():
    now = int(time.time())
    with get_db() as db:
        row = db.execute(
            """
            SELECT id, text, url, last_posted_at, post_every_min
            FROM ads
            WHERE status='approved'
            ORDER BY last_posted_at ASC
            LIMIT 1
            """
        ).fetchone()

    if not row:
        return None

    last_posted = int(row["last_posted_at"] or 0)
    every = int(row["post_every_min"] or 720) * 60
    if now - last_posted < every:
        return None

    return dict(row)


def mark_posted(ad_id: int):
    now = int(time.time())
    with get_db() as db:
        db.execute(
            "UPDATE ads SET last_posted_at=? WHERE id=?",
            (now, ad_id),
        )
