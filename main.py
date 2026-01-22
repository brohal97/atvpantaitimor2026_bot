import os, io, re, tempfile
from datetime import datetime
from pyrogram import Client, filters
from google.cloud import vision

# ================== SETTINGS ==================
TARGET_ACC = "8606018423"
TARGET_BANK = "CIMB BANK"
MAX_REPLY_CHARS = 3500

# ================== GOOGLE CREDS ==================
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

app = Client("ocr_receipt_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ================== VISION ==================
vision_client = vision.ImageAnnotatorClient()

# ================== NORMALIZE ==================
def normalize_ocr_text(s: str) -> str:
    """Normalization minima & selamat untuk tarikh/amount/akaun."""
    if not s:
        return ""
    trans = str.maketrans({
        "O": "0", "o": "0",
        "I": "1", "|": "1",
        "S": "5", "s": "5",
    })
    s = s.translate(trans)
    s = re.sub(r"[ \t]+", " ", s)
    return s

def normalize_for_status(s: str) -> str:
    """Normalization khas untuk status sahaja (lebih agresif)."""
    if not s:
        return ""
    t = s

    # Betulkan OCR typo biasa utk "successful"
    # (bukan tambah keyword baru; ini cuma betulkan ejaan OCR)
    t = t.replace("5uccessful", "Successful")
    t = t.replace("successfu1", "Successful")
    t = t.replace("successfu|", "Successful")
    t = t.replace("successfull", "Successful")
    t = t.replace("succesful", "Successful")
    t = t.replace("suceessful", "Successful")
    t = t.replace("successfui", "Successful")
    t = re.sub(r"[ \t]+", " ", t)
    return t

def digits_only(s: str) -> str:
    return re.sub(r"\D+", "", s or "")

def account_found(text: str) -> bool:
    t = normalize_ocr_text(text)
    return TARGET_ACC in digits_only(t)

def format_dt(dt: datetime) -> str:
    ddmmyyyy = dt.strftime("%d/%m/%Y")
    h, m = dt.hour, dt.minute
    ap = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{ddmmyyyy} | {h12}:{m:02d}{ap}"

def build_line(ok_text: str, bad_text: str, ok: bool, ok_emoji="✅", bad_emoji="❌") -> str:
    return f"{ok_text} {ok_emoji}" if ok else f"{bad_text} {bad_emoji}"

# ================== DATETIME PARSER ==================
def parse_datetime(text: str):
    t = normalize_ocr_text(text)

    p_time = re.compile(r"\b(\d{1,2})[:\.](\d{2})(?:[:\.](\d{2}))?\s*(am|pm)?\b", re.I)

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

    dates, times = [], []

    p_dmy = re.compile(r"\b(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{2,4})\b")
    for m in p_dmy.finditer(t):
        dates.append((m.start(), (m.group(1), m.group(2), m.group(3))))

    p_ymd = re.compile(r"\b(\d{4})[\/\-\.](\d{1,2})[\/\-\.](\d{1,2})\b")
    for m in p_ymd.finditer(t):
        dates.append((m.start(), (m.group(3), m.group(2), m.group(1))))

    p_d_mon_y = re.compile(
        r"\b(\d{1,2})(?:st|nd|rd|th|hb)?\s*(?:[\/\-\.\s])\s*([A-Za-z]+)\s*(?:[\/\-\.\s])?\s*(\d{2,4})\b",
        re.I
    )
    for m in p_d_mon_y.finditer(t):
        d, mon, y = m.group(1), m.group(2), m.group(3)
        mo = month_to_int(mon)
        if mo:
            dates.append((m.start(), (d, str(mo), y)))

    p_mon_d_y = re.compile(
        r"\b([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th|hb)?\s*,?\s+(\d{2,4})\b",
        re.I
    )
    for m in p_mon_d_y.finditer(t):
        mon, d, y = m.group(1), m.group(2), m.group(3)
        mo = month_to_int(mon)
        if mo:
            dates.append((m.start(), (d, str(mo), y)))

    for m in p_time.finditer(t):
        times.append((m.start(), (m.group(1), m.group(2), m.group(4))))

    if not dates:
        return None

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

# ================== AMOUNT (WITH SEN) ==================
def parse_amount(text: str):
    t = normalize_ocr_text(text).lower()
    keywords = ["amount", "total", "jumlah", "amaun", "grand total", "payment", "paid", "pay", "transfer", "successful"]

    def score_match(val: float, start: int) -> float:
        window = t[max(0, start - 60): start + 60]
        near_kw = any(k in window for k in keywords)
        return (100 if near_kw else 0) + min(val, 999999) / 1000.0

    candidates = []
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
        candidates.append((score_match(val, m.start()) + 1000, val))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]

def format_amount_rm(val: float) -> str:
    return f"RM{val:.2f}"

# ================== STATUS (YOUR LIST ONLY) ==================
POSITIVE_KW = [
    "successful", "success", "completed", "complete",
    "transaction successful", "payment successful", "transfer successful",
    "paid", "payment received", "received", "funds received",
    "credited", "credit", "approved", "verified", "posted",
    "settled", "processed",
    "berjaya", "berjaya diproses", "transaksi berjaya", "pembayaran berjaya",
    "pemindahan berjaya", "diterima", "telah diterima", "sudah masuk",
    "dana diterima", "dikreditkan", "diluluskan", "selesai", "telah selesai",
    "berjaya dihantar",
]

NEGATIVE_KW = [
    "pending", "processing", "in progress", "queued", "awaiting", "awaiting confirmation",
    "not received", "unpaid", "failed", "unsuccessful", "rejected", "declined",
    "cancelled", "canceled", "reversed", "refunded", "void", "timeout", "timed out",
    "belum masuk", "belum diterima", "belum terima", "belum berjaya", "dalam proses",
    "sedang diproses", "menunggu pengesahan", "gagal", "tidak berjaya", "ditolak",
    "dibatalkan", "dipulangkan", "diproses semula",
    "ibg", "interbank giro", "scheduled transfer", "future dated", "effective date", "pending settlement",
]

def _find_status_original(text: str, keyword: str):
    """
    Cari keyword dalam text original (case-insensitive) dan pulangkan substring asal.
    """
    m = re.search(re.escape(keyword), text, flags=re.I)
    if not m:
        return None
    return text[m.start():m.end()]

def detect_payment_status_original(text: str):
    """
    Output ikut resit (bukan terjemah):
      - contoh: "Successful ✅"
      - contoh: "Pending ‼️"
    Rules:
      - Jika jumpa positive -> ✅
      - Jika jumpa negative (dan tiada positive) -> ‼️
      - Jika tak jumpa -> "Status tidak pasti ❓"
    """
    # guna versi status-normalized untuk detect
    t_norm = normalize_for_status(text)
    t_low = t_norm.lower()

    # 1) scan POSITIVE dulu (kalau dua-dua ada, positive menang)
    for kw in POSITIVE_KW:
        if kw in t_low:
            # ambil balik ejaan asal dari teks (try original text dulu)
            orig = _find_status_original(text, kw) or kw
            return (orig.strip(), "✅")

    # 2) scan NEGATIVE
    for kw in NEGATIVE_KW:
        if kw in t_low:
            orig = _find_status_original(text, kw) or kw
            return (orig.strip(), "‼️")

    return ("Status tidak pasti", "❓")

# ================== BOT HANDLER ==================
@app.on_message(filters.photo)
async def ocr_photo(_, message):
    photo_path = None
    try:
        photo_path = await message.download()
        with io.open(photo_path, "rb") as f:
            content = f.read()

        image = vision.Image(content=content)

        resp = vision_client.document_text_detection(image=image)

        if resp.error and resp.error.message:
            await message.reply_text(f"❌ OCR Error: {resp.error.message}")
            return

        text = resp.full_text_annotation.text.strip() if resp.full_text_annotation and resp.full_text_annotation.text else ""
        if not text:
            await message.reply_text("❌ OCR tak jumpa teks (cuba gambar lebih jelas).")
            return

        # 1) ACCOUNT
        ok_acc = account_found(text)
        line1 = build_line(f"{TARGET_ACC} {TARGET_BANK}", "No akaun tidak sah", ok_acc, "✅", "❌")

        # 2) DATETIME
        dt = parse_datetime(text)
        ok_dt = dt is not None
        line2 = build_line(format_dt(dt) if ok_dt else "", "Tarikh tidak dijumpai", ok_dt, "✅", "❌")

        # 3) AMOUNT
        amt = parse_amount(text)
        ok_amt = amt is not None
        line3 = build_line(format_amount_rm(amt) if ok_amt else "", "Total tidak dijumpai", ok_amt, "✅", "❌")

        # 4) STATUS (ikut resit)
        status_text, status_emoji = detect_payment_status_original(text)
        line4 = f"{status_text} {status_emoji}"

        reply = f"{line1}\n{line2}\n{line3}\n{line4}"
        if len(reply) > MAX_REPLY_CHARS:
            reply = reply[:MAX_REPLY_CHARS] + "\n...\n(terlalu panjang)"

        await message.reply_text(reply)

    except Exception as e:
        await message.reply_text(f"❌ Error: {type(e).__name__}: {e}")

    finally:
        if photo_path:
            try:
                os.remove(photo_path)
            except:
                pass

app.run()
