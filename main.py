import os, io, re, tempfile
from datetime import datetime
from pyrogram import Client, filters
from google.cloud import vision

# ================== SETTINGS ==================
TARGET_ACC = "8606018423"
TARGET_BANK = "CIMB BANK"
MAX_REPLY_CHARS = 3500

# ================== GOOGLE CREDS (Railway Env) ==================
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

# ================== TELEGRAM ==================
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Missing API_ID / API_HASH / BOT_TOKEN")

app = Client("ocr_receipt_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ================== VISION ==================
vision_client = vision.ImageAnnotatorClient()

# ================== HELPERS ==================
def normalize_ocr_text(s: str) -> str:
    """
    Kemaskan OCR (minima, selamat).
    Nota: sengaja TIDAK tukar 'l'->'1' supaya Julai/Disember tak rosak.
    """
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

    for m in p_time.finditer(t):
        times.append((m.start(), (m.group(1), m.group(2), m.group(4))))

    if not dates:
        return None

    # Pair nearest date-time
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
    """
    Ambil amount dengan sen.
    Prioriti RM/MYR dahulu.
    """
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

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    return None

def format_amount_rm(val: float) -> str:
    return f"RM{val:.2f}"

# ================== STATUS (YOUR LIST ONLY) ==================
POSITIVE_KW = [
    # English ✅
    "successful", "success", "completed", "complete",
    "transaction successful", "payment successful", "transfer successful",
    "paid", "payment received", "received", "funds received",
    "credited", "credit", "approved", "verified", "posted",
    "settled", "processed",

    # BM ✅
    "berjaya", "berjaya diproses", "transaksi berjaya", "pembayaran berjaya",
    "pemindahan berjaya", "diterima", "telah diterima", "sudah masuk",
    "dana diterima", "dikreditkan", "diluluskan", "selesai", "telah selesai",
    "berjaya dihantar",
]

NEGATIVE_KW = [
    # English ‼️
    "pending", "processing", "in progress", "queued", "awaiting", "awaiting confirmation",
    "not received", "unpaid", "failed", "unsuccessful", "rejected", "declined",
    "cancelled", "canceled", "reversed", "refunded", "void", "timeout", "timed out",

    # BM ‼️
    "belum masuk", "belum diterima", "belum terima", "belum berjaya", "dalam proses",
    "sedang diproses", "menunggu pengesahan", "gagal", "tidak berjaya", "ditolak",
    "dibatalkan", "dipulangkan", "diproses semula",

    # Istilah bank ‼️
    "ibg", "interbank giro", "scheduled transfer", "future dated", "effective date", "pending settlement",
]

def detect_payment_status(text: str):
    """
    Output: (label, emoji)
      - jika jumpa NEGATIVE -> "Duit belum masuk" ‼️
      - jika jumpa POSITIVE -> "Duit sudah masuk" ✅
      - jika tak jumpa -> "Status tidak pasti" ❓
    Nota: kalau ada NEGATIVE + POSITIVE serentak, pilih POSITIVE (✅).
    """
    t = normalize_ocr_text(text).lower()

    has_pos = any(k in t for k in POSITIVE_KW)
    has_neg = any(k in t for k in NEGATIVE_KW)

    if has_neg and not has_pos:
        return ("Duit belum masuk", "‼️")
    if has_pos:
        return ("Duit sudah masuk", "✅")
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
        resp = vision_client.text_detection(image=image)

        if resp.error and resp.error.message:
            await message.reply_text(f"❌ OCR Error: {resp.error.message}")
            return

        text = (resp.text_annotations[0].description.strip()
                if resp.text_annotations else "")

        if not text:
            await message.reply_text("❌ OCR tak jumpa teks (cuba gambar lebih jelas).")
            return

        # 1) ACCOUNT
        ok_acc = account_found(text)
        line1 = build_line(
            f"{TARGET_ACC} {TARGET_BANK}",
            "No akaun tidak sah",
            ok_acc,
            ok_emoji="✅",
            bad_emoji="❌"
        )

        # 2) DATETIME
        dt = parse_datetime(text)
        ok_dt = dt is not None
        line2 = build_line(
            format_dt(dt) if ok_dt else "",
            "Tarikh tidak dijumpai",
            ok_dt,
            ok_emoji="✅",
            bad_emoji="❌"
        )

        # 3) AMOUNT
        amt = parse_amount(text)
        ok_amt = amt is not None
        line3 = build_line(
            format_amount_rm(amt) if ok_amt else "",
            "Total tidak dijumpai",
            ok_amt,
            ok_emoji="✅",
            bad_emoji="❌"
        )

        # 4) STATUS
        status_text, status_emoji = detect_payment_status(text)
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

