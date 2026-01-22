import os, io, re, tempfile
from datetime import datetime
from pyrogram import Client, filters
from google.cloud import vision

# ================== TARGET ==================
TARGET_ACC = "8606018423"
TARGET_BANK = "CIMB BANK"

# ============ Google creds from env ============
creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON", "").strip()
if not creds_json:
    raise RuntimeError("Missing env var: GOOGLE_APPLICATION_CREDENTIALS_JSON")

tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
tmp.write(creds_json.encode("utf-8"))
tmp.close()
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tmp.name

# ================== Telegram ==================
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

app = Client("ocr_test_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ================== Vision ==================
vision_client = vision.ImageAnnotatorClient()

# ================== HELPERS ==================
def digits_only(s: str) -> str:
    return re.sub(r"\D+", "", s or "")

def account_found(text: str) -> bool:
    return TARGET_ACC in digits_only(text)

def format_dt(dt: datetime) -> str:
    ddmmyyyy = dt.strftime("%d/%m/%Y")
    h, m = dt.hour, dt.minute
    ap = "am" if h < 12 else "pm"
    h12 = h % 12
    if h12 == 0:
        h12 = 12
    return f"{ddmmyyyy} | {h12}:{m:02d}{ap}"

def parse_datetime(text: str):
    t = text

    p_time = re.compile(r"\b(\d{1,2})[:\.](\d{2})(?:[:\.](\d{2}))?\s*(am|pm)?\b", re.I)
    p_dmy  = re.compile(r"\b(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{2,4})\b")
    p_ymd  = re.compile(r"\b(\d{4})[\/\-\.](\d{1,2})[\/\-\.](\d{1,2})\b")

    month_names = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t)?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    p_words = re.compile(rf"\b(\d{{1,2}})\s+{month_names}\s+(\d{{4}})\b", re.I)

    dates, times = [], []

    for m in p_words.finditer(t):
        dates.append(("words", m.start(), (m.group(1), m.group(2), m.group(3))))
    for m in p_dmy.finditer(t):
        dates.append(("dmy", m.start(), (m.group(1), m.group(2), m.group(3))))
    for m in p_ymd.finditer(t):
        dates.append(("ymd", m.start(), (m.group(3), m.group(2), m.group(1))))
    for m in p_time.finditer(t):
        times.append((m.start(), (m.group(1), m.group(2), m.group(4))))

    if not dates:
        return None

    best_date = dates[0]
    best_time = times[0] if times else None

    if times:
        best = None
        for d in dates:
            for tm in times:
                dist = abs(d[1] - tm[0])
                if best is None or dist < best[0]:
                    best = (dist, d, tm)
        _, best_date, best_time = best

    kind, _, (dd, mm_or_mon, yyyy) = best_date
    y = int(yyyy)
    if y < 100:
        y += 2000

    if kind == "words":
        mon = mm_or_mon.lower()
        mon_map = {
            "jan": 1, "january": 1, "feb": 2, "february": 2,
            "mar": 3, "march": 3, "apr": 4, "april": 4,
            "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
            "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
            "oct": 10, "october": 10, "nov": 11, "november": 11,
            "dec": 12, "december": 12
        }
        mo = mon_map.get(mon[:3])
        if not mo:
            return None
    else:
        mo = int(mm_or_mon)

    d = int(dd)

    if best_time:
        _, (hh, minute, ap) = best_time
        hh, minute = int(hh), int(minute)
        if ap:
            ap = ap.lower()
            if ap == "pm" and hh != 12:
                hh += 12
            if ap == "am" and hh == 12:
                hh = 0
    else:
        hh, minute = 0, 0

    try:
        return datetime(y, mo, d, hh, minute)
    except:
        return None

def parse_amount(text: str):
    """
    Cari amount, utamakan baris yang ada keyword.
    """
    t = text.lower()
    keywords = ["amount", "total", "jumlah", "amaun", "grand total", "payment", "paid", "rm", "myr"]
    p = re.compile(r"(rm|myr)\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)", re.I)

    candidates = []
    for m in p.finditer(t):
        start = m.start()
        num_str = m.group(2)
        clean = num_str.replace(",", "")
        try:
            val = float(clean)
        except:
            continue

        window = t[max(0, start - 40): start + 40]
        score = (50 if any(k in window for k in keywords) else 0) + min(val, 999999) / 1000.0
        candidates.append((score, val))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return candidates[0][1]

def format_amount_rm(val: float) -> str:
    return f"RM{int(round(val))}"

# ================== BOT HANDLER ==================
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
            return

        # 1) Account
        line1 = f"{TARGET_ACC} {TARGET_BANK}" if account_found(text) else "No akaun tidak sah"

        # 2) Date + time
        dt = parse_datetime(text)
        line2 = format_dt(dt) if dt else "Tarikh tidak dijumpai"

        # 3) Amount
        amt = parse_amount(text)
        line3 = format_amount_rm(amt) if amt is not None else "Total tidak dijumpai"

        await message.reply_text(f"{line1}\n{line2}\n{line3}")

    except Exception as e:
        await message.reply_text(f"❌ Error: {type(e).__name__}: {e}")

app.run()
