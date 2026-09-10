import asyncio
import json
import time
from collections import defaultdict

from aiogram import Router, F
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.types import (
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument
)

from database import get_pool
from config import STORAGE_CHANNEL_ID
from utils.points import get_points, charge_points, MEDIA_COST, fmt_points
from utils.user_lang import get_user_language
from utils.language import media_watermark


router = Router()

PAGE_SIZE = 10

SAME_PAGE_COOLDOWN = 3600
CHANGE_PAGE_COOLDOWN = 10

USER_LOCK = defaultdict(lambda: asyncio.Lock())

PAGE_CACHE = {}
PAGE_CHANGE = {}
NAV_CACHE = {}


# =========================
# UTIL
# =========================

async def clear_cache_loop():

    while True:

        await asyncio.sleep(3600)

        now = time.time()

        for cache in [PAGE_CACHE, PAGE_CHANGE]:

            remove = []

            for key, value in list(cache.items()):

                if now - value[0] > 7200:
                    remove.append(key)

            for key in remove:
                del cache[key]


def clean_file_id(fid):
    return fid.get("file_id") if isinstance(fid, dict) else fid


def normalize_type(ftype):
    return (ftype or "document").lower()


# =========================
# FAVORITE + RATING BUTTON
# =========================

def build_reaction_buttons(code):

    return [
        [
            InlineKeyboardButton(
                text="❤️ Favorite",
                callback_data=f"favorite:{code}"
            ),
            InlineKeyboardButton(
                text="⭐ Rating",
                callback_data=f"rating:{code}"
            )
        ]
    ]


# =========================
# SEND PAGE
# =========================

async def send_page(bot, chat_id, user_id, code, page=1):
    pool = await get_pool()
    file = await pool.fetchrow("SELECT * FROM files WHERE code=$1 LIMIT 1", code)
    if not file:
        return False

    from utils.user import get_user_status
    user_level = await get_user_status(pool, user_id)

    media = file["media"]
    if isinstance(media, str):
        try:
            media = json.loads(media)
        except Exception:
            return False
    if not isinstance(media, list) or not media:
        return False

    creator_access = await pool.fetchval(
        """SELECT COALESCE(is_creator,FALSE) AND COALESCE(creator_status,'none')='approved'
           FROM users WHERE user_id=$1""", user_id) or False
    owner_access = int(file["owner_id"] or 0) == int(user_id)
    purchase_access = await pool.fetchval(
        """SELECT EXISTS(SELECT 1 FROM file_purchases
           WHERE user_id=$1
          AND (LOWER(TRIM(COALESCE(file_code, ''))) = LOWER(TRIM($2))
               OR LOWER(TRIM(COALESCE(code, ''))) = LOWER(TRIM($2)))
          AND status='paid')""",
        user_id, code) or False
    point_unlock_access = bool(await pool.fetchval("SELECT EXISTS(SELECT 1 FROM point_code_unlocks WHERE user_id=$1 AND LOWER(TRIM(code))=LOWER(TRIM($2)))", user_id, file["code"]))
    if bool(file["is_paid"]):
        privileged = bool(owner_access or purchase_access or point_unlock_access)
        if not privileged:
            from handlers.pay import paid_unlock_keyboard
            lang=await get_user_language(user_id); price=int(file.get("price") or 0)
            text={"id":f"🔒 <b>FILE BERBAYAR</b>\n\n🔑 CODE: <code>{code}</code>\n💰 Harga: <b>Rp {price:,}</b>\n\nPilih cara membuka file:","en":f"🔒 <b>PAID FILE</b>\n\n🔑 CODE: <code>{code}</code>\n💰 Price: <b>Rp {price:,}</b>\n\nChoose how to unlock this file:","zh":f"🔒 <b>付费文件</b>\n\n🔑 代码：<code>{code}</code>\n💰 价格：<b>Rp {price:,}</b>\n\n请选择解锁方式："}
            await bot.send_message(chat_id,text.get(lang,text["id"]),parse_mode="HTML",reply_markup=paid_unlock_keyboard(code,lang))
            return False
    else:
        privileged = bool(owner_access or creator_access or user_level in ("vip", "vvip"))

    # FREE files consume 1.20 points per successfully opened media.
    # Require enough points for the whole page before sending the album.
    if not privileged and not bool(file["is_paid"]):
        needed = (len(media[(max(1,int(page))-1)*PAGE_SIZE:max(1,int(page))*PAGE_SIZE]) * MEDIA_COST)
        points = await get_points(pool, user_id)
        if points < needed:
            lang = await get_user_language(user_id)
            text = {
                "id": f"⭐ <b>POIN TIDAK CUKUP</b>\n\nHalaman ini membutuhkan <b>{fmt_points(needed)} poin</b>.\nPoin kamu: <b>{fmt_points(points)}</b>.",
                "en": f"⭐ <b>NOT ENOUGH POINTS</b>\n\nThis page needs <b>{fmt_points(needed)} points</b>.\nYour points: <b>{fmt_points(points)}</b>.",
                "zh": f"⭐ <b>积分不足</b>\n\n此页需要 <b>{fmt_points(needed)} 积分</b>。\n你的积分：<b>{fmt_points(points)}</b>。",
            }
            await bot.send_message(chat_id,text.get(lang,text["id"]),parse_mode="HTML")
            return False

    total_pages = max(1, (len(media) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(int(page), total_pages))
    start = (page - 1) * PAGE_SIZE
    chunk = media[start:start + PAGE_SIZE]

    if not privileged and not bool(file["is_paid"]):
        charge_count = len([x for x in chunk if isinstance(x, dict) and x.get("file_id")])
        if charge_count:
            try:
                await charge_points(pool, user_id, MEDIA_COST * charge_count, "media_open", f"page:{user_id}:{code}:{page}", f"Open page {page} of {code}")
            except Exception:
                lang = await get_user_language(user_id)
                points = await get_points(pool,user_id)
                text={
                    "id": f"⭐ <b>POIN TIDAK CUKUP</b>\n\nPoin kamu: <b>{fmt_points(points)}</b>.",
                    "en": f"⭐ <b>NOT ENOUGH POINTS</b>\n\nYour points: <b>{fmt_points(points)}</b>.",
                    "zh": f"⭐ <b>积分不足</b>\n\n你的积分：<b>{fmt_points(points)}</b>。",
                }
                await bot.send_message(chat_id,text.get(lang,text["id"]),parse_mode="HTML")
                return False

    # Unique view only on first page.
    if page == 1:
        viewed = await pool.fetchrow(
            """INSERT INTO file_views(user_id,file_code) VALUES($1,$2)
               ON CONFLICT(user_id,file_code) DO NOTHING RETURNING user_id""",
            user_id, code)
        if viewed:
            await pool.execute(
                """UPDATE files SET views=COALESCE(views,0)+1,
                   view_count=COALESCE(view_count,0)+1 WHERE code=$1""", code)

    share_media = file["share_media"]
    protect = not bool(True if share_media is None else share_media)

    # Stored media are read from the Storage Channel by message_id.
    # A page contains up to PAGE_SIZE items; each stored message keeps its
    # original Telegram media/file_id and therefore remains usable after the
    # bot itself is replaced.
    from utils.media_sender import safe_copy_from_storage, safe_copy_from_source

    sent_count = 0
    failed_count = 0
    me = await bot.get_me()
    bot_name = f"@{me.username}" if me.username else "@bot"

    # Build ONE Telegram media-group bubble whenever the stored media are
    # album-compatible and have their Storage Channel file_id. The message_id
    # remains the durable Storage Channel reference; file_id is the payload
    # Telegram needs for sendMediaGroup.
    prepared = []
    for idx, item in enumerate(chunk):
        if not isinstance(item, dict):
            continue
        storage_message_id = (
            item.get("storage_message_id")
            or item.get("channel_message_id")
            or (item.get("message_id") if not item.get("source_chat_id") else None)
        )
        fid = clean_file_id(item.get("file_id"))
        typ = normalize_type(item.get("type"))
        position = start + idx + 1
        media_code = f"{code}-m{position:03d}"
        cap = media_watermark(lang, media_code, bot_name, position, len(media))
        prepared.append((item, storage_message_id, fid, typ, cap, position))

    # A media group is possible for photo/video together, or documents/audio
    # of the same kind. Voice/other media are delivered individually.
    album_kind = None
    if prepared and all(x[2] and x[1] for x in prepared):
        types = {x[3] for x in prepared}
        if types <= {"photo", "video"}:
            album_kind = "visual"
        elif types == {"document"}:
            album_kind = "document"
        elif types == {"audio"}:
            album_kind = "audio"

    if album_kind and 2 <= len(prepared) <= 10:
        group = []
        for _, _, fid, typ, cap, _ in prepared:
            if album_kind == "visual":
                group.append(
                    InputMediaPhoto(media=fid, caption=cap, parse_mode="HTML")
                    if typ == "photo" else
                    InputMediaVideo(media=fid, caption=cap, parse_mode="HTML")
                )
            elif album_kind == "document":
                group.append(InputMediaDocument(media=fid, caption=cap, parse_mode="HTML"))
            else:
                # aiogram exposes InputMediaAudio; import lazily to keep the
                # existing imports minimal on installations without audio.
                from aiogram.types import InputMediaAudio
                group.append(InputMediaAudio(media=fid, caption=cap, parse_mode="HTML"))
        try:
            await bot.send_media_group(
                chat_id=chat_id,
                media=group,
                protect_content=protect,
            )
            sent_count = len(group)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(max(float(exc.retry_after), 1.0) + 0.5)
            try:
                await bot.send_media_group(chat_id=chat_id, media=group, protect_content=protect)
                sent_count = len(group)
            except Exception:
                failed_count = len(group)
        except Exception:
            # Fall back to Storage Channel message_id delivery below.
            logger = __import__("logging").getLogger(__name__)
            logger.exception("SEND PAGE MEDIA GROUP ERROR | code=%s page=%s", code, page)
            sent_count = 0

    # Fallback / non-album path: always prefer the durable Storage Channel
    # message_id. FREE/non-storage media use source_chat_id + message_id.
    if sent_count == 0:
        from utils.media_sender import safe_copy_from_storage, safe_copy_from_source
        for item, storage_message_id, fid, typ, cap, _ in prepared:
            try:
                result = None
                source_chat_id = item.get("source_chat_id")
                original_message_id = item.get("message_id")
                if source_chat_id and not storage_message_id:
                    result = await safe_copy_from_source(
                        bot, chat_id, source_chat_id, original_message_id,
                        protect_content=protect, delay=0.0, caption=cap
                    )
                elif storage_message_id:
                    result = await safe_copy_from_storage(
                        bot, chat_id, storage_message_id,
                        protect_content=protect, delay=0.0, caption=cap
                    )
                elif fid:
                    if typ == "photo":
                        result = await bot.send_photo(chat_id, fid, caption=cap, parse_mode="HTML", protect_content=protect)
                    elif typ == "video":
                        result = await bot.send_video(chat_id, fid, caption=cap, parse_mode="HTML", protect_content=protect)
                    elif typ == "audio":
                        result = await bot.send_audio(chat_id, fid, caption=cap, parse_mode="HTML", protect_content=protect)
                    else:
                        result = await bot.send_document(chat_id, fid, caption=cap, parse_mode="HTML", protect_content=protect)
                if result is not None:
                    sent_count += 1
                else:
                    failed_count += 1
            except TelegramRetryAfter as exc:
                await asyncio.sleep(max(float(exc.retry_after), 1.0) + 0.5)
                try:
                    if storage_message_id:
                        result = await safe_copy_from_storage(
                            bot, chat_id, storage_message_id,
                            protect_content=protect, delay=0.0, caption=cap
                        )
                    elif fid:
                        if typ == "photo":
                            result = await bot.send_photo(chat_id, fid, caption=cap, parse_mode="HTML", protect_content=protect)
                        elif typ == "video":
                            result = await bot.send_video(chat_id, fid, caption=cap, parse_mode="HTML", protect_content=protect)
                        else:
                            result = await bot.send_document(chat_id, fid, caption=cap, parse_mode="HTML", protect_content=protect)
                    else:
                        result = None
                    if result is not None:
                        sent_count += 1
                    else:
                        failed_count += 1
                except Exception:
                    failed_count += 1
            except Exception:
                failed_count += 1

            if sent_count < len(prepared):
                await asyncio.sleep(1.0)
    if sent_count == 0:
        return False

    # Compact status bubble: e.g. 1/4 for a 40-media code.
    status_text = {
        "id": f"📦 <b>Page {page}/{total_pages}</b> • <b>{sent_count}/{len(chunk)}</b> media terkirim • Total <b>{len(media)}</b>",
        "en": f"📦 <b>Page {page}/{total_pages}</b> • <b>{sent_count}/{len(chunk)}</b> media sent • Total <b>{len(media)}</b>",
        "zh": f"📦 <b>第 {page}/{total_pages} 页</b> • 已发送 <b>{sent_count}/{len(chunk)}</b> 个媒体 • 共 <b>{len(media)}</b> 个",
    }.get(lang, f"📦 <b>Page {page}/{total_pages}</b> • <b>{sent_count}/{len(chunk)}</b> media terkirim")
    status = await bot.send_message(chat_id, status_text, parse_mode="HTML")

    # Navigation is deliberately not auto-advanced. The next page requires a
    # button press and the handler enforces a 5-second cooldown.
    keyboard = [
        build_page_buttons(code, page, total_pages, lang),
        [
            InlineKeyboardButton(text=("👍 Suka" if lang == "id" else "👍 Like" if lang == "en" else "👍 喜欢"), callback_data=f"like:{code}"),
            InlineKeyboardButton(text=("👎 Tidak Suka" if lang == "id" else "👎 Dislike" if lang == "en" else "👎 不喜欢"), callback_data=f"dislike:{code}"),
        ],
        [
            InlineKeyboardButton(text=("❤️ Favorit" if lang == "id" else "❤️ Favorite" if lang == "en" else "❤️ 收藏"), callback_data=f"favorite:{code}"),
            InlineKeyboardButton(text=("⭐ Rating" if lang != "zh" else "⭐ 评分"), callback_data=f"rating:{code}"),
        ],
        [
            InlineKeyboardButton(text=("🛍️ Marketplace" if lang != "zh" else "🛍️ 市场"), callback_data="marketplace"),
            InlineKeyboardButton(text=("🔍 Cari Code" if lang == "id" else "🔍 Search Code" if lang == "en" else "🔍 搜索代码"), callback_data="search_code"),
        ],
        [InlineKeyboardButton(text=("📤 Kirim Semua" if lang == "id" else "📤 Send All" if lang == "en" else "📤 全部发送"), callback_data=f"all:{code}")],
    ]
    try:
        await status.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    except Exception:
        pass

    NAV_CACHE[(user_id, code)] = status.message_id
    return True


# =========================
# PAGE BUTTONS
# =========================

def build_page_buttons(code: str, page: int, total: int, lang: str = "id"):

    row = []


    # PREV
    if page > 1:

        row.append(
            InlineKeyboardButton(
                text=("⬅️ Sebelumnya" if lang == "id" else "⬅️ Prev" if lang == "en" else "⬅️ 上一页"),
                callback_data=f"page:{code}:{page-1}"
            )
        )


    # NOMOR HALAMAN
    start = max(1, page - 2)
    end = min(total, page + 2)


    for i in range(start, end + 1):

        emoji = (
            "🔲"
            if i == page
            else (
                "▫️"
                if i < page
                else "▪️"
            )
        )


        row.append(
            InlineKeyboardButton(
                text=f"{i}{emoji}",
                callback_data=f"page:{code}:{i}"
            )
        )


    # NEXT
    if page < total:

        row.append(
            InlineKeyboardButton(
                text=("Berikutnya ➡️" if lang == "id" else "Next ➡️" if lang == "en" else "下一页 ➡️"),
                callback_data=f"page:{code}:{page+1}"
            )
        )

    else:

        row.append(
            InlineKeyboardButton(
                text=("✅ SELESAI" if lang == "id" else "✅ END" if lang == "en" else "✅ 结束"),
                callback_data="end_page"
            )
        )


    return row


# =========================
# PAGE HANDLER
# =========================

@router.callback_query(F.data.startswith("page:"))
async def page_handler(call: CallbackQuery):

    user_id = call.from_user.id


    try:

        await call.answer("📂 Loading...")

    except:
        pass


    try:

        _, code, page = call.data.split(":")

        page = int(page)

    except Exception:

        return await call.answer(
            "❌ Data halaman rusak",
            show_alert=True
        )


    async with USER_LOCK[user_id]:

        # Minimum 5 seconds between page requests for the same code.
        nav_key = (user_id, code)
        now = time.time()
        last = PAGE_CHANGE.get(nav_key, 0.0)
        if last and now - last < CHANGE_PAGE_COOLDOWN:
            remaining = CHANGE_PAGE_COOLDOWN - (now - last)
            return await call.answer(
                f"⏳ Tunggu {remaining:.1f} detik sebelum membuka page berikutnya.",
                show_alert=True,
            )
        PAGE_CHANGE[nav_key] = now

        # Deliberate 10-second pacing before changing page to reduce Telegram
        # burst traffic. The callback is already acknowledged above.
        if last:
            await asyncio.sleep(CHANGE_PAGE_COOLDOWN)

        # =========================
        # HAPUS NAV LAMA
        # =========================

        old_nav = NAV_CACHE.get(
            (user_id, code)
        )


        if old_nav:

            try:

                await call.bot.delete_message(
                    call.message.chat.id,
                    old_nav
                )

            except:
                pass


            NAV_CACHE.pop(
                (user_id, code),
                None
            )


        # =========================
        # SEND PAGE
        # =========================

        result = await send_page(
            bot=call.bot,
            chat_id=call.message.chat.id,
            user_id=user_id,
            code=code,
            page=page
        )


        if not result:

            try:

                await call.answer(
                    "❌ Gagal membuka halaman",
                    show_alert=True
                )

            except:
                pass


# =========================
# END PAGE
# =========================

@router.callback_query(F.data == "end_page")
async def end_page(call: CallbackQuery):

    try:

        await call.answer(
            "📄 Semua file sudah ditampilkan.",
            show_alert=True
        )

    except:
        pass
