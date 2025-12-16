import sqlite3
from contextlib import contextmanager
from typing import Iterator
from config import DB_PATH


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.executescript(
            """
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS referrals (
                user_id INTEGER PRIMARY KEY,
                ref1 INTEGER,
                ref2 INTEGER,
                ref3 INTEGER
            );

            CREATE TABLE IF NOT EXISTS vip (
                user_id INTEGER PRIMARY KEY,
                vip_until INTEGER
            );

            CREATE TABLE IF NOT EXISTS balances (
                user_id INTEGER PRIMARY KEY,
                tickets INTEGER DEFAULT 0,
                ref_earn_stars REAL DEFAULT 0,
                total_spent_stars REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS ads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER,
                text TEXT,
                url TEXT,
                status TEXT DEFAULT 'pending',
                created_at INTEGER,
                approved_at INTEGER,
                last_posted_at INTEGER DEFAULT 0,
                post_every_min INTEGER DEFAULT 720
            );

            CREATE TABLE IF NOT EXISTS lottery_round (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT DEFAULT 'open',
                jackpot_tickets INTEGER DEFAULT 0,
                created_at INTEGER,
                closed_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS lottery_entries (
                round_id INTEGER,
                user_id INTEGER,
                tickets INTEGER,
                created_at INTEGER
            );
            """
        )
