from pyrogram import Client, filters
import os
from datetime import datetime
import pytz

# Ambil token dari environment variables Railway
API_ID = 26569722
API_HASH = "809be041fdf8d87452174360e2d3122c"
BOT_TOKEN = os.environ.get("BOT_TOKEN")

bot = Client("atv_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@bot.on_message(filters.photo)
async def handle_photo(client, message):
    # Set masa Malaysia
    kl_pytz = pytz.timezone('Asia/Kuala_Lumpur')
    tarikh_sekarang = datetime.now(kl_pytz).strftime('%d/%m/%Y %H:%M')
    
    # Padam gambar asal
    await message.delete()
    
    # Balas mesej dengan ayat yang diminta
    await message.reply(f"✅ **REKOD DITERIMA**\n\n**Tarikh sekian :** {tarikh_sekarang}")

if __name__ == "__main__":
    bot.run()
