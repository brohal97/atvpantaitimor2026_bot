import os, io, re, tempfile
from datetime import datetime
from pyrogram import Client, filters
from google.cloud import vision

# ================== TARGET ==================
TARGET_ACC = "8606018423"
TARGET_BANK = "CIMB BANK"

# ============ Google creds from env ============
# Railway Variables:
#   API_ID, API_HASH, BOT_TOKEN
#   GOOGLE_APPLICATION_CREDENTIALS_JSON  (paste FULL JSON content)
creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON", "").strip()
if not creds_json:
    raise RuntimeError("Missing env var: GOOGLE_APPLICATION_CREDENTIALS_JSON")

tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
tmp.write(creds_json.encode("utf-8"))
tmp.close()
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tmp.name

# ================== Telegram ==================
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Missing API_ID / API_HASH / BOT_TOKEN")

app = Client("ocr_receipt_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ================== Vision ==================
vision_client = vision.ImageAnnotatorClient()

# ================== HELPERS ==================
def normalize_ocr_text(s: str) -> str:
    """
    Betulkan salah OCR biasa + kemaskan whitespace.
    (Tidak tukar 'l' -> '1' supaya perkataan bulan BM tidak rosak: Julai, Disember)
    """
    if not s:
        return ""
    trans = str.maketrans({
        "O": "0", "o": "0",   # O->0
        "I": "1", "|": "1",   # I/| -> 1
        "S": "5", "s": "5",   # S->5
    })
    s = s.translate(trans)
    s = re.sub(r"[ \t]+", " ", s)
    return s

def digits_only(s: str) -> str:
    return re.sub(r"\D+", "", s or "")

def account_found(text: str) -> bool:
    """
    Akan jumpa walaupun format:
    - 8 6 0 6 0 1 8 4 2 3
    - 8606 0184 23
    - 86-06-01-84-23
    """
    t = normalize_ocr_text(text)
    return TARGET_ACC in digits_only(t)

def format_dt(dt: datetime) -> str:
    # output: DD/MM/YYYY | 12:30am
    ddmmyyyy = dt.strftime("%d/%m/%Y")
    h, m = dt.hour, dt.minute
    ap = "am" if h < 12 else "pm"
    h12 = h % 12
    if h12 == 0:
        h12 = 12
    return f"{ddmmyyyy} | {h12}:{m:02d}{ap}"

# ================== DATETIME PARSER ==================
def parse_datetime(text: str):
    t = normalize_ocr_text(text)

    # time: 14:17 / 2:17 PM / 02.17pm / 02:17:59
    p_time = re.compile(r"\b(\d{1,2})[:\.](\d{2})(?:[:\.](\d{2}))?\s*(am|pm)?\b", re.I)

    # month map (EN + BM)
    mon_map = {
        # EN
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12,

        # BM
        "januari": 1,
        "februari": 2,
        "mac": 3,
        "april": 4,
        "mei": 5,
        "jun": 6,
        "julai": 7,
        "ogos": 8,
        "september": 9, "sep": 9, "sept": 9,
        "oktober": 10, "oct": 10,
        "november": 11, "nov": 11,
        "disember": 12, "dec": 12,
    }

    def month_to_int(m: str):
        if not m:
            return None
        m2 = m.strip().lower()
        m2 = re.sub(r"\.+$", "", m2)
        m2 = re.sub(r"[^a-z]", "", m2)
        if not m2:
            return None
        if m2 in mon_map:
            return mon_map[m2]
        if len(m2) >= 3 and m2[:3] in mon_map:
            return mon_map[m2[:3]]
        return None

    dates = []  # (pos, (d, m, y))
    times = []  # (pos, (hh, mm, ampm))

    # A) numeric D/M/Y: 22/01/2026, 2-1-26
    p_dmy = re.compile(r"\b(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{2,4})\b")
    for m in p_dmy.finditer(t):
        dates.append((m.start(), (m.group(1), m.group(2), m.group(3))))

    # B) numeric Y/M/D: 2026/01/22
    p_ymd = re.compile(r"\b(\d{4})[\/\-\.](\d{1,2})[\/\-\.](\d{1,2})\b")
    for m in p_ymd.finditer(t):
        dates.append((m.start(), (m.group(3), m.group(2), m.group(1))))

    # C) D MON Y: 22 Jan 2026 / 22/Jan/2026 / 22 Januari 2026 / 22hb Januari 2026
    p_d_mon_y = re.compile(
        r"\b(\d{1,2})(?:st|nd|rd|th|hb)?\s*(?:[\/\-\.\s])\s*([A-Za-z]+)\s*(?:[\/\-\.\s])?\s*(\d{2,4})\b",
        re.I
    )
    for m in p_d_mon_y.finditer(t):
        d, mon, y = m.group(1), m.group(2), m.group(3)
        mo = month_to_int(mon)
        if mo:
            dates.append((m.start(), (d, str(mo), y)))

    # D) MON D, Y: Jan 22, 2026 / January 22 2026 / Januari 22, 2026
    p_mon_d_y = re.compile(
        r"\b([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th|hb)?\s*,?\s+(\d{2,4})\b",
        re.I
    )
    for m in p_mon_d_y.finditer(t):
        mon, d, y = m.group(1), m.group(2), m.group(3)
        mo = month_to_int(mon)
        if mo:
            dates.append((m.start(), (d, str(mo), y)))

    # times
    for m in p_time.finditer(t):
        times.append((m.start(), (m.group(1), m.group(2), m.group(4))))

    if not dates:
        return None

    # pair nearest date-time
    best_date = dates[0]
    best_time = times[0] if times else None

    if times:
        best = None
        for dpos, dval in dates:
            for tpos, tval in times:
                dist = abs(dpos - tpos)
                if best is None or dist < best[0]:
                    best = (dist, (dpos, dval), (tpos, tval))
        _, best_date, best_time = best

    _, (dd, mm, yyyy) = best_date
    y = int(yyyy)
    if y < 100:
        y += 2000
    mo = int(mm)
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

# ================== AMOUNT PARSER (WITH SEN) ==================
def parse_amount(text: str):
    """
    Ambil amount dengan sen.
    Prioriti: RM/MYR dahulu. Kalau tak jumpa, fallback kepada nombor dekat keyword.
    """
    t = normalize_ocr_text(text).lower()
    keywords = ["amount", "total", "jumlah", "amaun", "grand total", "payment", "paid", "pay", "transfer", "successful"]

    def score_match(val: float, start: int) -> float:
        window = t[max(0, start - 60): start + 60]
        near_kw = any(k in window for k in keywords)
        return (100 if near_kw else 0) + min(val, 999999) / 1000.0

    candidates = []

    # PASS 1: RM/MYR formats
    p_rm = re.compile(
        r"\b(?:rm|myr)\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)\b",
        re.I
    )
    for m in p_rm.finditer(t):
        num_str = m.group(1).replace(",", "")
        try:
            val = float(num_str)
        except:
            continue
        candidates.append((score_match(val, m.start()) + 1000, val))  # tambah bonus utk RM/MYR

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    # PASS 2 (fallback): nombor biasa dekat keyword
    p_num = re.compile(r"\b([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)\b")
    for m in p_num.finditer(t):
        num_str = m.group(1).replace(",", "")
        try:
            val = float(num_str)
        except:
            continue
        candidates.append((score_match(val, m.start()), val))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]

def format_amount_rm(val: float) -> str:
    # ✅ kekalkan sen: RM119.70
    return f"RM{val:.2f}"

# ================== BOT HANDLER ==================
@app.on_message(filters.photo)
async def ocr_photo(_, message):
    photo_path = None
    try:
        photo_path = await message.download()
        with io.open(photo_path, "rb") as f:
            content = f.read()

        image = vision.Image(content=content)
        resp = vision_client.text_detection(image=image)

        if resp.error and resp.error.message:
            await message.reply_text(f"❌ OCR Error: {resp.error.message}")
            return

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

    finally:
        if photo_path:
            try:
                os.remove(photo_path)
            except:
                pass

app.run()
