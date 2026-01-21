import telebot
import os

# Kod ini akan ambil token dari setting Railway nanti
API_TOKEN = os.getenv('BOT_TOKEN')
bot = telebot.TeleBot(API_TOKEN)

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        staf = message.from_user.first_name
        # Bot hantar mesej pengesahan
        bot.send_message(message.chat.id, f"✅ *REKOD DITERIMA*\n━━━━━━━━━━━━━━\n👤 Staf: {staf}\n📝 Status: Gambar telah direkod dan dipadam.\n━━━━━━━━━━━━━━", parse_mode='Markdown')
        # Bot padam gambar asal staf
        bot.delete_message(message.chat.id, message.message_id)
    except Exception as e:
        print(f"Ralat: {e}")

bot.infinity_polling()
