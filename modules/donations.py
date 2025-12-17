from db import add_donation, top_donors

def register_donation(user_id: int, amount: float, currency: str):
    add_donation(user_id, amount, currency)

def get_top(limit: int = 5):
    return top_donors(limit)
