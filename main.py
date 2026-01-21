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

# ================= TEMP STORAGE =================
# key = message_id, value = {"items": {produk: qty}}
ORDER_STATE = {}

PRODUK_LIST = {
    "125_FULL": "125 FULL SPEC",
    "125_BIG": "125 BIG BODY",
    "YAMA": "YAMA SPORT",
    "GY6": "GY6 200CC",
    "HAMMER_ARM": "HAMMER ARMOUR",
    "BIG_HAMMER": "BIG HAMMER",
    "TROLI_BESI": "TROLI BESI",
    "TROLI_PLASTIK": "TROLI PLASTIK"
}

# ====== STEP A ======
@bot.on_callback_query(filters.regex("^hantar_detail$"))
async def senarai_produk(client, callback):
    msg_id = callback.message.id
    ORDER_STATE.setdefault(msg_id, {"items": {}})

    items = ORDER_STATE[msg_id]["items"]

    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"produk_{key}")]
        for key, name in PRODUK_LIST.items()
        if key not in items
    ]

    await callback.message.edit_reply_markup(
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await callback.answer()

# ====== STEP B ======
@bot.on_callback_query(filters.regex("^produk_"))
async def pilih_kuantiti(client, callback):
    produk_key = callback.data.replace("produk_", "")
    callback.message._selected_produk = produk_key  # simpan sementara

    keyboard_qty = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1", callback_data=f"qty_{produk_key}_1"),
            InlineKeyboardButton("2", callback_data=f"qty_{produk_key}_2"),
            InlineKeyboardButton("3", callback_data=f"qty_{produk_key}_3"),
        ],
        [
            InlineKeyboardButton("4", callback_data=f"qty_{produk_key}_4"),
            InlineKeyboardButton("5", callback_data=f"qty_{produk_key}_5"),
        ]
    ])

    await callback.message.edit_reply_markup(reply_markup=keyboard_qty)
    await callback.answer("Pilih kuantiti")

# ====== STEP C ======
@bot.on_callback_query(filters.regex("^qty_"))
async def simpan_item(client, callback):
    _, produk_key, qty = callback.data.split("_")
    msg = callback.message
    msg_id = msg.id

    ORDER_STATE.setdefault(msg_id, {"items": {}})
    ORDER_STATE[msg_id]["items"][produk_key] = int(qty)

    # bina caption baru
    base_caption = msg.caption.split("\n\n")[0]
    lines = [base_caption, ""]

    for k, q in ORDER_STATE[msg_id]["items"].items():
        lines.append(f"{PRODUK_LIST[k]} | {q}")

    caption_baru = "\n".join(lines)

    # bina butang produk yang BELUM dipilih
    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"produk_{key}")]
        for key, name in PRODUK_LIST.items()
        if key not in ORDER_STATE[msg_id]["items"]
    ]

    await msg.edit_caption(
        caption=caption_baru,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )

    await callback.answer("Produk ditambah")

# ================= FOTO =================
@bot.on_message(filters.photo & ~filters.bot)
async def handle_photo(client, message):
    tz = pytz.timezone("Asia/Kuala_Lumpur")
    now = datetime.now(tz)

    hari = ["Isnin","Selasa","Rabu","Khamis","Jumaat","Sabtu","Ahad"][now.weekday()]
    tarikh = now.strftime("%-d/%-m/%Y")
    jam = now.strftime("%I:%M%p").lower()

    caption = f"{hari} | {tarikh} | {jam}"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("NAMA PRODUK", callback_data="hantar_detail")]
    ])

    try:
        await message.delete()
    except:
        pass

    await client.send_photo(
        chat_id=message.chat.id,
        photo=message.photo.file_id,
        caption=caption,
        reply_markup=keyboard
    )

if __name__ == "__main__":
    bot.run()

