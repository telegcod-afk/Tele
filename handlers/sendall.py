"""Safe paginated Send All delivery.
Each batch contains at most 10 media, followed by a manual Continue/Stop choice.
"""
import asyncio, json, logging
from aiogram import Router, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramRetryAfter
from utils.media_sender import safe_copy_from_storage, safe_copy_from_source
from utils.share_unlock import telegram_setting
from utils.points import get_points, charge_points, MEDIA_COST, fmt_points
from utils.user_lang import get_user_language
from utils.language import media_watermark

logger = logging.getLogger(__name__)
SEND_INTERVAL = 2.0
BATCH_SIZE = 10

def final_keyboard(code, lang="id"):
    idn, zh = lang == "id", lang == "zh"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👍 Suka" if idn else "👍 Like" if not zh else "👍 喜欢", callback_data=f"like:{code}"),
         InlineKeyboardButton(text="👎 Tidak Suka" if idn else "👎 Dislike" if not zh else "👎 不喜欢", callback_data=f"dislike:{code}")],
        [InlineKeyboardButton(text="❤️ Favorit" if idn else "❤️ Favorite" if not zh else "❤️ 收藏", callback_data=f"favorite:{code}"),
         InlineKeyboardButton(text="⭐ Rating" if not zh else "⭐ 评分", callback_data=f"rating:{code}")],
        [InlineKeyboardButton(text="🛍️ Marketplace" if not zh else "🛍️ 市场", callback_data="marketplace"),
         InlineKeyboardButton(text="🔍 Cari Code" if idn else "🔍 Search Code" if not zh else "🔍 搜索代码", callback_data="search_code")],
    ])

def continue_keyboard(code, next_offset, lang="id"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("▶️ Lanjut Kirim" if lang == "id" else "▶️ Continue" if lang == "en" else "▶️ 继续发送"), callback_data=f"allnext:{code}:{next_offset}")],
        [InlineKeyboardButton(text=("⛔ Stop Kirim" if lang == "id" else "⛔ Stop" if lang == "en" else "⛔ 停止发送"), callback_data=f"allstop:{code}")],
    ])

async def send_all(bot, chat_id, code, file, user_level, offset=0, status_message=None):
    media = file.get("media")
    if isinstance(media, str):
        try: media = json.loads(media)
        except Exception: return False
    if not isinstance(media, list) or not media: return False

    total = len(media)
    offset = max(0, min(int(offset), total))
    if offset >= total:
        lang = await get_user_language(chat_id)
        msg = {"id":"✅ <b>Semua media sudah terkirim.</b>","en":"✅ <b>All media have been sent.</b>","zh":"✅ <b>所有媒体已发送。</b>"}.get(lang,"✅ <b>Semua media sudah terkirim.</b>")
        if status_message:
            try: await status_message.edit_text(msg, parse_mode="HTML", reply_markup=final_keyboard(code, lang))
            except Exception: pass
        else:
            await bot.send_message(chat_id, msg, parse_mode="HTML", reply_markup=final_keyboard(code, lang))
        return True

    send_interval = await telegram_setting("telegram_user_send_delay", SEND_INTERVAL)
    batch_end = min(offset + BATCH_SIZE, total)
    batch = media[offset:batch_end]

    # FREE files consume 1.20 points per media. Charge the batch atomically
    # before sending to avoid races when users press Continue quickly.
    owner_access = int(file.get("owner_id") or 0) == int(chat_id)
    pool = await _get_pool()
    paid_access = bool(await pool.fetchval("SELECT EXISTS(SELECT 1 FROM file_purchases WHERE user_id=$1 AND (LOWER(TRIM(COALESCE(file_code,'')))=LOWER(TRIM($2)) OR LOWER(TRIM(COALESCE(code,'')))=LOWER(TRIM($2))) AND status='paid')",chat_id,code))
    point_unlock_access = bool(await pool.fetchval("SELECT EXISTS(SELECT 1 FROM point_code_unlocks WHERE user_id=$1 AND LOWER(TRIM(code))=LOWER(TRIM($2)))",chat_id,code))
    if bool(file.get("is_paid")):
        privileged_user = owner_access or paid_access or point_unlock_access
        if not privileged_user:
            from handlers.pay import paid_unlock_keyboard
            lang=await get_user_language(chat_id); price=int(file.get("price") or 0)
            text={"id":f"🔒 <b>FILE BERBAYAR</b>\n\n💰 Harga: <b>Rp {price:,}</b>\n\nPilih cara membuka file:","en":f"🔒 <b>PAID FILE</b>\n\n💰 Price: <b>Rp {price:,}</b>\n\nChoose how to unlock this file:","zh":f"🔒 <b>付费文件</b>\n\n💰 价格：<b>Rp {price:,}</b>\n\n请选择解锁方式："}
            await bot.send_message(chat_id,text.get(lang,text["id"]),parse_mode="HTML",reply_markup=paid_unlock_keyboard(code,lang)); return False
    else:
        privileged_user = owner_access or user_level in ("vip", "vvip")
    if not bool(file.get("is_paid")) and not privileged_user:
        charge_count = len([x for x in batch if isinstance(x, dict) and x.get("file_id")])
        if charge_count:
            try:
                await charge_points(await _get_pool(), chat_id, MEDIA_COST*charge_count, "media_open", f"all:{chat_id}:{code}:{offset}", f"Open all batch {offset}-{batch_end} of {code}")
            except Exception:
                points=await get_points(await _get_pool(),chat_id)
                lang=await get_user_language(chat_id)
                text={"id":f"⭐ <b>POIN TIDAK CUKUP</b>\n\nBatch ini membutuhkan <b>{fmt_points(MEDIA_COST*charge_count)} poin</b>.\nPoin kamu: <b>{fmt_points(points)}</b>.","en":f"⭐ <b>NOT ENOUGH POINTS</b>\n\nThis batch needs <b>{fmt_points(MEDIA_COST*charge_count)} points</b>.\nYour points: <b>{fmt_points(points)}</b>.","zh":f"⭐ <b>积分不足</b>\n\n此批次需要 <b>{fmt_points(MEDIA_COST*charge_count)} 积分</b>。\n你的积分：<b>{fmt_points(points)}</b>。"}
                await bot.send_message(chat_id,text.get(lang,text["id"]),parse_mode="HTML")
                return False
    me = await bot.get_me()
    bot_name = f"@{me.username}" if me.username else "@bot"
    lang = await get_user_language(chat_id)

    if status_message is None:
        status_message = await bot.send_message(
            chat_id,
            (f"⏳ <b>Send All</b> • Media {offset+1}-{batch_end}/{total}\n🛡️ Delay {send_interval:g}s/media" if lang == "en" else f"⏳ <b>全部发送</b> • 媒体 {offset+1}-{batch_end}/{total}\n🛡️ 每个媒体间隔 {send_interval:g} 秒" if lang == "zh" else f"⏳ <b>Kirim Semua</b> • Media {offset+1}-{batch_end}/{total}\n🛡️ Jeda {send_interval:g} detik/media"),
            parse_mode="HTML",
        )
    else:
        try:
            await status_message.edit_text(
                (f"⏳ <b>Send All</b> • Media {offset+1}-{batch_end}/{total}\n🛡️ Delay {send_interval:g}s/media" if lang == "en" else f"⏳ <b>全部发送</b> • 媒体 {offset+1}-{batch_end}/{total}\n🛡️ 每个媒体间隔 {send_interval:g} 秒" if lang == "zh" else f"⏳ <b>Kirim Semua</b> • Media {offset+1}-{batch_end}/{total}\n🛡️ Jeda {send_interval:g} detik"),
                parse_mode="HTML")
        except Exception: pass

    success = 0
    failed = 0
    share_media = file.get("share_media", True)
    protect = not bool(share_media)

    for pos, item in enumerate(batch, start=offset + 1):
        if not isinstance(item, dict):
            failed += 1
            continue
        message_id = item.get("message_id")
        storage_message_id = (
            item.get("storage_message_id")
            or item.get("channel_message_id")
            or (message_id if not item.get("source_chat_id") else None)
        )
        if not message_id and not storage_message_id:
            failed += 1
            continue

        # IMPORTANT: metadata is attached to the media itself, not sent as a
        # separate bubble. When the media is forwarded/shared, its caption
        # travels with it.
        media_code = f"{code}-m{pos:03d}"
        media_caption = media_watermark(lang, media_code, bot_name, pos, total)

        # Stored files are intentionally delivered from the Storage Channel.
        # The storage message_id is the durable reference that survives bot
        # replacement. file_id is only a fallback when Telegram cannot copy
        # the stored message.
        storage_message_id = (
            item.get("storage_message_id")
            or item.get("channel_message_id")
            or (message_id if not item.get("source_chat_id") else None)
        )
        source_chat_id = item.get("source_chat_id")
        fid = item.get("file_id")
        typ = str(item.get("type") or "document").lower()

        try:
            try:
                await bot.send_chat_action(chat_id=chat_id, action="typing")
            except Exception:
                pass

            result = None
            if source_chat_id and not storage_message_id:
                # FREE/non-storage media: original user message.
                result = await safe_copy_from_source(
                    bot, chat_id, source_chat_id, message_id,
                    protect_content=protect, delay=0.0,
                    caption=media_caption
                )
            elif storage_message_id:
                # PAID/stored media: Storage Channel is the primary source.
                result = await safe_copy_from_storage(
                    bot, chat_id, storage_message_id,
                    protect_content=protect, delay=0.0,
                    caption=media_caption
                )

            # file_id is only a fallback, never the primary storage route.
            if result is None and fid:
                if typ == "photo":
                    result = await bot.send_photo(
                        chat_id, fid, caption=media_caption,
                        parse_mode="HTML", protect_content=protect)
                elif typ == "video":
                    result = await bot.send_video(
                        chat_id, fid, caption=media_caption,
                        parse_mode="HTML", protect_content=protect)
                elif typ == "audio":
                    result = await bot.send_audio(
                        chat_id, fid, caption=media_caption,
                        parse_mode="HTML", protect_content=protect)
                elif typ == "voice":
                    result = await bot.send_voice(
                        chat_id, fid, caption=media_caption,
                        parse_mode="HTML", protect_content=protect)
                else:
                    result = await bot.send_document(
                        chat_id, fid, caption=media_caption,
                        parse_mode="HTML", protect_content=protect)

            if result is not None:
                success += 1
            else:
                failed += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(max(float(exc.retry_after), 1.0) + 0.5)
            try:
                if fid:
                    if typ == "photo":
                        result = await bot.send_photo(chat_id, fid, caption=media_caption, parse_mode="HTML", protect_content=protect)
                    elif typ == "video":
                        result = await bot.send_video(chat_id, fid, caption=media_caption, parse_mode="HTML", protect_content=protect)
                    elif typ == "audio":
                        result = await bot.send_audio(chat_id, fid, caption=media_caption, parse_mode="HTML", protect_content=protect)
                    else:
                        result = await bot.send_document(chat_id, fid, caption=media_caption, parse_mode="HTML", protect_content=protect)
                    success += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
        except Exception:
            logger.exception("OPEN ALL MEDIA ERROR | code=%s media=%s", code, pos)
            failed += 1


        if pos < batch_end:
            await asyncio.sleep(max(float(send_interval), 2.0))

    # Refund failed/invalid media so only successfully opened media costs points.
    if not bool(file.get("is_paid")) and not privileged_user and failed:
        try:
            from utils.points import add_points
            await add_points(await _get_pool(), chat_id, MEDIA_COST * failed, "media_refund", f"refund:{chat_id}:{code}:{offset}", f"Refund {failed} failed media from {code}")
        except Exception:
            logger.exception("POINT REFUND ERROR | user=%s code=%s offset=%s",chat_id,code,offset)

    remaining = total - batch_end
    if remaining > 0:
        text = (
            (f"📦 <b>Batch complete: {offset+1}-{batch_end}/{total}</b>\n✅ Sent: {success} • ⚠️ Failed: {failed}\n\n⏭️ <b>{remaining}</b> media remaining.\nChoose <b>Continue</b> or <b>Stop</b>." if lang == "en" else f"📦 <b>批次完成：{offset+1}-{batch_end}/{total}</b>\n✅ 成功：{success} • ⚠️ 失败：{failed}\n\n⏭️ 剩余 <b>{remaining}</b> 个媒体。\n请选择 <b>继续发送</b> 或 <b>停止</b>。" if lang == "zh" else f"📦 <b>Batch selesai: {offset+1}-{batch_end}/{total}</b>\n✅ Berhasil: {success} • ⚠️ Gagal: {failed}\n\n⏭️ Masih ada <b>{remaining}</b> media.\nPilih <b>Lanjut Kirim</b> atau <b>Stop</b>.")
        )
        try:
            await status_message.edit_text(text, parse_mode="HTML",
                                           reply_markup=continue_keyboard(code, batch_end, lang))
        except Exception:
            await bot.send_message(chat_id, text, parse_mode="HTML",
                                   reply_markup=continue_keyboard(code, batch_end, lang))
        return success > 0

    final_text = (f"✅ <b>Send All completed</b>\n\n📦 {success}/{total} media sent" if lang == "en" else f"✅ <b>全部发送完成</b>\n\n📦 已发送 {success}/{total} 个媒体" if lang == "zh" else f"✅ <b>Kirim Semua selesai</b>\n\n📦 {success}/{total} media terkirim")
    if failed: final_text += (f"\n⚠️ Failed: {failed}" if lang == "en" else f"\n⚠️ 失败：{failed}" if lang == "zh" else f"\n⚠️ Gagal: {failed}")
    final_text += ("\n\nAll media have been sent." if lang == "en" else "\n\n所有媒体已发送。" if lang == "zh" else "\n\nSemua media sudah dikirim.")
    try:
        await status_message.edit_text(final_text, parse_mode="HTML",
                                       reply_markup=final_keyboard(code, lang))
    except Exception:
        await bot.send_message(chat_id, final_text, parse_mode="HTML",
                               reply_markup=final_keyboard(code, lang))
    return success > 0

async def _get_pool():
    from database import get_pool
    return await get_pool()

async def _load_file(code):
    from database import get_pool
    pool = await get_pool()
    return await pool.fetchrow("SELECT * FROM files WHERE code=$1 LIMIT 1", code)

async def _can_open(pool, file, user_id):
    from utils.user import get_user_status
    level = await get_user_status(pool, user_id)
    if int(file.get("owner_id") or 0) == int(user_id) or level in ("vip","vvip"):
        return True, level
    paid = await pool.fetchval("""SELECT EXISTS(
        SELECT 1 FROM file_purchases WHERE user_id=$1
          AND (LOWER(TRIM(COALESCE(file_code, ''))) = LOWER(TRIM($2))
               OR LOWER(TRIM(COALESCE(code, ''))) = LOWER(TRIM($2)))
          AND status='paid')""",
        user_id, file["code"])
    creator = await pool.fetchval("""SELECT COALESCE(is_creator,FALSE)
        AND COALESCE(creator_status,'none')='approved' FROM users WHERE user_id=$1""", user_id)
    if not file.get("is_paid"):
        pts = await get_points(pool,user_id)
        media_count = int(file.get("media_count") or len(file.get("media") or []))
        return bool(pts >= media_count * 0 + MEDIA_COST), level
    return bool(paid or creator), level

router = Router()

@router.callback_query(F.data.startswith("allnext:"))
async def all_next(call):
    await call.answer("⏳ Melanjutkan pengiriman...")
    _, code, offset = call.data.split(":", 2)
    file = await _load_file(code)
    if not file: return await call.answer("❌ Code tidak ditemukan.", show_alert=True)
    from database import get_pool
    pool = await get_pool()
    allowed, level = await _can_open(pool, file, call.from_user.id)
    if not allowed:
        return await call.answer("❌ Akses tidak tersedia.", show_alert=True)
    await send_all(call.bot, call.message.chat.id, code, file, level, int(offset), call.message)

@router.callback_query(F.data.startswith("allstop:"))
async def all_stop(call):
    lang = await get_user_language(call.from_user.id)
    await call.answer({"id":"⛔ Pengiriman dihentikan.","en":"⛔ Sending stopped.","zh":"⛔ 已停止发送。"}.get(lang,"⛔ Pengiriman dihentikan."))
    code = call.data.split(":",1)[1]
    try:
        await call.message.edit_text(
            f"⛔ <b>{'Send All stopped.' if lang == 'en' else '全部发送已停止。' if lang == 'zh' else 'Send All dihentikan.'}</b>\n\n🔑 <code>{code}</code>",
            parse_mode="HTML", reply_markup=final_keyboard(code, lang))
    except Exception: pass
