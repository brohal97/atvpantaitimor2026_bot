from pyrogram import Client, filters
import os
from datetime import datetime
import pytz

# Ambil token terus dari Railway
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Guna konfigurasi default yang lebih stabil
bot = Client(
    "atvpantaitimor_bot",
    api_id=2040, 
    api_hash="b18441a4833da9d0bd3395b54b7a7525",
    bot_token=BOT_TOKEN
)

@bot.on_message(filters.photo)
async def handle_photo(client, message):
    try:
        # Set masa Malaysia
        kl_pytz = pytz.timezone('Asia/Kuala_Lumpur')
        waktu = datetime.now(kl_pytz).strftime('%d/%m/%Y %H:%M')
        
        # Padam gambar asal
        await message.delete()
        
        # Balas mesej
        ayat = f"✅ **REKOD DITERIMA**\n\n**Tarikh sekian :** {waktu}"
        await client.send_message(message.chat.id, ayat)
    except Exception as e:
        print(f"Ralat: {e}")

if __name__ == "__main__":
    bot.run()
