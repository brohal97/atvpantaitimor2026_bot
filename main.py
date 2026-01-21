import os
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
# key = bot_message_id
# value = {
#   "chat_id": int,
#   "photo_id": str,
#   "base_caption": str,         # hari | tarikh | jam
#   "items": {produk_key: qty_int},
#   "prices": {produk_key: unit_price_int},  # simpan harga SEUNIT
#   "dest": str | None
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

# ================= HARGA LIST =================
HARGA_START = 2500
HARGA_END = 3000
HARGA_STEP = 10
HARGA_LIST = list(range(HARGA_START, HARGA_END + 1, HARGA_STEP))
HARGA_PER_PAGE = 15  # 3 baris x 5 butang

# ================= DESTINASI LIST =================
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


def build_caption(base_caption: str, items_dict: dict, prices_dict: dict | None = None, dest: str | None = None) -> str:
    """
    Caption:
    Rabu | 21/1/2026 | 11:18pm

    125 FULL SPEC | 2 | RM5140
    YAMA SPORT | 1 | RM2560

    Destinasi : JOHOR
    """
    prices_dict = prices_dict or {}

    lines = [base_caption]
    if items_dict:
        lines.append("")
        for k, q in items_dict.items():
            nama = PRODUK_LIST.get(k, k)

            unit_price = prices_dict.get(k)
            if unit_price is None:
                harga_display = "-"
            else:
                try:
                    total = int(unit_price) * int(q)
                except Exception:
                    total = unit_price
                harga_display = f"RM{total}"

            lines.append(f"{nama} | {q} | {harga_display}")

    if dest:
        lines.append("")
        lines.append(f"Destinasi : {dest}")

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
        [
            InlineKeyboardButton("⬅️ KEMBALI", callback_data="back_produk")
        ]
    ])


def build_harga_keyboard(items_dict: dict, prices_dict: dict | None = None) -> InlineKeyboardMarkup:
    """
    Lepas SUBMIT:
    - Butang harga hanya untuk item yang belum dipilih
    - Bila semua item ada harga -> muncul 📍 DESTINASI
    """
    prices_dict = prices_dict or {}
    rows = []

    for k in items_dict.keys():
        if k in prices_dict:
            continue
        nama = PRODUK_LIST.get(k, k)
        rows.append([InlineKeyboardButton(f"HARGA - {nama}", callback_data=f"harga_{k}")])

    if items_dict and all(k in prices_dict for k in items_dict.keys()):
        rows.append([InlineKeyboardButton("📍 DESTINASI", callback_data="destinasi")])

    rows.append([InlineKeyboardButton("⬅️ KEMBALI PRODUK", callback_data="back_produk")])
    return InlineKeyboardMarkup(rows)


def build_select_harga_keyboard(produk_key: str, page: int = 0) -> InlineKeyboardMarkup:
    total = len(HARGA_LIST)
    start = page * HARGA_PER_PAGE
    end = start + HARGA_PER_PAGE
    chunk = HARGA_LIST[start:end]

    rows = []
    for i in range(0, len(chunk), 5):
        row_prices = chunk[i:i + 5]
        rows.append([
            InlineKeyboardButton(str(p), callback_data=f"setharga_{produk_key}_{p}")
            for p in row_prices
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ PREV", callback_data=f"harga_page_{produk_key}_{page - 1}"))
    if end < total:
        nav.append(InlineKeyboardButton("NEXT ➡️", callback_data=f"harga_page_{produk_key}_{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton("⬅️ BACK (HARGA MENU)", callback_data="back_harga_menu")])
    return InlineKeyboardMarkup(rows)


def build_dest_keyboard() -> InlineKeyboardMarkup:
    """
    Senarai destinasi (susun 2 lajur).
    callback: setdest_<index>
    """
    rows = []
    for i in range(0, len(DEST_LIST), 2):
        left = InlineKeyboardButton(DEST_LIST[i], callback_data=f"setdest_{i}")
        if i + 1 < len(DEST_LIST):
            right = InlineKeyboardButton(DEST_LIST[i + 1], callback_data=f"setdest_{i + 1}")
            rows.append([left, right])
        else:
            rows.append([left])

    rows.append([InlineKeyboardButton("⬅️ BACK (HARGA MENU)", callback_data="back_harga_menu")])
    return InlineKeyboardMarkup(rows)


def build_after_dest_keyboard() -> InlineKeyboardMarkup:
    """
    Lepas pilih destinasi:
    - keluar butang KOS PENGHANTARAN
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚚 KOS PENGHANTARAN", callback_data="kos_penghantaran")],
        [InlineKeyboardButton("🗺️ TUKAR DESTINASI", callback_data="destinasi")],
        [InlineKeyboardButton("⬅️ KEMBALI PRODUK", callback_data="back_produk")]
    ])


async def repost_message(client: Client, old_msg, state: dict, reply_markup: InlineKeyboardMarkup | None):
    caption_baru = build_caption(
        state["base_caption"],
        state["items"],
        state.get("prices", {}),
        state.get("dest")
    )

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


def clone_state_for_new_msg(state: dict) -> dict:
    return {
        "chat_id": state["chat_id"],
        "photo_id": state["photo_id"],
        "base_caption": state["base_caption"],
        "items": dict(state.get("items", {})),
        "prices": dict(state.get("prices", {})),
        "dest": state.get("dest"),
    }


# ====== STEP A: tekan NAMA PRODUK ======
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


# ====== BACK ke senarai produk ======
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


# ====== STEP B: tekan produk -> keluar kuantiti ======
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


# ====== STEP C: tekan kuantiti -> PADAM & HANTAR SEMULA ======
@bot.on_callback_query(filters.regex(r"^qty_"))
async def simpan_qty_repost(client, callback):
    msg = callback.message
    old_msg_id = msg.id

    state = ORDER_STATE.get(old_msg_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai. Sila hantar gambar semula.", show_alert=True)
        return

    try:
        payload = callback.data[len("qty_"):]
        produk_key, qty_str = payload.rsplit("_", 1)
        qty = int(qty_str)
    except Exception:
        await callback.answer("Format kuantiti tidak sah. Cuba tekan semula.", show_alert=True)
        return

    state["items"][produk_key] = qty
    await callback.answer("Dikemaskini")

    keyboard_produk = build_produk_keyboard(state["items"])
    reply_markup = keyboard_produk if keyboard_produk.inline_keyboard else None

    new_msg = await repost_message(client, msg, state, reply_markup)

    ORDER_STATE[new_msg.id] = clone_state_for_new_msg(state)
    ORDER_STATE.pop(old_msg_id, None)


# ====== STEP D: tekan SUBMIT -> PADAM & HANTAR SEMULA + BUTANG HARGA ======
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

    harga_keyboard = build_harga_keyboard(state["items"], state.get("prices", {}))
    reply_markup = harga_keyboard if harga_keyboard.inline_keyboard else None

    new_msg = await repost_message(client, msg, state, reply_markup)

    ORDER_STATE[new_msg.id] = clone_state_for_new_msg(state)
    ORDER_STATE.pop(old_msg_id, None)


# ====== STEP E: tekan HARGA - {produk} -> keluar senarai harga ======
@bot.on_callback_query(filters.regex(r"^harga_"))
async def buka_senarai_harga(client, callback):
    msg_id = callback.message.id
    state = ORDER_STATE.get(msg_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    produk_key = callback.data.replace("harga_", "", 1)
    await callback.message.edit_reply_markup(reply_markup=build_select_harga_keyboard(produk_key, page=0))
    await callback.answer("Pilih harga")


# ====== Pagination harga ======
@bot.on_callback_query(filters.regex(r"^harga_page_"))
async def harga_pagination(client, callback):
    msg_id = callback.message.id
    state = ORDER_STATE.get(msg_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    payload = callback.data[len("harga_page_"):]
    try:
        produk_key, page_str = payload.rsplit("_", 1)
        page = int(page_str)
    except Exception:
        await callback.answer("Pagination tidak sah.", show_alert=True)
        return

    await callback.message.edit_reply_markup(reply_markup=build_select_harga_keyboard(produk_key, page=page))
    await callback.answer()


# ====== BACK dari senarai harga -> balik ke menu harga ======
@bot.on_callback_query(filters.regex(r"^back_harga_menu$"))
async def back_harga_menu(client, callback):
    msg_id = callback.message.id
    state = ORDER_STATE.get(msg_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    kb = build_harga_keyboard(state["items"], state.get("prices", {}))
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()


# ====== pilih harga -> PADAM & HANTAR SEMULA ======
@bot.on_callback_query(filters.regex(r"^setharga_"))
async def set_harga(client, callback):
    msg = callback.message
    old_msg_id = msg.id

    state = ORDER_STATE.get(old_msg_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    payload = callback.data[len("setharga_"):]
    try:
        produk_key, harga_str = payload.rsplit("_", 1)
        harga = int(harga_str)  # harga seunit
    except Exception:
        await callback.answer("Format harga tidak sah.", show_alert=True)
        return

    if "prices" not in state:
        state["prices"] = {}

    state["prices"][produk_key] = harga
    await callback.answer("Harga diset")

    kb = build_harga_keyboard(state["items"], state.get("prices", {}))
    reply_markup = kb if kb.inline_keyboard else None

    new_msg = await repost_message(client, msg, state, reply_markup)

    ORDER_STATE[new_msg.id] = clone_state_for_new_msg(state)
    ORDER_STATE.pop(old_msg_id, None)


# ====== DESTINASI: buka pilihan destinasi ======
@bot.on_callback_query(filters.regex(r"^destinasi$"))
async def buka_destinasi(client, callback):
    msg_id = callback.message.id
    state = ORDER_STATE.get(msg_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    # pastikan semua harga dah ada (safety)
    if not (state.get("items") and all(k in state.get("prices", {}) for k in state["items"].keys())):
        await callback.answer("Sila lengkapkan harga dulu.", show_alert=True)
        return

    await callback.message.edit_reply_markup(reply_markup=build_dest_keyboard())
    await callback.answer("Pilih destinasi")


# ====== SET DESTINASI -> PADAM & HANTAR SEMULA + BUTANG KOS PENGHANTARAN ======
@bot.on_callback_query(filters.regex(r"^setdest_"))
async def set_destinasi(client, callback):
    msg = callback.message
    old_msg_id = msg.id

    state = ORDER_STATE.get(old_msg_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    try:
        idx = int(callback.data.replace("setdest_", "", 1))
        dest = DEST_LIST[idx]
    except Exception:
        await callback.answer("Destinasi tidak sah.", show_alert=True)
        return

    state["dest"] = dest
    await callback.answer(f"Destinasi: {dest}")

    reply_markup = build_after_dest_keyboard()
    new_msg = await repost_message(client, msg, state, reply_markup)

    ORDER_STATE[new_msg.id] = clone_state_for_new_msg(state)
    ORDER_STATE.pop(old_msg_id, None)


# ====== KOS PENGHANTARAN (placeholder) ======
@bot.on_callback_query(filters.regex(r"^kos_penghantaran$"))
async def kos_penghantaran(client, callback):
    # Fungsi kos akan kita sambung lepas ini (senarai harga/angka kos, dll)
    await callback.answer("Fungsi KOS PENGHANTARAN belum diaktifkan lagi.", show_alert=True)


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
        "dest": None,
    }


if __name__ == "__main__":
    bot.run()
