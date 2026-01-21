import os
from copy import deepcopy
from datetime import datetime

import pytz
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ================= ENV =================
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Missing API credentials")

# ================= BOT =================
bot = Client(
    "atvpantaitimor2026_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ================= DATA =================
PRODUK_LIST = {
    "125_FULL": "125 FULL SPEC",
    "125_BIG": "125 BIG BODY",
    "YAMA": "YAMA SPORT",
    "GY6": "GY6 200CC",
}

HARGA_125_FULL = [str(x) for x in range(2500, 3001, 10)]

ORDER_STATE = {}

# ================= HELPERS =================
def clone_state(s):
    return {
        "chat_id": s["chat_id"],
        "photo_id": s["photo_id"],
        "base_caption": s["base_caption"],
        "items": deepcopy(s["items"]),
        "prices": deepcopy(s["prices"]),
    }

def build_caption(base, items, prices):
    lines = [base, ""]
    for k, q in items.items():
        nama = PRODUK_LIST[k]
        if k in prices:
            lines.append(f"{nama} | {q} | {prices[k]}")
        else:
            lines.append(f"{nama} | {q}")
    return "\n".join(lines)

# ================= KEYBOARDS =================
def keyboard_produk(items):
    rows = []
    for k, n in PRODUK_LIST.items():
        if k not in items:
            rows.append([InlineKeyboardButton(n, callback_data=f"produk_{k}")])
    if items:
        rows.append([InlineKeyboardButton("✅ SUBMIT", callback_data="submit")])
    return InlineKeyboardMarkup(rows)

def keyboard_qty(k):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1", callback_data=f"qty_{k}_1"),
            InlineKeyboardButton("2", callback_data=f"qty_{k}_2"),
            InlineKeyboardButton("3", callback_data=f"qty_{k}_3"),
        ],
        [InlineKeyboardButton("⬅️ KEMBALI", callback_data="back")]
    ])

def keyboard_harga(items, prices):
    rows = []
    for k in items:
        if k not in prices:
            rows.append([
                InlineKeyboardButton(
                    f"HARGA - {PRODUK_LIST[k]}",
                    callback_data=f"harga_{k}"
                )
            ])
    return InlineKeyboardMarkup(rows)

def keyboard_harga_125():
    rows, temp = [], []
    for h in HARGA_125_FULL:
        temp.append(
            InlineKeyboardButton(f"RM{h}", callback_data=f"harga_pilih_125_FULL_{h}")
        )
        if len(temp) == 3:
            rows.append(temp)
            temp = []
    if temp:
        rows.append(temp)
    rows.append([InlineKeyboardButton("❌ BATAL", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)

# ================= CALLBACKS =================
@bot.on_callback_query(filters.regex("^hantar_detail$"))
async def buka_produk(_, cb):
    state = ORDER_STATE.get(cb.message.id)
    if not state:
        return await cb.answer("Rekod tiada", show_alert=True)
    await cb.message.edit_reply_markup(keyboard_produk(state["items"]))
    await cb.answer()

@bot.on_callback_query(filters.regex("^produk_"))
async def pilih_qty(_, cb):
    key = cb.data.replace("produk_", "")
    await cb.message.edit_reply_markup(keyboard_qty(key))
    await cb.answer()

@bot.on_callback_query(filters.regex("^qty_"))
async def simpan_qty(client, cb):
    msg = cb.message
    state = ORDER_STATE[msg.id]

    _, key, qty = cb.data.split("_")
    state["items"][key] = int(qty)

    new = await client.send_photo(
        chat_id=state["chat_id"],
        photo=state["photo_id"],
        caption=build_caption(state["base_caption"], state["items"], state["prices"]),
        reply_markup=keyboard_produk(state["items"])
    )

    await msg.delete()
    ORDER_STATE[new.id] = clone_state(state)
    ORDER_STATE.pop(msg.id)
    await cb.answer("OK")

@bot.on_callback_query(filters.regex("^submit$"))
async def submit(client, cb):
    state = ORDER_STATE[cb.message.id]

    new = await client.send_photo(
        chat_id=state["chat_id"],
        photo=state["photo_id"],
        caption=build_caption(state["base_caption"], state["items"], state["prices"]),
        reply_markup=keyboard_harga(state["items"], state["prices"])
    )

    await cb.message.delete()
    ORDER_STATE[new.id] = clone_state(state)
    ORDER_STATE.pop(cb.message.id)
    await cb.answer()

@bot.on_callback_query(filters.regex("^harga_125_FULL$"))
async def buka_harga_125(_, cb):
    state = ORDER_STATE[cb.message.id]
    qty = state["items"]["125_FULL"]

    await cb.message.edit_caption(
        caption=f"{state['base_caption']}\n\nPilih harga:\n125 FULL SPEC | {qty} unit",
        reply_markup=keyboard_harga_125()
    )
    await cb.answer()

@bot.on_callback_query(filters.regex("^harga_pilih_125_FULL_"))
async def simpan_harga(client, cb):
    state = ORDER_STATE[cb.message.id]
    harga = cb.data.split("_")[-1]
    state["prices"]["125_FULL"] = f"RM{harga}"

    new = await client.send_photo(
        chat_id=state["chat_id"],
        photo=state["photo_id"],
        caption=build_caption(state["base_caption"], state["items"], state["prices"]),
        reply_markup=keyboard_harga(state["items"], state["prices"])
    )

    await cb.message.delete()
    ORDER_STATE[new.id] = clone_state(state)
    ORDER_STATE.pop(cb.message.id)
    await cb.answer("Harga disimpan")

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
    }

# ================= RUN =================
bot.run()
