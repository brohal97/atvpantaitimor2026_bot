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
    raise RuntimeError("Missing API_ID / API_HASH / BOT_TOKEN")

# ================= BOT =================
bot = Client(
    "atvpantaitimor2026_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ================= STATE =================
ORDER_STATE = {}
PENDING_PRICE = {}

PRODUK_LIST = {
    "125_FULL": "125 FULL SPEC",
    "125_BIG": "125 BIG BODY",
    "YAMA": "YAMA SPORT",
    "GY6": "GY6 200CC",
}

# ================= HELPERS =================
def normalize_price(text: str) -> str:
    digits = re.sub(r"[^\d]", "", text or "")
    return f"RM{digits}" if digits else ""

def build_caption(base_caption, items, prices):
    lines = [base_caption, ""]
    for k, q in items.items():
        nama = PRODUK_LIST.get(k, k)
        if k in prices:
            lines.append(f"{nama} | {q} | {prices[k]}")
        else:
            lines.append(f"{nama} | {q}")
    return "\n".join(lines)

def clone_state(state):
    return {
        "chat_id": state["chat_id"],
        "photo_id": state["photo_id"],
        "base_caption": state["base_caption"],
        "items": deepcopy(state["items"]),
        "prices": deepcopy(state["prices"]),
        "stage": state["stage"],
    }

# ================= KEYBOARDS =================
def produk_keyboard(items):
    rows = []
    for k, n in PRODUK_LIST.items():
        if k not in items:
            rows.append([InlineKeyboardButton(n, callback_data=f"produk_{k}")])
    if items:
        rows.append([InlineKeyboardButton("✅ SUBMIT", callback_data="submit")])
    return InlineKeyboardMarkup(rows)

def qty_keyboard(key):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1", callback_data=f"qty_{key}_1"),
         InlineKeyboardButton("2", callback_data=f"qty_{key}_2"),
         InlineKeyboardButton("3", callback_data=f"qty_{key}_3")],
        [InlineKeyboardButton("⬅️ KEMBALI", callback_data="back_produk")]
    ])

def harga_keyboard(items, prices):
    rows = []
    for k in items:
        if k not in prices:
            rows.append([InlineKeyboardButton(
                f"HARGA - {PRODUK_LIST.get(k)}",
                callback_data=f"harga_{k}"
            )])
    return InlineKeyboardMarkup(rows)

# ================= CALLBACKS =================
@bot.on_callback_query(filters.regex("^hantar_detail$"))
async def list_produk(_, cb):
    state = ORDER_STATE.get(cb.message.id)
    if not state:
        return await cb.answer("Rekod tiada", show_alert=True)
    await cb.message.edit_reply_markup(produk_keyboard(state["items"]))
    await cb.answer()

@bot.on_callback_query(filters.regex("^produk_"))
async def pilih_qty(_, cb):
    key = cb.data.replace("produk_", "")
    await cb.message.edit_reply_markup(qty_keyboard(key))
    await cb.answer()

@bot.on_callback_query(filters.regex("^qty_"))
async def simpan_qty(client, cb):
    msg = cb.message
    state = ORDER_STATE[msg.id]

    payload = cb.data.replace("qty_", "")
    key, qty = payload.rsplit("_", 1)
    state["items"][key] = int(qty)

    await cb.answer("OK")

    new = await client.send_photo(
        chat_id=state["chat_id"],
        photo=state["photo_id"],
        caption=build_caption(state["base_caption"], state["items"], state["prices"]),
        reply_markup=produk_keyboard(state["items"])
    )

    await msg.delete()
    ORDER_STATE[new.id] = clone_state(state)
    ORDER_STATE.pop(msg.id)

@bot.on_callback_query(filters.regex("^submit$"))
async def submit(_, cb):
    state = ORDER_STATE[cb.message.id]
    state["stage"] = "harga"

    new = await cb.message._client.send_photo(
        chat_id=state["chat_id"],
        photo=state["photo_id"],
        caption=build_caption(state["base_caption"], state["items"], state["prices"]),
        reply_markup=harga_keyboard(state["items"], state["prices"])
    )

    await cb.message.delete()
    ORDER_STATE[new.id] = clone_state(state)
    ORDER_STATE.pop(cb.message.id)
    await cb.answer()

# ================= 🔥 FORCE REPLY TRIK =================
@bot.on_callback_query(filters.regex("^harga_"))
async def harga_prompt(client, cb):
    bot_msg_id = cb.message.id
    state = ORDER_STATE[bot_msg_id]

    key = cb.data.replace("harga_", "")
    nama = PRODUK_LIST[key]
    qty = state["items"][key]

    prompt = await client.send_message(
        chat_id=state["chat_id"],
        text=f"Masukkan harga:\n{nama} | {qty} unit",
        reply_to_message_id=bot_msg_id,   # 🔥 ATTACH KE GAMBAR
        reply_markup=ForceReply(selective=False)
    )

    PENDING_PRICE[prompt.id] = {
        "bot_msg_id": bot_msg_id,
        "produk_key": key
    }

    await cb.answer()

# ================= TERIMA HARGA =================
@bot.on_message(filters.text & ~filters.bot)
async def terima_harga(client, msg):
    if not msg.reply_to_message:
        return

    pending = PENDING_PRICE.get(msg.reply_to_message.id)
    if not pending:
        return

    state = ORDER_STATE[pending["bot_msg_id"]]
    harga = normalize_price(msg.text)
    if not harga:
        return

    state["prices"][pending["produk_key"]] = harga

    try:
        await msg.delete()
        await msg.reply_to_message.delete()
    except:
        pass

    old = await client.get_messages(state["chat_id"], pending["bot_msg_id"])
    new = await client.send_photo(
        chat_id=state["chat_id"],
        photo=state["photo_id"],
        caption=build_caption(state["base_caption"], state["items"], state["prices"]),
        reply_markup=harga_keyboard(state["items"], state["prices"])
    )

    await old.delete()
    ORDER_STATE[new.id] = clone_state(state)
    ORDER_STATE.pop(pending["bot_msg_id"])
    PENDING_PRICE.pop(msg.reply_to_message.id)

# ================= FOTO =================
@bot.on_message(filters.photo & ~filters.bot)
async def handle_photo(_, msg):
    tz = pytz.timezone("Asia/Kuala_Lumpur")
    now = datetime.now(tz)

    base = f"{now.strftime('%A')} | {now.day}/{now.month}/{now.year} | {now.strftime('%I:%M%p').lower()}"

    try:
        await msg.delete()
    except:
        pass

    sent = await bot.send_photo(
        chat_id=msg.chat.id,
        photo=msg.photo.file_id,
        caption=base,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("NAMA PRODUK", callback_data="hantar_detail")]]
        )
    )

    ORDER_STATE[sent.id] = {
        "chat_id": msg.chat.id,
        "photo_id": msg.photo.file_id,
        "base_caption": base,
        "items": {},
        "prices": {},
        "stage": "produk",
    }

# ================= RUN =================
bot.run()


