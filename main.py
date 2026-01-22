from pyrogram import Client, filters
from google.cloud import vision
import io, os

bot = Client(
    "ocr_test_bot",
    api_id=int(os.environ["API_ID"]),
    api_hash=os.environ["API_HASH"],
    bot_token=os.environ["BOT_TOKEN"]
)

@bot.on_message(filters.photo)
async def ocr_test(client, message):
    photo = await message.download()

    vision_client = vision.ImageAnnotatorClient()
    with io.open(photo, "rb") as f:
        content = f.read()

    image = vision.Image(content=content)
    response = vision_client.text_detection(image=image)

    if response.text_annotations:
        await message.reply(response.text_annotations[0].description[:4000])
    else:
        await message.reply("❌ OCR tak jumpa teks")

bot.run()

