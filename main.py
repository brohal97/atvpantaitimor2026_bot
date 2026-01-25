# =========================
# ATV PANTAI TIMOR BOT (FULL VERSION)
# ✅ Repost gambar produk + caption kemas
# ✅ Bold style (produk) + Bold2 (tempat + jenis penghantaran)
# ✅ Auto betulkan produk/transport guna fuzzy match
# ✅ Auto insert ' | ' bila user tak guna pipes
# ✅ Auto isi ❓ bila user terlupa isi segmen (produk & penghantaran)
# ✅ RULE PENTING (NO-PIPES):
#    - "125cc foll sepek 1 5900" => "125CC FULL SPEC | 1 | RM5900"
#    - "125cc follspek 5900"     => "125CC FULL SPEC | ❓ | RM5900"
# ✅ Swipe kiri (Reply) upload resit berkali-kali:
#    - setiap kali user reply & hantar resit (1 keping / album), bot padam resit asal
#    - bot padam album lama (produk+resit) dan repost semula sebagai album baru (cumulative)
# =========================

import os, re, asyncio, time
from datetime import datetime
from difflib import SequenceMatcher

import pytz
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


# ================= BOLD STYLE 2 (KHAS TEMPAT + JENIS TRANSPORT) =================
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
FUZZY_THRESHOLD = float(os.getenv("FUZZY_THRESHOLD", "0.72"))


# ================= TRANSPORT FIXED TYPES =================
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
    if s == "❓":
        return "❓"

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
    if (seg or "").strip() == "❓":
        return False
    return bool(re.search(r"(?i)\b(?:rm)?\s*[0-9]{1,12}\b", (seg or "").strip()))


def is_product_line(line: str) -> bool:
    if ("|" not in line) and ("｜" not in line):
        return False
    parts = _split_pipes(line)
    if len(parts) < 3:
        return False

    seg2 = (parts[1] or "").strip()
    if not re.fullmatch(r"\d{1,3}", seg2):
        return False

    return _looks_like_money_tail(parts[-1])


def is_cost_or_transport_line(line: str) -> bool:
    # strict: mesti ada RM di segmen akhir (untuk total)
    if ("|" not in line) and ("｜" not in line):
        return False
    parts = _split_pipes(line)
    if len(parts) < 3:
        return False
    if is_product_line(line):
        return False
    return _looks_like_money_tail(parts[-1])


def is_transport_like_parts(parts) -> bool:
    # detect penghantaran walau kos ❓
    if not parts or len(parts) < 2:
        return False
    seg2 = (parts[1] or "").strip()
    if not seg2 or seg2 == "❓":
        return False
    name, score = best_transport_match(seg2)
    return bool(name and score >= TRANSPORT_THRESHOLD)


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


# ================= AUTO FILL ❓ FOR PIPES =================
def fill_missing_segments(parts, want_len=3):
    parts = list(parts or [])
    while len(parts) < want_len:
        parts.append("")
    out = []
    for p in parts[:want_len]:
        p = (p or "").strip()
        out.append(p if p else "❓")
    return out


# =========================================================
# ✅ NO-PIPES SMART PARSER (INI YANG AWAK MAHU)
# =========================================================
def _last_number_token(s: str):
    """
    Ambil nombor terakhir di hujung ayat.
    Support: "RM5900", "rm 5900", "5900"
    Return: (head_text, number_str or None)
    """
    s = (s or "").strip()
    if not s:
        return s, None

    m = re.search(r"(?i)\b(?:rm)?\s*([0-9]{1,12})\s*$", s)
    if not m:
        return s, None

    num = m.group(1)
    head = s[:m.start()].strip()
    return head, num


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


def _try_parse_product_no_pipes(line: str):
    """
    ✅ BARU (produk):
    - "nama qty harga"  -> nama | qty | RMharga
    - "nama harga"      -> nama | ❓ | RMharga   (INI KES 125cc follspek 5900)
    - "nama qty"        -> nama | qty | ❓
    - "harga"           -> ❓ | ❓ | RMharga
    - "nama"            -> nama | ❓ | ❓
    """
    s = (line or "").strip()
    if not s:
        return None

    head, num = _last_number_token(s)

    if not num:
        # tiada nombor langsung => nama sahaja
        return f"{s} | ❓ | ❓"

    n = int(num)

    # heuristic: <=30 dianggap qty
    if n <= 30:
        name_part = head.strip()
        if not name_part:
            name_part = "❓"
        return f"{name_part} | {n} | ❓"

    # n > 30 => harga
    money = f"RM{n}"

    # cuba detect qty di hujung head: "... 1"
    mqty = re.search(r"\b(\d{1,3})\s*$", head)
    if mqty:
        qty = int(mqty.group(1))
        name_part = head[:mqty.start()].strip()
        if not name_part:
            name_part = "❓"
        return f"{name_part} | {qty} | {money}"

    # tiada qty => auto ❓
    name_part = head.strip()
    if not name_part:
        name_part = "❓"
    return f"{name_part} | ❓ | {money}"


def _try_parse_cost_no_pipes(line: str):
    """
    ✅ BARU (penghantaran):
    - "tempat jenis kos" -> tempat | jenis | RMkos
    - "tempat kos"      -> tempat | ❓ | RMkos
    - "tempat jenis"    -> tempat | jenis | ❓
    - "jenis kos"       -> ❓ | jenis | RMkos
    - "kos"             -> ❓ | ❓ | RMkos
    """
    s = (line or "").strip()
    if not s:
        return None

    head, num = _last_number_token(s)
    money = None
    base = s

    if num:
        n = int(num)
        if n > 30:
            money = f"RM{n}"
            base = head.strip()
        else:
            # nombor kecil biasanya qty, bukan kos => treat kos tiada
            base = s

    words = [w for w in re.split(r"\s+", base) if w]

    if not words:
        if money:
            return f"❓ | ❓ | {money}"
        return None

    best_t, best_score, cut = _best_transport_suffix(words)
    if best_t and best_score >= TRANSPORT_THRESHOLD:
        dest = " ".join(words[:cut]).strip() if cut is not None else ""
        if not dest:
            dest = "❓"
        if not money:
            money = "❓"
        return f"{dest} | {best_t} | {money}"

    # tiada jenis match, tapi ada kos => tempat | ❓ | kos
    if money:
        dest = " ".join(words).strip()
        if not dest:
            dest = "❓"
        return f"{dest} | ❓ | {money}"

    return None


def auto_insert_pipes_if_missing(line: str) -> str:
    """
    ✅ BARU:
    Kalau user tak guna '|', kita auto jadikan 3 segmen dan isi ❓ ikut logic.
    Keutamaan:
    1) penghantaran
    2) produk
    """
    s = (line or "").strip()
    if not s:
        return s

    if ("|" in s) or ("｜" in s):
        return s

    as_cost = _try_parse_cost_no_pipes(s)
    if as_cost:
        return as_cost

    as_product = _try_parse_product_no_pipes(s)
    if as_product:
        return as_product

    return s


# ================= NORMALIZE DETAIL LINE =================
def normalize_detail_line(line: str) -> str:
    line = auto_insert_pipes_if_missing(line)

    if ("|" not in line) and ("｜" not in line):
        return line

    raw_parts = _split_pipes(line)
    parts = fill_missing_segments(raw_parts, 3)  # kosong -> ❓

    transport_like = is_transport_like_parts(parts)

    # segmen 1
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

    # segmen 2
    if transport_like:
        if parts[1] != "❓":
            best_t, tscore = best_transport_match(parts[1])
            if best_t and tscore >= TRANSPORT_THRESHOLD:
                parts[1] = best_t
    else:
        # qty produk: biar user, kalau kosong memang dah jadi ❓
        pass

    # segmen 3
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


def stylize_line_for_caption(line: str) -> str:
    # Penghantaran: tempat+jenis bold2, kos bold biasa (RMxxx / ❓)
    if ("|" in line) or ("｜" in line):
        parts = fill_missing_segments(_split_pipes(line), 3)
        if is_transport_like_parts(parts):
            return " | ".join([bold2(parts[0]), bold2(parts[1]), bold(parts[2])])
    # Produk / lain: bold biasa
    return bold(line)


def build_caption(user_caption: str) -> str:
    stamp = bold(make_stamp())

    detail_lines_raw = extract_lines(user_caption)
    detail_lines = [normalize_detail_line(x) for x in detail_lines_raw]

    total = calc_total(detail_lines)

    parts = [stamp, ""]
    for ln in detail_lines:
        parts.append(stylize_line_for_caption(ln))
    parts += ["", f"Total keseluruhan : {bold('RM' + str(total))}"]

    cap = "\n".join(parts)
    if len(cap) > 1024:
        cap = cap[:1000] + "\n...(caption terlalu panjang)"
    return cap


# =========================================================
# ✅ STATE: PRODUK/ALBUM (SUPAYA SWIPE KE-2, KE-3... BOLEH)
# =========================================================
STATE_TTL_SEC = float(os.getenv("STATE_TTL_SEC", "86400"))      # 24 jam
RECEIPT_DELAY_SEC = float(os.getenv("RECEIPT_DELAY_SEC", "1.0"))  # tunggu album resit complete

# state_id = (chat_id, root_id)
# data = {"product_file_id","caption","receipts":[...],"msg_ids":[...],"ts":epoch}
ORDER_STATES = {}
# map message_id -> state_id (supaya reply pada mana-mana keping album pun boleh)
MSGID_TO_STATE = {}

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
    # reply pada root single post (yang baru) => root = reply_to_id
    return (chat_id, reply_to_id)


async def _delete_message_safe(msg):
    try:
        await tg_call(msg.delete)
    except (MessageDeleteForbidden, ChatAdminRequired):
        pass
    except:
        pass


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


async def _send_album_and_update_state(client: Client, chat_id: int, state_id, product_file_id: str, caption: str, receipts: list):
    """
    Hantar album: [produk+caption] + receipts (cumulative)
    Update msg_ids + MSGID_TO_STATE
    """
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
        # pastikan caption hanya pada first item of first chunk
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

    for mid in sent_msg_ids:
        MSGID_TO_STATE[(chat_id, mid)] = state_id

    ORDER_STATES[state_id] = {
        "product_file_id": product_file_id,
        "caption": caption,
        "receipts": list(receipts),
        "msg_ids": list(sent_msg_ids),
        "ts": time.time(),
    }
    return sent_msg_ids


async def _merge_receipts_and_repost(client: Client, chat_id: int, reply_to_id: int, new_receipt_file_ids: list):
    """
    ✅ INI YANG BUAT PROSES BERULANG:
    - reply pada post produk (kali 1) atau reply pada album (kali 2/3/4...)
    - tambah resit (cumulative)
    - padam album lama
    - repost album baru
    """
    if not new_receipt_file_ids:
        return False

    async with _state_lock:
        _cleanup_states()
        state_id = _get_state_id_from_reply(chat_id, reply_to_id)
        state = ORDER_STATES.get(state_id)
        if not state:
            return False

        receipts = state.get("receipts", []) + list(new_receipt_file_ids)

        # padam album lama
        old_ids = state.get("msg_ids", [])
        await _delete_messages_safe(client, chat_id, old_ids)

        # buang mapping lama
        for mid in old_ids:
            MSGID_TO_STATE.pop((chat_id, mid), None)

        # repost album baru
        await _send_album_and_update_state(
            client, chat_id, state_id,
            state["product_file_id"],
            state.get("caption", ""),
            receipts
        )
        return True


# =========================================================
# ✅ RECEIPT GROUP BUFFER (album user)
# =========================================================
_pending_receipt_groups = {}  # key=(chat_id, media_group_id, reply_to_id) -> {"msgs":[Message], "task":Task}
_pending_lock = asyncio.Lock()


def is_reply_to_any_message(message) -> bool:
    try:
        return bool(message.reply_to_message and message.reply_to_message.id)
    except:
        return False


async def _process_receipt_group(client: Client, chat_id: int, media_group_id: str, reply_to_id: int):
    # tunggu sekejap supaya semua keping album resit sampai
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

    merged = await _merge_receipts_and_repost(client, chat_id, reply_to_id, receipt_file_ids)
    if merged:
        return

    # fallback: kalau tak jumpa state, repost resit sahaja (reply)
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


# ================= HANDLER (GABUNG) =================
@bot.on_message(filters.photo & ~filters.bot)
async def handle_photo(client, message):
    """
    1) Jika user swipe kiri (reply) dan hantar resit => proses resit (repeatable, cumulative album).
    2) Kalau bukan reply => post produk biasa => format caption & repost.
       -> simpan state awal (root = sent.id) supaya reply seterusnya boleh merge resit.
    """
    # ✅ receipt mode
    if is_reply_to_any_message(message):
        await handle_receipt_photo(client, message)
        return

    # ✅ normal mode (produk)
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

    # ✅ simpan state awal (supaya swipe/resit boleh merge)
    try:
        if sent and sent.photo:
            async with _state_lock:
                _cleanup_states()
                state_id = (chat_id, sent.id)
                ORDER_STATES[state_id] = {
                    "product_file_id": sent.photo.file_id,
                    "caption": sent.caption or new_caption,
                    "receipts": [],
                    "msg_ids": [sent.id],   # mula-mula masih single
                    "ts": time.time(),
                }
                MSGID_TO_STATE[(chat_id, sent.id)] = state_id
    except:
        pass


if __name__ == "__main__":
    bot.run()

