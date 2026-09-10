from __future__ import annotations
import logging, uuid
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from database import get_pool
from utils.points import get_points, checkin, fmt_points

router=Router(); logger=logging.getLogger(__name__)
PACKAGES=[(2000,2000),(5000,5000),(10000,10000),(20000,20000),(50000,50000)]

def menu_kb(lang):
    labels={"id":("📅 Cek In Harian","💳 Buy Poin","📖 Kegunaan Poin","⬅️ Kembali"),"en":("📅 Daily Check-in","💳 Buy Points","📖 How Points Work","⬅️ Back"),"zh":("📅 每日签到","💳 购买积分","📖 积分说明","⬅️ 返回")}
    a,b,c,d=labels.get(lang,labels['id'])
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=a,callback_data='points_checkin')],[InlineKeyboardButton(text=b,callback_data='points_buy')],[InlineKeyboardButton(text=c,callback_data='points_info')],[InlineKeyboardButton(text=d,callback_data='home')]])

async def lang(uid):
    pool=await get_pool(); return (await pool.fetchval('SELECT language FROM users WHERE user_id=$1',uid)) or 'id'

async def render(call):
    uid=call.from_user.id; l=await lang(uid); pts=await get_points(await get_pool(),uid)
    text={"id":f"⭐ <b>POIN KAMU</b>\\n\\nTotal Poin: <b>{fmt_points(pts)}</b>\\n\\nPoin dipakai untuk membuka code dan mengirim media.\\n\\n📅 Cek In • dapat poin harian\\n📤 Upload • 50 media = +10 poin, 100 media = +20 poin\\n📤 Share • tidak dapat poin langsung\\n👤 Orang membuka code yang kamu share • +1 poin\\n📦 Buka media FREE • 1.20 poin/media\\n💰 Code PAID • butuh poin sebesar harga code.","en":f"⭐ <b>YOUR POINTS</b>\\n\\nTotal Points: <b>{fmt_points(pts)}</b>\\n\\nPoints are used to open codes and deliver media.\\n\\n📅 Check-in • daily points\\n📤 Upload • 50 media = +10 points, 100 media = +20 points\\n📤 Share • no direct reward\\n👤 Someone opens your shared code • +1 point\\n📦 FREE media • 1.20 points/media\\n💰 PAID code • requires points equal to its price.","zh":f"⭐ <b>你的积分</b>\\n\\n总积分：<b>{fmt_points(pts)}</b>\\n\\n积分用于打开代码和发送媒体。\\n\\n📅 签到 • 每日获得积分\\n📤 上传 • 50 个媒体 = +10 积分，100 个媒体 = +20 积分\\n📤 分享 • 分享本身不奖励\\n👤 他人打开你分享的代码 • +1积分\\n📦 免费媒体 • 每个媒体消耗1.20积分\\n💰 付费代码 • 需要等于代码价格的积分。"}
    await call.message.edit_text(text[l],parse_mode='HTML',reply_markup=menu_kb(l)); await call.answer()

@router.callback_query(F.data=='points')
async def points_menu(call): await render(call)

@router.callback_query(F.data=='points_info')
async def points_info(call): await render(call)

@router.callback_query(F.data=='points_checkin')
async def points_checkin(call):
    await call.answer('⏳')
    uid=call.from_user.id; pool=await get_pool(); result, status=await checkin(pool,uid); l=await lang(uid)
    if status=='already': msg={'id':'⚠️ Kamu sudah check-in hari ini.','en':'⚠️ You already checked in today.','zh':'⚠️ 今天已经签到。'}[l]
    elif status=='user_not_found': msg='❌ User tidak ditemukan.'
    else:
        day=int(status); reward=['0.5','1','1','1','1.5','2','3'][day-1]
        msg={'id':f'✅ <b>Check-in berhasil!</b>\\n\\nHari ke-{day}: <b>+{reward} poin</b>\\nTotal: <b>{fmt_points(result)}</b>','en':f'✅ <b>Check-in complete!</b>\\n\\nDay {day}: <b>+{reward} points</b>\\nTotal: <b>{fmt_points(result)}</b>','zh':f'✅ <b>签到成功！</b>\\n\\n第 {day} 天：<b>+{reward} 积分</b>\\n总计：<b>{fmt_points(result)}</b>'}[l]
    await call.message.edit_text(msg,parse_mode='HTML',reply_markup=menu_kb(l))

@router.callback_query(F.data=='points_buy')
async def points_buy(call):
    l=await lang(call.from_user.id)
    title={'id':'💳 <b>BUY POIN</b>','en':'💳 <b>BUY POINTS</b>','zh':'💳 <b>购买积分</b>'}[l]
    desc={'id':'Pilih paket poin yang kamu butuhkan.','en':'Choose the points package you need.','zh':'选择需要的积分套餐。'}[l]
    one={'id':'1 poin = Rp1','en':'1 point = Rp1','zh':'1 积分 = Rp1'}[l]
    back={'id':'⬅️ Kembali','en':'⬅️ Back','zh':'⬅️ 返回'}[l]
    rows=[]
    for pts,amt in PACKAGES:
        unit={'id':'Poin','en':'Points','zh':'积分'}[l]
        rows.append([InlineKeyboardButton(text=f'⭐ {pts:,} {unit}  •  Rp {amt:,}'.replace(',','.'),callback_data=f'points_pkg:{pts}')])
    rows.append([InlineKeyboardButton(text=back,callback_data='points')])
    await call.message.edit_text(f'{title}\n\n{desc}\n\n<b>{one}</b>',parse_mode='HTML',reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()

@router.callback_query(F.data.startswith('points_pkg:'))
async def points_pkg(call):
    try: pts=int(call.data.split(':',1)[1])
    except ValueError: return await call.answer('❌ Invalid package.',show_alert=True)
    if pts not in dict(PACKAGES): return await call.answer('❌ Paket tidak valid.',show_alert=True)
    from handlers.pay import create_points_payment
    return await create_points_payment(call,pts)

async def settle(order_id:str):
    pool=await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row=await conn.fetchrow('SELECT * FROM point_orders WHERE order_id=$1 FOR UPDATE',order_id)
            if not row: return False
            if str(row['status']).lower()=='paid': return True
            await conn.execute("UPDATE point_orders SET status='paid',paid_at=NOW(),updated_at=NOW() WHERE id=$1",row['id'])
            ref=f'points_purchase:{row["id"]}'
            bal=await conn.fetchval("SELECT points FROM users WHERE user_id=$1 FOR UPDATE",row['user_id'])
            new=bal+row['points']
            await conn.execute('UPDATE users SET points=$1,updated_at=NOW() WHERE user_id=$2',new,row['user_id'])
            await conn.execute("INSERT INTO point_transactions(user_id,amount,balance_after,type,reference,description) VALUES($1,$2,$3,'purchase',$4,$5) ON CONFLICT(reference) DO NOTHING",row['user_id'],row['points'],new,ref,f'Buy {row["points"]} points')
            return True

# INTERNAL: routed centrally by handlers.pay
async def points_check(call):
    await call.answer('⏳ Mengecek...'); order=call.data.split(':',1)[1]; pool=await get_pool(); row=await pool.fetchrow('SELECT * FROM point_orders WHERE order_id=$1 AND user_id=$2',order,call.from_user.id)
    if not row: return await call.message.answer('❌ Order tidak ditemukan.')
    if str(row['status']).lower()=='paid': return await call.message.answer('✅ Poin sudah ditambahkan.')
    provider=str(row.get("provider") or "cashi").lower()
    if provider=="bayargg":
        from utils.bayargg import BayarGG
        result=await BayarGG.check_payment(order)
    else:
        result=await Cashi.check_payment(order)
    status=str((result or {}).get('status') or '').lower()
    if status in {'paid','success','settled','completed','completed_payment','success_payment','settlement'}:
        await settle(order); pts=await get_points(pool,call.from_user.id); return await call.message.answer(f'✅ <b>Pembayaran berhasil!</b>\\n\\n⭐ +{fmt_points(row["points"])} poin\\n⭐ Total: <b>{fmt_points(pts)}</b>',parse_mode='HTML')
    return await call.answer('⏳ Belum terkonfirmasi.',show_alert=True)
