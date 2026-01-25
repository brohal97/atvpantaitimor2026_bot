import os, re, asyncio
from datetime import datetime
import pytz
from difflib import SequenceMatcher

from pyrogram import Client, filters
from pyrogram.errors import FloodWait, RPCError, MessageDeleteForbidden, ChatAdminRequired


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


# ================= BOLD STYLE =================
BOLD_MAP = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
    "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
    "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"
)

def bold(text: str) -> str:
    return (text or "").translate(BOLD_MAP)


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


# ✅ separator: tepat 10 dash
SEP_10_DASH = "-" * 10


# ================= AUTO INSERT ' | ' IF USER TERLUPA =================
def _extract_tail_money(text: str):
    """
    Ambil duit di hujung:
      "... rm5200" / "... 5200" -> (head, "RM5200")
    Jika tiada nombor, return (text, None)
    """
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
    """
    Format tanpa '|':
      "<produk> <qty> <rm/harga>"
    contoh: "125ccc full spec 2 rm5200"
    """
    head, money = _extract_tail_money(line)
    if not money:
        return None

    # qty mesti nombor token terakhir dalam head
    mqty = re.search(r"\b(\d{1,3})\s*$", head)
    if not mqty:
        return None

    qty = mqty.group(1)
    name_part = head[:mqty.start()].strip()
    if not name_part:
        return None

    return f"{name_part} | {qty} | {money}"


def _best_transport_suffix(words):
    """
    Cari suffix (1-5 perkataan) yang paling hampir dengan 3 jenis transport.
    Return: (best_transport_name, score, cut_index)
    cut_index = index mula suffix dalam list words
    """
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
    """
    Format tanpa '|':
      "<destinasi> <jenis transport> <rm/harga>"
    contoh: "kota bharu lori kita hantar rm50"
    """
    head, money = _extract_tail_money(line)
    if not money:
        return None

    # pecah words
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
    """
    Jika user tak letak '|', cuba auto bina:
      - produk:  name | qty | RMxx
      - kos:    destinasi | jenis | RMxx
    Kalau gagal parse, return line asal.
    """
    s = (line or "").strip()
    if not s:
        return s

    # kalau user dah guna pipe biasa / fullwidth, biar
    if ("|" in s) or ("｜" in s):
        return s

    # cuba detect produk dulu (ada qty)
    as_product = _try_parse_product_no_pipes(s)
    if as_product:
        return as_product

    # kemudian cuba detect kos/transport
    as_cost = _try_parse_cost_no_pipes(s)
    if as_cost:
        return as_cost

    return s


def normalize_detail_line(line: str) -> str:
    # ✅ tambahan: auto masukkan "|" bila user terlupa
    line = auto_insert_pipes_if_missing(line)

    if ("|" not in line) and ("｜" not in line):
        return line

    parts = _split_pipes(line)
    if len(parts) < 2:
        return line

    # ===== segmen 1: produk/destinasi =====
    first = parts[0]
    best_name, score = best_product_match(first)
    if best_name and score >= FUZZY_THRESHOLD:
        parts[0] = best_name
    else:
        parts[0] = first.upper()

    # ===== segmen 2: jenis transport (untuk baris kos/destinasi) =====
    if len(parts) >= 3 and is_cost_or_transport_line(line):
        user_type = parts[1]
        best_t, tscore = best_transport_match(user_type)
        if best_t and tscore >= TRANSPORT_THRESHOLD:
            parts[1] = best_t

    # ===== segmen last: RM =====
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


def build_caption(user_caption: str) -> str:
    stamp = bold(make_stamp())

    detail_lines_raw = extract_lines(user_caption)
    detail_lines = [normalize_detail_line(x) for x in detail_lines_raw]

    total = calc_total(detail_lines)

    parts = []
    parts.append(stamp)
    parts.append("")

    inserted_sep = False
    for ln in detail_lines:
        # ✅ Auto letak 10 dash sebelum baris kos/destinasi (sekali sahaja)
        if (not inserted_sep) and is_cost_or_transport_line(ln):
            parts.append(bold(SEP_10_DASH))
            inserted_sep = True

        parts.append(bold(ln))

    parts.append("")
    parts.append(f"Total keseluruhan : {bold('RM' + str(total))}")

    cap = "\n".join(parts)
    if len(cap) > 1024:
        cap = cap[:1000] + "\n...(caption terlalu panjang)"
    return cap


# ================= HANDLER =================
@bot.on_message(filters.photo & ~filters.bot)
async def handle_photo(client, message):
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

    await tg_call(
        client.send_photo,
        chat_id=chat_id,
        photo=photo_id,
        caption=new_caption
    )


if __name__ == "__main__":
    bot.run()

