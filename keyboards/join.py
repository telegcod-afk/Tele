from urllib.parse import quote
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils.force_sub import CHANNELS

def join_kb(bot_username: str | None = None, user_id: int | None = None, lang: str = "id"):
    rows = []
    for idx, channel in enumerate(CHANNELS, 1):
        name = (
            "Channel Update" if idx == 1 else "Saluran Backup"
        ) if lang == "id" else (
            "Update Channel" if idx == 1 else "Backup Channel"
        )
        rows.append([InlineKeyboardButton(text=f"📢 {name}", url=channel["url"])])

    rows.append([InlineKeyboardButton(
        text="✅ Saya Sudah Join" if lang == "id" else "✅ I Joined",
        callback_data="check_sub"
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)
