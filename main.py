import os
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

@bot.on_message(filters.photo)
async def handle_photo(client, message):
    # 1) ambil file_id gambar + caption asal
    photo_id = message.photo.file_id
    caption = message.caption or ""

    # 2) cuba padam gambar asal (akan gagal jika bot tiada permission / private chat limit)
    try:
        await message.delete()
    except (MessageDeleteForbidden, ChatAdminRequired):
        # tak ada permission -> kita terus repost je tanpa delete
        pass
    except Exception:
        pass

    # 3) hantar semula gambar yang sama
    await client.send_photo(
        chat_id=message.chat.id,
        photo=photo_id,
        caption=caption
    )

if __name__ == "__main__":
    bot.run()
