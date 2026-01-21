import os
from datetime import datetime

import pytz
from pyrogram import Client, filters
from pyrogram.errors import MessageDeleteForbidden, ChatAdminRequired

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Missing API_ID / API_HASH / BOT_TOKEN in Railway Variables")

bot = Client(
    "atv_bot_2026",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

@bot.on_message(filters.photo & ~filters.bot)
async def handle_photo(client, message):
    photo_id = message.photo.file_id
    caption = message.caption or ""

    # 1) cuba padam gambar asal
    try:
        await message.delete()
    except (MessageDeleteForbidden, ChatAdminRequired):
        pass
    except Exception:
        pass

    # 2) repost gambar
    await client.send_photo(
        chat_id=message.chat.id,
        photo=photo_id,
        caption=caption
    )

    # 3) hantar tarikh & jam terkini (Malaysia)
    tz = pytz.timezone("Asia/Kuala_Lumpur")
    now = datetime.now(tz)

    tarikh = now.strftime("%d/%m/%Y")
    jam = now.strftime("%I:%M %p").lower()   # contoh: 04:25 pm

    await client.send_message(
        chat_id=message.chat.id,
        text=f"Tarikh terkini : {tarikh}\nJam : {jam}"
    )

if __name__ == "__main__":
    bot.run()
