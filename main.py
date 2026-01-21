from pyrogram import Client, filters
import os
from datetime import datetime
import pytz

# Maklumat API
API_ID = 26569722
API_HASH = "809be041fdf8d87452174360e2d3122c"
BOT_TOKEN = os.environ.get("BOT_TOKEN")

bot = Client("atv_bot_2026", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@bot.on_message(filters.photo)
async def handle_photo(client, message):
    try:
        # Set masa Malaysia
        kl_pytz = pytz.timezone('Asia/Kuala_Lumpur')
        tarikh_sekarang = datetime.now(kl_pytz).strftime('%d/%m/%Y %H:%M')
        
        # Simpan kapsyen asal jika ada
        caption_asal = message.caption if message.caption else ""
        
        # Padam gambar asal
        await message.delete()
        
        # Balas dengan mesej baru
        teks_balasan = (
            f"✅ **REKOD DITERIMA**\n\n"
            f"**Tarikh sekian :** {tarikh_sekarang}\n"
            f"**Nota :** {caption_asal}"
        )
        
        await client.send_message(chat_id=message.chat.id, text=teks_balasan)
        
    except Exception as e:
        print(f"Ralat: {e}")

if __name__ == "__main__":
    bot.run()
