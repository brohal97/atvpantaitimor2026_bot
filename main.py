import os
from datetime import datetime

import pytz
from pyrogram import Client, filters
from pyrogram.errors import MessageDeleteForbidden, ChatAdminRequired
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ================= ENV =================
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Missing API_ID / API_HASH / BOT_TOKEN in Railway Variables")

# ================= BOT =================
bot = Client(
    "atv_bot_2026",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ================= TEMP STATE (RAM) =================
# key = bot_message_id (mesej gambar yang bot hantar)
# value = {
#   "chat_id": int,
#   "photo_id": str,
#   "base_caption": str,   # hari | tarikh | jam
#   "items": {produk_key: qty_int}
# }
ORDER_STATE = {}

PRODUK_LIST = {
    "125_FULL": "125 FULL SPEC",
    "125_BIG": "125 BIG BODY",
    "YAMA": "YAMA SPORT",
    "GY6": "GY6 200CC",
    "HAMMER_ARM": "HAMMER ARMOUR",
    "BIG_HAMMER": "BIG HAMMER",
    "TROLI_BESI": "TROLI BESI",
    "TROLI_PLASTIK": "TROLI PLASTIK",
}

def build_produk_keyboard(items_dict: dict) -> InlineKeyboardMarkup:
    """Butang produk yang belum dipilih"""
    rows = []
    for key, name in PRODUK_LIST.items():
        if key not in items_dict:
            rows.append([InlineKeyboardButton(name, callback_data=f"produk_{key}")])
    # jika semua dah dipilih, tiada butang (return markup kosong / None di caller)
    return InlineKeyboardMarkup(rows)

def build_qty_keyboard(produk_key: str) -> InlineKeyboardMarkup:
    """Butang kuantiti untuk produk tertentu"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1", callback_data=f"qty_{produk_key}_1"),
            InlineKeyboardButton("2", callback_data=f"qty_{produk_key}_2"),
            InlineKeyboardButton("3", callback_data=f"qty_{produk_key}_3"),
        ],
        [
            InlineKeyboardButton("4", callback_data=f"qty_{produk_key}_4"),
            InlineKeyboardButton("5", callback_data=f"qty_{produk_key}_5"),
        ],
    ])

def build_caption(base_caption: str, items_dict: dict) -> str:
    """Caption akhir: base + senarai item"""
    lines = [base_caption]
    if items_dict:
        lines.append("")  # line kosong
        for k, q in items_dict.items():
            lines.append(f"{PRODUK_LIST.get(k, k)} | {q}")
    return "\n".join(lines)

# ====== STEP A: tekan NAMA PRODUK ======
@bot.on_callback_query(filters.regex("^hantar_detail$"))
async def senarai_produk(client, callback):
    msg_id = callback.message.id
    state = ORDER_STATE.get(msg_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai. Sila hantar gambar semula.", show_alert=True)
        return

    keyboard = build_produk_keyboard(state["items"])
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer()

# ====== STEP B: tekan produk -> keluar kuantiti ======
@bot.on_callback_query(filters.regex("^produk_"))
async def pilih_kuantiti(client, callback):
    msg_id = callback.message.id
    state = ORDER_STATE.get(msg_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai. Sila hantar gambar semula.", show_alert=True)
        return

    produk_key = callback.data.replace("produk_", "")
    await callback.message.edit_reply_markup(reply_markup=build_qty_keyboard(produk_key))
    await callback.answer("Pilih kuantiti")

# ====== STEP C: tekan kuantiti -> PADAM & HANTAR SEMULA ======
@bot.on_callback_query(filters.regex("^qty_"))
async def simpan_qty_repost(client, callback):
    msg = callback.message
    old_msg_id = msg.id

    state = ORDER_STATE.get(old_msg_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai. Sila hantar gambar semula.", show_alert=True)
        return

    # parse qty data: qty_{produk_key}_{n}
    _, produk_key, qty_str = callback.data.split("_", 2)
    qty = int(qty_str)

    # simpan item dipilih
    state["items"][produk_key] = qty

    # caption baru
    caption_baru = build_caption(state["base_caption"], state["items"])

    # keyboard produk balik semula (produk dipilih hilang)
    keyboard_produk = build_produk_keyboard(state["items"])
    reply_markup = keyboard_produk if keyboard_produk.inline_keyboard else None

    # cepat jawab callback dulu (elak loading lama)
    await callback.answer("Dikemaskini")

    # padam mesej lama (mesej bot)
    try:
        await msg.delete()
    except Exception:
        pass

    # hantar semula mesej baru
    new_msg = await client.send_photo(
        chat_id=state["chat_id"],
        photo=state["photo_id"],
        caption=caption_baru,
        reply_markup=reply_markup
    )

    # pindahkan state dari old_msg_id -> new_msg.id
    ORDER_STATE[new_msg.id] = {
        "chat_id": state["chat_id"],
        "photo_id": state["photo_id"],
        "base_caption": state["base_caption"],
        "items": dict(state["items"])  # copy
    }
    # buang state lama
    ORDER_STATE.pop(old_msg_id, None)

# ================= FOTO (staff hantar gambar) =================
@bot.on_message(filters.photo & ~filters.bot)
async def handle_photo(client, message):
    photo_id = message.photo.file_id

    # Masa Malaysia
    tz = pytz.timezone("Asia/Kuala_Lumpur")
    now = datetime.now(tz)

    hari = ["Isnin", "Selasa", "Rabu", "Khamis", "Jumaat", "Sabtu", "Ahad"][now.weekday()]
    tarikh = f"{now.day}/{now.month}/{now.year}"          # 1/1/2026
    jam = now.strftime("%I:%M%p").lower()                 # 06:05pm
    base_caption = f"{hari} | {tarikh} | {jam}"

    keyboard_awal = InlineKeyboardMarkup([
        [InlineKeyboardButton("NAMA PRODUK", callback_data="hantar_detail")]
    ])

    # Padam gambar asal (jika ada permission)
    try:
        await message.delete()
    except (MessageDeleteForbidden, ChatAdminRequired):
        pass
    except Exception:
        pass

    # Repost gambar (mesej bot)
    sent = await client.send_photo(
        chat_id=message.chat.id,
        photo=photo_id,
        caption=base_caption,
        reply_markup=keyboard_awal
    )

    # simpan state untuk mesej bot tersebut
    ORDER_ST_
