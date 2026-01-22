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
    Ini bantu untuk tarikh/masa/amount bila OCR baca 'O' sebagai '0' dll.
    """
    if not s:
        return ""
    trans = str.maketrans({
        "O": "0", "o": "0",         # O->0
        "I": "1", "l": "1", "|": "1",  # I/l/| -> 1
        "S": "5", "s": "5",         # S->5
        # "B": "8",  # (opsyen) kadang-kadang B->8, tapi boleh rosak perkataan "BANK"
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

def parse_datetime(text: str):
    """
    SUPPORT luas:
    - 22/01/2026, 22-01-26, 22.1.2026
    - 2026/01/22, 2026-1-22
    - 22 Jan 2026, 22 January 2026
    - 22/Jan/2026, 22-Jan-2026, 22.Jan.2026
    - Jan 22, 2026  (US style)
    - 22 Januari 2026, 22hb Januari 2026 (BM)
    Masa:
    - 10:38, 22:51, 10.38
    - 10:38 PM, 10:38PM, 10.38pm
    - 10:38:48 (saat diabaikan)
    """
    t = normalize_ocr_text(text)

    # TIME
    p_time = re.compile(
        r"\b(\d{1,2})[:\.](\d{2})(?:[:\.](\d{2}))?\s*(am|pm)?\b",
        re.I
    )

    # MONTH map (EN + BM + variants)
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
        m2 = re.sub(r"\.+$", "", m2)     # buang trailing dot: Jan.
        m2 = re.sub(r"[^a-z]", "", m2)   # buang comma/char pelik
        if not m2:
            return None
        if m2 in mon_map:
            return mon_map[m2]
        if len(m2) >= 3 and m2[:3] in mon_map:
            return mon_map[m2[:3]]
        return None

    dates = []  # (pos, (d, m, y))

    # A) numeric D/M/Y
    p_dmy = re.compile(r"\b(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{2,4})\b")
    for m in p_dmy.finditer(t):
        d, mo, y = m.group(1), m.group(2), m.group(3)
        dates.append((m.start(), (d, mo, y)))

    # B) numeric Y/M/D
    p_ymd = re.compile(r"\b(\d{4})[\/\-\.](\d{1,2})[\/\-\.](\d{1,2})\b")
    for m in p_ymd.finditer(t):
        y, mo, d = m.group(1), m.group(2), m.group(3)
        dates.append((m.start(), (d, mo, y)))

    # C) D MON Y with many separators: "22 Jan 2026", "22/Jan/2026", "22 Januari 2026", "22hb Januari 2026"
    p_d_mon_y = re.compile(
        r"\b(\d{1,2})(?:st|nd|rd|th|hb)?\s*"
        r"(?:[\/\-\.\s])\s*"
        r"([A-Za-z]+)\s*"
        r"(?:[\/\-\.\s])?\s*"
        r"(\d{2,4})\b",
        re.I
    )
    for m in p_d_mon_y.finditer(t):
        d, mon, y = m.group(1), m.group(2), m.group(3)
        mo = month_to_int(mon)
        if mo:
            dates.append((m.start(), (d, str(mo), y)))

    # D) MON D, Y: "Jan 22, 2026", "January 22 2026", "Januari 22, 2026"
    p_mon_d_y = re.compile(
        r"\b([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th|hb)?\s*,?\s+(\d{2,4})\b",
        re.I
    )
    for m in p_mon_d_y.finditer(t):
        mon, d, y = m.group(1), m.group(2), m.group(3)
        mo = month_to_int(mon)
        if mo:
            dates.append((m.start(), (d, str(mo), y)))

    # TIMES
    times = []  # (pos, (hh, mm, ampm))
    for m in p_time.finditer(t):
        times.append((m.start(), (m.group(1), m.group(2), m.group(4))))

    if not dates:
        return None

    # choose nearest date-time pair
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

def parse_amount(text: str):
    """
    Cari amount/total.
    - Utamakan yang ada RM/MYR.
    - Score tinggi jika dekat keyword.
    """
    t = normalize_ocr_text(text).lower()
    keywords = ["amount", "total", "jumlah", "amaun", "grand total", "payment", "paid", "pay", "transfer", "successful"]

    # Utamakan RM/MYR supaya tak tersalah baca tarikh
    p = re.compile(
        r"\b(?:rm|myr)\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)\b",
        re.I
    )

    candidates = []
    for m in p.finditer(t):
        num_str = m.group(1)
        start = m.start()
        clean = num_str.replace(",", "")
        try:
            val = float(clean)
        except:
            continue

        window = t[max(0, start - 50): start + 50]
        score = (80 if any(k in window for k in keywords) else 0) + min(val, 999999) / 1000.0
        candidates.append((score, val))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return candidates[0][1]

def format_amount_rm(val: float) -> str:
    # output tanpa sen: RM5900
    return f"RM{int(round(val))}"

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
        # cleanup downloaded photo file
        if photo_path:
            try:
                os.remove(photo_path)
            except:
                pass

app.run()
