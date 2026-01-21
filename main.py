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

# ====== STEP A: tekan NAMA PRODUK ======
@bot.on_callback_query(filters.regex("^hantar_detail$"))
async def pilih_produk(client, callback_query):
    keyboard_produk = InlineKeyboardMarkup([
        [InlineKeyboardButton("ATV 125cc Small Bull", callback_data="produk_125")],
        [InlineKeyboardButton("ATV 200cc DTL", callback_data="produk_200")],
        [InlineKeyboardButton("ATV XBL", callback_data="produk_xbl")],
        [InlineKeyboardButton("Lain-lain", callback_data="produk_lain")]
    ])

    await callback_query.message.edit_reply_markup(reply_markup=keyboard_produk)
    await callback_query.answer()

# ================= FOTO =================
@bot.on_message(filters.photo & ~filters.bot)
async def handle_photo(client, message):
    photo_id = message.photo.file_id
    caption_asal = message.caption or ""

    # Masa Malaysia
    tz = pytz.timezone("Asia/Kuala_Lumpur")
    now = datetime.now(tz)

    hari_map = {
        0: "Isnin",
        1: "Selasa",
        2: "Rabu",
        3: "Khamis",
        4: "Jumaat",
        5: "Sabtu",
        6: "Ahad"
    }
    hari = hari_map[now.weekday()]

    tarikh = now.strftime("%-d/%-m/%Y")
    jam = now.strftime("%I:%M%p").lower()

    cap_masa = f"{hari} | {tarikh} | {jam}"

    if caption_asal.strip():
        caption_baru = f"{caption_asal}\n\n{cap_masa}"
    else:
        caption_baru = cap_masa

    # Butang awal
    keyboard_awal = InlineKeyboardMarkup([
        [InlineKeyboardButton("NAMA PRODUK", callback_data="hantar_detail")]
    ])

    # Padam gambar asal
    try:
        await message.delete()
    except (MessageDeleteForbidden, ChatAdminRequired):
        pass
    except Exception:
        pass

    # Repost gambar
    await client.send_photo(
        chat_id=message.chat.id,
        photo=photo_id,
        caption=caption_baru,
        reply_markup=keyboard_awal
    )

if __name__ == "__main__":
    bot.run()


