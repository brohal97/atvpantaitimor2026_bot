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


# ================= SAFE TG CALL =================
async def tg_call(fn, *args, **kwargs):
    while True:
        try:
            return await fn(*args, **kwargs)
        except FloodWait as e:
            await asyncio.sleep(int(getattr(e, "value", 1)) + 1)
        except RPCError:
            await asyncio.sleep(0.2)


# ================= CORE HELPERS =================
def make_stamp() -> str:
    now = datetime.now(TZ)
    hari = HARI[now.weekday()]
    tarikh = f"{now.day}/{now.month}/{now.year}"
    jam = now.strftime("%I:%M%p").lower()  # contoh 9:30am
    return f"{hari} | {tarikh} | {jam}"


def clean_detail_text(text: str) -> str:
    """
    Buang baris kosong di hujung, dan buang baris yang ada 'total'
    (supaya total baru bot kira semula).
    """
    if not text:
        return ""
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]  # buang empty lines

    # buang mana2 line yang mengandungi "total"
    cleaned = []
    for ln in lines:
        if re.search(r"\btotal\b", ln, flags=re.IGNORECASE):
            continue
        cleaned.append(ln)

    return "\n".join(cleaned).strip()


def calc_total_from_text(text: str) -> int:
    """
    Jumlahkan semua nilai RMxxxx / rmxxxx yang muncul dalam detail.
    Contoh: RM5000 + RM5500 + rm300 = 10800
    """
    if not text:
        return 0

    # cari RM diikuti digit (boleh ada ruang)
    nums = re.findall(r"(?i)\bRM\s*([0-9]{1,12})\b", text)
    total = 0
    for n in nums:
        try:
            total += int(n)
        except:
            pass
    return total


def build_caption(user_caption: str) -> str:
    stamp = make_stamp()

    # detail = semua caption user, tapi buang baris TOTAL yang mungkin user letak
    detail = clean_detail_text(user_caption)

    # kira total dari semua RM dalam detail
    total = calc_total_from_text(detail)

    # caption akhir
    parts = [stamp]
    if detail:
        parts.append(detail)

    parts.append(f"Total keseluruhan : RM{total}")

    cap = "\n".join(parts).strip()

    # telegram caption limit safety
    if len(cap) > 1024:
        cap = cap[:1000] + "\n...(caption terlalu panjang)"

    return cap


# ================= MAIN HANDLER =================
@bot.on_message(filters.photo & ~filters.bot)
async def handle_photo_with_detail(client: Client, message):
    """
    User hantar GAMBAR + caption (detail).
    Bot padam mesej asal dan repost dengan stamp terkini + total automatik.
    """
    chat_id = message.chat.id
    photo_id = message.photo.file_id
    user_caption = (message.caption or "").strip()

    # kalau tiada detail, boleh biar (atau boleh warn). Saya biar tetap repost, total=0
    new_caption = build_caption(user_caption)

    # padam mesej asal untuk kemas
    try:
        await tg_call(message.delete)
    except (MessageDeleteForbidden, ChatAdminRequired):
        pass
    except:
        pass

    # repost (paling laju: terus send_photo, tanpa edit_caption)
    await tg_call(
        client.send_photo,
        chat_id=chat_id,
        photo=photo_id,
        caption=new_caption
    )


if __name__ == "__main__":
    bot.run()

