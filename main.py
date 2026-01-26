# =========================
# ATV PANTAI TIMOR BOT (VERSI PENUH + STABIL + OCR REPOST PASTI JADI)
#
# ✅ CLEAN TEXT DALAM GROUP:
# 1) Mana-mana user hantar TEXT sahaja (bukan reply) -> bot PADAM serta-merta
# 2) Reply (swipe kiri) tapi belum upload resit -> apa-apa text termasuk 123 -> bot PADAM serta-merta
# 3) Resit dah ada tapi password SALAH / text lain -> bot PADAM serta-merta
# 4) Hanya user ALLOW + password BETUL + resit ADA:
#    - Kalau OCR belum dibuat -> OCR + repost album
#    - Kalau OCR sudah dibuat -> FINALIZE: hantar album ke channel + padam semua dalam group
#
# ⚠️ BOT MESTI ADMIN group/supergroup + permission Delete messages
# =========================

import os, re, json, time, asyncio, tempfile, base64
from datetime import datetime
from difflib import SequenceMatcher
from typing import Optional, Dict, Any, List, Tuple

import pytz
from pyrogram import Client, filters
from pyrogram.errors import FloodWait, RPCError, MessageDeleteForbidden, ChatAdminRequired
from pyrogram.types import InputMediaPhoto

# ===== OCR (Google Vision) =====
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

OCR_TARGET_ACCOUNT = re.sub(r"\D", "", os.getenv("OCR_TARGET_ACCOUNT", "8606018423").strip())
OCR_TARGET_BANK_LABEL = os.getenv("OCR_TARGET_BANK_LABEL", "CIMB BANK").strip()
OCR_LANG_HINTS = [x.strip() for x in os.getenv("OCR_LANG_HINTS", "ms,en").split(",") if x.strip()]

ALLOWED_USER_IDS = {
    1150078068,
    6897594281,
    1198935605,
}
OFFICIAL_CHANNEL_ID = -1003573894188

TZ = pytz.timezone("Asia/Kuala_Lumpur")
HARI = ["Isnin", "Selasa", "Rabu", "Khamis", "Jumaat", "Sabtu", "Ahad"]


def is_allowed_user(message) -> bool:
    try:
        uid = int(message.from_user.id)
        return uid in ALLOWED_USER_IDS
    except Exception:
        return False


bot = Client(
    "atv_bot_detail_repost",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ================= GOOGLE CREDS =================
_OCR_READY = False
_OCR_INIT_ERROR = ""
VISION_CLIENT = None

def _get_google_json_env_value() -> str:
    candidates = [
        "GOOGLE_APPLICATION_CREDENTIALS_JSON",
        "GOOGLE_APPLICATION_CREDENTIALIALS_JSON",
        "GOOGLE_APPLICATION_CREDENTIALITALS_JSON",
        "GOOGLE_APPLICATION_CREDENTAILS_JSON",
    ]
    for k in candidates:
        v = (os.getenv(k, "") or "").strip()
        if v:
            return v
    return ""

def _try_decode_b64_creds() -> str:
    b64 = (os.getenv("GOOGLE_APPLICATION_CREDENTIALS_B64", "") or "").strip()
    if not b64:
        return ""
    try:
        raw = base64.b64decode(b64).decode("utf-8", errors="strict")
        return raw.strip()
    except Exception:
        return ""

def _repair_private_key_newlines(raw: str) -> str:
    if not raw:
        return raw
    pattern = re.compile(r'("private_key"\s*:\s*")(.+?)("(\s*,\s*"client_email"\s*:))', re.DOTALL)
    m = pattern.search(raw)
    if not m:
        return raw
    before = m.group(1)
    keyval = m.group(2)
    after = m.group(3)
    keyval = keyval.replace("\r", "")
    keyval = keyval.replace("\n", "\\n")
    fixed = raw[:m.start()] + before + keyval + after + raw[m.end():]
    return fixed

def init_vision_client():
    global _OCR_READY, _OCR_INIT_ERROR, VISION_CLIENT
    _OCR_READY = False
    _OCR_INIT_ERROR = ""
    VISION_CLIENT = None

    if vision is None:
        _OCR_INIT_ERROR = "google-cloud-vision belum dipasang"
        return

    raw = _try_decode_b64_creds()
    if not raw:
        raw = _get_google_json_env_value()

    if not raw:
        _OCR_INIT_ERROR = "GOOGLE_APPLICATION_CREDENTIALS_JSON kosong / tiada"
        return

    raw1 = raw.replace("\\n", "\n")
    data = None

    try:
        data = json.loads(raw1)
    except Exception:
        raw_fixed = _repair_private_key_newlines(raw1)
        try:
            data = json.loads(raw_fixed)
        except Exception as e:
            _OCR_INIT_ERROR = f"JSON service account tak valid: {e}"
            return

    try:
        pk = data.get("private_key", "")
        if isinstance(pk, str):
            data["private_key"] = pk.replace("\\n", "\n")
    except Exception:
        pass

    try:
        fd, path = tempfile.mkstemp(prefix="gcp-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
    except Exception as e:
        _OCR_INIT_ERROR = f"Gagal create file creds: {e}"
        return

    try:
        VISION_CLIENT = vision.ImageAnnotatorClient()
        _OCR_READY = True
    except Exception as e:
        _OCR_INIT_ERROR = f"Vision client gagal init: {e}"

init_vision_client()


# ================= SAFE TG CALL =================
async def tg_call(fn, *args, **kwargs):
    while True:
        try:
            return await fn(*args, **kwargs)
        except FloodWait as e:
            await asyncio.sleep(int(getattr(e, "value", 1)) + 1)
        except RPCError:
            await asyncio.sleep(0.2)

async def _delete_message_safe(msg):
    try:
        await tg_call(msg.delete)
    except (MessageDeleteForbidden, ChatAdminRequired):
        pass
    except:
        pass


# ================= BOLD STYLE (keep your original) =================
BOLD_MAP = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
    "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
    "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝗷𝟴𝟵".replace("𝗷", "𝟯")
)
def bold(text: str) -> str:
    return (text or "").translate(BOLD_MAP)

ALT_BOLD_MAP = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    "𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙"
    "𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
    "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗"
)
def bold2(text: str) -> str:
    return (text or "").translate(ALT_BOLD_MAP)


# ================= CAPTION (ringkas: guna code asal awak jika perlu) =================
PRODUCT_NAMES = [
    "125CC FULL SPEC", "125CC BIG BODY", "YAMA SPORT", "GY6 200CC",
    "HAMMER ARMOUR", "BIG HAMMER", "TROLI PLASTIK", "TROLI BESI",
]
FUZZY_THRESHOLD = float(os.getenv("FUZZY_THRESHOLD", "0.72"))
TRANSPORT_TYPES = ["Transport luar", "Pickup sendiri", "Lori kita hantar"]
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
    if not u: return None, 0.0
    best_name, best_score = None, 0.0
    for name, key in PRODUCT_KEYS.items():
        score = SequenceMatcher(None, u, key).ratio()
        if score > best_score:
            best_score, best_name = score, name
    return best_name, best_score

def best_transport_match(user_transport_segment: str):
    u = _norm_key(user_transport_segment)
    if not u: return None, 0.0
    best_name, best_score = None, 0.0
    for name, key in TRANSPORT_KEYS.items():
        score = SequenceMatcher(None, u, key).ratio()
        if score > best_score:
            best_score, best_name = score, name
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

def is_transport_like_parts(parts) -> bool:
    if not parts or len(parts) < 2:
        return False
    seg2 = (parts[1] or "").strip()
    if not seg2 or seg2 == "❓":
        return False
    name, score = best_transport_match(seg2)
    return bool(name and score >= TRANSPORT_THRESHOLD)

def _try_parse_product_no_pipes_strict(line: str):
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

    as_product = _try_parse_product_no_pipes_strict(s)
    if as_product:
        return as_product

    as_cost = _try_parse_cost_no_pipes(s)
    if as_cost:
        return as_cost

    head, money = _extract_tail_money(s)
    if money:
        head = head.strip()

        best_t, tscore = best_transport_match(head)
        if best_t and tscore >= TRANSPORT_THRESHOLD:
            return f"❓ | {best_t} | {money}"

        words = [w for w in re.split(r"\s+", head) if w]
        if words:
            tname, score, cut = _best_transport_suffix(words)
            if tname and score >= TRANSPORT_THRESHOLD:
                dest = " ".join(words[:cut]).strip()
                if not dest:
                    return f"❓ | {tname} | {money}"
                return f"{dest} | {tname} | {money}"

        if not head:
            return f"❓ | ❓ | {money}"
        return f"{head} | ❓ | {money}"

    return f"{s} | ❓ | ❓"

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

    if transport_like and parts[1] != "❓":
        best_t, tscore = best_transport_match(parts[1])
        if best_t and tscore >= TRANSPORT_THRESHOLD:
            parts[1] = best_t

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

def build_caption(user_caption: str) -> str:
    stamp = bold(make_stamp())
    detail_lines_raw = extract_lines(user_caption)
    detail_lines = [normalize_detail_line(x) for x in detail_lines_raw]

    if not detail_lines:
        detail_lines = [
            "❓ | ❓ | ❓",
            "❓ | ❓ | ❓",
        ]

    total = calc_total(detail_lines)

    parts = [stamp, ""]
    for idx, ln in enumerate(detail_lines):
        if not user_caption.strip() and idx == 1:
            parts.append(stylize_line_for_caption(ln, force_transport=True))
        else:
            parts.append(stylize_line_for_caption(ln))

    parts += ["", f"𝖳𝗈𝗍𝖺𝗅 𝗄𝖾𝗌𝖾𝗅𝗎𝗋𝗎𝗁𝖺𝗇 : {bold('RM' + str(total))}"]
    cap = "\n".join(parts)
    if len(cap) > 1024:
        cap = cap[:1000] + "\n...(caption terlalu panjang)"
    return cap

# ================= OCR (reuse your original parsing) =================
def _clean_ocr_text(t: str) -> str:
    t = (t or "").replace("\r", "\n")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

_MONTH_MAP = {
    "JAN": 1, "JANUARY": 1, "JANUARI": 1,
    "FEB": 2, "FEBRUARY": 2, "FEBRUARI": 2,
    "MAR": 3, "MARCH": 3, "MAC": 3,
    "APR": 4, "APRIL": 4,
    "MAY": 5, "MEI": 5,
    "JUN": 6, "JUNE": 6,
    "JUL": 7, "JULY": 7, "JULAI": 7,
    "AUG": 8, "AUGUST": 8, "OGOS": 8,
    "SEP": 9, "SEPT": 9, "SEPTEMBER": 9,
    "OCT": 10, "OCTOBER": 10, "OKTOBER": 10,
    "NOV": 11, "NOVEMBER": 11,
    "DEC": 12, "DECEMBER": 12, "DISEMBER": 12,
}

def _fmt_dt(day: int, month: int, year: int, hour: int, minute: int, ampm: Optional[str]) -> Optional[str]:
    if not (1 <= day <= 31 and 1 <= month <= 12 and year >= 1900): return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59): return None

    ap = (ampm or "").strip().lower().replace(".", "")
    if ap in ["a", "am"]: ap = "am"
    elif ap in ["p", "pm"]: ap = "pm"
    else: ap = ""

    if not ap:
        if hour == 0: hour12, ap = 12, "am"
        elif 1 <= hour <= 11: hour12, ap = hour, "am"
        elif hour == 12: hour12, ap = 12, "pm"
        else: hour12, ap = hour - 12, "pm"
    else:
        h = hour
        if ap == "am" and h == 12: h = 0
        if ap == "pm" and 1 <= h <= 11: h += 12
        if h == 0: hour12, ap = 12, "am"
        elif 1 <= h <= 11: hour12, ap = h, "am"
        elif h == 12: hour12, ap = 12, "pm"
        else: hour12, ap = h - 12, "pm"

    return f"{day:02d}/{month:02d}/{year:04d} | {hour12}:{minute:02d}{ap}"

def _find_datetime(text: str) -> Optional[str]:
    t = (text or "").replace("—", "-").replace("–", "-")

    pat1 = re.compile(
        r"\b(?P<d>\d{1,2})\s+(?P<m>[A-Za-z]{3,12})\s+(?P<y>\d{4})\s*,?\s*"
        r"(?P<h>\d{1,2})[:.](?P<mn>\d{2})(?:[:.]\d{2})?\s*(?P<ap>AM|PM|am|pm)?\b"
    )
    m = pat1.search(t)
    if m:
        day = int(m.group("d"))
        mon_txt = m.group("m").upper()
        mon = _MONTH_MAP.get(mon_txt) or _MONTH_MAP.get(mon_txt[:3])
        if mon:
            out = _fmt_dt(day, mon, int(m.group("y")), int(m.group("h")), int(m.group("mn")), m.group("ap"))
            if out: return out

    pat2 = re.compile(
        r"\b(?P<d>\d{1,2})[\/\-.](?P<m>\d{1,2})[\/\-.](?P<y>\d{2,4})\s*,?\s*"
        r"(?P<h>\d{1,2})[:.](?P<mn>\d{2})(?:[:.]\d{2})?\s*(?P<ap>AM|PM|am|pm)?\b"
    )
    m = pat2.search(t)
    if m:
        yraw = m.group("y")
        year = int(yraw) + 2000 if len(yraw) == 2 else int(yraw)
        out = _fmt_dt(int(m.group("d")), int(m.group("m")), year, int(m.group("h")), int(m.group("mn")), m.group("ap"))
        if out: return out

    return None

def _digits_all(text: str) -> str:
    return re.sub(r"\D", "", text or "")

def _find_account_and_label(text: str) -> Optional[str]:
    if not OCR_TARGET_ACCOUNT: return None
    digits = _digits_all(text)
    if OCR_TARGET_ACCOUNT in digits:
        return f"{OCR_TARGET_ACCOUNT} {OCR_TARGET_BANK_LABEL}".strip()
    return None

def _extract_amount_candidates(text: str) -> List[Tuple[float, str]]:
    t = text or ""
    out: List[Tuple[float, str]] = []
    money_pat = re.compile(
        r"(?i)\b(?:rm|myr)\s*([0-9]{1,3}(?:[,][0-9]{3})*(?:\.[0-9]{2})?|[0-9]{1,12}(?:\.[0-9]{2})?)\b"
        r"|\b([0-9]{1,3}(?:[,][0-9]{3})*(?:\.[0-9]{2})?|[0-9]{1,12}(?:\.[0-9]{2})?)\s*(?:rm|myr)\b"
    )
    for m in money_pat.finditer(t):
        num = m.group(1) or m.group(2)
        if not num: continue
        raw = num.replace(",", "")
        try:
            val = float(raw)
        except:
            continue
        if val <= 0 or val > 100000000:
            continue
        pretty = f"RM{val:,.2f}".replace(",", "")
        out.append((val, pretty))
    return out

def _find_total_amount(text: str) -> Optional[str]:
    t = text or ""
    cands = _extract_amount_candidates(t)
    if not cands:
        return None
    v, p = max(cands, key=lambda x: x[0])
    return p

async def ocr_extract_from_bytes(img_bytes: bytes) -> Dict[str, Any]:
    def _run():
        image = vision.Image(content=img_bytes)
        resp = VISION_CLIENT.document_text_detection(
            image=image,
            image_context={"language_hints": OCR_LANG_HINTS}
        )
        if resp.error.message:
            raise RuntimeError(resp.error.message)
        full = ""
        try:
            if resp.full_text_annotation and resp.full_text_annotation.text:
                full = resp.full_text_annotation.text
        except:
            full = ""
        if not full:
            resp2 = VISION_CLIENT.text_detection(image=image, image_context={"language_hints": OCR_LANG_HINTS})
            if resp2.error.message:
                raise RuntimeError(resp2.error.message)
            if resp2.text_annotations:
                full = resp2.text_annotations[0].description or ""
        return full

    text = await asyncio.to_thread(_run)
    text = _clean_ocr_text(text)

    dt = _find_datetime(text)
    total = _find_total_amount(text)
    acc_label = _find_account_and_label(text)
    return {"raw": text, "datetime": dt, "total": total, "account_label": acc_label}

def build_ocr_block_one(ocr: Dict[str, Any], note: str = "") -> str:
    dt = ocr.get("datetime")
    acc_label = ocr.get("account_label")
    total = ocr.get("total")
    lines = [
        f"✅ {bold(dt) if dt else '❓'}",
        f"✅ {bold(acc_label) if acc_label else '❓'}",
        f"✅ {bold(total) if total else '❓'}",
    ]
    if note:
        lines.append(f"⚠️ {note}")
    return "\n".join(lines)

def build_ocr_paragraph_multi(all_blocks: List[str]) -> str:
    return "\n\n".join(all_blocks)

def strip_existing_ocr_block(caption: str) -> str:
    cap = caption or ""
    cap = re.sub(r"\n✅\s*\d{2}\/\d{2}\/\d{4}\s*\|\s*[0-9:apm]+\s*\n✅.*?\n✅.*?(?=\n\n✅|\Z)", "", cap, flags=re.DOTALL)
    cap = re.sub(r"\n{3,}", "\n\n", cap)
    return cap.strip()


# =========================================================
# ✅ STATE
# =========================================================
STATE_TTL_SEC = float(os.getenv("STATE_TTL_SEC", "86400"))
RECEIPT_DELAY_SEC = float(os.getenv("RECEIPT_DELAY_SEC", "1.0"))

ORDER_STATES = {}    # (chat_id, root_id) -> state
MSGID_TO_STATE = {}  # (chat_id, msg_id) -> (chat_id, root_id)
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

async def _send_media_group_in_chunks(client: Client, chat_id: int, media: List[InputMediaPhoto]) -> List[int]:
    chunks, cur = [], []
    for m in media:
        cur.append(m)
        if len(cur) == 10:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)

    sent_msg_ids: List[int] = []
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
    return sent_msg_ids

async def _send_album_and_update_state(client, chat_id, state_id, product_file_id, caption, receipts, ocr_applied):
    media = [InputMediaPhoto(media=product_file_id, caption=caption)]
    for fid in receipts:
        media.append(InputMediaPhoto(media=fid))

    sent_msg_ids = await _send_media_group_in_chunks(client, chat_id, media)

    for mid in sent_msg_ids:
        MSGID_TO_STATE[(chat_id, mid)] = state_id

    ORDER_STATES[state_id] = {
        "product_file_id": product_file_id,
        "caption": caption,
        "receipts": list(receipts),
        "msg_ids": list(sent_msg_ids),
        "ocr_applied": bool(ocr_applied),
        "ts": time.time(),
    }
    return sent_msg_ids

async def _send_album_to_channel(client, channel_id, product_file_id, caption, receipts) -> bool:
    try:
        media = [InputMediaPhoto(media=product_file_id, caption=caption)]
        for fid in receipts:
            media.append(InputMediaPhoto(media=fid))
        await _send_media_group_in_chunks(client, channel_id, media)
        return True
    except Exception:
        return False


# =========================================================
# ✅ RECEIPT BUFFER
# =========================================================
_pending_receipt_groups = {}
_pending_lock = asyncio.Lock()

def is_reply_to_any_message(message) -> bool:
    try:
        return bool(message.reply_to_message and message.reply_to_message.id)
    except:
        return False

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
            client, chat_id, state_id,
            state["product_file_id"],
            state.get("caption", ""),
            receipts,
            ocr_applied=False
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

    await _merge_receipts_and_repost(client, chat_id, reply_to_id, receipt_file_ids)

async def handle_receipt_photo(client: Client, message):
    chat_id = message.chat.id
    reply_to_id = message.reply_to_message.id

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

    receipt_fid = message.photo.file_id if message.photo else None
    await _delete_message_safe(message)
    if not receipt_fid:
        return

    await _merge_receipts_and_repost(client, chat_id, reply_to_id, [receipt_fid])


# =========================================================
# ✅ OCR APPLY
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

async def _apply_ocr_and_repost_album(client: Client, chat_id: int, reply_to_id: int) -> bool:
    async with _state_lock:
        _cleanup_states()
        state_id = _get_state_id_from_reply(chat_id, reply_to_id)
        state = ORDER_STATES.get(state_id)
        if not state:
            return False

        receipts = list(state.get("receipts", []))
        if not receipts:
            return False

        product_file_id = state.get("product_file_id")
        caption_now = state.get("caption", "")
        old_ids = list(state.get("msg_ids", []))

    blocks: List[str] = []

    if not _OCR_READY or not VISION_CLIENT:
        note = f"OCR tak aktif ({_OCR_INIT_ERROR})"
        for _ in receipts:
            blocks.append(build_ocr_block_one({"datetime": None, "total": None, "account_label": None}, note=note))
    else:
        for fid in receipts:
            img_bytes = await _download_file_bytes(client, fid)
            if not img_bytes:
                blocks.append(build_ocr_block_one({"datetime": None, "total": None, "account_label": None}, note="OCR gagal (download resit gagal)"))
                continue
            try:
                ocr_data = await ocr_extract_from_bytes(img_bytes)
                blocks.append(build_ocr_block_one(ocr_data, note=""))
            except Exception as e:
                blocks.append(build_ocr_block_one({"datetime": None, "total": None, "account_label": None}, note=f"OCR gagal ({e})"))

    cleaned = strip_existing_ocr_block(caption_now)
    new_caption = (cleaned + "\n\n" + build_ocr_paragraph_multi(blocks)).strip()

    if len(new_caption) > 1024:
        new_caption = new_caption[:1000] + "\n...(caption terlalu panjang)"

    async with _state_lock:
        _cleanup_states()
        state = ORDER_STATES.get(state_id)
        if not state:
            return False

        await _delete_messages_safe(client, chat_id, old_ids)
        for mid in old_ids:
            MSGID_TO_STATE.pop((chat_id, mid), None)

        await _send_album_and_update_state(
            client=client,
            chat_id=chat_id,
            state_id=state_id,
            product_file_id=product_file_id,
            caption=new_caption,
            receipts=receipts,
            ocr_applied=True
        )
        return True


# =========================================================
# ✅ FINALIZE
# =========================================================
async def _finalize_to_channel_and_delete(client: Client, chat_id: int, reply_to_id: int) -> bool:
    async with _state_lock:
        _cleanup_states()
        state_id = _get_state_id_from_reply(chat_id, reply_to_id)
        state = ORDER_STATES.get(state_id)
        if not state:
            return False
        if not state.get("ocr_applied", False):
            return False

        product_file_id = state.get("product_file_id")
        caption = state.get("caption", "")
        receipts = list(state.get("receipts", []))
        group_msg_ids = list(state.get("msg_ids", []))

    ok = await _send_album_to_channel(client, OFFICIAL_CHANNEL_ID, product_file_id, caption, receipts)
    if not ok:
        return False

    async with _state_lock:
        _cleanup_states()
        state = ORDER_STATES.get(state_id)
        if not state:
            return True

        msg_ids = list(state.get("msg_ids", group_msg_ids))
        await _delete_messages_safe(client, chat_id, msg_ids)
        for mid in msg_ids:
            MSGID_TO_STATE.pop((chat_id, mid), None)
        ORDER_STATES.pop(state_id, None)

    return True


# =========================================================
# ✅ PENTING: TEXT CLEANER (GROUP/SUPERGROUP)
# - INI YANG BUAT PADAM TEXT SERTA-MERTA
# - group=0 supaya dia jalan awal
# =========================================================
@bot.on_message(filters.group & filters.text & ~filters.bot, group=0)
async def group_text_cleaner_and_trigger(client: Client, message):
    txt = (message.text or "").strip()

    # 1) Kalau bukan reply -> padam terus
    if not is_reply_to_any_message(message):
        await _delete_message_safe(message)
        return

    chat_id = message.chat.id
    reply_to_id = message.reply_to_message.id

    # cari state berdasarkan reply target
    async with _state_lock:
        _cleanup_states()
        sid = _get_state_id_from_reply(chat_id, reply_to_id)
        st = ORDER_STATES.get(sid)

    # 2) Reply tapi bukan reply pada order/album -> padam terus
    if not st:
        await _delete_message_safe(message)
        return

    # 3) Reply pada order, kalau password salah / text lain -> padam terus
    if txt != OCR_TRIGGER_CODE:
        await _delete_message_safe(message)
        return

    # password betul -> tetap padam text tersebut dulu (clean)
    await _delete_message_safe(message)

    # hanya user allow
    if not is_allowed_user(message):
        return

    # mesti ada sekurang-kurangnya 1 resit
    receipts = list(st.get("receipts", []) or [])
    if not receipts:
        return

    # mode: OCR dulu, kemudian finalize
    if st.get("ocr_applied", False):
        await _finalize_to_channel_and_delete(client, chat_id, reply_to_id)
    else:
        await _apply_ocr_and_repost_album(client, chat_id, reply_to_id)


# ================= PHOTO HANDLER =================
@bot.on_message(filters.photo & ~filters.bot)
async def handle_photo(client, message):
    # kalau reply pada album/order -> ini resit
    if is_reply_to_any_message(message):
        await handle_receipt_photo(client, message)
        return

    chat_id = message.chat.id
    photo_id = message.photo.file_id
    user_caption = message.caption or ""

    new_caption = build_caption(user_caption)

    try:
        await tg_call(message.delete)
    except (MessageDeleteForbidden, ChatAdminRequired):
        pass
    except:
        pass

    sent = await tg_call(client.send_photo, chat_id=chat_id, photo=photo_id, caption=new_caption)

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
                    "ocr_applied": False,
                    "ts": time.time(),
                }
                MSGID_TO_STATE[(chat_id, sent.id)] = state_id
    except:
        pass


if __name__ == "__main__":
    bot.run()

