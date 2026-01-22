# =========================
# ATV PANTAI TIMOR BOT
# + OCR skrip (Google Vision)
# + Lepas tekan PAYMENT SETTLE:
#   - Ayat "SLIDE KIRI TAMBAH RESIT" hilang
#   - Diganti dengan hasil OCR UNTUK SEMUA RESIT (maks 9 dalam album, tapi OCR boleh simpan lebih)
# + Butang "BUTANG SEMAK BAYARAN" akan re-run OCR untuk SEMUA RESIT dan update caption album
# + ✅ PAYMENT SETTLE ADA PASSWORD KEYPAD (0-9 + BACK + OKEY)
# =========================

import os, io, re, tempfile
from datetime import datetime

import pytz
from pyrogram import Client, filters
from pyrogram.errors import MessageDeleteForbidden, ChatAdminRequired
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto

from google.cloud import vision  # ✅ OCR skrip

# ================= ENV =================
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Missing API_ID / API_HASH / BOT_TOKEN in Railway Variables")

# ================= PASSWORD SETTINGS =================
# Set dekat Railway env: PAYMENT_PIN=1234
PAYMENT_PIN = os.getenv("PAYMENT_PIN", "1234").strip()
MAX_PIN_TRIES = 5  # berapa kali salah sebelum reset paksa

# ================= OCR SETTINGS (OCR skrip) =================
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

vision_client = vision.ImageAnnotatorClient()

# ================= BOT =================
bot = Client(
    "atv_bot_2026",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ================= TEMP STATE (RAM) =================
# Key ORDER_STATE:
# - Semasa belum LOCK: key = anchor msg id (gambar order)
# - Selepas rebuild album: key = control msg id (mesej butang bawah)
ORDER_STATE = {}

# Mapping reply untuk album image -> control_msg_id
REPLY_MAP = {}

# ================= DATA =================
PRODUK_LIST = {
    "125_FULL": "125 FULL SPEC",
    "125_BIG": "125 BIG BODY",
    "YAMA": "YAMA SPORT",
    "GY6": "GY6 200CC",
    "HAMMER_ARM": "HAMMER ARMOUR",
    "BIG_HAMMER": "BIG HAMMER",
    "TROLI_BESI": "TROLI BESI",
    "TROLI_PLASTIK": "TROLI PLASTIK",
}

HARGA_START = 2500
HARGA_END = 3000
HARGA_STEP = 10
HARGA_LIST = list(range(HARGA_START, HARGA_END + 1, HARGA_STEP))
HARGA_PER_PAGE = 15  # 3 baris x 5 butang

DEST_LIST = [
    "JOHOR",
    "KEDAH",
    "KELANTAN",
    "MELAKA",
    "NEGERI SEMBILAN",
    "PAHANG",
    "PERAK",
    "PERLIS",
    "PULAU PINANG",
    "SELANGOR",
    "TERENGGANU",
    "LANGKAWI",
    "PICKUP SENDIRI",
    "LORI KITA HANTAR",
]

KOS_START = 0
KOS_END = 1500
KOS_STEP = 10
KOS_LIST = list(range(KOS_START, KOS_END + 1, KOS_STEP))
KOS_PER_PAGE = 15  # 3 baris x 5 butang

# Album Telegram max 10 media: 1 order + 9 resit
MAX_RECEIPTS_IN_ALBUM = 9

# ✅ OCR yang dipaparkan dalam caption boleh jadi banyak
# tapi Telegram ada limit caption 1024 chars. Kita limit untuk stabil.
MAX_OCR_RESULTS_IN_CAPTION = 10

# ================= TEXT STYLE =================
BOLD_MAP = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
    "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
    "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"
)

def bold(text: str) -> str:
    return text.translate(BOLD_MAP)

# ================= UTIL (ORDER) =================
def is_all_prices_done(items_dict: dict, prices_dict: dict) -> bool:
    if not items_dict:
        return False
    return all(k in prices_dict for k in items_dict.keys())

def calc_products_total(items_dict: dict, prices_dict: dict) -> int:
    total = 0
    for k, qty in items_dict.items():
        unit = prices_dict.get(k)
        if unit is None:
            continue
        try:
            total += int(unit) * int(qty)
        except Exception:
            pass
    return total

def build_ocr_block(state: dict) -> str:
    """
    Gabungkan semua OCR result (ikut turutan resit).
    - Ambil state["ocr_results"] (list[str]) kalau ada
    - Limit paparan untuk stabil (caption limit 1024)
    """
    results = state.get("ocr_results") or []
    if not results:
        return ""

    show = results[-MAX_OCR_RESULTS_IN_CAPTION:]
    blocks = []
    for txt in show:
        t = (txt or "").strip()
        if not t:
            continue
        blocks.append(t)

    out = "\n\n".join(blocks)

    if len(results) > len(show):
        out += f"\n\n(+{len(results) - len(show)} resit lagi tidak dipaparkan sebab limit caption)"

    return out.strip()

def build_caption(
    base_caption: str,
    items_dict: dict,
    prices_dict: dict | None = None,
    dest: str | None = None,
    ship_cost: int | None = None,
    locked: bool = False,
    receipts_count: int = 0,
    paid: bool = False,
    state: dict | None = None,
) -> str:
    """
    ✅ BEHAVIOR:
    - LOCK + belum paid -> tunjuk arahan "SLIDE KIRI ..."
    - LOCK + sudah paid -> buang arahan slide, ganti OCR result untuk SEMUA resit dalam caption
    """
    prices_dict = prices_dict or {}
    lines = [base_caption]

    if items_dict:
        lines.append("")
        for k, q in items_dict.items():
            nama = PRODUK_LIST.get(k, k)
            unit_price = prices_dict.get(k)
            if unit_price is None:
                harga_display = "-"
            else:
                try:
                    total_line = int(unit_price) * int(q)
                    harga_display = f"RM{total_line}"
                except Exception:
                    harga_display = f"RM{unit_price}"
            lines.append(f"{nama} | {q} | {harga_display}")

    if dest:
        lines.append("")
        if ship_cost is None:
            lines.append(f"Destinasi : {dest}")
        else:
            lines.append(f"Destinasi : {dest} | RM{int(ship_cost)}")

    if items_dict and is_all_prices_done(items_dict, prices_dict) and ship_cost is not None:
        prod_total = calc_products_total(items_dict, prices_dict)
        grand_total = prod_total + int(ship_cost)
        lines.append("")
        lines.append(f"TOTAL KESELURUHAN : RM{grand_total}")

    if locked:
        lines.append("")
        if paid and state:
            ocr_block = build_ocr_block(state)
            if ocr_block:
                lines.append(ocr_block)
            else:
                lines.append("❌ OCR belum ada (tekan BUTANG SEMAK BAYARAN).")
        else:
            if receipts_count <= 0:
                lines.append("⬅️" + bold("SLIDE KIRI UPLOAD RESIT"))
            else:
                lines.append("⬅️" + bold("SLIDE KIRI TAMBAH RESIT"))

    cap = "\n".join(lines)
    if len(cap) > 1024:
        cap = cap[:1000] + "\n...(caption terlalu panjang)"
    return cap

# ================= KEYBOARDS =================
def build_payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("PAYMENT SETTLE", callback_data="pay_settle")]])

def build_semak_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("BUTANG SEMAK BAYARAN", callback_data="semak_bayaran")]])

def build_pin_keyboard() -> InlineKeyboardMarkup:
    """
    Keypad nombor 0-9 + BACK + OKEY
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1", callback_data="pin_1"),
            InlineKeyboardButton("2", callback_data="pin_2"),
            InlineKeyboardButton("3", callback_data="pin_3"),
        ],
        [
            InlineKeyboardButton("4", callback_data="pin_4"),
            InlineKeyboardButton("5", callback_data="pin_5"),
            InlineKeyboardButton("6", callback_data="pin_6"),
        ],
        [
            InlineKeyboardButton("7", callback_data="pin_7"),
            InlineKeyboardButton("8", callback_data="pin_8"),
            InlineKeyboardButton("9", callback_data="pin_9"),
        ],
        [
            InlineKeyboardButton("0", callback_data="pin_0"),
        ],
        [
            InlineKeyboardButton("🔙 BACK", callback_data="pin_back"),
            InlineKeyboardButton("✅ OKEY", callback_data="pin_ok"),
        ],
    ])

def mask_pin(buf: str) -> str:
    if not buf:
        return "(kosong)"
    return "•" * len(buf)

def build_pin_prompt_text(buf: str) -> str:
    return f"🔐 Sila masukkan PASSWORD untuk PAYMENT SETTLE\n\nPIN: {mask_pin(buf)}"

# ================= SAFE DELETE =================
async def safe_delete(client: Client, chat_id: int, message_id: int):
    try:
        await client.delete_messages(chat_id, message_id)
    except Exception:
        pass

async def delete_bundle(client: Client, state: dict):
    """
    Padam SEMUA bundle:
    - album (jika ada)
    - control msg (jika ada)
    - anchor msg (jika ada)
    """
    chat_id = state["chat_id"]

    for mid in (state.get("album_msg_ids") or []):
        await safe_delete(client, chat_id, mid)
        REPLY_MAP.pop(mid, None)

    if state.get("control_msg_id"):
        await safe_delete(client, chat_id, state["control_msg_id"])

    if state.get("anchor_msg_id"):
        await safe_delete(client, chat_id, state["anchor_msg_id"])

# ================= OCR skrip (helpers) =================
def normalize_ocr_text(s: str) -> str:
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

def parse_datetime(text: str):
    t = normalize_ocr_text(text)

    p_time = re.compile(r"\b(\d{1,2})[:\.](\d{2})(?:[:\.](\d{2}))?\s*(am|pm)?\b", re.I)

    mon_map = {
        "jan": 1, "january": 1, "januari": 1,
        "feb": 2, "february": 2, "februari": 2,
        "mar": 3, "march": 3, "mac": 3,
        "apr": 4, "april": 4,
        "may": 5, "mei": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7, "julai": 7,
        "aug": 8, "august": 8, "ogos": 8,
        "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10, "oktober": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12, "disember": 12,
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
    except Exception:
        return None

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
        except Exception:
            continue
        candidates.append((score_match(val, m.start()) + 1000, val))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]

def format_amount_rm(val: float) -> str:
    return f"RM{val:.2f}"

POSITIVE_KW = [
    "transaction successful", "payment successful", "transfer successful",
    "successful", "success", "completed", "complete",
    "paid", "payment received", "funds received", "received",
    "credited", "approved", "verified", "posted", "settled", "processed",
    "berjaya diproses", "transaksi berjaya", "pembayaran berjaya",
    "pemindahan berjaya", "diterima", "telah diterima", "sudah masuk",
    "dana diterima", "dikreditkan", "diluluskan", "selesai", "telah selesai",
]

NEGATIVE_KW = [
    "pending settlement", "scheduled transfer", "future dated", "effective date",
    "pending", "processing", "in progress", "queued", "awaiting", "awaiting confirmation",
    "not received", "unpaid", "failed", "unsuccessful", "rejected", "declined",
    "cancelled", "canceled", "reversed", "refunded", "void", "timeout", "timed out",
    "belum masuk", "belum diterima", "belum terima", "dalam proses",
    "sedang diproses", "menunggu pengesahan", "gagal", "tidak berjaya", "ditolak",
    "dibatalkan", "dipulangkan", "diproses semula",
    "ibg", "interbank giro",
]

def detect_status_original(text: str) -> str:
    t = normalize_ocr_text(text).lower()

    pos_hit = None
    for kw in sorted(POSITIVE_KW, key=len, reverse=True):
        if kw in t:
            pos_hit = kw
            break

    neg_hit = None
    for kw in sorted(NEGATIVE_KW, key=len, reverse=True):
        if kw in t:
            neg_hit = kw
            break

    if pos_hit:
        return f"{pos_hit} ✅"
    if neg_hit:
        return f"{neg_hit} ‼️"
    return "Status tidak pasti ❓"

async def run_ocr_on_receipt_file_id(client: Client, file_id: str) -> str:
    tmp_path = None
    try:
        tmp_path = await client.download_media(file_id)
        with io.open(tmp_path, "rb") as f:
            content = f.read()

        image = vision.Image(content=content)
        resp = vision_client.document_text_detection(image=image)

        if resp.error and resp.error.message:
            return f"❌ OCR Error: {resp.error.message}"

        text = resp.full_text_annotation.text.strip() if resp.full_text_annotation and resp.full_text_annotation.text else ""
        if not text:
            return "❌ OCR tak jumpa teks (cuba gambar lebih jelas)."

        ok_acc = account_found(text)
        line1 = f"{TARGET_ACC} {TARGET_BANK} ✅" if ok_acc else "No akaun tidak sah ❌"

        dt = parse_datetime(text)
        line2 = f"{format_dt(dt)} ✅" if dt else "Tarikh tidak dijumpai ❌"

        amt = parse_amount(text)
        line3 = f"{format_amount_rm(amt)} ✅" if amt is not None else "Total tidak dijumpai ❌"

        line4 = detect_status_original(text)

        return "\n".join([line1, line2, line3, line4])

    except Exception as e:
        return f"❌ Error OCR: {type(e).__name__}: {e}"
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

async def run_ocr_for_all_receipts(client: Client, state: dict) -> list[str]:
    """
    ✅ OCR untuk SEMUA resit dalam state["receipts"]
    """
    receipts = state.get("receipts") or []
    results = []
    for fid in receipts:
        try:
            results.append(await run_ocr_on_receipt_file_id(client, fid))
        except Exception as e:
            results.append(f"❌ OCR Error: {type(e).__name__}: {e}")
    return results

# ================= ALBUM SENDER =================
async def send_or_rebuild_album(client: Client, state: dict) -> int:
    chat_id = state["chat_id"]

    receipts_album = list(state.get("receipts", []))[-MAX_RECEIPTS_IN_ALBUM:]
    state["receipts_album"] = receipts_album

    caption = build_caption(
        state["base_caption"],
        state.get("items", {}),
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=True,
        receipts_count=len(receipts_album),
        paid=bool(state.get("paid")),
        state=state,
    )

    media = [InputMediaPhoto(media=state["photo_id"], caption=caption)]
    for r in receipts_album:
        media.append(InputMediaPhoto(media=r))

    album_msgs = await client.send_media_group(chat_id=chat_id, media=media)
    album_ids = [m.id for m in album_msgs]
    album_first_id = album_msgs[0].id

    if state.get("paid"):
        control_text = "SEMAK OCR BAYARAN"
        control_markup = build_semak_keyboard()
    else:
        control_text = "TEKAN BUTANG DIBAWAH SAHKAN PEMBAYARAN SELESAI"
        control_markup = build_payment_keyboard()

    control = await client.send_message(
        chat_id=chat_id,
        text=control_text,
        reply_markup=control_markup
    )

    for mid in album_ids:
        REPLY_MAP[mid] = control.id

    state["album_msg_ids"] = album_ids
    state["album_first_id"] = album_first_id
    state["control_msg_id"] = control.id
    state["anchor_msg_id"] = None

    return control.id

async def deny_if_locked(state: dict, callback) -> bool:
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return False
    if state.get("locked"):
        await callback.answer("Order ini sudah LAST SUBMIT (LOCK).", show_alert=True)
        return False
    return True

# ================= KEYBOARDS (SEBELUM LOCK) =================
def build_produk_keyboard(items_dict: dict) -> InlineKeyboardMarkup:
    rows = []
    for key, name in PRODUK_LIST.items():
        if key not in items_dict:
            rows.append([InlineKeyboardButton(name, callback_data=f"produk_{key}")])
    if items_dict:
        rows.append([InlineKeyboardButton("✅ SUBMIT", callback_data="submit")])
    return InlineKeyboardMarkup(rows)

def build_qty_keyboard(produk_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1", callback_data=f"qty_{produk_key}_1"),
            InlineKeyboardButton("2", callback_data=f"qty_{produk_key}_2"),
            InlineKeyboardButton("3", callback_data=f"qty_{produk_key}_3"),
        ],
        [
            InlineKeyboardButton("4", callback_data=f"qty_{produk_key}_4"),
            InlineKeyboardButton("5", callback_data=f"qty_{produk_key}_5"),
        ],
        [InlineKeyboardButton("⬅️ KEMBALI", callback_data="back_produk")]
    ])

def build_harga_keyboard(items_dict: dict, prices_dict: dict | None = None) -> InlineKeyboardMarkup:
    prices_dict = prices_dict or {}
    rows = []
    for k in items_dict.keys():
        if k in prices_dict:
            continue
        nama = PRODUK_LIST.get(k, k)
        rows.append([InlineKeyboardButton(f"HARGA - {nama}", callback_data=f"harga_{k}")])

    if items_dict and all(k in prices_dict for k in items_dict.keys()):
        rows.append([InlineKeyboardButton("📍 DESTINASI", callback_data="destinasi")])

    rows.append([InlineKeyboardButton("⬅️ KEMBALI PRODUK", callback_data="back_produk")])
    return InlineKeyboardMarkup(rows)

def build_select_harga_keyboard(produk_key: str, page: int = 0) -> InlineKeyboardMarkup:
    total = len(HARGA_LIST)
    start = page * HARGA_PER_PAGE
    end = start + HARGA_PER_PAGE
    chunk = HARGA_LIST[start:end]

    rows = []
    for i in range(0, len(chunk), 5):
        row_prices = chunk[i:i + 5]
        rows.append([InlineKeyboardButton(str(p), callback_data=f"setharga_{produk_key}_{p}") for p in row_prices])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ PREV", callback_data=f"harga_page_{produk_key}_{page - 1}"))
    if end < total:
        nav.append(InlineKeyboardButton("NEXT ➡️", callback_data=f"harga_page_{produk_key}_{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton("⬅️ BACK (HARGA MENU)", callback_data="back_harga_menu")])
    return InlineKeyboardMarkup(rows)

def build_dest_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(DEST_LIST), 2):
        left = InlineKeyboardButton(DEST_LIST[i], callback_data=f"setdest_{i}")
        if i + 1 < len(DEST_LIST):
            right = InlineKeyboardButton(DEST_LIST[i + 1], callback_data=f"setdest_{i + 1}")
            rows.append([left, right])
        else:
            rows.append([left])
    rows.append([InlineKeyboardButton("⬅️ BACK (HARGA MENU)", callback_data="back_harga_menu")])
    return InlineKeyboardMarkup(rows)

def build_after_dest_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚚 KOS PENGHANTARAN", callback_data="kos_penghantaran")],
        [InlineKeyboardButton("🗺️ TUKAR DESTINASI", callback_data="destinasi")],
        [InlineKeyboardButton("⬅️ KEMBALI PRODUK", callback_data="back_produk")]
    ])

def build_select_kos_keyboard(page: int = 0) -> InlineKeyboardMarkup:
    total = len(KOS_LIST)
    start = page * KOS_PER_PAGE
    end = start + KOS_PER_PAGE
    chunk = KOS_LIST[start:end]

    rows = []
    for i in range(0, len(chunk), 5):
        row_cost = chunk[i:i + 5]
        rows.append([InlineKeyboardButton(str(c), callback_data=f"setkos_{c}") for c in row_cost])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ PREV", callback_data=f"kos_page_{page - 1}"))
    if end < total:
        nav.append(InlineKeyboardButton("NEXT ➡️", callback_data=f"kos_page_{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton("⬅️ BACK (MENU DESTINASI)", callback_data="back_after_dest")])
    return InlineKeyboardMarkup(rows)

def build_after_cost_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ LAST SUBMIT", callback_data="last_submit")],
        [InlineKeyboardButton("✏️ TUKAR KOS PENGHANTARAN", callback_data="kos_penghantaran")],
        [InlineKeyboardButton("🗺️ TUKAR DESTINASI", callback_data="destinasi")],
        [InlineKeyboardButton("⬅️ KEMBALI PRODUK", callback_data="back_produk")],
    ])

# ================= CALLBACKS =================
@bot.on_callback_query(filters.regex(r"^hantar_detail$"))
async def senarai_produk(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    await callback.message.edit_reply_markup(reply_markup=build_produk_keyboard(state["items"]))
    await callback.answer()

@bot.on_callback_query(filters.regex(r"^back_produk$"))
async def back_produk(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    await callback.message.edit_reply_markup(reply_markup=build_produk_keyboard(state["items"]))
    await callback.answer()

@bot.on_callback_query(filters.regex(r"^produk_"))
async def pilih_kuantiti(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    produk_key = callback.data.replace("produk_", "", 1)
    await callback.message.edit_reply_markup(reply_markup=build_qty_keyboard(produk_key))
    await callback.answer("Pilih kuantiti")

@bot.on_callback_query(filters.regex(r"^qty_"))
async def simpan_qty_repost(client, callback):
    msg = callback.message
    old_id = msg.id
    state = ORDER_STATE.get(old_id)
    if not await deny_if_locked(state, callback):
        return

    try:
        payload = callback.data[len("qty_"):]
        produk_key, qty_str = payload.rsplit("_", 1)
        qty = int(qty_str)
    except Exception:
        await callback.answer("Format kuantiti tidak sah.", show_alert=True)
        return

    state["items"][produk_key] = qty
    await callback.answer("Dikemaskini")

    caption_baru = build_caption(
        state["base_caption"],
        state["items"],
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=bool(state.get("locked")),
        receipts_count=len(state.get("receipts", [])),
        paid=bool(state.get("paid")),
        state=state,
    )

    try:
        await msg.delete()
    except Exception:
        pass

    new_msg = await client.send_photo(
        chat_id=state["chat_id"],
        photo=state["photo_id"],
        caption=caption_baru,
        reply_markup=build_produk_keyboard(state["items"]),
    )

    ORDER_STATE[new_msg.id] = {**state, "anchor_msg_id": new_msg.id}
    ORDER_STATE.pop(old_id, None)

@bot.on_callback_query(filters.regex(r"^submit$"))
async def submit_order(client, callback):
    msg = callback.message
    old_id = msg.id
    state = ORDER_STATE.get(old_id)
    if not await deny_if_locked(state, callback):
        return
    if not state["items"]:
        await callback.answer("Sila pilih sekurang-kurangnya 1 produk dulu.", show_alert=True)
        return

    await callback.answer("Submit...")

    caption_baru = build_caption(
        state["base_caption"],
        state["items"],
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=bool(state.get("locked")),
        receipts_count=len(state.get("receipts", [])),
        paid=bool(state.get("paid")),
        state=state,
    )

    kb = build_harga_keyboard(state["items"], state.get("prices", {}))

    try:
        await msg.delete()
    except Exception:
        pass

    new_msg = await client.send_photo(
        chat_id=state["chat_id"],
        photo=state["photo_id"],
        caption=caption_baru,
        reply_markup=kb
    )

    ORDER_STATE[new_msg.id] = {**state, "anchor_msg_id": new_msg.id}
    ORDER_STATE.pop(old_id, None)

@bot.on_callback_query(filters.regex(r"^harga_"))
async def buka_senarai_harga(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    produk_key = callback.data.replace("harga_", "", 1)
    await callback.message.edit_reply_markup(reply_markup=build_select_harga_keyboard(produk_key, page=0))
    await callback.answer("Pilih harga")

@bot.on_callback_query(filters.regex(r"^harga_page_"))
async def harga_pagination(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    payload = callback.data[len("harga_page_"):]
    try:
        produk_key, page_str = payload.rsplit("_", 1)
        page = int(page_str)
    except Exception:
        await callback.answer("Pagination tidak sah.", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=build_select_harga_keyboard(produk_key, page=page))
    await callback.answer()

@bot.on_callback_query(filters.regex(r"^back_harga_menu$"))
async def back_harga_menu(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    kb = build_harga_keyboard(state["items"], state.get("prices", {}))
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@bot.on_callback_query(filters.regex(r"^setharga_"))
async def set_harga(client, callback):
    msg = callback.message
    old_id = msg.id
    state = ORDER_STATE.get(old_id)
    if not await deny_if_locked(state, callback):
        return

    payload = callback.data[len("setharga_"):]
    try:
        produk_key, harga_str = payload.rsplit("_", 1)
        harga = int(harga_str)
    except Exception:
        await callback.answer("Format harga tidak sah.", show_alert=True)
        return

    state["prices"][produk_key] = harga
    await callback.answer("Harga diset")

    caption_baru = build_caption(
        state["base_caption"],
        state["items"],
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=bool(state.get("locked")),
        receipts_count=len(state.get("receipts", [])),
        paid=bool(state.get("paid")),
        state=state,
    )

    kb = build_harga_keyboard(state["items"], state.get("prices", {}))

    try:
        await msg.delete()
    except Exception:
        pass

    new_msg = await client.send_photo(
        chat_id=state["chat_id"],
        photo=state["photo_id"],
        caption=caption_baru,
        reply_markup=kb
    )

    ORDER_STATE[new_msg.id] = {**state, "anchor_msg_id": new_msg.id}
    ORDER_STATE.pop(old_id, None)

@bot.on_callback_query(filters.regex(r"^destinasi$"))
async def buka_destinasi(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    if not is_all_prices_done(state.get("items", {}), state.get("prices", {})):
        await callback.answer("Sila lengkapkan harga dulu.", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=build_dest_keyboard())
    await callback.answer("Pilih destinasi")

@bot.on_callback_query(filters.regex(r"^setdest_"))
async def set_destinasi(client, callback):
    msg = callback.message
    old_id = msg.id
    state = ORDER_STATE.get(old_id)
    if not await deny_if_locked(state, callback):
        return

    try:
        idx = int(callback.data.replace("setdest_", "", 1))
        dest = DEST_LIST[idx]
    except Exception:
        await callback.answer("Destinasi tidak sah.", show_alert=True)
        return

    state["dest"] = dest
    state["ship_cost"] = None
    await callback.answer(f"Destinasi: {dest}")

    caption_baru = build_caption(
        state["base_caption"],
        state["items"],
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=bool(state.get("locked")),
        receipts_count=len(state.get("receipts", [])),
        paid=bool(state.get("paid")),
        state=state,
    )

    try:
        await msg.delete()
    except Exception:
        pass

    new_msg = await client.send_photo(
        chat_id=state["chat_id"],
        photo=state["photo_id"],
        caption=caption_baru,
        reply_markup=build_after_dest_keyboard()
    )

    ORDER_STATE[new_msg.id] = {**state, "anchor_msg_id": new_msg.id}
    ORDER_STATE.pop(old_id, None)

@bot.on_callback_query(filters.regex(r"^back_after_dest$"))
async def back_after_dest(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    if state.get("ship_cost") is not None:
        await callback.message.edit_reply_markup(reply_markup=build_after_cost_keyboard())
    else:
        await callback.message.edit_reply_markup(reply_markup=build_after_dest_keyboard())
    await callback.answer()

@bot.on_callback_query(filters.regex(r"^kos_penghantaran$"))
async def buka_kos_penghantaran(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    if not state.get("dest"):
        await callback.answer("Sila pilih DESTINASI dulu.", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=build_select_kos_keyboard(page=0))
    await callback.answer("Pilih kos penghantaran")

@bot.on_callback_query(filters.regex(r"^kos_page_"))
async def kos_pagination(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    try:
        page = int(callback.data.replace("kos_page_", "", 1))
    except Exception:
        await callback.answer("Pagination tidak sah.", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=build_select_kos_keyboard(page=page))
    await callback.answer()

@bot.on_callback_query(filters.regex(r"^setkos_"))
async def set_kos(client, callback):
    msg = callback.message
    old_id = msg.id
    state = ORDER_STATE.get(old_id)
    if not await deny_if_locked(state, callback):
        return

    try:
        kos = int(callback.data.replace("setkos_", "", 1))
    except Exception:
        await callback.answer("Kos tidak sah.", show_alert=True)
        return

    state["ship_cost"] = kos
    await callback.answer(f"Kos diset: {kos}")

    caption_baru = build_caption(
        state["base_caption"],
        state["items"],
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=bool(state.get("locked")),
        receipts_count=len(state.get("receipts", [])),
        paid=bool(state.get("paid")),
        state=state,
    )

    try:
        await msg.delete()
    except Exception:
        pass

    new_msg = await client.send_photo(
        chat_id=state["chat_id"],
        photo=state["photo_id"],
        caption=caption_baru,
        reply_markup=build_after_cost_keyboard()
    )

    ORDER_STATE[new_msg.id] = {**state, "anchor_msg_id": new_msg.id}
    ORDER_STATE.pop(old_id, None)

# ====== LAST SUBMIT (LOCK) ======
@bot.on_callback_query(filters.regex(r"^last_submit$"))
async def last_submit(client, callback):
    msg = callback.message
    old_id = msg.id
    state = ORDER_STATE.get(old_id)

    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    if not state.get("items"):
        await callback.answer("Item kosong.", show_alert=True)
        return
    if not is_all_prices_done(state.get("items", {}), state.get("prices", {})):
        await callback.answer("Harga belum lengkap.", show_alert=True)
        return
    if not state.get("dest"):
        await callback.answer("Destinasi belum dipilih.", show_alert=True)
        return
    if state.get("ship_cost") is None:
        await callback.answer("Kos penghantaran belum dipilih.", show_alert=True)
        return

    state["locked"] = True
    state.setdefault("receipts", [])
    state.setdefault("paid", False)
    state.setdefault("paid_at", None)
    state.setdefault("paid_by", None)
    state.setdefault("ocr_results", [])

    # ✅ PIN STATE
    state["pin_mode"] = False
    state["pin_active_user"] = None
    state["pin_buffer"] = ""
    state["pin_tries"] = 0

    state["album_msg_ids"] = None
    state["album_first_id"] = None
    state["control_msg_id"] = None
    state["anchor_msg_id"] = old_id

    await callback.answer("Last submit ✅")

    caption_baru = build_caption(
        state["base_caption"],
        state["items"],
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=True,
        receipts_count=len(state.get("receipts", [])),
        paid=False,
        state=state,
    )

    try:
        await msg.edit_caption(caption=caption_baru, reply_markup=None)
    except Exception:
        try:
            await msg.delete()
        except Exception:
            pass
        new_msg = await client.send_photo(
            chat_id=state["chat_id"],
            photo=state["photo_id"],
            caption=caption_baru
        )
        ORDER_STATE[new_msg.id] = {**state, "anchor_msg_id": new_msg.id}
        ORDER_STATE.pop(old_id, None)
        return

    ORDER_STATE[old_id] = state

# ================= PAYMENT SETTLE (PASSWORD FLOW) =================
async def do_payment_settle_after_pin(client: Client, callback, state: dict):
    """
    Proses settle sebenar: OCR semua resit + rebuild album
    """
    receipts = state.get("receipts") or []
    if not receipts:
        await callback.answer("Tiada resit. Sila upload resit dulu.", show_alert=True)
        return

    await callback.answer("Proses OCR semua resit & settle...")

    tz = pytz.timezone("Asia/Kuala_Lumpur")
    now = datetime.now(tz)
    state["paid"] = True
    state["paid_at"] = now.strftime("%d/%m/%Y %I:%M%p").lower()
    state["paid_by"] = callback.from_user.id if callback.from_user else None

    # ✅ OCR semua resit
    state["ocr_results"] = await run_ocr_for_all_receipts(client, state)

    # reset PIN mode
    state["pin_mode"] = False
    state["pin_active_user"] = None
    state["pin_buffer"] = ""
    state["pin_tries"] = 0

    # padam bundle lama (album/control/anchor)
    await delete_bundle(client, state)

    # rebuild album
    new_control_id = await send_or_rebuild_album(client, state)

    # rebind key state
    for k in list(ORDER_STATE.keys()):
        if ORDER_STATE.get(k) is state:
            ORDER_STATE.pop(k, None)
    ORDER_STATE[new_control_id] = state

@bot.on_callback_query(filters.regex(r"^pay_settle$"))
async def pay_settle_password_start(client, callback):
    """
    Bila tekan PAYMENT SETTLE -> keluar keypad PIN
    """
    control_id = callback.message.id
    state = ORDER_STATE.get(control_id)

    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return
    if not state.get("locked"):
        await callback.answer("Sila LAST SUBMIT dulu.", show_alert=True)
        return

    # kalau dah paid, tak perlu settle
    if state.get("paid"):
        await callback.answer("Order ini sudah PAID ✅", show_alert=True)
        return

    user_id = callback.from_user.id if callback.from_user else None
    if not user_id:
        await callback.answer("User tidak sah.", show_alert=True)
        return

    # lock keypad utk 1 user sahaja
    active = state.get("pin_active_user")
    if active and active != user_id:
        await callback.answer("Keypad sedang digunakan oleh user lain.", show_alert=True)
        return

    state["pin_mode"] = True
    state["pin_active_user"] = user_id
    state["pin_buffer"] = ""
    state["pin_tries"] = 0

    try:
        await callback.message.edit_text(
            build_pin_prompt_text(state["pin_buffer"]),
            reply_markup=build_pin_keyboard()
        )
    except Exception:
        pass

    await callback.answer("Masukkan password")

# ===== PIN INPUT DIGITS =====
@bot.on_callback_query(filters.regex(r"^pin_[0-9]$"))
async def pin_press_digit(client, callback):
    control_id = callback.message.id
    state = ORDER_STATE.get(control_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    if not state.get("pin_mode"):
        await callback.answer("Sila tekan PAYMENT SETTLE dulu.", show_alert=True)
        return

    user_id = callback.from_user.id if callback.from_user else None
    if state.get("pin_active_user") != user_id:
        await callback.answer("Ini bukan keypad anda.", show_alert=True)
        return

    digit = callback.data.split("_", 1)[1]

    # limit panjang buffer
    buf = state.get("pin_buffer", "")
    if len(buf) >= max(4, len(PAYMENT_PIN)):
        await callback.answer("PIN sudah cukup, tekan OKEY.", show_alert=True)
        return

    state["pin_buffer"] = buf + digit

    try:
        await callback.message.edit_text(
            build_pin_prompt_text(state["pin_buffer"]),
            reply_markup=build_pin_keyboard()
        )
    except Exception:
        pass

    await callback.answer()

# ===== PIN BACK =====
@bot.on_callback_query(filters.regex(r"^pin_back$"))
async def pin_back(client, callback):
    control_id = callback.message.id
    state = ORDER_STATE.get(control_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    user_id = callback.from_user.id if callback.from_user else None
    if state.get("pin_active_user") and state.get("pin_active_user") != user_id:
        await callback.answer("Ini bukan keypad anda.", show_alert=True)
        return

    # reset pin mode
    state["pin_mode"] = False
    state["pin_active_user"] = None
    state["pin_buffer"] = ""
    state["pin_tries"] = 0

    try:
        await callback.message.edit_text(
            "TEKAN BUTANG DIBAWAH SAHKAN PEMBAYARAN SELESAI",
            reply_markup=build_payment_keyboard()
        )
    except Exception:
        pass

    await callback.answer("Kembali")

# ===== PIN OKEY =====
@bot.on_callback_query(filters.regex(r"^pin_ok$"))
async def pin_ok(client, callback):
    control_id = callback.message.id
    state = ORDER_STATE.get(control_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    if not state.get("pin_mode"):
        await callback.answer("Sila tekan PAYMENT SETTLE dulu.", show_alert=True)
        return

    user_id = callback.from_user.id if callback.from_user else None
    if state.get("pin_active_user") != user_id:
        await callback.answer("Ini bukan keypad anda.", show_alert=True)
        return

    buf = state.get("pin_buffer", "")

    if not buf:
        await callback.answer("PIN kosong. Sila tekan nombor.", show_alert=True)
        return

    # semak
    if buf == PAYMENT_PIN:
        # betul
        await do_payment_settle_after_pin(client, callback, state)
        return

    # salah
    state["pin_tries"] = int(state.get("pin_tries", 0)) + 1
    state["pin_buffer"] = ""

    if state["pin_tries"] >= MAX_PIN_TRIES:
        # reset & keluar
        state["pin_mode"] = False
        state["pin_active_user"] = None
        state["pin_tries"] = 0
        state["pin_buffer"] = ""

        try:
            await callback.message.edit_text(
                "❌ Password salah terlalu banyak kali.\n\nTEKAN BUTANG DIBAWAH SAHKAN PEMBAYARAN SELESAI",
                reply_markup=build_payment_keyboard()
            )
        except Exception:
            pass

        await callback.answer("Salah banyak kali. Reset.", show_alert=True)
        return

    try:
        await callback.message.edit_text(
            f"❌ Password salah. Cuba lagi.\n\n{build_pin_prompt_text(state['pin_buffer'])}",
            reply_markup=build_pin_keyboard()
        )
    except Exception:
        pass

    await callback.answer("Password salah", show_alert=True)

# ================= BUTANG SEMAK BAYARAN (OCR semua resit + update caption) =================
@bot.on_callback_query(filters.regex(r"^semak_bayaran$"))
async def semak_bayaran(client, callback):
    control_id = callback.message.id
    state = ORDER_STATE.get(control_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    receipts = state.get("receipts") or []
    if not receipts:
        await callback.answer("Tiada resit untuk disemak.", show_alert=True)
        return

    await callback.answer("Semak OCR semua resit...")

    state["ocr_results"] = await run_ocr_for_all_receipts(client, state)

    if state.get("album_first_id"):
        new_caption = build_caption(
            state["base_caption"],
            state.get("items", {}),
            state.get("prices", {}),
            state.get("dest"),
            state.get("ship_cost"),
            locked=True,
            receipts_count=len(state.get("receipts_album", []) or []),
            paid=True,
            state=state,
        )
        try:
            await client.edit_message_caption(
                chat_id=state["chat_id"],
                message_id=state["album_first_id"],
                caption=new_caption
            )
        except Exception:
            pass

# ================= PHOTO HANDLER =================
@bot.on_message(filters.photo & ~filters.bot)
async def handle_photo(client, message):
    chat_id = message.chat.id

    # ---------- KES B: RESIT (SWIPE REPLY) ----------
    if message.reply_to_message:
        replied_id = message.reply_to_message.id

        control_id = None
        state = None

        if replied_id in ORDER_STATE:
            state = ORDER_STATE.get(replied_id)
            control_id = replied_id
        elif replied_id in REPLY_MAP:
            control_id = REPLY_MAP[replied_id]
            state = ORDER_STATE.get(control_id)

        if state and state.get("locked"):
            try:
                await message.delete()
            except Exception:
                pass

            state.setdefault("receipts", [])
            state["receipts"].append(message.photo.file_id)

            # bila tambah resit selepas paid, reset paid->False supaya staff settle semula
            if state.get("paid"):
                state["paid"] = False
                state["paid_at"] = None
                state["paid_by"] = None

            state.setdefault("ocr_results", [])

            await delete_bundle(client, state)
            new_control_id = await send_or_rebuild_album(client, state)

            for k in list(ORDER_STATE.keys()):
                if ORDER_STATE.get(k) is state:
                    ORDER_STATE.pop(k, None)
            ORDER_STATE[new_control_id] = state
            return

    # ---------- KES A: ORDER BARU ----------
    photo_id = message.photo.file_id

    tz = pytz.timezone("Asia/Kuala_Lumpur")
    now = datetime.now(tz)

    hari = ["Isnin", "Selasa", "Rabu", "Khamis", "Jumaat", "Sabtu", "Ahad"][now.weekday()]
    tarikh = f"{now.day}/{now.month}/{now.year}"
    jam = now.strftime("%I:%M%p").lower()
    base_caption = f"{hari} | {tarikh} | {jam}"

    keyboard_awal = InlineKeyboardMarkup([
        [InlineKeyboardButton("NAMA PRODUK", callback_data="hantar_detail")]
    ])

    try:
        await message.delete()
    except (MessageDeleteForbidden, ChatAdminRequired):
        pass
    except Exception:
        pass

    sent = await client.send_photo(
        chat_id=chat_id,
        photo=photo_id,
        caption=base_caption,
        reply_markup=keyboard_awal
    )

    ORDER_STATE[sent.id] = {
        "chat_id": chat_id,
        "photo_id": photo_id,
        "base_caption": base_caption,
        "items": {},
        "prices": {},
        "dest": None,
        "ship_cost": None,
        "receipts": [],
        "receipts_album": [],
        "paid": False,
        "paid_at": None,
        "paid_by": None,
        "locked": False,

        "anchor_msg_id": sent.id,
        "album_msg_ids": None,
        "album_first_id": None,
        "control_msg_id": None,

        "ocr_results": [],

        # PIN
        "pin_mode": False,
        "pin_active_user": None,
        "pin_buffer": "",
        "pin_tries": 0,
    }

if __name__ == "__main__":
    bot.run()

