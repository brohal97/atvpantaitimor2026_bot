import os
import re
from copy import deepcopy
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
bot = Client("atv_bot_2026", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ================= STATE =================
# ORDER_STATE key = bot_message_id (mesej gambar bot yang aktif)
# value = {
#   "chat_id": int,
#   "photo_id": str,
#   "base_caption": str,
#   "items": {produk_key: qty_int},
#   "prices": {produk_key: "RM4000"},
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
    if not digits:
        return ""
    return f"RM{digits}"

def build_caption(base_caption: str, items_dict: dict, prices_dict: dict) -> str:
    """
    Format final yang awak nak:

    Rabu | 21/1/2026 | 08:31pm

    125 FULL SPEC | 1 | RM4000
    """
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

def clone_state(state: dict) -> dict:
    return {
        "chat_id": state["chat_id"],
        "photo_id": state["photo_id"],
        "base_caption": state["base_caption"],
        "items": deepcopy(state.get("items", {})),
        "prices": deepcopy(state.get("prices", {})),
        "stage": state.get("stage", "produk"),
    }

# ================= CALLBACKS =================
@bot.on_callback_query(filters.regex(r"^hantar_detail$"))
async def senarai_produk(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not state:
        return await callback.answer("Rekod tidak dijumpai. Sila hantar gambar semula.", show_alert=True)

    await callback.message.edit_reply_markup(reply_markup=build_produk_keyboard(state["items"]))
    await callback.answer()

@bot.on_callback_query(filters.regex(r"^back_produk$"))
async def back_produk(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not state:
        return await callback.answer("Rekod tidak dijumpai.", show_alert=True)

    await callback.message.edit_reply_markup(reply_markup=build_produk_keyboard(state["items"]))
    await callback.answer()

@bot.on_callback_query(filters.regex(r"^produk_"))
async def pilih_kuantiti(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not state:
        return await callback.answer("Rekod tidak dijumpai. Sila hantar gambar semula.", show_alert=True)

    produk_key = callback.data.replace("produk_", "", 1)
    await callback.message.edit_reply_markup(reply_markup=build_qty_keyboard(produk_key))
    await callback.answer("Pilih kuantiti")

@bot.on_callback_query(filters.regex(r"^qty_"))
async def simpan_qty_repost(client, callback):
    msg = callback.message
    state = ORDER_STATE.get(msg.id)
    if not state:
        return await callback.answer("Rekod tidak dijumpai.", show_alert=True)

    try:
        payload = callback.data[len("qty_"):]
        produk_key, qty_str = payload.rsplit("_", 1)
        qty = int(qty_str)
    except Exception:
        return await callback.answer("Format kuantiti tidak sah.", show_alert=True)

    state["items"][produk_key] = qty
    await callback.answer("Dikemaskini")

    keyboard = build_produk_keyboard(state["items"])
    new_msg = await repost_photo(client, msg, state, keyboard)

    ORDER_STATE[new_msg.id] = clone_state(state)
    ORDER_STATE.pop(msg.id, None)

@bot.on_callback_query(filters.regex(r"^submit$"))
async def submit_order(client, callback):
    msg = callback.message
    state = ORDER_STATE.get(msg.id)
    if not state:
        return await callback.answer("Rekod tidak dijumpai.", show_alert=True)

    if not state["items"]:
        return await callback.answer("Sila pilih sekurang-kurangnya 1 produk.", show_alert=True)

    state["stage"] = "harga"
    await callback.answer("Sila isi harga")

    harga_keyboard = build_harga_keyboard(state["items"], state["prices"])
    new_msg = await repost_photo(client, msg, state, harga_keyboard)

    ORDER_STATE[new_msg.id] = clone_state(state)
    ORDER_STATE.pop(msg.id, None)

@bot.on_callback_query(filters.regex(r"^harga_cancel$"))
async def harga_cancel(client, callback):
    await callback.answer("Batal")

@bot.on_callback_query(filters.regex(r"^harga_done$"))
async def harga_done(client, callback):
    await callback.answer("Semua harga sudah diisi.")

# ===== Tekan HARGA -> TRIK RESIT: ForceReply + reply_to_message_id + pending map =====
@bot.on_callback_query(filters.regex(r"^harga_"))
async def minta_harga(client, callback):
    bot_msg_id = callback.message.id
    state = ORDER_STATE.get(bot_msg_id)
    if not state:
        return await callback.answer("Rekod tidak dijumpai.", show_alert=True)

    produk_key = callback.data.replace("harga_", "", 1)
    nama = PRODUK_LIST.get(produk_key, produk_key)
    qty = state["items"].get(produk_key, 1)

    # ✅ Ini yang buat "Reply UI" auto keluar di telefon
    # ✅ Trik: text prompt dibuat macam quote/caption (supaya staff nampak macam reply pada gambar)
    # ✅ Arahan letak dalam placeholder (tak kacau preview quote)
    quote_like_text = f"{state['base_caption']}\n{nama} | {qty}"

    prompt = await client.send_message(
        chat_id=state["chat_id"],
        text=quote_like_text,
        reply_to_message_id=bot_msg_id,  # reply kepada GAMBAR
        reply_markup=ForceReply(
            selective=False,
            input_field_placeholder=f"Taip harga untuk {nama} | {qty} unit (contoh: 4000 / RM4000)"
        )
    )

    PENDING_PRICE[prompt.id] = {"bot_msg_id": bot_msg_id, "produk_key": produk_key}
    await callback.answer("Sila taip harga")

# ================= TERIMA HARGA (mesti reply pada prompt ForceReply) =================
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

    # padam mesej staff + prompt (kalau bot admin)
    try:
        await message.delete()
    except Exception:
        pass

    try:
        await message.reply_to_message.delete()
    except Exception:
        pass

    # repost gambar dengan caption update
    harga_keyboard = build_harga_keyboard(state["items"], state["prices"])

    try:
        old_photo_msg = await client.get_messages(state["chat_id"], bot_msg_id)
    except Exception:
        PENDING_PRICE.pop(prompt_id, None)
        return

    new_msg = await repost_photo(client, old_photo_msg, state, harga_keyboard)

    ORDER_STATE[new_msg.id] = clone_state(state)
    ORDER_STATE.pop(bot_msg_id, None)
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

