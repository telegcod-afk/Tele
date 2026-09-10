from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

from database import get_pool
from handlers.sendall import send_all
from utils.user import get_user_status  # 🔥 TAMBAH INI
from utils.points import get_points, fmt_points
from utils.user_lang import get_user_language

router = Router()


def open_keyboard(code, lang="id"):
    labels = {
        "id": ("📂 Open Page", "📤 Open All"),
        "en": ("📂 Open Page", "📤 Open All"),
        "zh": ("📂 打开页面", "📤 全部打开"),
    }
    page_label, all_label = labels.get(lang, labels["id"])
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=page_label,
                    callback_data=f"page:{code}:1"
                )
            ],
            [
                InlineKeyboardButton(
                    text=all_label,
                    callback_data=f"all:{code}"
                )
            ]
        ]
    )



@router.callback_query(F.data.startswith("open_code:"))
async def open_code_callback(call: CallbackQuery, state=None):
    try:
        await call.answer("⏳ Opening...", show_alert=False)
    except Exception:
        pass
    code = call.data.split(":", 1)[1].strip()
    from handlers.getfile import process_code
    from aiogram.fsm.context import FSMContext
    # Callback has no FSM in this handler unless injected by aiogram; process_code
    # accepts a tiny compatibility state, so use its own helper.
    return await process_code(call.message, code)

@router.callback_query(F.data.startswith("all:"))
async def open_all(call: CallbackQuery):
    """Canonical Open All entry. Delivery/access logic lives in sendall.py."""
    code = call.data.split(":", 1)[1].strip()
    lang = await get_user_language(call.from_user.id)
    ack = {"id":"⏳ Menyiapkan semua media...","en":"⏳ Preparing all media...","zh":"⏳ 正在准备全部媒体……"}.get(lang, "⏳ Menyiapkan semua media...")
    try:
        await call.answer(ack)
    except Exception:
        pass

    pool = await get_pool()
    file = await pool.fetchrow(
        """SELECT * FROM files
           WHERE LOWER(TRIM(code)) = LOWER(TRIM($1))
           LIMIT 1""",
        code,
    )
    if not file:
        try:
            await call.answer(
                {"id":"❌ File tidak ditemukan.","en":"❌ File not found.","zh":"❌ 找不到文件。"}.get(lang, "❌ File tidak ditemukan."),
                show_alert=True,
            )
        except Exception:
            pass
        return

    user_level = await get_user_status(pool, call.from_user.id)
    # send_all.py is the single canonical Open All implementation.
    await send_all(
        bot=call.bot,
        chat_id=call.message.chat.id,
        code=str(file.get("code") or code),
        file=file,
        user_level=user_level,
    )
