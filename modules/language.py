from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from locales import LANGS
from db import set_lang

def lang_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇺🇦 Українська", callback_data="lang:ua")],
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang:en")],
        [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang:ru")],
    ])

def apply_lang_choice(user_id: int, lang: str):
    if lang not in LANGS:
        lang = "ua"
    set_lang(user_id, lang)
    return lang
