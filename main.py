# Contoh ayat yang anda mahukan
@bot.on_message(filters.photo)
async def handle_photo(client, message):
    from datetime import datetime
    import pytz
    
    # Set masa Malaysia
   kl_pytz = pytz.timezone('Asia/Kuala_Lumpur')
    tarikh_sekarang = datetime.now(kl_pytz).strftime('%d/%m/%Y %H:%M')
    
    # Padam gambar asal
    await message.delete()
    
    # Balas mesej dengan ayat yang diminta
    await message.reply(f"✅ **REKOD DITERIMA**\n\n**Tarikh sekian :** {tarikh_sekarang}")
