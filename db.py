import sqlite3
import time
from contextlib import contextmanager
from config import DB_PATH

def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

@contextmanager
def get_db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with get_db() as db:
        db.execute("PRAGMA journal_mode=WAL;")
        db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            lang TEXT DEFAULT 'ua',
            tickets INTEGER DEFAULT 0,
            vip_until INTEGER DEFAULT 0,
            donated_total REAL DEFAULT 0,
            donated_xtr INTEGER DEFAULT 0,
            donated_uah REAL DEFAULT 0,
            donated_usd REAL DEFAULT 0,
            created_at INTEGER DEFAULT 0
        )
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS refs (
            user_id INTEGER PRIMARY KEY,
            ref1 INTEGER,
            ref2 INTEGER,
            ref3 INTEGER
        )
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS lottery_entries (
            cycle_id INTEGER,
            user_id INTEGER,
            tickets INTEGER,
            PRIMARY KEY (cycle_id, user_id)
        )
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS lottery_cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ends_at INTEGER,
            started_at INTEGER,
            winner_id INTEGER DEFAULT NULL,
            closed INTEGER DEFAULT 0
        )
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS ads_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            link TEXT,
            price REAL,
            currency TEXT,
            status TEXT, -- pending_payment / pending_review / approved / rejected / posted
            created_at INTEGER
        )
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS donations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            currency TEXT,
            ts INTEGER
        )
        """)

        now = int(time.time())
        # create first lottery cycle if none
        row = db.execute("SELECT id FROM lottery_cycles ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            db.execute(
                "INSERT INTO lottery_cycles(ends_at, started_at, closed) VALUES (?,?,0)",
                (now + 7 * 86400, now),
            )

def get_or_create_user(user_id: int, username: str | None, first_name: str | None):
    now = int(time.time())
    with get_db() as db:
        u = db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if u:
            # keep profile fresh
            db.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?", (username, first_name, user_id))
            return dict(u)
        db.execute(
            "INSERT INTO users(user_id, username, first_name, created_at) VALUES (?,?,?,?)",
            (user_id, username, first_name, now),
        )
        return dict(db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone())

def set_lang(user_id: int, lang: str):
    with get_db() as db:
        db.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, user_id))

def add_tickets(user_id: int, amount: int):
    with get_db() as db:
        db.execute("UPDATE users SET tickets=tickets+? WHERE user_id=?", (amount, user_id))

def get_user(user_id: int):
    with get_db() as db:
        u = db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return dict(u) if u else None

def top_tickets(limit: int = 5):
    with get_db() as db:
        rows = db.execute(
            "SELECT user_id, tickets FROM users ORDER BY tickets DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

def add_donation(user_id: int, amount: float, currency: str):
    import time
    ts = int(time.time())
    with get_db() as db:
        db.execute("INSERT INTO donations(user_id, amount, currency, ts) VALUES (?,?,?,?)", (user_id, amount, currency, ts))
        if currency == "XTR":
            db.execute("UPDATE users SET donated_xtr=donated_xtr+?, donated_total=donated_total+? WHERE user_id=?", (int(amount), amount, user_id))
        elif currency == "UAH":
            db.execute("UPDATE users SET donated_uah=donated_uah+?, donated_total=donated_total+? WHERE user_id=?", (amount, amount, user_id))
        elif currency == "USD":
            db.execute("UPDATE users SET donated_usd=donated_usd+?, donated_total=donated_total+? WHERE user_id=?", (amount, amount, user_id))

def top_donors(limit: int = 5):
    with get_db() as db:
        rows = db.execute(
            "SELECT user_id, donated_total, donated_xtr, donated_uah, donated_usd "
            "FROM users ORDER BY donated_total DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
        db.execute("""
        CREATE TABLE IF NOT EXISTS referral_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            link TEXT,
            reward_stars INTEGER DEFAULT 1,
            active INTEGER DEFAULT 1
        )
        """)

        db.execute("""
        CREATE TABLE IF NOT EXISTS referral_task_logs (
            user_id INTEGER,
            task_id INTEGER,
            completed INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, task_id)
        )
        """)
