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


def extract_lines(text: str):
    lines = []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        # buang baris total lama kalau ada
        if re.search(r"\btotal\b", ln, flags=re.IGNORECASE):
            continue
        lines.append(ln)
    return lines


def _normalize_rm_value(val: str) -> str:
    """
    Jadikan nilai akhir sentiasa format: RM<angka>
    - "200" -> "RM200"
    - "rm200" / "Rm 200" -> "RM200"
    - "RM200" -> "RM200"
    Jika tak jumpa nombor, pulangkan asal.
    """
    s = (val or "").strip()
    if not s:
        return s

    # cari nombor pertama (support koma/spasi)
    m = re.search(r"(?i)\b(?:rm)?\s*([0-9]{1,12})\b", s)
    if not m:
        # kalau user tulis macam "rm 300." atau ada simbol pelik, cuba cari digits sahaja
        m2 = re.search(r"([0-9]{1,12})", s)
        if not m2:
            return s
        num = m2.group(1)
        return f"RM{num}"

    num = m.group(1)
    return f"RM{num}"


def normalize_detail_line(line: str) -> str:
    """
    Rules:
    1) Segmen pertama (nama produk/destinasi) -> UPPERCASE
    2) Segmen terakhir -> pastikan bermula 'RM' uppercase, auto tambah jika user lupa.
    """
    if "|" not in line:
        return line

    parts = [p.strip() for p in line.split("|")]
    if len(parts) < 2:
        return line

    # segmen pertama: uppercase
    parts[0] = parts[0].upper()

    # segmen terakhir: normalize RM
    parts[-1] = _normalize_rm_value(parts[-1])

    return " | ".join(parts)


# ✅ TAMBAHAN SAHAJA: kesan baris transport + separator 10 dash
SEP_10_DASH = "-" * 10

def is_transport_line(line: str) -> bool:
    # Kesan baris seperti: "IPOH PERAK | Transport luar | RM300"
    if "|" not in (line or ""):
        return False
    parts = [p.strip() for p in line.split("|")]
    if len(parts) < 3:
        return False
    return bool(re.search(r"\btransport\b", parts[1], flags=re.IGNORECASE))


def calc_total(lines):
    total = 0
    for ln in lines:
        # kira semua nombor selepas RM (case-insensitive)
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
    # normalize dulu (supaya total kira betul walaupun user tak tulis RM)
    detail_lines = [normalize_detail_line(x) for x in detail_lines_raw]

    total = calc_total(detail_lines)

    parts = []
    parts.append(stamp)
    parts.append("")  # perenggan kosong

    inserted_sep = False
    for ln in detail_lines:
        # ✅ TAMBAHAN SAHAJA: auto letak 10 dash sebelum baris transport (sekali sahaja)
        if (not inserted_sep) and is_transport_line(ln):
            parts.append(SEP_10_DASH)
            inserted_sep = True

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
