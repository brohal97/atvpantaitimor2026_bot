import os
from datetime import datetime

import pytz
from pyrogram import Client, filters
from pyrogram.errors import MessageDeleteForbidden, ChatAdminRequired
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
)

# ================= ENV =================
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Missing API_ID / API_HASH / BOT_TOKEN in Railway Variables")

# ================= BOT =================
bot = Client(
    "atv_bot_2026",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ================= TEMP STATE (RAM) =================
ORDER_STATE = {}
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
HARGA_PER_PAGE = 15

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
KOS_PER_PAGE = 15

MAX_RECEIPTS_IN_ALBUM = 9

# ================= TEXT STYLE =================
BOLD_MAP = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
    "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
    "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"
)

def bold(text: str) -> str:
    return text.translate(BOLD_MAP)

# ================= UTIL =================
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
        total += int(unit) * int(qty)
    return total

def build_caption(
    base_caption,
    items_dict,
    prices_dict=None,
    dest=None,
    ship_cost=None,
    locked=False,
    receipts_count=0,
):
    prices_dict = prices_dict or {}
    lines = [base_caption]

    if items_dict:
        lines.append("")
        for k, q in items_dict.items():
            nama = PRODUK_LIST.get(k, k)
            unit = prices_dict.get(k)
            harga = "-" if unit is None else f"RM{int(unit) * int(q)}"
            lines.append(f"{nama} | {q} | {harga}")

    if dest:
        lines.append("")
        if ship_cost is None:
            lines.append(f"Destinasi : {dest}")
        else:
            lines.append(f"Destinasi : {dest} | RM{ship_cost}")

    if items_dict and is_all_prices_done(items_dict, prices_dict) and ship_cost is not None:
        total = calc_products_total(items_dict, prices_dict) + int(ship_cost)
        lines.append("")
        lines.append(f"TOTAL KESELURUHAN : RM{total}")

    if locked:
        lines.append("")
        if receipts_count == 0:
            lines.append("⬅️" + bold("SLIDE KIRI UPLOAD RESIT"))
        else:
            lines.append("⬅️" + bold("SLIDE KIRI TAMBAH RESIT"))

    return "\n".join(lines)

def build_payment_keyboard(paid: bool):
    if paid:
        return InlineKeyboardMarkup([[InlineKeyboardButton("PAYMENT SETTLED", callback_data="noop")]])
    return InlineKeyboardMarkup([[InlineKeyboardButton("PAYMENT SETTLE", callback_data="pay_settle")]])

# ================= PHOTO HANDLER =================
@bot.on_message(filters.photo & ~filters.bot)
async def handle_photo(client, message):
    chat_id = message.chat.id

    if message.reply_to_message:
        replied_id = message.reply_to_message.id

        state = ORDER_STATE.get(replied_id)
        if not state and replied_id in REPLY_MAP:
            state = ORDER_STATE.get(REPLY_MAP[replied_id])

        if state and state.get("locked"):
            try:
                await message.delete()
            except Exception:
                pass

            state["receipts"].append(message.photo.file_id)
            state["receipts"] = state["receipts"][-MAX_RECEIPTS_IN_ALBUM:]

            media = [InputMediaPhoto(
                media=state["photo_id"],
                caption=build_caption(
                    state["base_caption"],
                    state["items"],
                    state["prices"],
                    state["dest"],
                    state["ship_cost"],
                    locked=True,
                    receipts_count=len(state["receipts"])
                )
            )]

            for r in state["receipts"]:
                media.append(InputMediaPhoto(media=r))

            album = await client.send_media_group(chat_id, media)
            control = await client.send_message(
                chat_id,
                "TEKAN BUTANG DIBAWAH SAHKAN PEMBAYARAN SELESAI",
                reply_markup=build_payment_keyboard(state["paid"])
            )

            for m in album:
                REPLY_MAP[m.id] = control.id

            ORDER_STATE[control.id] = state
            return

    photo_id = message.photo.file_id
    tz = pytz.timezone("Asia/Kuala_Lumpur")
    now = datetime.now(tz)
    hari = ["Isnin","Selasa","Rabu","Khamis","Jumaat","Sabtu","Ahad"][now.weekday()]
    base_caption = f"{hari} | {now.day}/{now.month}/{now.year} | {now.strftime('%I:%M%p').lower()}"

    try:
        await message.delete()
    except Exception:
        pass

    sent = await client.send_photo(
        chat_id,
        photo_id,
        caption=base_caption,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("NAMA PRODUK", callback_data="hantar_detail")]]
        )
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
        "paid": False,
        "locked": False,
    }

if __name__ == "__main__":
    bot.run()

