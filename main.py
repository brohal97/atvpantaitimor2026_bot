# =========================
# ATV PANTAI TIMOR BOT (VERSI PENUH + STABIL + OCR TRIGGER)
#
# ✅ Fungsi utama:
# 1) Repost gambar produk + caption auto kemas
# 2) Auto ❓ jika user lupa isi segmen (produk / penghantaran)
# 3) Jika caption kosong: auto 2 baris:
#       ❓ | ❓ | ❓   (produk)
#       ❓ | ❓ | ❓   (penghantaran)
# 4) Harga TIDAK didarab kuantiti (Total = jumlah semua RM pada baris)
# 5) Swipe kiri (reply) + upload resit:
#    bot padam resit asal + padam album lama, repost album baru:
#    [produk+caption] + [semua resit terkumpul] (repeatable)
#
# ✅ Fix penting:
# - Jika user taip penghantaran tanpa tempat: "transport luar 350"
#   output WAJIB: "❓ | Transport luar | RM350"
# - Jika user taip produk tanpa qty: "125cc follspek 5900"
#   output WAJIB: "125CC FULL SPEC | ❓ | RM5900"
#
# ✅ OCR TRIGGER:
# - Staff reply (swipe kiri) pada post produk/album + taip "123" hantar
# - Hanya berfungsi jika sekurang-kurangnya 1 resit sudah di-upload utk order itu
# - OCR baca resit terakhir: tarikh@masa + nombor akaun target + total resit
# - Bila trigger berjaya:
#   bot PADAM semua album lama dan REPOST semula album baru bersama hasil OCR dalam caption
#
# =========================

import os, re, io, json, time, asyncio, tempfile
from datetime import datetime
from difflib import SequenceMatcher
from typing import Optional, Dict, Any, List

import pytz
from pyrogram import Client, filters
from pyrogram.errors import FloodWait, RPCError, MessageDeleteForbidden, ChatAdminRequired
from pyrogram.types import InputMediaPhoto

# ===== OCR (Google Vision) =====
# pip install google-cloud-vision
try:
    from google.cloud import vision
except Exception:
    vision = None


# ================= ENV =================
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Missing API_ID / API_HASH / BOT_TOKEN")

OCR_TRIGGER_CODE = os.getenv("OCR_TRIGGER_CODE", "123").strip()
OCR_TARGET_ACCOUNT = os.getenv("OCR_TARGET_ACCOUNT", "8606018423").strip()
OCR_LANG_HINTS = [x.strip() for x in os.getenv("OCR_LANG_HINTS", "ms,en").split(",") if x.strip()]

TZ = pytz.timezone("Asia/Kuala_Lumpur")
HARI = ["Isnin", "Selasa", "Rabu", "Khamis", "Jumaat", "Sabtu", "Ahad"]


# ================= BOT =================
bot = Client(
    "atv_bot_detail_repost",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


# ================= GOOGLE CREDS (Railway JSON env -> file) =================
_OCR_READY = False
VISION_CLIENT = None
_GOOGLE_CREDS_TMP_PATH = None

def ensure_google_creds_file():
    """
    Railway: simpan JSON service account dalam env GOOGLE_APPLICATION_CREDENTIALS_JSON
    Kita tukar jadi file sementara dan set GOOGLE_APPLICATION_CREDENTIALS.
    """
    global _GOOGLE_CREDS_TMP_PATH
    raw = (os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", "") or "").strip()
    if not raw:
        return False

    raw = raw.replace("\\n", "\n")  # kalau Railway escape newline
    try:
        data = json.loads(raw)
    except Exception:
        return False

    fd, path = tempfile.mkstemp(prefix="gcp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
    _GOOGLE_CREDS_TMP_PATH = path
    return True

def init_vision_client():
    global _OCR_READY, VISION_CLIENT
    if vision is None:
        _OCR_READY = False
        VISION_CLIENT = None
        return

    ok = ensure_google_creds_file()
    if not ok:
        _OCR_READY = False
        VISION_CLIENT = None
        return

    try:
        VISION_CLIENT = vision.ImageAnnotatorClient()
        _OCR_READY = True
    except Exception:
        _OCR_READY = False
        VISION_CLIENT = None

init_vision_client()


# ================= BOLD STYLE (UNTUK PRODUK & UMUM) =================
BOLD_MAP = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
    "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
    "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"
)
def bold(text: str) -> str:
    return (text or "").translate(BOLD_MAP)

# ================= BOLD STYLE 2 (KHAS UNTUK TEMPAT + JENIS TRANSPORT) =================
ALT_BOLD_MAP = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    "𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙"
    "𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳"
    "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗"
)
def bold2(text: str) -> str:
    return (text or "").translate(ALT_BOLD_MAP)


# ================= SAFE TG CALL =================
async def tg_call(fn, *args, **kwargs):
    while True:
        try:
            return await fn(*args, **kwargs)
        except FloodWait as e:
            await asyncio.sleep(int(getattr(e, "value", 1)) + 1)
        except RPCError:
            await asyncio.sleep(0.2)


# ================= FIXED NAMES =================
PRODUCT_NAMES = [
    "125CC FULL SPEC",
    "125CC BIG BODY",
    "YAMA SPORT",
    "GY6 200CC",
    "HAMMER ARMOUR",
    "BIG HAMMER",
    "TROLI PLASTIK",
    "TROLI BESI",
]
FUZZY_THRESHOLD = float(os.getenv("FUZZY_THRESHOLD", "0.72"))

TRANSPORT_TYPES = [
    "Transport luar",
    "Pickup sendiri",
    "Lori kita hantar",
]
TRANSPORT_THRESHOLD = float(os.getenv("TRANSPORT_THRESHOLD", "0.70"))


def _norm_key(s: str) -> str:
    s = (s or "").upper()
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

PRODUCT_KEYS = {name: _norm_key(name) for name in PRODUCT_NAMES}
TRANSPORT_KEYS = {name: _norm_key(name) for name in TRANSPORT_TYPES}

def best_product_match(user_first_segment: str):
    u = _norm_key(user_first_segment)
    if not u:
        return None, 0.0
    best_name, best_score = None, 0.0
    for name, key in PRODUCT_KEYS.items():
        score = SequenceMatcher(None, u, key).ratio()
        if score > best_score:
            best_score = score
            best_name = name
    return best_name, best_score

def best_transport_match(user_transport_segment: str):
    u = _norm_key(user_transport_segment)
    if not u:
        return None, 0.0
    best_name, best_score = None, 0.0
    for name, key in TRANSPORT_KEYS.items():
        score = SequenceMatcher(None, u, key).ratio()
        if score > best_score:
            best_score = score
            best_name = name
    return best_name, best_score


# ================= CORE CAPTION LOGIC =================
def make_stamp() -> str:
    now = datetime.now(TZ)
    hari = HARI[now.weekday()]
    tarikh = f"{now.day}/{now.month}/{now.year}"
    jam = now.strftime("%I:%M%p").lower()
    return f"{hari} | {tarikh} | {jam}"

def extract_lines(text: str):
    lines = []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if re.search(r"\btotal\b", ln, flags=re.IGNORECASE):
            continue
        lines.append(ln)
    return lines

def _split_pipes(line: str):
    if "｜" in line and "|" not in line:
        return [p.strip() for p in line.split("｜")]
    return [p.strip() for p in line.split("|")]

def _join_pipes(parts):
    return " | ".join([p.strip() for p in parts])

def _normalize_rm_value(val: str) -> str:
    s = (val or "").strip()
    if not s:
        return s
    if s == "❓":
        return "❓"
    m = re.search(r"(?i)\b(?:rm)?\s*([0-9]{1,12})\b", s)
    if not m:
        m2 = re.search(r"([0-9]{1,12})", s)
        if not m2:
            return s
        return f"RM{m2.group(1)}"
    return f"RM{m.group(1)}"

def _extract_tail_money(text: str):
    s = (text or "").strip()
    if not s:
        return s, None
    m = re.search(r"(?i)(?:\brm\b\s*)?([0-9]{1,12})\s*$", s)
    if not m:
        return s, None
    num = m.group(1)
    head = s[:m.start()].strip()
    return head, f"RM{num}"


# ================= NAMA TEMPAT: Title Case =================
def _cap_word(w: str) -> str:
    if not w:
        return w
    if w == "❓":
        return "❓"
    if w.isdigit():
        return w
    if w.isalpha() and len(w) <= 2:
        return w.upper()
    return w.lower().capitalize()

def place_title_case(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return s
    if s == "❓":
        return "❓"
    tokens = [t for t in re.split(r"\s+", s) if t]
    out = []
    for t in tokens:
        if "-" in t:
            parts = t.split("-")
            out.append("-".join(_cap_word(p) for p in parts))
        else:
            out.append(_cap_word(t))
    return " ".join(out)


# ================= DETECT TRANSPORT-LIKE =================
def is_transport_like_parts(parts) -> bool:
    """
    Baris penghantaran jika segmen-2 match jenis transport (walau kos ❓).
    """
    if not parts or len(parts) < 2:
        return False
    seg2 = (parts[1] or "").strip()
    if not seg2 or seg2 == "❓":
        return False
    name, score = best_transport_match(seg2)
    return bool(name and score >= TRANSPORT_THRESHOLD)


# ================= AUTO INSERT PIPES (NO PIPES) =================
def _try_parse_product_no_pipes_strict(line: str):
    """
    Accept: "nama qty harga"
    Reject: "nama harga" (tiada qty) -> akan jadi "nama | ❓ | RMharga"
    """
    head, money = _extract_tail_money(line)
    if not money:
        return None

    mqty = re.search(r"\b(\d{1,3})\s*$", head)
    if not mqty:
        return None

    qty = mqty.group(1)
    name_part = head[:mqty.start()].strip()
    if not name_part:
        return None

    return f"{name_part} | {qty} | {money}"

def _best_transport_suffix(words):
    best_name, best_score, best_cut = None, 0.0, None
    n = len(words)
    for L in range(1, min(5, n) + 1):
        cut = n - L
        cand = " ".join(words[cut:])
        name, score = best_transport_match(cand)
        if name and score > best_score:
            best_score = score
            best_name = name
            best_cut = cut
    return best_name, best_score, best_cut

def _try_parse_cost_no_pipes(line: str):
    """
    Accept: "ipoh perak lori kita hantar 350" => "ipoh perak | lori kita hantar | RM350"
    """
    head, money = _extract_tail_money(line)
    if not money:
        return None

    words = [w for w in re.split(r"\s+", head.strip()) if w]
    if len(words) < 2:
        return None

    best_t, score, cut = _best_transport_suffix(words)
    if not best_t or score < TRANSPORT_THRESHOLD:
        return None

    dest = " ".join(words[:cut]).strip()
    if not dest:
        return None

    return f"{dest} | {best_t} | {money}"

def auto_insert_pipes_if_missing(line: str) -> str:
    s = (line or "").strip()
    if not s:
        return "❓ | ❓ | ❓"

    if ("|" in s) or ("｜" in s):
        return s

    # 1) produk lengkap (mesti ada qty)
    as_product = _try_parse_product_no_pipes_strict(s)
    if as_product:
        return as_product

    # 2) penghantaran lengkap (dest + type + kos)
    as_cost = _try_parse_cost_no_pipes(s)
    if as_cost:
        return as_cost

    # 3) fallback separa: ada harga di hujung
    head, money = _extract_tail_money(s)
    if money:
        head = head.strip()

        # ✅ FIX: "transport luar 350" -> "❓ | Transport luar | RM350"
        best_t, tscore = best_transport_match(head)
        if best_t and tscore >= TRANSPORT_THRESHOLD:
            return f"❓ | {best_t} | {money}"

        # cuba detect suffix transport (dest + transport)
        words = [w for w in re.split(r"\s+", head) if w]
        if words:
            tname, score, cut = _best_transport_suffix(words)
            if tname and score >= TRANSPORT_THRESHOLD:
                dest = " ".join(words[:cut]).strip()
                if not dest:
                    return f"❓ | {tname} | {money}"
                return f"{dest} | {tname} | {money}"

        # default: treat as produk (nama | ❓ | RM)
        if not head:
            return f"❓ | ❓ | {money}"
        return f"{head} | ❓ | {money}"

    # 4) tiada nombor pun
    return f"{s} | ❓ | ❓"


# ================= FILL ❓ SEGMENTS =================
def fill_missing_segments(parts, want_len=3):
    parts = list(parts or [])
    while len(parts) < want_len:
        parts.append("")
    out = []
    for p in parts[:want_len]:
        p = (p or "").strip()
        out.append(p if p else "❓")
    return out

def normalize_detail_line(line: str) -> str:
    line = auto_insert_pipes_if_missing(line)

    if ("|" not in line) and ("｜" not in line):
        return "❓ | ❓ | ❓"

    raw_parts = _split_pipes(line)
    parts = fill_missing_segments(raw_parts, 3)

    transport_like = is_transport_like_parts(parts)

    # seg1
    if transport_like:
        if parts[0] != "❓":
            parts[0] = place_title_case(parts[0])
    else:
        if parts[0] != "❓":
            best_name, score = best_product_match(parts[0])
            if best_name and score >= FUZZY_THRESHOLD:
                parts[0] = best_name
            else:
                parts[0] = parts[0].upper()

    # seg2
    if transport_like and parts[1] != "❓":
        best_t, tscore = best_transport_match(parts[1])
        if best_t and tscore >= TRANSPORT_THRESHOLD:
            parts[1] = best_t

    # seg3
    if parts[2] != "❓":
        parts[2] = _normalize_rm_value(parts[2])

    return _join_pipes(parts)

def calc_total(lines):
    total = 0
    for ln in lines:
        nums = re.findall(r"(?i)\bRM\s*([0-9]{1,12})\b", ln)
        for n in nums:
            try:
                total += int(n)
            except:
                pass
    return total

def stylize_line_for_caption(line: str, force_transport: bool = False) -> str:
    if ("|" in line) or ("｜" in line):
        parts = fill_missing_segments(_split_pipes(line), 3)

        if force_transport or is_transport_like_parts(parts):
            return " | ".join([bold2(parts[0]), bold2(parts[1]), bold(parts[2])])

        return bold(_join_pipes(parts))

    return bold(line)


# ================= OCR PARSE HELPERS =================
def _clean_ocr_text(t: str) -> str:
    t = t or ""
    t = t.replace("\r", "\n")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

def _find_datetime(text: str) -> Optional[str]:
    t = text

    # 20 Jan 2026 10:17:21 AM
    m = re.search(
        r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?)\b",
        t, re.IGNORECASE
    )
    if m:
        return m.group(1).strip()

    # 20/01/2026 07:05 AM  or  20-01-2026 07:05
    m = re.search(
        r"\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})\s+(\d{1,2}:\d{2}(?::\d{2})?)\s*(AM|PM)?\b",
        t, re.IGNORECASE
    )
    if m:
        d = m.group(1)
        tm = m.group(2)
        ap = (m.group(3) or "").upper()
        return f"{d} {tm} {ap}".strip()

    return None

def _find_total_amount(text: str) -> Optional[str]:
    # ambil semua RMxxx.xx / RMxxxx
    amts = []
    for m in re.finditer(
        r"(?i)\bRM\s*([0-9]{1,3}(?:[,][0-9]{3})*(?:\.[0-9]{2})?|[0-9]{1,12}(?:\.[0-9]{2})?)\b",
        text
    ):
        raw = m.group(1).replace(",", "")
        try:
            amts.append(float(raw))
        except:
            pass

    if not amts:
        return None

    mx = max(amts)  # paling selamat untuk resit: ambil nilai terbesar
    if float(mx).is_integer():
        return f"RM{int(mx)}"
    return f"RM{mx:.2f}"

def _target_account_found(text: str, target: str) -> bool:
    if not target:
        return False
    digits = re.sub(r"\D", "", text or "")
    return target in digits

async def ocr_extract_from_bytes(img_bytes: bytes) -> Dict[str, Any]:
    def _run():
        image = vision.Image(content=img_bytes)
        resp = VISION_CLIENT.text_detection(
            image=image,
            image_context={"language_hints": OCR_LANG_HINTS}
        )
        if resp.error.message:
            raise RuntimeError(resp.error.message)

        full = ""
        try:
            if resp.text_annotations:
                full = resp.text_annotations[0].description or ""
        except:
            pass
        return full

    text = await asyncio.to_thread(_run)
    text = _clean_ocr_text(text)

    dt = _find_datetime(text)
    total = _find_total_amount(text)
    acc_ok = _target_account_found(text, OCR_TARGET_ACCOUNT)

    return {
        "raw": text,
        "datetime": dt,
        "total": total,
        "account_ok": acc_ok,
    }

def build_ocr_paragraph(ocr: Dict[str, Any]) -> str:
    dt = ocr.get("datetime")
    total = ocr.get("total")
    acc_ok = bool(ocr.get("account_ok"))

    lines = []
    lines.append("")  # satu perenggan kosong
    lines.append(f"✅ Tarikh@waktu jam : {bold(dt) if dt else '❓'}")

    if OCR_TARGET_ACCOUNT:
        if acc_ok:
            lines.append(f"✅ No akaun : {bold(OCR_TARGET_ACCOUNT)}")
        else:
            lines.append(f"✅ No akaun : {bold(OCR_TARGET_ACCOUNT)} (❌ tak jumpa)")
    else:
        lines.append("✅ No akaun : ❓")

    lines.append(f"✅ Total dalam resit : {bold(total) if total else '❓'}")
    return "\n".join(lines)

def strip_existing_ocr_block(caption: str) -> str:
    cap = caption or ""
    cap = re.sub(
        r"\n✅ Tarikh@waktu jam[^\n]*\n✅ No akaun[^\n]*\n✅ Total dalam resit[^\n]*",
        "",
        cap
    )
    cap = re.sub(r"\n{3,}", "\n\n", cap)
    return cap.strip()


def build_caption(user_caption: str) -> str:
    stamp = bold(make_stamp())
    detail_lines_raw = extract_lines(user_caption)
    detail_lines = [normalize_detail_line(x) for x in detail_lines_raw]

    # ✅ jika caption kosong, paksa 2 baris: produk + penghantaran
    if not detail_lines:
        detail_lines = [
            "❓ | ❓ | ❓",  # produk
            "❓ | ❓ | ❓",  # penghantaran
        ]

    total = calc_total(detail_lines)

    parts = [stamp, ""]
    for idx, ln in enumerate(detail_lines):
        if not user_caption.strip() and idx == 1:
            parts.append(stylize_line_for_caption(ln, force_transport=True))
        else:
            parts.append(stylize_line_for_caption(ln))

    parts += ["", f"Total keseluruhan : {bold('RM' + str(total))}"]

    cap = "\n".join(parts)
    if len(cap) > 1024:
        cap = cap[:1000] + "\n...(caption terlalu panjang)"
    return cap


# =========================================================
# ✅ STATE: PRODUK/ALBUM
# =========================================================
STATE_TTL_SEC = float(os.getenv("STATE_TTL_SEC", "86400"))  # 24 jam
RECEIPT_DELAY_SEC = float(os.getenv("RECEIPT_DELAY_SEC", "1.0"))

# state:
# {
#   "product_file_id": str,
#   "caption": str,
#   "receipts": [file_id...],
#   "msg_ids": [message_id...],
#   "ts": epoch
# }
ORDER_STATES = {}   # (chat_id, root_id) -> state
MSGID_TO_STATE = {} # (chat_id, msg_id) -> (chat_id, root_id)
_state_lock = asyncio.Lock()

def _cleanup_states():
    now = time.time()
    kill = []
    for sid, data in ORDER_STATES.items():
        if now - float(data.get("ts", now)) > STATE_TTL_SEC:
            kill.append(sid)
    for sid in kill:
        data = ORDER_STATES.pop(sid, None)
        if data:
            for mid in data.get("msg_ids", []):
                MSGID_TO_STATE.pop((sid[0], mid), None)

def _get_state_id_from_reply(chat_id: int, reply_to_id: int):
    sid = MSGID_TO_STATE.get((chat_id, reply_to_id))
    if sid:
        return sid
    return (chat_id, reply_to_id)

async def _delete_messages_safe(client: Client, chat_id: int, msg_ids):
    if not msg_ids:
        return
    try:
        await tg_call(client.delete_messages, chat_id, msg_ids)
    except (MessageDeleteForbidden, ChatAdminRequired):
        for mid in msg_ids:
            try:
                await tg_call(client.delete_messages, chat_id, mid)
            except:
                pass
    except:
        pass

async def _send_album_and_update_state(
    client: Client,
    chat_id: int,
    state_id,
    product_file_id: str,
    caption: str,
    receipts: list
):
    # bina media list
    media = [InputMediaPhoto(media=product_file_id, caption=caption)]
    for fid in receipts:
        media.append(InputMediaPhoto(media=fid))

    # chunk max 10
    chunks, cur = [], []
    for m in media:
        cur.append(m)
        if len(cur) == 10:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)

    sent_msg_ids = []
    for idx, ch in enumerate(chunks):
        if idx > 0:
            try:
                ch[0].caption = None
            except:
                pass

        res = await tg_call(client.send_media_group, chat_id=chat_id, media=ch)
        try:
            for m in res:
                sent_msg_ids.append(m.id)
        except:
            pass

    # update mapping
    for mid in sent_msg_ids:
        MSGID_TO_STATE[(chat_id, mid)] = state_id

    # update state
    ORDER_STATES[state_id] = {
        "product_file_id": product_file_id,
        "caption": caption,
        "receipts": list(receipts),
        "msg_ids": list(sent_msg_ids),
        "ts": time.time(),
    }
    return sent_msg_ids


# =========================================================
# ✅ RECEIPT GROUP BUFFER (album user)
# =========================================================
_pending_receipt_groups = {}  # (chat_id, media_group_id, reply_to_id) -> {"msgs":[Message], "task":Task}
_pending_lock = asyncio.Lock()

def is_reply_to_any_message(message) -> bool:
    try:
        return bool(message.reply_to_message and message.reply_to_message.id)
    except:
        return False

async def _delete_message_safe(msg):
    try:
        await tg_call(msg.delete)
    except (MessageDeleteForbidden, ChatAdminRequired):
        pass
    except:
        pass

async def _merge_receipts_and_repost(client: Client, chat_id: int, reply_to_id: int, new_receipt_file_ids: list):
    if not new_receipt_file_ids:
        return False

    async with _state_lock:
        _cleanup_states()
        state_id = _get_state_id_from_reply(chat_id, reply_to_id)
        state = ORDER_STATES.get(state_id)
        if not state:
            return False

        receipts = state.get("receipts", []) + list(new_receipt_file_ids)

        old_ids = state.get("msg_ids", [])
        await _delete_messages_safe(client, chat_id, old_ids)

        for mid in old_ids:
            MSGID_TO_STATE.pop((chat_id, mid), None)

        await _send_album_and_update_state(
            client=client,
            chat_id=chat_id,
            state_id=state_id,
            product_file_id=state["product_file_id"],
            caption=state.get("caption", ""),
            receipts=receipts
        )
        return True

async def _process_receipt_group(client: Client, chat_id: int, media_group_id: str, reply_to_id: int):
    await asyncio.sleep(RECEIPT_DELAY_SEC)

    async with _pending_lock:
        key = (chat_id, media_group_id, reply_to_id)
        data = _pending_receipt_groups.pop(key, None)

    if not data:
        return

    msgs = sorted(data.get("msgs", []), key=lambda m: m.id)
    receipt_file_ids = [m.photo.file_id for m in msgs if m.photo]

    for m in msgs:
        await _delete_message_safe(m)

    if not receipt_file_ids:
        return

    merged = await _merge_receipts_and_repost(client, chat_id, reply_to_id, receipt_file_ids)
    if merged:
        return

    # fallback: repost resit sahaja sebagai album reply
    try:
        medias = [InputMediaPhoto(media=fid) for fid in receipt_file_ids]
        await tg_call(client.send_media_group, chat_id=chat_id, media=medias, reply_to_message_id=reply_to_id)
    except:
        pass

async def handle_receipt_photo(client: Client, message):
    chat_id = message.chat.id
    reply_to_id = message.reply_to_message.id

    # album receipts
    if message.media_group_id:
        key = (chat_id, str(message.media_group_id), reply_to_id)
        async with _pending_lock:
            if key not in _pending_receipt_groups:
                _pending_receipt_groups[key] = {"msgs": [], "task": None}
                _pending_receipt_groups[key]["task"] = asyncio.create_task(
                    _process_receipt_group(client, chat_id, str(message.media_group_id), reply_to_id)
                )
            _pending_receipt_groups[key]["msgs"].append(message)
        return

    # single receipt
    receipt_fid = message.photo.file_id if message.photo else None
    await _delete_message_safe(message)
    if not receipt_fid:
        return

    merged = await _merge_receipts_and_repost(client, chat_id, reply_to_id, [receipt_fid])
    if merged:
        return

    # fallback: repost single resit reply
    try:
        await tg_call(client.send_photo, chat_id=chat_id, photo=receipt_fid, reply_to_message_id=reply_to_id)
    except:
        pass


# =========================================================
# ✅ OCR TRIGGER (reply + "123") -> DELETE ALBUM LAMA + REPOST DGN OCR
# =========================================================
async def _download_file_bytes(client: Client, file_id: str) -> Optional[bytes]:
    try:
        path = await tg_call(client.download_media, file_id)
        if not path:
            return None
        with open(path, "rb") as f:
            return f.read()
    except:
        return None

async def _apply_ocr_to_order(client: Client, chat_id: int, reply_to_id: int) -> bool:
    # OCR mesti ready
    if not _OCR_READY or not VISION_CLIENT:
        return False

    # 1) ambil state + pastikan ada resit
    async with _state_lock:
        _cleanup_states()
        state_id = _get_state_id_from_reply(chat_id, reply_to_id)
        state = ORDER_STATES.get(state_id)
        if not state:
            return False

        receipts = state.get("receipts", [])
        if not receipts:
            return False  # syarat: mesti ada sekurang-kurangnya 1 resit

        product_file_id = state.get("product_file_id")
        caption_now = state.get("caption", "")
        old_ids = list(state.get("msg_ids", []))
        last_receipt = receipts[-1]

    # 2) download resit terakhir -> OCR
    img_bytes = await _download_file_bytes(client, last_receipt)
    if not img_bytes:
        return False

    try:
        ocr = await ocr_extract_from_bytes(img_bytes)
    except:
        return False

    # 3) bina caption baru (buang OCR lama, tambah OCR baru)
    cleaned = strip_existing_ocr_block(caption_now)
    new_caption = cleaned + build_ocr_paragraph(ocr)
    if len(new_caption) > 1024:
        new_caption = new_caption[:1000] + "\n...(caption terlalu panjang)"

    # 4) delete album lama + repost album baru (produk+caption OCR + semua resit)
    async with _state_lock:
        _cleanup_states()
        state = ORDER_STATES.get(state_id)
        if not state:
            return False

        # delete album lama
        await _delete_messages_safe(client, chat_id, old_ids)
        for mid in old_ids:
            MSGID_TO_STATE.pop((chat_id, mid), None)

        try:
            await _send_album_and_update_state(
                client=client,
                chat_id=chat_id,
                state_id=state_id,
                product_file_id=product_file_id,
                caption=new_caption,
                receipts=receipts
            )
            return True
        except:
            return False


@bot.on_message(filters.text & ~filters.bot)
async def handle_text_trigger(client: Client, message):
    # mesti reply
    if not is_reply_to_any_message(message):
        return

    txt = (message.text or "").strip()
    if txt != OCR_TRIGGER_CODE:
        return

    chat_id = message.chat.id
    reply_to_id = message.reply_to_message.id

    # padam mesej "123" untuk kekalkan chat kemas
    await _delete_message_safe(message)

    # ikut request awak:
    # jika tak ada resit pertama -> "tidak ada apa2 berlaku"
    await _apply_ocr_to_order(client, chat_id, reply_to_id)
    return


# ================= HANDLER PHOTO =================
@bot.on_message(filters.photo & ~filters.bot)
async def handle_photo(client, message):
    # ✅ receipt mode (reply)
    if is_reply_to_any_message(message):
        await handle_receipt_photo(client, message)
        return

    # ✅ normal mode (repost caption kemas)
    chat_id = message.chat.id
    photo_id = message.photo.file_id
    user_caption = message.caption or ""

    new_caption = build_caption(user_caption)

    # padam mesej asal (user)
    try:
        await tg_call(message.delete)
    except (MessageDeleteForbidden, ChatAdminRequired):
        pass
    except:
        pass

    # repost versi kemas (bot)
    sent = await tg_call(
        client.send_photo,
        chat_id=chat_id,
        photo=photo_id,
        caption=new_caption
    )

    # simpan state awal
    try:
        if sent and sent.photo:
            async with _state_lock:
                _cleanup_states()
                state_id = (chat_id, sent.id)

                ORDER_STATES[state_id] = {
                    "product_file_id": sent.photo.file_id,
                    "caption": sent.caption or new_caption,
                    "receipts": [],
                    "msg_ids": [sent.id],
                    "ts": time.time(),
                }
                MSGID_TO_STATE[(chat_id, sent.id)] = state_id
    except:
        pass


if __name__ == "__main__":
    bot.run()
