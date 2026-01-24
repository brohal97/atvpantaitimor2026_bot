# =========================
# ATV PANTAI TIMOR BOT
# + OCR skrip (Google Vision)
# + PAYMENT SETTLE ada password keypad
# + SEMAK BAYARAN: hanya user tertentu + keypad password
#   - betul -> OCR semua resit -> COPY ke channel rasmi -> delete dalam group
# + BACK (GLOBAL): undo 1 langkah + padam selection 1 langkah
# + INPUT HARGA & KOS TRANSPORT: keypad nombor manual (0-9) + BACKSPACE + OKEY
#   - BACK pada keypad = padam 1 digit (kalau kosong, cancel balik 1 halaman)
# =========================

import os, io, re, tempfile, traceback
from datetime import datetime
from typing import Dict, List, Optional, Set, Any, Tuple

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
PAYMENT_PIN = os.getenv("PAYMENT_PIN", "1234").strip()
MAX_PIN_TRIES = 5


# ================= SEMAK BAYARAN (ROLE + PIN + CHANNEL) =================
OFFICIAL_CHANNEL_ID = int(os.getenv("OFFICIAL_CHANNEL_ID", "-1003573894188"))  # contoh: -1001234567890
if not OFFICIAL_CHANNEL_ID:
    raise RuntimeError("Missing env var: OFFICIAL_CHANNEL_ID (channel rasmi)")

SEMAK_PIN = os.getenv("SEMAK_PIN", "4321").strip()
SEMAK_ALLOWED_IDS_RAW = os.getenv("SEMAK_ALLOWED_IDS", "1150078068").strip()


def parse_allowed_ids(raw: str) -> Set[int]:
    out: Set[int] = set()
    if not raw:
        return out
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except Exception:
            pass
    return out


SEMAK_ALLOWED_IDS = parse_allowed_ids(SEMAK_ALLOWED_IDS_RAW)


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
ORDER_STATE: Dict[int, Dict[str, Any]] = {}   # key = message_id (order msg sebelum lock) / control msg id (selepas rebuild)
REPLY_MAP: Dict[int, int] = {}               # album message id -> control msg id


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

DEST_LIST = [
    "JOHOR", "KEDAH", "KELANTAN", "MELAKA", "NEGERI SEMBILAN", "PAHANG", "PERAK", "PERLIS",
    "PULAU PINANG", "SELANGOR", "TERENGGANU", "LANGKAWI", "PICKUP SENDIRI", "KITA HANTAR",
]

MAX_RECEIPTS_IN_ALBUM = 9
MAX_OCR_RESULTS_IN_CAPTION = 10

# input keypad limit (harga/kos) - boleh ubah kalau perlu
MAX_NUM_DIGITS = 6  # contoh: 999999


# ================= TEXT STYLE =================
BOLD_MAP = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
    "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
    "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"
)


def bold(text: str) -> str:
    return (text or "").translate(BOLD_MAP)


# ================= CUSTOM TEXT (USER REQUEST) =================
TXT_PAYMENT_CONTROL = bold("⏬Tekan butang sahkan bayaran⏬")
TXT_SEMAK_CONTROL = bold("🔻Semak pembayaran dengan segera🔻")
TXT_SEMAK_PIN_TITLE = bold("ISI PASWORD JIKA BAYARAN TELAH DISEMAK")


# ================= UTIL (ORDER) =================
def is_all_prices_done(items_dict: Dict[str, int], prices_dict: Dict[str, int]) -> bool:
    if not items_dict:
        return False
    return all(k in prices_dict for k in items_dict.keys())


def calc_products_total(items_dict: Dict[str, int], prices_dict: Dict[str, int]) -> int:
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


def build_ocr_block(state: Dict[str, Any]) -> str:
    results = state.get("ocr_results") or []
    if not results:
        return ""
    show = results[-MAX_OCR_RESULTS_IN_CAPTION:]
    blocks: List[str] = []
    for txt in show:
        t = (txt or "").strip()
        if t:
            blocks.append(t)

    out = "\n\n".join(blocks)
    if len(results) > len(show):
        out += f"\n\n(+{len(results)-len(show)} resit lagi tidak dipaparkan sebab limit caption)"
    return out.strip()


def build_caption(
    base_caption: str,
    items_dict: Dict[str, int],
    prices_dict: Optional[Dict[str, int]] = None,
    dest: Optional[str] = None,
    ship_cost: Optional[int] = None,
    locked: bool = False,
    receipts_count: int = 0,
    paid: bool = False,
    state: Optional[Dict[str, Any]] = None,
    extra_lines: Optional[List[str]] = None,
) -> str:
    prices_dict = prices_dict or {}
    lines = [bold(base_caption)]

    if items_dict:
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
            lines.append(bold(f"{nama} | {q} | {harga_display}"))

    if dest:
        if ship_cost is None:
            lines.append(f"Destinasi : {bold(dest)}")
        else:
            lines.append(f"Destinasi : {bold(f'{dest} | RM{int(ship_cost)}')}")

    if items_dict and is_all_prices_done(items_dict, prices_dict) and ship_cost is not None:
        prod_total = calc_products_total(items_dict, prices_dict)
        grand_total = prod_total + int(ship_cost)
        lines.append(f"TOTAL KESELURUHAN : {bold(f'RM{grand_total}')}")

    if extra_lines:
        lines.append("")
        lines.extend(extra_lines)

    if locked:
        if paid and state:
            lines.append("")
            ocr_block = build_ocr_block(state)
            lines.append(ocr_block if ocr_block else "❌ OCR belum ada (tekan BUTANG SEMAK BAYARAN).")
        else:
            lines.append("")
            if receipts_count <= 0:
                lines.append("⬅️" + bold("SLIDE KIRI UPLOAD RESIT"))
            else:
                lines.append("⬅️" + bold("SLIDE KIRI TAMBAH RESIT"))

    cap = "\n".join(lines)
    if len(cap) > 1024:
        cap = cap[:1000] + "\n...(caption terlalu panjang)"
    return cap


# ================= GLOBAL BACK (UNDO) =================
BACK_CB = "nav_back"


def push_history(state: Dict[str, Any], prev_view: str, prev_ctx: Dict[str, Any], undo: Optional[Dict[str, Any]] = None):
    state.setdefault("history", [])
    state["history"].append({
        "view": prev_view,
        "ctx": dict(prev_ctx or {}),
        "undo": undo
    })


def apply_undo(state: Dict[str, Any], undo: Dict[str, Any]):
    if not undo:
        return

    t = undo.get("type")

    if t == "set_qty":
        k = undo["produk_key"]
        prev = undo.get("prev")  # None => remove
        if prev is None:
            state.get("items", {}).pop(k, None)
            state.get("prices", {}).pop(k, None)  # bila item dipadam, harga item juga padam
        else:
            state.setdefault("items", {})[k] = int(prev)

    elif t == "set_price":
        k = undo["produk_key"]
        prev = undo.get("prev")
        if prev is None:
            state.get("prices", {}).pop(k, None)
        else:
            state.setdefault("prices", {})[k] = int(prev)

    elif t == "set_dest":
        state["dest"] = undo.get("prev_dest")
        state["ship_cost"] = undo.get("prev_ship_cost")

    elif t == "set_ship_cost":
        state["ship_cost"] = undo.get("prev")

    if not state.get("items"):
        state["items"] = {}
        state["prices"] = {}
        state["dest"] = None
        state["ship_cost"] = None


def pop_history_restore(state: Dict[str, Any]) -> bool:
    hist = state.get("history", [])
    if not hist:
        return False
    last = hist.pop()
    undo = last.get("undo")
    if undo:
        apply_undo(state, undo)
    state["view"] = last.get("view")
    state["ctx"] = last.get("ctx", {}) or {}
    return True


# ================= KEYBOARDS =================
def kb_back_row() -> List[InlineKeyboardButton]:
    return [InlineKeyboardButton("🔙 BACK", callback_data=BACK_CB)]


def build_payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("PAYMENT SETTLE", callback_data="pay_settle")]])


def build_semak_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("BUTANG SEMAK BAYARAN", callback_data="semak_bayaran")]])


def build_pin_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1", callback_data=f"{prefix}_1"),
            InlineKeyboardButton("2", callback_data=f"{prefix}_2"),
            InlineKeyboardButton("3", callback_data=f"{prefix}_3"),
        ],
        [
            InlineKeyboardButton("4", callback_data=f"{prefix}_4"),
            InlineKeyboardButton("5", callback_data=f"{prefix}_5"),
            InlineKeyboardButton("6", callback_data=f"{prefix}_6"),
        ],
        [
            InlineKeyboardButton("7", callback_data=f"{prefix}_7"),
            InlineKeyboardButton("8", callback_data=f"{prefix}_8"),
            InlineKeyboardButton("9", callback_data=f"{prefix}_9"),
        ],
        [InlineKeyboardButton("0", callback_data=f"{prefix}_0")],
        [
            InlineKeyboardButton("🔙 BACK", callback_data=f"{prefix}_back"),
            InlineKeyboardButton("✅ OKEY", callback_data=f"{prefix}_ok"),
        ],
    ])


# keypad nombor (harga/kos)
def build_num_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1", callback_data=f"{prefix}_1"),
            InlineKeyboardButton("2", callback_data=f"{prefix}_2"),
            InlineKeyboardButton("3", callback_data=f"{prefix}_3"),
        ],
        [
            InlineKeyboardButton("4", callback_data=f"{prefix}_4"),
            InlineKeyboardButton("5", callback_data=f"{prefix}_5"),
            InlineKeyboardButton("6", callback_data=f"{prefix}_6"),
        ],
        [
            InlineKeyboardButton("7", callback_data=f"{prefix}_7"),
            InlineKeyboardButton("8", callback_data=f"{prefix}_8"),
            InlineKeyboardButton("9", callback_data=f"{prefix}_9"),
        ],
        [InlineKeyboardButton("0", callback_data=f"{prefix}_0")],
        [
            InlineKeyboardButton("🔙 BACK", callback_data=f"{prefix}_back"),
            InlineKeyboardButton("✅ OKEY", callback_data=f"{prefix}_ok"),
        ],
    ])


def mask_pin(buf: str) -> str:
    return "(kosong)" if not buf else ("•" * len(buf))


def pin_prompt_text(title: str, buf: str) -> str:
    # kekal utk payment settle
    return f"🔐 {title}\n\nPIN: {mask_pin(buf)}"


def semak_pin_prompt_text(buf: str) -> str:
    # ikut permintaan user (bold + ayat baru)
    return f"{TXT_SEMAK_PIN_TITLE}\n\nPIN: {mask_pin(buf)}"


# ================= SAFE DELETE =================
async def safe_delete(client: Client, chat_id: int, message_id: int):
    try:
        await client.delete_messages(chat_id, message_id)
    except Exception:
        pass


async def delete_bundle(client: Client, state: Dict[str, Any]):
    chat_id = state["chat_id"]

    for mid in (state.get("album_msg_ids") or []):
        await safe_delete(client, chat_id, mid)
        REPLY_MAP.pop(mid, None)

    if state.get("control_msg_id"):
        await safe_delete(client, chat_id, state["control_msg_id"])

    if state.get("anchor_msg_id"):
        await safe_delete(client, chat_id, state["anchor_msg_id"])


# ================= MESSAGE RENDER (EDIT / FALLBACK REPOST) =================
async def replace_order_message(client: Client, msg, state: Dict[str, Any], caption: str, keyboard: Optional[InlineKeyboardMarkup]):
    """
    Cuba edit caption+keyboard. Kalau gagal, delete & hantar semula (stabil).
    Pastikan ORDER_STATE key ikut message id terbaru.
    """
    old_id = msg.id
    try:
        await msg.edit_caption(caption=caption, reply_markup=keyboard)
        return msg
    except Exception:
        pass

    try:
        await msg.delete()
    except Exception:
        pass

    new_msg = await client.send_photo(
        chat_id=state["chat_id"],
        photo=state["photo_id"],
        caption=caption,
        reply_markup=keyboard
    )

    ORDER_STATE.pop(old_id, None)
    ORDER_STATE[new_msg.id] = state
    state["anchor_msg_id"] = new_msg.id
    return new_msg


# ================= FLOW VIEWS =================
VIEW_AWAL = "awal"
VIEW_PRODUK = "produk"
VIEW_QTY = "qty"
VIEW_HARGA_MENU = "harga_menu"
VIEW_HARGA_INPUT = "harga_input"
VIEW_DEST = "dest"
VIEW_AFTER_DEST = "after_dest"
VIEW_KOS_INPUT = "kos_input"
VIEW_AFTER_COST = "after_cost"

# callback prefix keypad harga/kos
PRICE_PREFIX = "pr"
KOS_PREFIX = "tr"


def build_awal_keyboard() -> InlineKeyboardMarkup:
    # ✅ HALAMAN PERTAMA: TIADA BUTANG BACK
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("NAMA PRODUK", callback_data="hantar_detail")],
    ])


def build_produk_keyboard(items_dict: Dict[str, int]) -> InlineKeyboardMarkup:
    rows = []
    for key, name in PRODUK_LIST.items():
        if key not in items_dict:
            rows.append([InlineKeyboardButton(name, callback_data=f"produk_{key}")])

    if items_dict:
        rows.append([InlineKeyboardButton("✅ SUBMIT", callback_data="submit")])

    rows.append(kb_back_row())
    return InlineKeyboardMarkup(rows)


def build_qty_keyboard(produk_key: str) -> InlineKeyboardMarkup:
    # ✅ (1) keypad kuantiti 1-15
    rows: List[List[InlineKeyboardButton]] = []
    nums = list(range(1, 16))
    for i in range(0, len(nums), 3):
        chunk = nums[i:i+3]
        rows.append([InlineKeyboardButton(str(n), callback_data=f"qty_{produk_key}_{n}") for n in chunk])
    rows.append(kb_back_row())
    return InlineKeyboardMarkup(rows)


def build_harga_menu_keyboard(items_dict: Dict[str, int], prices_dict: Dict[str, int]) -> InlineKeyboardMarkup:
    rows = []
    for k in items_dict.keys():
        if k in prices_dict:
            continue
        nama = PRODUK_LIST.get(k, k)
        rows.append([InlineKeyboardButton(f"HARGA - {nama}", callback_data=f"harga_{k}")])

    if items_dict and all(k in prices_dict for k in items_dict.keys()):
        rows.append([InlineKeyboardButton("📍 DESTINASI", callback_data="destinasi")])

    rows.append(kb_back_row())
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
    rows.append(kb_back_row())
    return InlineKeyboardMarkup(rows)


def build_after_dest_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚚 KOS TRANSPORT", callback_data="kos_transport")],
        [InlineKeyboardButton("🗺️ TUKAR DESTINASI", callback_data="destinasi")],
        kb_back_row()
    ])


def build_after_cost_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ LAST SUBMIT", callback_data="last_submit")],
        [InlineKeyboardButton("✏️ TUKAR KOS TRANSPORT", callback_data="kos_transport")],
        [InlineKeyboardButton("🗺️ TUKAR DESTINASI", callback_data="destinasi")],
        kb_back_row()
    ])


def get_keyboard_for_view(state: Dict[str, Any]) -> InlineKeyboardMarkup:
    view = state.get("view", VIEW_AWAL)
    ctx = state.get("ctx", {}) or {}
    items = state.get("items", {}) or {}
    prices = state.get("prices", {}) or {}

    if view == VIEW_AWAL:
        return build_awal_keyboard()
    if view == VIEW_PRODUK:
        return build_produk_keyboard(items)
    if view == VIEW_QTY:
        return build_qty_keyboard(ctx.get("produk_key", ""))
    if view == VIEW_HARGA_MENU:
        return build_harga_menu_keyboard(items, prices)
    if view == VIEW_HARGA_INPUT:
        return build_num_keyboard(PRICE_PREFIX)
    if view == VIEW_DEST:
        return build_dest_keyboard()
    if view == VIEW_AFTER_DEST:
        return build_after_dest_keyboard()
    if view == VIEW_KOS_INPUT:
        return build_num_keyboard(KOS_PREFIX)
    if view == VIEW_AFTER_COST:
        return build_after_cost_keyboard()

    return build_awal_keyboard()


def build_extra_lines_for_input(state: Dict[str, Any]) -> Optional[List[str]]:
    view = state.get("view")
    ctx = state.get("ctx", {}) or {}
    buf = (ctx.get("num_buf") or "").strip()

    if view == VIEW_HARGA_INPUT:
        # ✅ (2) buang ayat “Tekan nombor 0-9...”
        pk = ctx.get("produk_key", "")
        nama = PRODUK_LIST.get(pk, pk) or "PRODUK"
        shown = buf if buf else "-"
        return [
            bold("MASUKKAN HARGA PRODUK"),
            f"{nama}",
            f"HARGA: {bold('RM' + shown)}",
        ]

    if view == VIEW_KOS_INPUT:
        # ✅ (3) buang ayat “Tekan nombor 0-9...”
        shown = buf if buf else "-"
        return [
            bold("MASUKKAN KOS TRANSPORT"),
            f"KOS: {bold('RM' + shown)}",
        ]

    return None


async def render_order(client: Client, callback, state: Dict[str, Any]):
    extra = build_extra_lines_for_input(state)
    caption = build_caption(
        state["base_caption"],
        state.get("items", {}),
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=False,
        receipts_count=len(state.get("receipts", [])),
        paid=bool(state.get("paid")),
        state=state,
        extra_lines=extra
    )
    kb = get_keyboard_for_view(state)
    new_msg = await replace_order_message(client, callback.message, state, caption, kb)
    return new_msg


async def deny_if_locked(state: Optional[Dict[str, Any]], callback) -> bool:
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return False
    if state.get("locked"):
        await callback.answer("Order ini sudah LAST SUBMIT (LOCK).", show_alert=True)
        return False
    return True


# ================= OCR skrip (helpers) =================
def normalize_for_text(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\u00a0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s


def normalize_for_digits(s: str) -> str:
    if not s:
        return ""
    trans = str.maketrans({
        "O": "0", "o": "0",
        "I": "1", "i": "1",
        "l": "1", "|": "1",
    })
    s = s.translate(trans)
    s = s.replace("\u00a0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s


def digits_only(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def account_found(text: str) -> bool:
    t = normalize_for_digits(text)
    return TARGET_ACC in digits_only(t)


def format_dt(dt: datetime) -> str:
    ddmmyyyy = dt.strftime("%d/%m/%Y")
    h, m = dt.hour, dt.minute
    ap = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return bold(f"{ddmmyyyy} | {h12}:{m:02d}{ap}")


def parse_datetime(text: str) -> Optional[datetime]:
    t = normalize_for_text(text)

    p_time = re.compile(
        r"\b(\d{1,2})[:\.](\d{2})(?:[:\.](\d{2}))?\s*"
        r"(a\.?\s*m\.?|p\.?\s*m\.?)?\b",
        re.I
    )

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

    def month_to_int(m: str) -> Optional[int]:
        if not m:
            return None
        m2 = re.sub(r"[^a-z]", "", m.strip().lower())
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

    p_d_mon_y = re.compile(r"\b(\d{1,2})\s*([A-Za-z]+)\s*(\d{2,4})\b", re.I)
    for m in p_d_mon_y.finditer(t):
        d, mon, y = m.group(1), m.group(2), m.group(3)
        mo = month_to_int(mon)
        if mo:
            dates.append((m.start(), (d, str(mo), y)))

    for m in p_time.finditer(t):
        ap_raw = m.group(4) or ""
        ap_letters = re.sub(r"[^a-z]", "", ap_raw.lower())
        times.append((m.start(), (m.group(1), m.group(2), ap_letters)))

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
            if ap.startswith("p") and hh != 12:
                hh += 12
            if ap.startswith("a") and hh == 12:
                hh = 0
    else:
        hh, minute = 0, 0

    try:
        return datetime(y, mo, d, hh, minute)
    except Exception:
        return None


def parse_amount(text: str) -> Optional[float]:
    t = normalize_for_digits(text).lower()
    keywords = ["amount", "total", "jumlah", "amaun", "grand total", "payment", "paid", "pay", "transfer", "successful"]

    def score_match(val: float, start: int) -> float:
        window = t[max(0, start - 80): start + 80]
        near_kw = any(k in window for k in keywords)
        return (100 if near_kw else 0) + min(val, 999999) / 1000.0

    candidates: List[tuple] = []
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
    return float(candidates[0][1])


def format_amount_rm(val: float) -> str:
    return f"RM{val:,.2f}"


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


def with_icon_left(line: str, ok: bool) -> str:
    icon = "✅" if ok else "❌"
    return f"{icon}{(line or '').strip()}"


def detect_status_clean(full_text: str) -> Tuple[str, bool]:
    t = normalize_for_text(full_text).lower()

    neg_hit = next((kw for kw in sorted(NEGATIVE_KW, key=len, reverse=True) if kw in t), None)
    if neg_hit:
        if "pending" in neg_hit:
            return ("pending", False)
        if "failed" in neg_hit or "unsuccessful" in neg_hit or "rejected" in neg_hit or "declined" in neg_hit:
            return ("failed", False)
        return (neg_hit, False)

    pos_hit = next((kw for kw in sorted(POSITIVE_KW, key=len, reverse=True) if kw in t), None)
    if pos_hit:
        return ("successful", True)

    if "success" in t or "berjaya" in t or "selesai" in t:
        return ("successful", True)

    return ("status tidak pasti", False)


async def run_ocr_on_receipt_file_id(client: Client, file_id: str) -> str:
    tmp_path = None
    try:
        tmp_path = await client.download_media(file_id)
        with io.open(tmp_path, "rb") as f:
            content = f.read()

        image = vision.Image(content=content)
        resp = vision_client.document_text_detection(image=image)

        if resp.error and resp.error.message:
            return with_icon_left(f"OCR Error: {resp.error.message}", False)

        text = resp.full_text_annotation.text.strip() if resp.full_text_annotation and resp.full_text_annotation.text else ""
        if not text:
            return with_icon_left("OCR tak jumpa teks (cuba gambar lebih jelas).", False)

        dt = parse_datetime(text)
        line1 = with_icon_left(format_dt(dt), True) if dt else with_icon_left("Tarikh tidak dijumpai", False)

        ok_acc = account_found(text)
        line2 = with_icon_left(bold(f"{TARGET_ACC} {TARGET_BANK}"), True) if ok_acc else with_icon_left("No akaun tidak sah", False)

        st_label, st_ok = detect_status_clean(text)
        line3 = with_icon_left(st_label, st_ok)

        amt = parse_amount(text)
        line4 = with_icon_left(bold(format_amount_rm(amt)), True) if amt is not None else with_icon_left("Total tidak dijumpai", False)

        return "\n".join([line1, line2, line3, line4])

    except Exception as e:
        return with_icon_left(f"Error OCR: {type(e).__name__}: {e}", False)

    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass


async def run_ocr_for_all_receipts(client: Client, state: Dict[str, Any]) -> List[str]:
    receipts = state.get("receipts") or []
    results: List[str] = []
    for fid in receipts:
        try:
            results.append(await run_ocr_on_receipt_file_id(client, fid))
        except Exception as e:
            results.append(with_icon_left(f"OCR Error: {type(e).__name__}: {e}", False))
    return results


# ================= ALBUM SENDER =================
async def send_or_rebuild_album(client: Client, state: Dict[str, Any]) -> int:
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

    if state.get("paid"):
        # ✅ (5) ubah ayat semak bayaran (bold)
        control_text = TXT_SEMAK_CONTROL
        control_markup = build_semak_keyboard()
    else:
        # ✅ (4) ubah ayat payment settle (bold)
        control_text = TXT_PAYMENT_CONTROL
        control_markup = build_payment_keyboard()

    control = await client.send_message(chat_id=chat_id, text=control_text, reply_markup=control_markup)

    for mid in album_ids:
        REPLY_MAP[mid] = control.id

    state["album_msg_ids"] = album_ids
    state["control_msg_id"] = control.id
    state["anchor_msg_id"] = None

    return control.id


# ================= TRANSFER TO CHANNEL =================
async def copy_album_to_channel(client: Client, state: Dict[str, Any]) -> None:
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
        paid=True,
        state=state,
    )

    media = [InputMediaPhoto(media=state["photo_id"], caption=caption)]
    for r in receipts_album:
        media.append(InputMediaPhoto(media=r))

    await client.send_media_group(chat_id=OFFICIAL_CHANNEL_ID, media=media)


# ================= CALLBACKS: GLOBAL BACK =================
@bot.on_callback_query(filters.regex(rf"^{BACK_CB}$"))
async def nav_back(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    if not pop_history_restore(state):
        await callback.answer("Tiada langkah untuk undur.", show_alert=True)
        return

    await render_order(client, callback, state)
    await callback.answer("Undo ✅")


# ================= CALLBACKS: ORDER FLOW =================
@bot.on_callback_query(filters.regex(r"^hantar_detail$"))
async def senarai_produk(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    push_history(state, prev_view=VIEW_AWAL, prev_ctx=state.get("ctx", {}) or {}, undo=None)

    state["view"] = VIEW_PRODUK
    state["ctx"] = {}
    await render_order(client, callback, state)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^produk_"))
async def pilih_kuantiti(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    produk_key = callback.data.replace("produk_", "", 1)

    push_history(state, prev_view=VIEW_PRODUK, prev_ctx=state.get("ctx", {}) or {}, undo=None)

    state["view"] = VIEW_QTY
    state["ctx"] = {"produk_key": produk_key}
    await render_order(client, callback, state)
    await callback.answer("Pilih kuantiti")


@bot.on_callback_query(filters.regex(r"^qty_"))
async def simpan_qty(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    payload = callback.data[len("qty_"):]
    try:
        produk_key, qty_str = payload.rsplit("_", 1)
        qty = int(qty_str)
    except Exception:
        await callback.answer("Format kuantiti tidak sah.", show_alert=True)
        return

    # safety: hanya 1-15
    if qty < 1 or qty > 15:
        await callback.answer("Kuantiti mesti 1 hingga 15.", show_alert=True)
        return

    prev_qty = state.get("items", {}).get(produk_key)
    push_history(
        state,
        prev_view=VIEW_QTY,
        prev_ctx=state.get("ctx", {}) or {},
        undo={"type": "set_qty", "produk_key": produk_key, "prev": prev_qty}
    )

    state.setdefault("items", {})[produk_key] = qty

    state["view"] = VIEW_PRODUK
    state["ctx"] = {}
    await render_order(client, callback, state)
    await callback.answer("Disimpan")


@bot.on_callback_query(filters.regex(r"^submit$"))
async def submit_order(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    if not state.get("items"):
        await callback.answer("Sila pilih sekurang-kurangnya 1 produk dulu.", show_alert=True)
        return

    push_history(state, prev_view=VIEW_PRODUK, prev_ctx=state.get("ctx", {}) or {}, undo=None)

    state["view"] = VIEW_HARGA_MENU
    state["ctx"] = {}
    await render_order(client, callback, state)
    await callback.answer("Set harga")


# ====== HARGA: BUKA KEYPAD ======
@bot.on_callback_query(filters.regex(r"^harga_"))
async def buka_harga_keypad(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    produk_key = callback.data.replace("harga_", "", 1)

    push_history(state, prev_view=VIEW_HARGA_MENU, prev_ctx=state.get("ctx", {}) or {}, undo=None)

    state["view"] = VIEW_HARGA_INPUT
    state["ctx"] = {"produk_key": produk_key, "num_buf": ""}
    await render_order(client, callback, state)
    await callback.answer("Masukkan harga")


@bot.on_callback_query(filters.regex(rf"^{PRICE_PREFIX}_[0-9]$"))
async def harga_digit(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    if state.get("view") != VIEW_HARGA_INPUT:
        await callback.answer("Bukan halaman harga.", show_alert=True)
        return

    digit = callback.data.split("_", 1)[1]
    ctx = state.get("ctx", {}) or {}
    buf = (ctx.get("num_buf") or "")

    if len(buf) >= MAX_NUM_DIGITS:
        await callback.answer("Digit sudah maksimum.", show_alert=True)
        return

    ctx["num_buf"] = buf + digit
    state["ctx"] = ctx
    await render_order(client, callback, state)
    await callback.answer()


@bot.on_callback_query(filters.regex(rf"^{PRICE_PREFIX}_back$"))
async def harga_backspace_or_cancel(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    if state.get("view") != VIEW_HARGA_INPUT:
        await callback.answer("Bukan halaman harga.", show_alert=True)
        return

    ctx = state.get("ctx", {}) or {}
    buf = (ctx.get("num_buf") or "")
    if buf:
        ctx["num_buf"] = buf[:-1]
        state["ctx"] = ctx
        await render_order(client, callback, state)
        await callback.answer("Padam 1 digit")
        return

    # kalau kosong: cancel balik 1 halaman (undo langkah masuk keypad)
    if pop_history_restore(state):
        await render_order(client, callback, state)
        await callback.answer("Kembali")
    else:
        await callback.answer("Tiada langkah untuk undur.", show_alert=True)


@bot.on_callback_query(filters.regex(rf"^{PRICE_PREFIX}_ok$"))
async def harga_okey_set(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    if state.get("view") != VIEW_HARGA_INPUT:
        await callback.answer("Bukan halaman harga.", show_alert=True)
        return

    ctx = state.get("ctx", {}) or {}
    buf = (ctx.get("num_buf") or "").strip()
    produk_key = ctx.get("produk_key", "")

    if not buf:
        await callback.answer("Sila masukkan nombor harga.", show_alert=True)
        return

    try:
        harga = int(buf)
    except Exception:
        await callback.answer("Harga tidak sah.", show_alert=True)
        return

    prev_price = state.get("prices", {}).get(produk_key)
    push_history(
        state,
        prev_view=VIEW_HARGA_INPUT,
        prev_ctx=dict(ctx),
        undo={"type": "set_price", "produk_key": produk_key, "prev": prev_price}
    )

    state.setdefault("prices", {})[produk_key] = harga

    # balik ke menu harga
    state["view"] = VIEW_HARGA_MENU
    state["ctx"] = {}
    await render_order(client, callback, state)
    await callback.answer("Harga diset ✅")


# ====== DESTINASI ======
@bot.on_callback_query(filters.regex(r"^destinasi$"))
async def buka_destinasi(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    if not is_all_prices_done(state.get("items", {}), state.get("prices", {})):
        await callback.answer("Sila lengkapkan harga dulu.", show_alert=True)
        return

    push_history(state, prev_view=VIEW_HARGA_MENU, prev_ctx=state.get("ctx", {}) or {}, undo=None)

    state["view"] = VIEW_DEST
    state["ctx"] = {}
    await render_order(client, callback, state)
    await callback.answer("Pilih destinasi")


@bot.on_callback_query(filters.regex(r"^setdest_"))
async def set_destinasi(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    try:
        idx = int(callback.data.replace("setdest_", "", 1))
        dest = DEST_LIST[idx]
    except Exception:
        await callback.answer("Destinasi tidak sah.", show_alert=True)
        return

    prev_dest = state.get("dest")
    prev_ship = state.get("ship_cost")
    push_history(
        state,
        prev_view=VIEW_DEST,
        prev_ctx=state.get("ctx", {}) or {},
        undo={"type": "set_dest", "prev_dest": prev_dest, "prev_ship_cost": prev_ship}
    )

    state["dest"] = dest
    state["ship_cost"] = None

    state["view"] = VIEW_AFTER_DEST
    state["ctx"] = {}
    await render_order(client, callback, state)
    await callback.answer(f"Destinasi: {dest}")


# ====== KOS TRANSPORT: KEYPAD ======
@bot.on_callback_query(filters.regex(r"^kos_transport$"))
async def buka_kos_transport_keypad(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    if not state.get("dest"):
        await callback.answer("Sila pilih DESTINASI dulu.", show_alert=True)
        return

    push_history(state, prev_view=state.get("view", VIEW_AFTER_DEST), prev_ctx=state.get("ctx", {}) or {}, undo=None)

    state["view"] = VIEW_KOS_INPUT
    state["ctx"] = {"num_buf": ""}  # kos tidak perlukan produk_key
    await render_order(client, callback, state)
    await callback.answer("Masukkan kos transport")


@bot.on_callback_query(filters.regex(rf"^{KOS_PREFIX}_[0-9]$"))
async def kos_digit(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    if state.get("view") != VIEW_KOS_INPUT:
        await callback.answer("Bukan halaman kos.", show_alert=True)
        return

    digit = callback.data.split("_", 1)[1]
    ctx = state.get("ctx", {}) or {}
    buf = (ctx.get("num_buf") or "")

    if len(buf) >= MAX_NUM_DIGITS:
        await callback.answer("Digit sudah maksimum.", show_alert=True)
        return

    ctx["num_buf"] = buf + digit
    state["ctx"] = ctx
    await render_order(client, callback, state)
    await callback.answer()


@bot.on_callback_query(filters.regex(rf"^{KOS_PREFIX}_back$"))
async def kos_backspace_or_cancel(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    if state.get("view") != VIEW_KOS_INPUT:
        await callback.answer("Bukan halaman kos.", show_alert=True)
        return

    ctx = state.get("ctx", {}) or {}
    buf = (ctx.get("num_buf") or "")
    if buf:
        ctx["num_buf"] = buf[:-1]
        state["ctx"] = ctx
        await render_order(client, callback, state)
        await callback.answer("Padam 1 digit")
        return

    # kosong: cancel balik 1 halaman (undo langkah masuk keypad)
    if pop_history_restore(state):
        await render_order(client, callback, state)
        await callback.answer("Kembali")
    else:
        await callback.answer("Tiada langkah untuk undur.", show_alert=True)


@bot.on_callback_query(filters.regex(rf"^{KOS_PREFIX}_ok$"))
async def kos_okey_set(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    if state.get("view") != VIEW_KOS_INPUT:
        await callback.answer("Bukan halaman kos.", show_alert=True)
        return

    ctx = state.get("ctx", {}) or {}
    buf = (ctx.get("num_buf") or "").strip()

    if not buf:
        await callback.answer("Sila masukkan nombor kos.", show_alert=True)
        return

    try:
        kos = int(buf)
    except Exception:
        await callback.answer("Kos tidak sah.", show_alert=True)
        return

    prev_cost = state.get("ship_cost")
    push_history(
        state,
        prev_view=VIEW_KOS_INPUT,
        prev_ctx=dict(ctx),
        undo={"type": "set_ship_cost", "prev": prev_cost}
    )

    state["ship_cost"] = kos

    state["view"] = VIEW_AFTER_COST
    state["ctx"] = {}
    await render_order(client, callback, state)
    await callback.answer("Kos diset ✅")


# ====== LAST SUBMIT (LOCK) ======
@bot.on_callback_query(filters.regex(r"^last_submit$"))
async def last_submit(client, callback):
    msg = callback.message
    state = ORDER_STATE.get(msg.id)

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
        await callback.answer("Kos transport belum dipilih.", show_alert=True)
        return

    # lock
    state["locked"] = True
    state.setdefault("receipts", [])
    state.setdefault("paid", False)
    state.setdefault("paid_at", None)
    state.setdefault("paid_by", None)
    state.setdefault("ocr_results", [])

    # reset view/history (lepas lock, memang tiada BACK flow)
    state["view"] = VIEW_AWAL
    state["ctx"] = {}
    state["history"] = []

    # PAYMENT PIN STATE
    state["pin_mode"] = False
    state["pin_active_user"] = None
    state["pin_buffer"] = ""
    state["pin_tries"] = 0

    # SEMAK PIN STATE
    state["sp_mode"] = False
    state["sp_active_user"] = None
    state["sp_buffer"] = ""
    state["sp_tries"] = 0

    state["album_msg_ids"] = None
    state["control_msg_id"] = None
    state["anchor_msg_id"] = msg.id

    await callback.answer("Last submit ✅")

    caption_baru = build_caption(
        state["base_caption"],
        state.get("items", {}),
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
        new_msg = await client.send_photo(chat_id=state["chat_id"], photo=state["photo_id"], caption=caption_baru)
        ORDER_STATE.pop(msg.id, None)
        ORDER_STATE[new_msg.id] = state
        state["anchor_msg_id"] = new_msg.id


# ================= PAYMENT SETTLE (PASSWORD FLOW) =================
async def do_payment_settle_after_pin(client: Client, callback, state: Dict[str, Any]):
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

    state["ocr_results"] = await run_ocr_for_all_receipts(client, state)

    state["pin_mode"] = False
    state["pin_active_user"] = None
    state["pin_buffer"] = ""
    state["pin_tries"] = 0

    await delete_bundle(client, state)
    new_control_id = await send_or_rebuild_album(client, state)

    for k in list(ORDER_STATE.keys()):
        if ORDER_STATE.get(k) is state:
            ORDER_STATE.pop(k, None)
    ORDER_STATE[new_control_id] = state


@bot.on_callback_query(filters.regex(r"^pay_settle$"))
async def pay_settle_password_start(client, callback):
    control_id = callback.message.id
    state = ORDER_STATE.get(control_id)

    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return
    if not state.get("locked"):
        await callback.answer("Sila LAST SUBMIT dulu.", show_alert=True)
        return
    if state.get("paid"):
        await callback.answer("Order ini sudah PAID ✅", show_alert=True)
        return

    user_id = callback.from_user.id if callback.from_user else None
    if not user_id:
        await callback.answer("User tidak sah.", show_alert=True)
        return

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
            pin_prompt_text("Sila masukkan PASSWORD untuk PAYMENT SETTLE", state["pin_buffer"]),
            reply_markup=build_pin_keyboard("pin")
        )
    except Exception:
        pass

    await callback.answer("Masukkan password")


@bot.on_callback_query(filters.regex(r"^pin_[0-9]$"))
async def pin_press_digit(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not state or not state.get("pin_mode"):
        await callback.answer("Sila tekan PAYMENT SETTLE dulu.", show_alert=True)
        return
    user_id = callback.from_user.id if callback.from_user else None
    if state.get("pin_active_user") != user_id:
        await callback.answer("Ini bukan keypad anda.", show_alert=True)
        return

    digit = callback.data.split("_", 1)[1]
    buf = state.get("pin_buffer", "")
    if len(buf) >= max(4, len(PAYMENT_PIN)):
        await callback.answer("PIN sudah cukup, tekan OKEY.", show_alert=True)
        return

    state["pin_buffer"] = buf + digit
    try:
        await callback.message.edit_text(
            pin_prompt_text("Sila masukkan PASSWORD untuk PAYMENT SETTLE", state["pin_buffer"]),
            reply_markup=build_pin_keyboard("pin")
        )
    except Exception:
        pass
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^pin_back$"))
async def pin_back(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return
    user_id = callback.from_user.id if callback.from_user else None
    if state.get("pin_active_user") and state.get("pin_active_user") != user_id:
        await callback.answer("Ini bukan keypad anda.", show_alert=True)
        return

    state["pin_mode"] = False
    state["pin_active_user"] = None
    state["pin_buffer"] = ""
    state["pin_tries"] = 0

    try:
        await callback.message.edit_text(TXT_PAYMENT_CONTROL, reply_markup=build_payment_keyboard())
    except Exception:
        pass
    await callback.answer("Kembali")


@bot.on_callback_query(filters.regex(r"^pin_ok$"))
async def pin_ok(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not state or not state.get("pin_mode"):
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

    if buf == PAYMENT_PIN:
        await do_payment_settle_after_pin(client, callback, state)
        return

    state["pin_tries"] = int(state.get("pin_tries", 0)) + 1
    state["pin_buffer"] = ""

    if state["pin_tries"] >= MAX_PIN_TRIES:
        state["pin_mode"] = False
        state["pin_active_user"] = None
        state["pin_tries"] = 0
        state["pin_buffer"] = ""
        try:
            await callback.message.edit_text(
                "❌ Password salah terlalu banyak kali.\n\n" + TXT_PAYMENT_CONTROL,
                reply_markup=build_payment_keyboard()
            )
        except Exception:
            pass
        await callback.answer("Salah banyak kali. Reset.", show_alert=True)
        return

    try:
        await callback.message.edit_text(
            "❌ Password salah. Cuba lagi.\n\n" + pin_prompt_text("Sila masukkan PASSWORD untuk PAYMENT SETTLE", ""),
            reply_markup=build_pin_keyboard("pin")
        )
    except Exception:
        pass
    await callback.answer("Password salah", show_alert=True)


# ================= SEMAK BAYARAN (AUTH + PIN + MOVE CHANNEL) =================
def is_semak_allowed(user_id: Optional[int]) -> bool:
    if not user_id:
        return False
    if not SEMAK_ALLOWED_IDS:
        return True
    return user_id in SEMAK_ALLOWED_IDS


async def back_to_semak_page(callback, state: Dict[str, Any]):
    try:
        await callback.message.edit_text(TXT_SEMAK_CONTROL, reply_markup=build_semak_keyboard())
    except Exception:
        pass


@bot.on_callback_query(filters.regex(r"^semak_bayaran$"))
async def semak_bayaran_start_pin(client, callback):
    control_id = callback.message.id
    state = ORDER_STATE.get(control_id)

    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    user_id = callback.from_user.id if callback.from_user else None
    if not is_semak_allowed(user_id):
        await callback.answer("❌ Anda tidak dibenarkan tekan butang ini.", show_alert=True)
        return

    if not (state.get("receipts") or []):
        await callback.answer("Tiada resit untuk disemak.", show_alert=True)
        return

    active = state.get("sp_active_user")
    if active and active != user_id:
        await callback.answer("Keypad sedang digunakan oleh user lain.", show_alert=True)
        return

    state["sp_mode"] = True
    state["sp_active_user"] = user_id
    state["sp_buffer"] = ""
    state["sp_tries"] = 0

    try:
        # ✅ (6) ayat baru + bold
        await callback.message.edit_text(
            semak_pin_prompt_text(state["sp_buffer"]),
            reply_markup=build_pin_keyboard("sp")
        )
    except Exception:
        pass

    await callback.answer("Masukkan password")


@bot.on_callback_query(filters.regex(r"^sp_[0-9]$"))
async def sp_press_digit(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not state or not state.get("sp_mode"):
        await callback.answer("Sila tekan BUTANG SEMAK BAYARAN dulu.", show_alert=True)
        return

    user_id = callback.from_user.id if callback.from_user else None
    if state.get("sp_active_user") != user_id:
        await callback.answer("Ini bukan keypad anda.", show_alert=True)
        return

    digit = callback.data.split("_", 1)[1]
    buf = state.get("sp_buffer", "")
    if len(buf) >= max(4, len(SEMAK_PIN)):
        await callback.answer("PIN sudah cukup, tekan OKEY.", show_alert=True)
        return

    state["sp_buffer"] = buf + digit
    try:
        await callback.message.edit_text(
            semak_pin_prompt_text(state["sp_buffer"]),
            reply_markup=build_pin_keyboard("sp")
        )
    except Exception:
        pass
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^sp_back$"))
async def sp_back(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    user_id = callback.from_user.id if callback.from_user else None
    if state.get("sp_active_user") and state.get("sp_active_user") != user_id:
        await callback.answer("Ini bukan keypad anda.", show_alert=True)
        return

    state["sp_mode"] = False
    state["sp_active_user"] = None
    state["sp_buffer"] = ""
    state["sp_tries"] = 0

    await back_to_semak_page(callback, state)
    await callback.answer("Kembali")


@bot.on_callback_query(filters.regex(r"^sp_ok$"))
async def sp_ok_move(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not state or not state.get("sp_mode"):
        await callback.answer("Sila tekan BUTANG SEMAK BAYARAN dulu.", show_alert=True)
        return

    user_id = callback.from_user.id if callback.from_user else None
    if state.get("sp_active_user") != user_id:
        await callback.answer("Ini bukan keypad anda.", show_alert=True)
        return

    buf = (state.get("sp_buffer", "") or "").strip()
    if not buf:
        await callback.answer("PIN kosong. Sila tekan nombor.", show_alert=True)
        return

    if buf != SEMAK_PIN:
        state["sp_tries"] = int(state.get("sp_tries", 0)) + 1
        state["sp_buffer"] = ""
        if state["sp_tries"] >= MAX_PIN_TRIES:
            state["sp_mode"] = False
            state["sp_active_user"] = None
            state["sp_tries"] = 0
            state["sp_buffer"] = ""
            await back_to_semak_page(callback, state)
            await callback.answer("❌ Salah banyak kali. Reset.", show_alert=True)
            return

        try:
            await callback.message.edit_text(
                "❌ Password salah. Cuba lagi.\n\n" + semak_pin_prompt_text(""),
                reply_markup=build_pin_keyboard("sp")
            )
        except Exception:
            pass
        await callback.answer("Password salah", show_alert=True)
        return

    await callback.answer("Proses pindah ke channel...")

    try:
        # 0) test channel access
        try:
            await client.get_chat(OFFICIAL_CHANNEL_ID)
        except Exception as e:
            await client.send_message(
                chat_id=state["chat_id"],
                text=f"❌ DEBUG: Bot tak dapat akses channel OFFICIAL_CHANNEL_ID={OFFICIAL_CHANNEL_ID}\n{type(e).__name__}: {e}"
            )
            await back_to_semak_page(callback, state)
            return

        # 1) OCR semua resit
        state["ocr_results"] = await run_ocr_for_all_receipts(client, state)

        # reset semak pin
        state["sp_mode"] = False
        state["sp_active_user"] = None
        state["sp_buffer"] = ""
        state["sp_tries"] = 0

        # 2) copy album ke channel
        try:
            await copy_album_to_channel(client, state)
        except Exception as e:
            await client.send_message(
                chat_id=state["chat_id"],
                text=f"❌ DEBUG: Gagal hantar ke channel OFFICIAL_CHANNEL_ID={OFFICIAL_CHANNEL_ID}\n{type(e).__name__}: {e}"
            )
            await back_to_semak_page(callback, state)
            return

        # 3) delete bundle dalam group
        try:
            await delete_bundle(client, state)
        except Exception as e:
            await client.send_message(
                chat_id=state["chat_id"],
                text=f"⚠️ DEBUG: Hantar channel berjaya, tapi gagal delete dalam group.\nPastikan bot admin group + Delete messages ON.\n{type(e).__name__}: {e}"
            )

        # 4) buang state dari memori
        for k in list(ORDER_STATE.keys()):
            if ORDER_STATE.get(k) is state:
                ORDER_STATE.pop(k, None)

        # ✅ TIADA mesej ditinggalkan dalam group
        return

    except Exception as e:
        try:
            tb = traceback.format_exc()
            await client.send_message(
                chat_id=state["chat_id"],
                text=f"❌ DEBUG CRASH sp_ok_move\n{type(e).__name__}: {e}\n\n{tb[-1500:]}"
            )
        except Exception:
            pass
        await back_to_semak_page(callback, state)


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

    try:
        await message.delete()
    except (MessageDeleteForbidden, ChatAdminRequired):
        pass
    except Exception:
        pass

    sent = await client.send_photo(
        chat_id=chat_id,
        photo=photo_id,
        caption=bold(base_caption),
        reply_markup=build_awal_keyboard()
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
        "control_msg_id": None,

        "ocr_results": [],

        # FLOW STATE
        "view": VIEW_AWAL,
        "ctx": {},
        "history": [],

        # PAYMENT PIN
        "pin_mode": False,
        "pin_active_user": None,
        "pin_buffer": "",
        "pin_tries": 0,

        # SEMAK PIN
        "sp_mode": False,
        "sp_active_user": None,
        "sp_buffer": "",
        "sp_tries": 0,
    }


if __name__ == "__main__":
    bot.run()

