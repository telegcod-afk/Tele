import asyncio
import json
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio

from database import get_pool
from utils.media_sender import deliver_one, safe_copy_from_storage, media_message_id

router = Router()

PAGE_SIZE = 10
CHANGE_PAGE_COOLDOWN = 3.0
_last_page = {}


def _caption(code: str, index: int, total: int, media: dict) -> str:
    watermark = media.get("caption") or media.get("watermark")
    if watermark:
        return str(watermark)
    return (
        f"🔑 {code}-M{index:03d}\n"
        f"🤖 @Telecodrobot\n"
        f"📦 Media {index}/{total}"
    )


def _page_kb(code: str, page_no: int, pages: int):
    nav = []
    if page_no > 1:
        nav.append(("⬅️ Prev", f"page:{code}:{page_no-1}"))
    nav.append((f"📄 {page_no}/{pages}", f"page:{code}:{page_no}"))
    if page_no < pages:
        nav.append(("Next ➡️", f"page:{code}:{page_no+1}"))

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t, callback_data=d) for t, d in nav],
            [
                InlineKeyboardButton(text="👍 Like", callback_data=f"like:{code}"),
                InlineKeyboardButton(text="👎 No Like", callback_data=f"dislike:{code}"),
            ],
            [
                InlineKeyboardButton(text="🛍 Marketplace", callback_data="marketplace"),
                InlineKeyboardButton(text="🔎 Cari Code", callback_data="search_code"),
            ],
        ]
    )


async def _load(code: str):
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT *
        FROM files
        WHERE lower(code)=lower($1)
        LIMIT 1
        """,
        code,
    )
    if not row:
        return None, []

    data = dict(row)
    raw = data.get("media") or data.get("medias") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = []
    if not isinstance(raw, list):
        raw = []

    return data, [dict(x) if not isinstance(x, dict) else x for x in raw]


def _album_items(items, code, offset, total):
    result = []
    for i, m in enumerate(items, start=offset + 1):
        fid = m.get("file_id")
        typ = str(m.get("file_type") or m.get("type") or "").lower()
        if not fid:
            return None
        cap = _caption(code, i, total, m)
        if typ in {"photo", "image"}:
            result.append(InputMediaPhoto(media=fid, caption=cap))
        elif typ == "video":
            result.append(InputMediaVideo(media=fid, caption=cap))
        else:
            return None
    return result


async def send_page(message, code: str, page_no: int = 1):
    data, medias = await _load(code)
    if not data:
        await message.answer("❌ Code tidak ditemukan.")
        return False

    total = len(medias)
    if total == 0:
        await message.answer("❌ Tidak ada media pada Code ini.")
        return False

    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page_no = max(1, min(int(page_no), pages))
    start = (page_no - 1) * PAGE_SIZE
    items = medias[start:start + PAGE_SIZE]

    # Preferred: one Telegram album/bubble for photo/video pages.
    album = _album_items(items, code, start, total)
    if album:
        try:
            await message.bot.send_media_group(
                chat_id=message.chat.id,
                media=album,
            )
            await message.answer(
                f"📄 <b>Page {page_no}/{pages}</b> • {len(items)} media",
                parse_mode="HTML",
                reply_markup=_page_kb(code, page_no, pages),
            )
            return True
        except Exception:
            pass

    # Durable fallback: copy each stored/source message, still sequential.
    sent = 0
    for idx, m in enumerate(items, start=start + 1):
        result = await deliver_one(
            message.bot,
            message.chat.id,
            m,
            caption=_caption(code, idx, total, m),
        )
        if result:
            sent += 1
        await asyncio.sleep(0.35)

    await message.answer(
        f"📄 <b>Page {page_no}/{pages}</b> • {sent}/{len(items)} media",
        parse_mode="HTML",
        reply_markup=_page_kb(code, page_no, pages),
    )
    return sent > 0


@router.callback_query(F.data.startswith("page:"))
async def page_handler(call: CallbackQuery):
    parts = call.data.split(":", 2)
    if len(parts) != 3:
        await call.answer("Invalid page.", show_alert=True)
        return

    code, page_no = parts[1], int(parts[2])
    key = (call.from_user.id, code)
    now = asyncio.get_running_loop().time()
    if now - _last_page.get(key, 0) < CHANGE_PAGE_COOLDOWN:
        await call.answer("⏳ Tunggu sebentar...", show_alert=True)
        return

    _last_page[key] = now
    await call.answer()
    # Immediate localized loading state masks DB/media lookup latency.
    try:
        pool = await get_pool()
        lang = (await pool.fetchval(
            "SELECT language FROM users WHERE user_id=$1", call.from_user.id
        ) or "id")
    except Exception:
        lang = "id"
    loading = {
        "id": "🔎 <b>Mencari Media Code...</b>\n\n⏳ Mohon tunggu sebentar...",
        "en": "🔎 <b>Searching Code Media...</b>\n\n⏳ Please wait a moment...",
        "zh": "🔎 <b>正在查找 Code 媒体...</b>\n\n⏳ 请稍候...",
    }.get(lang, "🔎 <b>Mencari Media Code...</b>\n\n⏳ Mohon tunggu sebentar...")
    try:
        await call.message.edit_text(loading, parse_mode="HTML")
    except Exception:
        pass
    await send_page(call.message, code, page_no)
