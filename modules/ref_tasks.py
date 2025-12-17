from db import get_db, add_tickets, add_donation

def add_ref_task(title: str, link: str, reward: int = 1):
    with get_db() as db:
        db.execute(
            "INSERT INTO referral_tasks(title, link, reward_stars) VALUES (?,?,?)",
            (title, link, reward)
        )

def get_active_tasks():
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM referral_tasks WHERE active=1"
        ).fetchall()
        return [dict(r) for r in rows]

def complete_task(user_id: int, task_id: int):
    with get_db() as db:
        r = db.execute(
            "SELECT completed FROM referral_task_logs WHERE user_id=? AND task_id=?",
            (user_id, task_id)
        ).fetchone()
        if r:
            return False

        task = db.execute(
            "SELECT reward_stars FROM referral_tasks WHERE id=?",
            (task_id,)
        ).fetchone()

        if not task:
            return False

        db.execute(
            "INSERT INTO referral_task_logs(user_id, task_id, completed) VALUES (?,?,1)",
            (user_id, task_id)
        )

    # 1 ⭐ = 1 білет (можеш міняти)
    add_tickets(user_id, task["reward_stars"])
    add_donation(user_id, task["reward_stars"], "XTR")
    return True
