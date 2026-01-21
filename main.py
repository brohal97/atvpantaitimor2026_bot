import os
import re
from datetime import datetime

import pytz
from pyrogram import Client, filters
from pyrogram.errors import MessageDeleteForbidden, ChatAdminRequired
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply

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
# key = bot_message_id (mesej gambar bot)
# value = {
#   "chat_id": int,
#   "photo_id": str,
#   "base_caption": str,
#   "items": {produk_key: qty_int},
#   "prices": {produk_key: price_str},
#   "stage": "produk" | "harga",
# }
ORDER_STATE = {}

# PENDING_PRICE key = prompt_message_id
# value = {"bot_msg_id": int, "produk_key": str}
PENDING_PRICE = {}

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

# ================= HELPERS =================
def normalize_price(text: str) -> str:
    s = (text or "").strip()
    digits = re.sub(r"[^\d]", "", s)
    return digits

def build_caption(base_caption: str, items_dict: dict, prices_dict: dict, header: str = "") -> str:
    lines = []
    if header:
        lines.append(header)
        lines.append("")
    lines.append(base_caption)

    if items_dict:
        lines.append("")
        for k, q in items_dict.items():
            nama = PRODUK_LIST.get(k, k)
            if k in prices_dict and str(prices_dict[k]).strip():
                lines.append(f"{nama} | {q} | {prices_dict[k]}")
            else:
                lines.append(f"{nama} | {q}")
    return "\n".join(lines)

def build_produk_keyboard(items_dict: dict) -> InlineKeyboardMarkup:
    rows = []
    for key, name in PRODUK_LIST.items():
        if key not in items_dict:
            rows.append([InlineKeyboardButton(name, callback_data=f"produk_{key}")])
    if items_dict:
        rows.append([InlineKeyboardButton("✅ SUBMIT", callback_data="submit")])
    return InlineKeyboardMarkup(rows)

def build_qty_keyboard(produk_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1", callback_data=f"qty_{produk_key}_1"),
            InlineKeyboardButton("2", callback_data=f"qty_{produk_key}_2"),
            InlineKeyboardButton("3", callback_data=f"qty_{produk_key}_3"),
        ],
        [
            InlineKeyboardButton("4", callback_data=f"qty_{produk_key}_4"),
            InlineKeyboardButton("5", callback_data=f"qty_{produk_key}_5"),
        ],
        [InlineKeyboardButton("⬅️ KEMBALI", callback_data="back_produk")]
    ])

def build_harga_keyboard(items_dict: dict, prices_dict: dict) -> InlineKeyboardMarkup:
    rows = []
    for k in items_dict.keys():
        if k not in prices_dict:
            nama = PRODUK_LIST.get(k, k)
            rows.append([InlineKeyboardButton(f"HARGA - {nama}", callback_data=f"harga_{k}")])

    if not rows and items_dict:
        rows = [[InlineKeyboardButton("✅ SEMUA HARGA SIAP", callback_data="harga_done")]]

    rows.append([InlineKeyboardButton("❌ BATAL", callback_data="harga_cancel")])
    return InlineKeyboardMarkup(rows)

async def repost_photo(client, old_msg, state: dict, reply_markup):
    # Paparkan header [HARGA] bila stage == harga
    header = "[HARGA]" if state.get("stage") == "harga" else ""
    caption_baru = build_caption(state["base_caption"], state["items"], state["prices"], header=header)

    try:
        await old_msg.delete()
    except Exception:
        pass

    new_msg = await client.send_photo(
        chat_id=state["chat_id"],
        photo=state["photo_id"],
        caption=caption_baru,
        reply_markup=reply_markup
    )
    return new_msg

# ================= CALLBACKS =================

@bot.on_callback_query(filters.regex(r"^hantar_detail$"))
async def senarai_produk(client, callback):
    msg_id = callback.message.id
    state = ORDER_STATE.get(msg_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai. Sila hantar gambar semula.", show_alert=True)
        return

    keyboard = build_produk_keyboard(state["items"])
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer()

@bot.on_callback_query(filters.regex(r"^back_produk$"))
async def back_produk(client, callback):
    msg_id = callback.message.id
    state = ORDER_STATE.get(msg_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    keyboard = build_produk_keyboard(state["items"])
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer()

@bot.on_callback_query(filters.regex(r"^produk_"))
async def pilih_kuantiti(client, callback):
    msg_id = callback.message.id
    state = ORDER_STATE.get(msg_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    produk_key = callback.data.replace("produk_", "", 1)
    await callback.message.edit_reply_markup(reply_markup=build_qty_keyboard(produk_key))
    await callback.answer("Pilih kuantiti")

@bot.on_callback_query(filters.regex(r"^qty_"))
async def simpan_qty_repost(client, callback):
    msg = callback.message
    old_msg_id = msg.id
    state = ORDER_STATE.get(old_msg_id)

    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    try:
        payload = callback.data[len("qty_"):]
        produk_key, qty_str = payload.rsplit("_", 1)
        qty = int(qty_str)
    except Exception:
        await callback.answer("Format kuantiti tidak sah.", show_alert=True)
        return

    state["items"][produk_key] = qty
    await callback.answer("Dikemaskini")

    keyboard_produk = build_produk_keyboard(state["items"])
    reply_markup = keyboard_produk if keyboard_produk.inline_keyboard else None

    new_msg = await repost_photo(client, msg, state, reply_markup)

    ORDER_STATE[new_msg.id] = {**state}
    ORDER_STATE.pop(old_msg_id, None)

@bot.on_callback_query(filters.regex(r"^submit$"))
async def submit_order(client, callback):
    msg = callback.message
    old_msg_id = msg.id
    state = ORDER_STATE.get(old_msg_id)

    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    if not state["items"]:
        await callback.answer("Sila pilih sekurang-kurangnya 1 produk.", show_alert=True)
        return

    state["stage"] = "harga"

    await callback.answer("Sila isi harga")

    harga_keyboard = build_harga_keyboard(state["items"], state["prices"])
    reply_markup = harga_keyboard if harga_keyboard.inline_keyboard else None

    new_msg = await repost_photo(client, msg, state, reply_markup)

    ORDER_STATE[new_msg.id] = {**state}
    ORDER_STATE.pop(old_msg_id, None)

@bot.on_callback_query(filters.regex(r"^harga_cancel$"))
async def harga_cancel(client, callback):
    await callback.answer("Batal")
    # tiada perubahan, cuma biar user tekan harga semula

@bot.on_callback_query(filters.regex(r"^harga_done$"))
async def harga_done(client, callback):
    await callback.answer("Semua harga sudah diisi.")

# ===== Tekan HARGA -> bot auto buka reply mode (ForceReply) =====
@bot.on_callback_query(filters.regex(r"^harga_"))
async def minta_harga(client, callback):
    bot_msg_id = callback.message.id
    state = ORDER_STATE.get(bot_msg_id)

    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    produk_key = callback.data.replace("harga_", "", 1)
    nama = PRODUK_LIST.get(produk_key, produk_key)

    # ✅ Ini kunci: bot hantar prompt yg REPLY kepada gambar + ForceReply
    prompt = await client.send_message(
        chat_id=state["chat_id"],
        text=f"Taip harga untuk: {nama}\nContoh: 2950 atau RM2950",
        reply_to_message_id=bot_msg_id,                  # reply kepada gambar
        reply_markup=ForceReply(selective=True)          # auto buka reply UI
    )

    # simpan pending: bila staff send harga (reply kepada prompt), kita tahu produk mana
    PENDING_PRICE[prompt.id] = {"bot_msg_id": bot_msg_id, "produk_key": produk_key}

    await callback.answer("Sila taip harga (auto reply)")

# ================= TERIMA HARGA (mesti reply prompt) =================
@bot.on_message(filters.text & ~filters.bot)
async def terima_harga(client, message):
    if not message.reply_to_message:
        return

    prompt_id = message.reply_to_message.id
    pending = PENDING_PRICE.get(prompt_id)
    if not pending:
        return

    bot_msg_id = pending["bot_msg_id"]
    produk_key = pending["produk_key"]

    state = ORDER_STATE.get(bot_msg_id)
    if not state:
        PENDING_PRICE.pop(prompt_id, None)
        return

    harga = normalize_price(message.text)
    if not harga:
        return

    state["prices"][produk_key] = harga

    # padam mesej staff (jika bot admin)
    try:
        await message.delete()
    except Exception:
        pass

    # padam prompt bot
    try:
        await message.reply_to_message.delete()
    except Exception:
        pass

    # repost gambar dengan caption update & butang tinggal yang belum isi harga
    harga_keyboard = build_harga_keyboard(state["items"], state["prices"])
    reply_markup = harga_keyboard if harga_keyboard.inline_keyboard else None

    try:
        old_photo_msg = await client.get_messages(state["chat_id"], bot_msg_id)
    except Exception:
        PENDING_PRICE.pop(prompt_id, None)
        return

    new_msg = await repost_photo(client, old_photo_msg, state, reply_markup)

    # pindah state ke message baru
    ORDER_STATE[new_msg.id] = {**state}
    ORDER_STATE.pop(bot_msg_id, None)

    # buang pending
    PENDING_PRICE.pop(prompt_id, None)

# ================= FOTO =================
@bot.on_message(filters.photo & ~filters.bot)
async def handle_photo(client, message):
    photo_id = message.photo.file_id

    tz = pytz.timezone("Asia/Kuala_Lumpur")
    now = datetime.now(tz)

    hari = ["Isnin", "Selasa", "Rabu", "Khamis", "Jumaat", "Sabtu", "Ahad"][now.weekday()]
    tarikh = f"{now.day}/{now.month}/{now.year}"
    jam = now.strftime("%I:%M%p").lower()
    base_caption = f"{hari} | {tarikh} | {jam}"

    keyboard_awal = InlineKeyboardMarkup([
        [InlineKeyboardButton("NAMA PRODUK", callback_data="hantar_detail")]
    ])

    try:
        await message.delete()
    except (MessageDeleteForbidden, ChatAdminRequired):
        pass
    except Exception:
        pass

    sent = await client.send_photo(
        chat_id=message.chat.id,
        photo=photo_id,
        caption=base_caption,
        reply_markup=keyboard_awal
    )

    ORDER_STATE[sent.id] = {
        "chat_id": message.chat.id,
        "photo_id": photo_id,
        "base_caption": base_caption,
        "items": {},
        "prices": {},
        "stage": "produk",
    }

if __name__ == "__main__":
    bot.run()
