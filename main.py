import os
import re
from datetime import datetime

import pytz
from pyrogram import Client, filters
from pyrogram.errors import MessageDeleteForbidden, ChatAdminRequired
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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
#   "base_caption": str,     # hari | tarikh | jam
#   "items": {produk_key: qty_int},
#   "prices": {produk_key: price_str},
#   "stage": "produk" | "harga",          # mode semasa
#   "await_price_for": produk_key|None,   # jika sedang tunggu harga produk mana
# }
ORDER_STATE = {}

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
def build_caption(base_caption: str, items_dict: dict, prices_dict: dict, hint: str = "") -> str:
    lines = [base_caption]
    if items_dict:
        lines.append("")
        for k, q in items_dict.items():
            nama = PRODUK_LIST.get(k, k)
            if k in prices_dict and str(prices_dict[k]).strip():
                lines.append(f"{nama} | {q} | {prices_dict[k]}")
            else:
                lines.append(f"{nama} | {q}")
    if hint:
        lines.append("")
        lines.append(hint)
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

    # kalau semua harga siap, letak butang siap (optional)
    if not rows and items_dict:
        rows = [[InlineKeyboardButton("✅ SEMUA HARGA SIAP", callback_data="harga_done")]]

    # butang cancel input harga (akan wujud bila sedang input)
    rows.append([InlineKeyboardButton("❌ BATAL", callback_data="harga_cancel")])
    return InlineKeyboardMarkup(rows)

def normalize_price(text: str) -> str:
    """
    Terima input macam:
    - 2950
    - RM2950
    - rm 2,950
    - 2 950
    Output: 2950 atau RM2950 (awak boleh ubah style di sini)
    """
    s = text.strip()

    # ambil nombor sahaja (buang rm, koma, space)
    digits = re.sub(r"[^\d]", "", s)
    if not digits:
        return ""

    # contoh: auto letak RM (kalau awak nak)
    # return f"RM{digits}"
    return digits  # kekal nombor sahaja

async def repost_photo(client, old_msg, state: dict, reply_markup, hint: str = ""):
    caption_baru = build_caption(state["base_caption"], state["items"], state["prices"], hint=hint)

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
    state["await_price_for"] = None

    await callback.answer("Sila isi harga")

    harga_keyboard = build_harga_keyboard(state["items"], state["prices"])
    reply_markup = harga_keyboard if harga_keyboard.inline_keyboard else None

    new_msg = await repost_photo(client, msg, state, reply_markup, hint="Tekan butang HARGA, kemudian taip harga dan send.")

    ORDER_STATE[new_msg.id] = {**state}
    ORDER_STATE.pop(old_msg_id, None)

@bot.on_callback_query(filters.regex(r"^harga_cancel$"))
async def harga_cancel(client, callback):
    await callback.answer("Batal input harga")
    # tak buat apa-apa, cuma clear mode menunggu harga
    msg_id = callback.message.id
    state = ORDER_STATE.get(msg_id)
    if state:
        state["await_price_for"] = None

@bot.on_callback_query(filters.regex(r"^harga_done$"))
async def harga_done(client, callback):
    await callback.answer("Semua harga sudah diisi.")

@bot.on_callback_query(filters.regex(r"^harga_"))
async def minta_harga(client, callback):
    msg_id = callback.message.id
    state = ORDER_STATE.get(msg_id)

    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    produk_key = callback.data.replace("harga_", "", 1)
    nama = PRODUK_LIST.get(produk_key, produk_key)

    # set mode tunggu harga
    state["stage"] = "harga"
    state["await_price_for"] = produk_key

    await callback.answer(f"Taip harga untuk {nama}")

    # update caption hint supaya staff nampak arahan terus dalam gambar
    harga_keyboard = build_harga_keyboard(state["items"], state["prices"])
    hint = f"➡️ Taip harga untuk: {nama} (contoh 2950) dan SEND."
    try:
        await callback.message.edit_caption(
            caption=build_caption(state["base_caption"], state["items"], state["prices"], hint=hint),
            reply_markup=harga_keyboard
        )
    except Exception:
        pass

# ================= CAPTURE TEKS (harga) =================
@bot.on_message(filters.text & ~filters.bot)
async def tangkap_harga(client, message):
    # cari state yang sedang menunggu harga dalam chat ini
    # (kita ambil state latest untuk chat itu)
    chat_id = message.chat.id

    # cari state message_id paling baru dalam ORDER_STATE yang chat_id sama
    # (simple approach: loop semua)
    bot_msg_id = None
    state = None
    for mid, st in ORDER_STATE.items():
        if st.get("chat_id") == chat_id and st.get("stage") == "harga" and st.get("await_price_for"):
            bot_msg_id = mid
            state = st
            break

    if not state:
        return  # bukan input harga

    produk_key = state["await_price_for"]
    price_norm = normalize_price(message.text or "")
    if not price_norm:
        return

    # simpan harga & clear awaiting
    state["prices"][produk_key] = price_norm
    state["await_price_for"] = None

    # cuba padam mesej staff (kalau bot admin)
    try:
        await message.delete()
    except Exception:
        pass

    # repost gambar: caption update + butang harga tinggal yang belum diisi
    harga_keyboard = build_harga_keyboard(state["items"], state["prices"])
    reply_markup = harga_keyboard if harga_keyboard.inline_keyboard else None

    # ambil mesej gambar bot lama
    try:
        old_photo_msg = await client.get_messages(chat_id, bot_msg_id)
    except Exception:
        return

    new_msg = await repost_photo(
        client,
        old_photo_msg,
        state,
        reply_markup,
        hint="Tekan butang HARGA seterusnya, kemudian taip harga dan SEND."
    )

    ORDER_STATE[new_msg.id] = {**state}
    ORDER_STATE.pop(bot_msg_id, None)

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
        "await_price_for": None,
    }

if __name__ == "__main__":
    bot.run()

