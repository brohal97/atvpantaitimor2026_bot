import os, re, asyncio, time
from datetime import datetime
import pytz
from difflib import SequenceMatcher

from pyrogram import Client, filters
from pyrogram.errors import FloodWait, RPCError, MessageDeleteForbidden, ChatAdminRequired
from pyrogram.types import InputMediaPhoto


# ================= ENV =================
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Missing API_ID / API_HASH / BOT_TOKEN")


# ================= BOT =================
bot = Client(
    "atv_bot_detail_repost",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

TZ = pytz.timezone("Asia/Kuala_Lumpur")
HARI = ["Isnin", "Selasa", "Rabu", "Khamis", "Jumaat", "Sabtu", "Ahad"]


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


# ================= PRODUCT FIXED NAMES =================
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
FUZZY_THRESHOLD = float(os.getenv("FUZZY_THRESHOLD", "0.72"))  # produk


# ================= TRANSPORT FIXED TYPES (SEGMENT KE-2) =================
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

    best_name = None
    best_score = 0.0
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

    best_name = None
    best_score = 0.0
    for name, key in TRANSPORT_KEYS.items():
        score = SequenceMatcher(None, u, key).ratio()
        if score > best_score:
            best_score = score
            best_name = name

    return best_name, best_score


# ================= CORE LOGIC =================
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


def _normalize_rm_value(val: str) -> str:
    s = (val or "").strip()
    if not s:
        return s

    m = re.search(r"(?i)\b(?:rm)?\s*([0-9]{1,12})\b", s)
    if not m:
        m2 = re.search(r"([0-9]{1,12})", s)
        if not m2:
            return s
        num = m2.group(1)
        return f"RM{num}"

    num = m.group(1)
    return f"RM{num}"


def _split_pipes(line: str):
    if "｜" in line and "|" not in line:
        return [p.strip() for p in line.split("｜")]
    return [p.strip() for p in line.split("|")]


def _join_pipes(parts):
    return " | ".join([p.strip() for p in parts])


def _looks_like_money_tail(seg: str) -> bool:
    return bool(re.search(r"(?i)\b(?:rm)?\s*[0-9]{1,12}\b", (seg or "").strip()))


def is_product_line(line: str) -> bool:
    if ("|" not in line) and ("｜" not in line):
        return False
    parts = _split_pipes(line)
    if len(parts) < 3:
        return False

    seg2 = parts[1]
    if not re.fullmatch(r"\d{1,3}", seg2.strip()):
        return False

    return _looks_like_money_tail(parts[-1])


def is_cost_or_transport_line(line: str) -> bool:
    if ("|" not in line) and ("｜" not in line):
        return False
    parts = _split_pipes(line)
    if len(parts) < 3:
        return False

    if is_product_line(line):
        return False

    return _looks_like_money_tail(parts[-1])


# ================= NAMA TEMPAT: HURUF DEPAN SAHAJA (Title Case) =================
def _cap_word(w: str) -> str:
    if not w:
        return w
    if w.isdigit():
        return w
    if w.isalpha() and len(w) <= 2:
        return w.upper()  # contoh: TS
    return w.lower().capitalize()

def place_title_case(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return s
    tokens = [t for t in re.split(r"\s+", s) if t]
    out = []
    for t in tokens:
        if "-" in t:
            parts = t.split("-")
            out.append("-".join(_cap_word(p) for p in parts))
        else:
            out.append(_cap_word(t))
    return " ".join(out)


# ================= AUTO INSERT ' | ' IF USER TERLUPA =================
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


def _try_parse_product_no_pipes(line: str):
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
    best_name = None
    best_score = 0.0
    best_cut = None

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
        return s

    if ("|" in s) or ("｜" in s):
        return s

    as_product = _try_parse_product_no_pipes(s)
    if as_product:
        return as_product

    as_cost = _try_parse_cost_no_pipes(s)
    if as_cost:
        return as_cost

    return s


def normalize_detail_line(line: str) -> str:
    line = auto_insert_pipes_if_missing(line)

    if ("|" not in line) and ("｜" not in line):
        return line

    parts = _split_pipes(line)
    if len(parts) < 2:
        return line

    first = parts[0]
    best_name, score = best_product_match(first)

    if best_name and score >= FUZZY_THRESHOLD:
        parts[0] = best_name
    else:
        if is_cost_or_transport_line(line):
            parts[0] = place_title_case(first)
        else:
            parts[0] = first.upper()

    if len(parts) >= 3 and is_cost_or_transport_line(line):
        user_type = parts[1]
        best_t, tscore = best_transport_match(user_type)
        if best_t and tscore >= TRANSPORT_THRESHOLD:
            parts[1] = best_t

    parts[-1] = _normalize_rm_value(parts[-1])
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


def stylize_line_for_caption(line: str) -> str:
    if is_cost_or_transport_line(line):
        parts = _split_pipes(line)
        if len(parts) >= 3:
            seg0 = bold2(parts[0])
            seg1 = bold2(parts[1])
            seg_last = bold(parts[-1])
            mid = []
            if len(parts) > 3:
                for p in parts[2:-1]:
                    mid.append(bold(p))
            return " | ".join([seg0, seg1] + mid + [seg_last])

    return bold(line)


def build_caption(user_caption: str) -> str:
    stamp = bold(make_stamp())

    detail_lines_raw = extract_lines(user_caption)
    detail_lines = [normalize_detail_line(x) for x in detail_lines_raw]
    total = calc_total(detail_lines)

    parts = []
    parts.append(stamp)
    parts.append("")
    for ln in detail_lines:
        parts.append(stylize_line_for_caption(ln))
    parts.append("")
    parts.append(f"Total keseluruhan : {bold('RM' + str(total))}")

    cap = "\n".join(parts)
    if len(cap) > 1024:
        cap = cap[:1000] + "\n...(caption terlalu panjang)"
    return cap


# =========================================================
# ✅ STORE POST PRODUK BOT (supaya boleh gabung dgn resit)
# =========================================================
PRODUCT_TTL_SEC = float(os.getenv("PRODUCT_TTL_SEC", "86400"))  # 24 jam
PRODUCT_POSTS = {}  # key=(chat_id, msg_id) -> {"photo": file_id, "caption": str, "ts": epoch}

def _cleanup_product_posts():
    now = time.time()
    to_del = []
    for k, v in PRODUCT_POSTS.items():
        if now - float(v.get("ts", now)) > PRODUCT_TTL_SEC:
            to_del.append(k)
    for k in to_del:
        PRODUCT_POSTS.pop(k, None)


# =========================================================
# ✅ RECEIPT REPLY -> PADAM & REPOST ALBUM BERSAMA PRODUK
# =========================================================
RECEIPT_DELAY_SEC = float(os.getenv("RECEIPT_DELAY_SEC", "1.0"))

_pending_receipt_groups = {}  # key=(chat_id, media_group_id, reply_to_id) -> {"msgs":[Message], "task":Task}
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


async def _repost_album_with_product(client: Client, chat_id: int, reply_to_id: int, receipt_file_ids: list):
    """
    Padam post produk bot + padam resit, kemudian hantar album:
    [produk (dengan caption)] + [resit-resit]
    """
    _cleanup_product_posts()
    prod = PRODUCT_POSTS.get((chat_id, reply_to_id))
    if not prod:
        return False

    prod_photo = prod["photo"]
    prod_caption = prod.get("caption", "")

    media = [InputMediaPhoto(media=prod_photo, caption=prod_caption)]
    for fid in receipt_file_ids:
        media.append(InputMediaPhoto(media=fid))

    # Telegram limit media_group = 10 item
    # Kalau resit banyak, dia akan hantar batch 10-10 (produk batch pertama sahaja).
    chunks = []
    cur = []
    for m in media:
        cur.append(m)
        if len(cur) == 10:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)

    # padam post produk bot dulu
    try:
        await tg_call(client.delete_messages, chat_id, reply_to_id)
    except:
        pass

    # send batch pertama (ada produk+caption)
    ok = True
    for idx, ch in enumerate(chunks):
        try:
            await tg_call(client.send_media_group, chat_id=chat_id, media=ch)
        except:
            ok = False
            break

        # batch seterusnya: jangan ulang caption (kalau ada)
        if idx == 0 and len(chunks) > 1:
            # buang caption pada first media untuk batch seterusnya (safety)
            pass

    return ok


async def _process_receipt_group(client: Client, chat_id: int, media_group_id: str, reply_to_id: int):
    await asyncio.sleep(RECEIPT_DELAY_SEC)

    async with _pending_lock:
        key = (chat_id, media_group_id, reply_to_id)
        data = _pending_receipt_groups.pop(key, None)

    if not data:
        return

    msgs = sorted(data.get("msgs", []), key=lambda m: m.id)
    receipt_file_ids = [m.photo.file_id for m in msgs if m.photo]

    # padam semua mesej resit user
    for m in msgs:
        await _delete_message_safe(m)

    if not receipt_file_ids:
        return

    # cuba gabung bersama produk (kalau reply pada post produk bot)
    merged = await _repost_album_with_product(client, chat_id, reply_to_id, receipt_file_ids)
    if merged:
        return

    # fallback (kalau bukan reply pada post produk bot): repost resit sahaja sebagai album reply
    try:
        medias = [InputMediaPhoto(media=fid) for fid in receipt_file_ids]
        await tg_call(client.send_media_group, chat_id=chat_id, media=medias, reply_to_message_id=reply_to_id)
    except:
        pass


async def handle_receipt_photo(client: Client, message):
    chat_id = message.chat.id
    reply_to_id = message.reply_to_message.id

    # album
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

    # single photo resit
    receipt_fid = message.photo.file_id if message.photo else None
    await _delete_message_safe(message)
    if not receipt_fid:
        return

    merged = await _repost_album_with_product(client, chat_id, reply_to_id, [receipt_fid])
    if merged:
        return

    # fallback: repost single resit reply
    try:
        await tg_call(client.send_photo, chat_id=chat_id, photo=receipt_fid, reply_to_message_id=reply_to_id)
    except:
        pass


# ================= HANDLER (GABUNG) =================
@bot.on_message(filters.photo & ~filters.bot)
async def handle_photo(client, message):
    """
    1) Jika user reply (swipe kiri) dan hantar resit => padam semua & repost album bersama produk (jika reply pada post bot).
    2) Kalau bukan reply => post produk biasa => bot format caption & repost.
    """
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

    # repost versi kemas (bot) + SIMPAN untuk gabung resit nanti
    sent = await tg_call(
        client.send_photo,
        chat_id=chat_id,
        photo=photo_id,
        caption=new_caption
    )

    # simpan info post bot
    try:
        if sent and sent.photo:
            PRODUCT_POSTS[(chat_id, sent.id)] = {
                "photo": sent.photo.file_id,
                "caption": sent.caption or new_caption,
                "ts": time.time()
            }
            _cleanup_product_posts()
    except:
        pass


if __name__ == "__main__":
    bot.run()

