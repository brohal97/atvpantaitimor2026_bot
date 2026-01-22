import os, io, re, tempfile
from datetime import datetime
from pyrogram import Client, filters
from google.cloud import vision

# ================== TARGET ==================
TARGET_ACC = "8606018423"
TARGET_BANK = "CIMB BANK"

# ================== GOOGLE CREDS ==================
# Railway env vars:
# API_ID, API_HASH, BOT_TOKEN
# GOOGLE_APPLICATION_CREDENTIALS_JSON  (paste FULL JSON)
creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON", "").strip()
if not creds_json:
    raise RuntimeError("Missing env var: GOOGLE_APPLICATION_CREDENTIALS_JSON")

tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
tmp.write(creds_json.encode("utf-8"))
tmp.close()
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tmp.name

# ================== TELEGRAM ==================
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Missing API_ID / API_HASH / BOT_TOKEN")

app = Client(
    "ocr_receipt_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ================== VISION ==================
vision_client = vision.ImageAnnotatorClient()

# ================== HELPERS ==================
def normalize_ocr_text(s: str) -> str:
    """Ringankan kesilapan OCR biasa (SELAMAT utk tarikh & amount)."""
    if not s:
        return ""
    trans = str.maketrans({
        "O": "0", "o": "0",
        "I": "1", "|": reminder_ocr_error := "1",
        "S": "5", "s": "5",
    })
    s = s.translate(trans)
    s = re.sub(r"[ \t]+", " ", s)
    return s

def digits_only(s: str) -> str:
    return re.sub(r"\D+", "", s or "")

def account_found(text: str) -> bool:
    t = normalize_ocr_text(text)
    return TARGET_ACC in digits_only(t)

def format_dt(dt: datetime) -> str:
    d = dt.strftime("%d/%m/%Y")
    h, m = dt.hour, dt.minute
    ap = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{d} | {h12}:{m:02d}{ap}"

# ================== DATETIME ==================
def parse_datetime(text: str):
    t = normalize_ocr_text(text)

    p_time = re.compile(r"\b(\d{1,2})[:\.](\d{2})(?:[:\.]\d{2})?\s*(am|pm)?\b", re.I)

    mon = {
        "jan":1,"january":1,"januari":1,
        "feb":2,"february":2,"februari":2,
        "mar":3,"march":3,"mac":3,
        "apr":4,"april":4,
        "may":5,"mei":5,
        "jun":6,"june":6,
        "jul":7,"july":7,"julai":7,
        "aug":8,"august":8,"ogos":8,
        "sep":9,"sept":9,"september":9,
        "oct":10,"october":10,"oktober":10,
        "nov":11,"november":11,
        "dec":12,"december":12,"disember":12
    }

    dates = []

    # D/M/Y
    for m in re.finditer(r"\b(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{2,4})\b", t):
        dates.append((m.start(), (m.group(1), m.group(2), m.group(3))))

    # Y/M/D
    for m in re.finditer(r"\b(\d{4})[\/\-\.](\d{1,2})[\/\-\.](\d{1,2})\b", t):
        dates.append((m.start(), (m.group(3), m.group(2), m.group(1))))

    # D MON Y
    for m in re.finditer(r"\b(\d{1,2})\s*([A-Za-z]+)\s*(\d{4})\b", t):
        mm = mon.get(m.group(2).lower()[:3])
        if mm:
            dates.append((m.start(), (m.group(1), str(mm), m.group(3))))

    if not dates:
        return None

    times = []
    for m in p_time.finditer(t):
        times.append((m.start(), (m.group(1), m.group(2), m.group(3))))

    _, (dd, mm, yy) = dates[0]
    y = int(yy) + (2000 if int(yy) < 100 else 0)
    mo, d = int(mm), int(dd)

    hh = minute = 0
    if times:
        _, (h, mi, ap) = times[0]
        hh, minute = int(h), int(mi)
        if ap:
            ap = ap.lower()
            if ap == "pm" and hh != 12: hh += 12
            if ap == "am" and hh == 12: hh = 0

    return datetime(y, mo, d, hh, minute)

# ================== AMOUNT (WITH SEN) ==================
def parse_amount(text: str):
    """
    Support:
    RM119.70
    RM 5,900.00
    MYR119.7
    Amount 119.70
    """
    t = normalize_ocr_text(text).lower()
    keywords = ["amount","total","jumlah","amaun","payment","paid","successful","transfer"]

    p = re.compile(
        r"\b(?:rm|myr)?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+\.[0-9]{1,2})\b",
        re.I
    )

    candidates = []
    for m in p.finditer(t):
        num = m.group(1).replace(",", "")
        try:
            val = float(num)
        except:
            continue
        window = t[max(0, m.start()-40): m.start()+40]
        score = (80 if any(k in window for k in keywords) else 0) + val
        candidates.append((score, val))

    if not candidates:
        return None

    candidates.sort(reverse=True)
    return candidates[0][1]

def format_amount_rm(val: float) -> str:
    """KEKALKAN SEN – TIADA ROUNDING"""
    return f"RM{val:.2f}"

# ================== BOT HANDLER ==================
@app.on_message(filters.photo)
async def ocr_handler(_, message):
    photo_path = None
    try:
        photo_path = await message.download()
        with open(photo_path, "rb") as f:
            content = f.read()

        image = vision.Image(content=content)
        resp = vision_client.text_detection(image=image)

        text = resp.text_annotations[0].description if resp.text_annotations else ""
        if not text.strip():
            await message.reply_text("❌ OCR tak jumpa teks.")
            return

        line1 = f"{TARGET_ACC} {TARGET_BANK}" if account_found(text) else "No akaun tidak sah"

        dt = parse_datetime(text)
        line2 = format_dt(dt) if dt else "Tarikh tidak dijumpai"

        amt = parse_amount(text)
        line3 = format_amount_rm(amt) if amt is not None else "Total tidak dijumpai"

        await message.reply_text(f"{line1}\n{line2}\n{line3}")

    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")

    finally:
        if photo_path:
            try: os.remove(photo_path)
            except: pass

app.run()
