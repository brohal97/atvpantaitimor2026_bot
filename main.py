import os
from datetime import datetime

import pytz
from pyrogram import Client, filters
from pyrogram.errors import MessageDeleteForbidden, ChatAdminRequired

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

@bot.on_message(filters.photo & ~filters.bot)
async def handle_photo(client, message):
    photo_id = message.photo.file_id
    caption_asal = message.caption or ""

    # Masa Malaysia
    tz = pytz.timezone("Asia/Kuala_Lumpur")
    now = datetime.now(tz)

    tarikh = now.strftime("%-d/%-m/%Y")   # 1/1/2025
    jam = now.strftime("%I:%M %p").lower()  # 01:10 pm

    # Caption akhir (ringkas)
    if caption_asal.strip():
        caption_baru = f"{caption_asal}\n\n{tarikh} | {jam}"
    else:
        caption_baru = f"{tarikh} | {jam}"

    # Padam gambar asal (jika ada permission)
    try:
        await message.delete()
    except (MessageDeleteForbidden, ChatAdminRequired):
        pass
    except Exception:
        pass

    # Hantar semula gambar + caption
    await client.send_photo(
        chat_id=message.chat.id,
        photo=photo_id,
        caption=caption_baru
    )

if __name__ == "__main__":
    bot.run()

