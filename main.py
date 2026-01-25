import os, re, asyncio
from datetime import datetime
import pytz

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


# ================= CORE LOGIC =================
def make_stamp() -> str:
    now = datetime.now(TZ)
    hari = HARI[now.weekday()]
    tarikh = f"{now.day}/{now.month}/{now.year}"
    jam = now.strftime("%I:%M%p").lower()
    return f"{hari} | {tarikh} | {jam}"


def is_separator_line(ln: str) -> bool:
    """
    Buang line yang user taip seperti:
    -----
    _____
    ─────
    """
    s = (ln or "").strip()
    if not s:
        return True
    return bool(re.match(r"^[\s\-_─—=]{3,}$", s))


def extract_lines(text: str):
    lines = []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        # buang baris total lama kalau ada
        if re.search(r"\btotal\b", ln, flags=re.IGNORECASE):
            continue
        # buang separator yang user buat sendiri
        if is_separator_line(ln):
            continue
        lines.append(ln)
    return lines


def _normalize_rm_value(val: str) -> str:
    """
    Pastikan nilai akhir format RM<angka> (RM huruf besar).
    - "200" -> "RM200"
    - "rm200" / "Rm 200" -> "RM200"
    - "RM200" -> "RM200"
    """
    s = (val or "").strip()
    if not s:
        return s

    m = re.search(r"(?i)\brm\s*([0-9]{1,12})\b", s)
    if m:
        return f"RM{m.group(1)}"

    m2 = re.search(r"\b([0-9]{1,12})\b", s)
    if m2:
        return f"RM{m2.group(1)}"

    return s


def normalize_detail_line(line: str) -> str:
    """
    - Segmen pertama (nama produk) -> UPPERCASE
    - Segmen terakhir -> auto RM huruf besar + auto tambah RM jika user lupa
    """
    if "|" not in line:
        return line.strip()

    parts = [p.strip() for p in line.split("|")]
    if len(parts) < 2:
        return line.strip()

    # segmen pertama uppercase (nama produk / tempat)
    parts[0] = parts[0].upper()

    # segmen terakhir normalize RM
    parts[-1] = _normalize_rm_value(parts[-1])

    return " | ".join(parts)


def is_transport_line(line: str) -> bool:
    """
    Kesan baris transport:
    contoh: "IPOH PERAK | Transport luar | RM300"
    """
    if "|" not in line:
        return False
    parts = [p.strip() for p in line.split("|")]
    if len(parts) < 3:
        return False
    return bool(re.search(r"transport", parts[1], flags=re.IGNORECASE))


def make_separator_for_transport(line: str) -> str:
    """
    ✅ Garisan berhujung pada nilai RM dalam baris transport.
    Contoh: "IPOH PERAK | Transport luar | RM300"
    Garisan panjang = sampai hujung "RM300" sahaja.
    """
    # kemaskan spacing dulu supaya ukuran stabil
    clean = re.sub(r"\s+", " ", (line or "").strip())
    clean = re.sub(r"\s*\|\s*", " | ", clean).strip()

    # ambil substring sampai hujung RMxxxx
    m = re.search(r"\bRM\s*[0-9]{1,12}\b", clean, flags=re.IGNORECASE)
    if m:
        clean = clean[:m.end()].strip()

    # clamp (supaya tak jadi pelik)
    MIN_SEP = int(os.getenv("MIN_SEP_LEN", "12"))
    MAX_SEP = int(os.getenv("MAX_SEP_LEN", "45"))  # ✅ kecilkan default max
    n = len(clean)
    if n < MIN_SEP:
        n = MIN_SEP
    if n > MAX_SEP:
        n = MAX_SEP

    return "─" * n


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

    raw_lines = extract_lines(user_caption)
    detail_lines = [normalize_detail_line(x) for x in raw_lines]
    total = calc_total(detail_lines)

    # cari baris transport terakhir (kalau ada)
    transport_idx = None
    transport_line = None
    for i, ln in enumerate(detail_lines):
        if is_transport_line(ln):
            transport_idx = i
            transport_line = ln

    parts = []
    parts.append(stamp)
    parts.append("")  # perenggan kosong

    for i, ln in enumerate(detail_lines):
        # sebelum baris transport, letak 1 separator sahaja (ikut hujung RM)
        if transport_idx is not None and i == transport_idx and transport_line:
            parts.append(make_separator_for_transport(transport_line))

        parts.append(bold(ln))

    parts.append("")  # perenggan kosong
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

    # padam mesej asal
    try:
        await tg_call(message.delete)
    except (MessageDeleteForbidden, ChatAdminRequired):
        pass
    except:
        pass

    # repost versi kemas
    await tg_call(
        client.send_photo,
        chat_id=chat_id,
        photo=photo_id,
        caption=new_caption
    )


if __name__ == "__main__":
    bot.run()
