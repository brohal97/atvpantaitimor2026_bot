import os, io, tempfile
from pyrogram import Client, filters
from google.cloud import vision

# --- Railway env vars needed:
# API_ID, API_HASH, BOT_TOKEN
# GOOGLE_APPLICATION_CREDENTIALS_JSON  (paste full JSON content)

# 1) Convert JSON string env -> temp file path for Google SDK
creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON", "").strip()
if not creds_json:
    raise RuntimeError("Missing env var: GOOGLE_APPLICATION_CREDENTIALS_JSON")

tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
tmp.write(creds_json.encode("utf-8"))
tmp.close()
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tmp.name

# 2) Telegram bot init
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

app = Client("ocr_test_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# 3) Vision client
vision_client = vision.ImageAnnotatorClient()

@app.on_message(filters.photo)
async def ocr_photo(_, message):
    try:
        photo_path = await message.download()
        with io.open(photo_path, "rb") as f:
            content = f.read()

        image = vision.Image(content=content)
        resp = vision_client.text_detection(image=image)

        text = (resp.text_annotations[0].description.strip()
                if resp.text_annotations else "")

        if not text:
            await message.reply_text("❌ OCR tak jumpa teks (cuba gambar lebih jelas).")
        else:
            # limit panjang reply supaya tak overflow
            if len(text) > 3500:
                text = text[:3500] + "\n...\n(terlalu panjang)"
            await message.reply_text("✅ OCR Result:\n\n" + text)

    except Exception as e:
        await message.reply_text(f"❌ Error: {type(e).__name__}: {e}")

app.run()

