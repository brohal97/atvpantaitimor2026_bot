import os
from datetime import datetime

import pytz
from pyrogram import Client, filters
from pyrogram.errors import MessageDeleteForbidden, ChatAdminRequired
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ForceReply
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
# ORDER_STATE key = bot_message_id (mesej gambar yg bot hantar)
# value = {
#   "chat_id": int,
#   "photo_id": str,
#   "base_caption": str,     # hari | tarikh | jam
#   "items": {produk_key: qty_int},
#   "prices": {produk_key: price_str}
# }
ORDER_STATE = {}

# PENDING_PRICE key = prompt_message_id (mesej "Sila reply harga...")
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
def build_caption(base_caption: str, items_dict: dict, prices_dict: dict) -> str:
    lines = [base_caption]
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
    """
    Papar butang produk yang belum dipilih + SUBMIT (kalau ada item dipilih).
    """
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
        [
            InlineKeyboardButton("⬅️ KEMBALI", callback_data="back_produk")
        ]
    ])

def build_harga_keyboard(items_dict: dict, prices_dict: dict) -> InlineKeyboardMarkup:
    """
    Lepas SUBMIT: papar butang harga ikut item dipilih yang BELUM ada harga lagi.
    """
    rows = []
    for k in items_dict.keys():
        if k not in prices_dict:  # belum isi harga
            nama = PRODUK_LIST.get(k, k)
            rows.append([InlineKeyboardButton(f"HARGA - {nama}", callback_data=f"harga_{k}")])

    # kalau semua dah ada harga, kita boleh tunjuk satu butang siap (optional)
    if not rows and items_dict:
        rows = [[InlineKeyboardButton("✅ SEMUA HARGA SIAP", callback_data="harga_done")]]

    return InlineKeyboardMarkup(rows)

async def repost_message(client, old_msg, state: dict, reply_markup):
    """
    Padam mesej lama + hantar semula gambar (caption terkini) + reply_markup
    """
    caption_baru = build_caption(state["base_caption"], state["items"], state["prices"])

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

# STEP A: tekan NAMA PRODUK
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

# BACK dari qty -> balik produk
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

# STEP B: tekan produk -> keluar qty
@bot.on_callback_query(filters.regex(r"^produk_"))
async def pilih_kuantiti(client, callback):
    msg_id = callback.message.id
    state = ORDER_STATE.get(msg_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai. Sila hantar gambar semula.", show_alert=True)
        return

    produk_key = callback.data.replace("produk_", "", 1)
    await callback.message.edit_reply_markup(reply_markup=build_qty_keyboard(produk_key))
    await callback.answer("Pilih kuantiti")

# STEP C: tekan qty -> padam & repost + senarai produk (tinggal) + submit
@bot.on_callback_query(filters.regex(r"^qty_"))
async def simpan_qty_repost(client, callback):
    msg = callback.message
    old_msg_id = msg.id

    state = ORDER_STATE.get(old_msg_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai. Sila hantar gambar semula.", show_alert=True)
        return

    try:
        payload = callback.data[len("qty_"):]          # contoh: "125_FULL_2"
        produk_key, qty_str = payload.rsplit("_", 1)   # => ("125_FULL", "2")
        qty = int(qty_str)
    except Exception:
        await callback.answer("Format kuantiti tidak sah. Cuba tekan semula.", show_alert=True)
        return

    state["items"][produk_key] = qty
    await callback.answer("Dikemaskini")

    keyboard_produk = build_produk_keyboard(state["items"])
    reply_markup = keyboard_produk if keyboard_produk.inline_keyboard else None

    new_msg = await repost_message(client, msg, state, reply_markup)

    ORDER_STATE[new_msg.id] = {
        "chat_id": state["chat_id"],
        "photo_id": state["photo_id"],
        "base_caption": state["base_caption"],
        "items": dict(state["items"]),
        "prices": dict(state["prices"]),
    }
    ORDER_STATE.pop(old_msg_id, None)

# STEP D: tekan SUBMIT -> padam & repost + butang HARGA ikut item dipilih (yang belum diisi)
@bot.on_callback_query(filters.regex(r"^submit$"))
async def submit_order(client, callback):
    msg = callback.message
    old_msg_id = msg.id

    state = ORDER_STATE.get(old_msg_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai. Sila hantar gambar semula.", show_alert=True)
        return

    if not state["items"]:
        await callback.answer("Sila pilih sekurang-kurangnya 1 produk dulu.", show_alert=True)
        return

    await callback.answer("Submit...")

    harga_keyboard = build_harga_keyboard(state["items"], state["prices"])
    reply_markup = harga_keyboard if harga_keyboard.inline_keyboard else None

    new_msg = await repost_message(client, msg, state, reply_markup)

    ORDER_STATE[new_msg.id] = {
        "chat_id": state["chat_id"],
        "photo_id": state["photo_id"],
        "base_caption": state["base_caption"],
        "items": dict(state["items"]),
        "prices": dict(state["prices"]),
    }
    ORDER_STATE.pop(old_msg_id, None)

# STEP E: tekan HARGA - {produk} -> bot minta staff REPLY harga
@bot.on_callback_query(filters.regex(r"^harga_"))
async def minta_harga(client, callback):
    bot_msg_id = callback.message.id
    state = ORDER_STATE.get(bot_msg_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    produk_key = callback.data.replace("harga_", "", 1)
    nama = PRODUK_LIST.get(produk_key, produk_key)

    # hantar prompt untuk reply harga (ForceReply)
    prompt = await client.send_message(
        chat_id=state["chat_id"],
        text=f"Sila reply harga untuk: {nama}\nContoh: 2950 atau RM2950",
        reply_to_message_id=bot_msg_id,
        reply_markup=ForceReply(selective=True)
    )

    # simpan pending (prompt id -> bot message id + produk_key)
    PENDING_PRICE[prompt.id] = {"bot_msg_id": bot_msg_id, "produk_key": produk_key}

    await callback.answer("Sila taip harga (reply)")

# Optional: bila semua harga siap
@bot.on_callback_query(filters.regex(r"^harga_done$"))
async def harga_done(client, callback):
    await callback.answer("Semua harga sudah diisi.")

# ================= TEXT REPLY (isi harga) =================
@bot.on_message(filters.text & ~filters.bot)
async def terima_harga(client, message):
    # mesti reply kepada prompt bot (ForceReply message)
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
        # cleanup
        PENDING_PRICE.pop(prompt_id, None)
        return

    harga_text = (message.text or "").strip()
    if not harga_text:
        return

    # simpan harga
    state["prices"][produk_key] = harga_text

    # cuba padam mesej harga staff (kalau bot ada permission admin)
    try:
        await message.delete()
    except Exception:
        pass

    # cuba padam prompt bot
    try:
        await message.reply_to_message.delete()
    except Exception:
        pass

    # selepas isi harga: repost gambar dengan caption update
    # dan butang bawah: tinggal harga untuk item yang belum ada harga
    harga_keyboard = build_harga_keyboard(state["items"], state["prices"])
    reply_markup = harga_keyboard if harga_keyboard.inline_keyboard else None

    # padam mesej gambar lama & hantar semula yang baru
    old_photo_msg = await client.get_messages(state["chat_id"], bot_msg_id)
    new_msg = await repost_message(client, old_photo_msg, state, reply_markup)

    # update state id (pindah ke message baru)
    ORDER_STATE[new_msg.id] = {
        "chat_id": state["chat_id"],
        "photo_id": state["photo_id"],
        "base_caption": state["base_caption"],
        "items": dict(state["items"]),
        "prices": dict(state["prices"]),
    }
    ORDER_STATE.pop(bot_msg_id, None)

    # cleanup pending
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

    # padam gambar asal (jika ada permission)
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
        "prices": {}
    }

if __name__ == "__main__":
    bot.run()

