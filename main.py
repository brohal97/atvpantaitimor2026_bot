import os
from datetime import datetime

import pytz
from pyrogram import Client, filters
from pyrogram.errors import MessageDeleteForbidden, ChatAdminRequired
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ForceReply,
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
# ORDER_STATE key = "CONTROL MESSAGE ID" (message yang ada buttons)
# state = {
#   "chat_id": int,
#   "photo_id": str,                # order photo file_id
#   "base_caption": str,
#   "items": {produk_key: qty_int},
#   "prices": {produk_key: unit_price_int},
#   "dest": str | None,
#   "ship_cost": int | None,
#   "receipts": [file_id, ...],
#   "paid": bool,
#   "paid_at": str | None,
#   "paid_by": int | None,
#   "locked": bool,
#
#   # bila dah jadi ALBUM (order+resit)
#   "album_msg_ids": [int, int] | None,   # msg ids album (order+resit)
#   "album_first_id": int | None,         # msg id pertama album (caption ada di sini)
#   "control_msg_id": int | None,         # msg id control (buttons) => sama dgn key ORDER_STATE
# }
ORDER_STATE = {}

# Mapping untuk detect reply pada mana-mana message dalam album -> pergi ke control message id
# key = album_message_id -> value = control_message_id
REPLY_MAP = {}

# Manual fallback (bila tekan ADD RESIT)
# key = (chat_id, user_id) -> value = control_msg_id
WAITING_RECEIPT = {}

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

# ================= HARGA PRODUK LIST =================
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

# ================= KOS PENGHANTARAN LIST =================
KOS_START = 0
KOS_END = 1500
KOS_STEP = 10
KOS_LIST = list(range(KOS_START, KOS_END + 1, KOS_STEP))
KOS_PER_PAGE = 15  # 3 baris x 5 butang


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
        try:
            total += int(unit) * int(qty)
        except Exception:
            pass
    return total


def build_caption(
    base_caption: str,
    items_dict: dict,
    prices_dict: dict | None = None,
    dest: str | None = None,
    ship_cost: int | None = None,
    locked: bool = False,
    paid: bool = False,
    receipts_count: int = 0,
    paid_at: str | None = None,
) -> str:
    prices_dict = prices_dict or {}
    lines = [base_caption]

    # list produk
    if items_dict:
        lines.append("")
        for k, q in items_dict.items():
            nama = PRODUK_LIST.get(k, k)
            unit_price = prices_dict.get(k)

            if unit_price is None:
                harga_display = "-"
            else:
                try:
                    total_line = int(unit_price) * int(q)
                except Exception:
                    total_line = unit_price
                harga_display = f"RM{total_line}"

            lines.append(f"{nama} | {q} | {harga_display}")

    # destinasi + kos
    if dest:
        lines.append("")
        if ship_cost is None:
            lines.append(f"Destinasi : {dest}")
        else:
            lines.append(f"Destinasi : {dest} | RM{int(ship_cost)}")

    # total keseluruhan
    if items_dict and is_all_prices_done(items_dict, prices_dict) and ship_cost is not None:
        prod_total = calc_products_total(items_dict, prices_dict)
        grand_total = prod_total + int(ship_cost)
        lines.append("")
        lines.append(f"TOTAL KESELURUHAN : RM{grand_total}")

    # arahan + status
    if locked:
        lines.append("")
        lines.append("🧾 JARI SLIDE KIRI (REPLY) PADA MESEJ INI UNTUK UPLOAD RESIT")
        if receipts_count:
            lines.append(f"📎 RESIT: {receipts_count} keping")
        if paid:
            if paid_at:
                lines.append(f"✅ PAYMENT SETTLED ({paid_at})")
            else:
                lines.append("✅ PAYMENT SETTLED")

    return "\n".join(lines)


def clone_state_for_new_msg(state: dict) -> dict:
    return {
        "chat_id": state["chat_id"],
        "photo_id": state["photo_id"],
        "base_caption": state["base_caption"],
        "items": dict(state.get("items", {})),
        "prices": dict(state.get("prices", {})),
        "dest": state.get("dest"),
        "ship_cost": state.get("ship_cost"),
        "receipts": list(state.get("receipts", [])),
        "paid": bool(state.get("paid", False)),
        "paid_at": state.get("paid_at"),
        "paid_by": state.get("paid_by"),
        "locked": bool(state.get("locked", False)),
        "album_msg_ids": list(state.get("album_msg_ids") or []) if state.get("album_msg_ids") else None,
        "album_first_id": state.get("album_first_id"),
        "control_msg_id": state.get("control_msg_id"),
    }


async def safe_delete(client: Client, chat_id: int, message_id: int):
    try:
        await client.delete_messages(chat_id, message_id)
    except Exception:
        pass


async def delete_whole_order_bundle(client: Client, state: dict):
    """
    Padam:
    - control message (buttons)
    - album (jika ada)
    """
    chat_id = state["chat_id"]

    # padam album msgs dulu
    album_ids = state.get("album_msg_ids") or []
    for mid in album_ids:
        await safe_delete(client, chat_id, mid)
        REPLY_MAP.pop(mid, None)

    # padam control msg
    if state.get("control_msg_id"):
        await safe_delete(client, chat_id, state["control_msg_id"])


async def repost_single_photo_message(client: Client, old_msg, state: dict, reply_markup: InlineKeyboardMarkup | None):
    caption_baru = build_caption(
        state["base_caption"],
        state["items"],
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=bool(state.get("locked")),
        paid=bool(state.get("paid")),
        receipts_count=len(state.get("receipts", [])),
        paid_at=state.get("paid_at"),
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


async def refresh_single_caption_and_kb(client: Client, msg, state: dict, kb: InlineKeyboardMarkup):
    """
    Untuk message single-photo (bukan album).
    """
    caption_baru = build_caption(
        state["base_caption"],
        state.get("items", {}),
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=bool(state.get("locked")),
        paid=bool(state.get("paid")),
        receipts_count=len(state.get("receipts", [])),
        paid_at=state.get("paid_at"),
    )

    try:
        await msg.edit_caption(caption=caption_baru, reply_markup=kb)
        return msg
    except Exception:
        # fallback repost
        new_msg = await repost_single_photo_message(client, msg, state, kb)
        # update state key
        ORDER_STATE[new_msg.id] = clone_state_for_new_msg(state)
        ORDER_STATE[new_msg.id]["control_msg_id"] = new_msg.id
        ORDER_STATE.pop(msg.id, None)
        return new_msg


def build_final_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ PAYMENT SETTLE", callback_data="pay_settle")],
        [InlineKeyboardButton("➕ ADD RESIT", callback_data="add_resit")],
    ])


async def convert_to_album_bundle(client: Client, state: dict, receipt_photo_id: str) -> int:
    """
    Buat 2 gambar duduk bersama (album):
    1) Gambar order (caption detail)
    2) Gambar resit
    + 1 message control (buttons) reply kepada album message pertama (nampak macam satu blok)
    Return: control_msg_id baru
    """
    chat_id = state["chat_id"]

    # update receipts list
    state.setdefault("receipts", [])
    state["receipts"].append(receipt_photo_id)

    caption = build_caption(
        state["base_caption"],
        state.get("items", {}),
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=True,
        paid=bool(state.get("paid")),
        receipts_count=len(state.get("receipts", [])),
        paid_at=state.get("paid_at"),
    )

    media = [
        InputMediaPhoto(media=state["photo_id"], caption=caption),
        InputMediaPhoto(media=receipt_photo_id),
    ]

    album_msgs = await client.send_media_group(chat_id=chat_id, media=media)
    album_ids = [m.id for m in album_msgs]
    album_first_id = album_msgs[0].id

    # Control message: letak text "invisible" supaya macam tak ada ayat (tapi buttons ada)
    invisible = "\u2060"  # WORD JOINER
    control = await client.send_message(
        chat_id=chat_id,
        text=invisible,
        reply_to_message_id=album_first_id,
        reply_markup=build_final_keyboard()
    )

    # save mapping reply->control
    for mid in album_ids:
        REPLY_MAP[mid] = control.id

    state["album_msg_ids"] = album_ids
    state["album_first_id"] = album_first_id
    state["control_msg_id"] = control.id

    return control.id


async def update_album_caption_only(client: Client, state: dict):
    """
    Bila paid/resit count berubah, update caption pada album_first_id.
    """
    if not state.get("album_first_id"):
        return

    caption = build_caption(
        state["base_caption"],
        state.get("items", {}),
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=True,
        paid=bool(state.get("paid")),
        receipts_count=len(state.get("receipts", [])),
        paid_at=state.get("paid_at"),
    )

    try:
        await client.edit_message_caption(
            chat_id=state["chat_id"],
            message_id=state["album_first_id"],
            caption=caption
        )
    except Exception:
        pass


async def deny_if_locked(state: dict, callback, allow_when_locked: bool = False) -> bool:
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return False
    if state.get("locked") and not allow_when_locked:
        await callback.answer("Order ini sudah LAST SUBMIT (LOCK).", show_alert=True)
        return False
    return True


# ================= KEYBOARDS (SEBELUM LOCK) =================
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


def build_harga_keyboard(items_dict: dict, prices_dict: dict | None = None) -> InlineKeyboardMarkup:
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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚚 KOS PENGHANTARAN", callback_data="kos_penghantaran")],
        [InlineKeyboardButton("🗺️ TUKAR DESTINASI", callback_data="destinasi")],
        [InlineKeyboardButton("⬅️ KEMBALI PRODUK", callback_data="back_produk")]
    ])


def build_select_kos_keyboard(page: int = 0) -> InlineKeyboardMarkup:
    total = len(KOS_LIST)
    start = page * KOS_PER_PAGE
    end = start + KOS_PER_PAGE
    chunk = KOS_LIST[start:end]

    rows = []
    for i in range(0, len(chunk), 5):
        row_cost = chunk[i:i + 5]
        rows.append([
            InlineKeyboardButton(str(c), callback_data=f"setkos_{c}")
            for c in row_cost
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ PREV", callback_data=f"kos_page_{page - 1}"))
    if end < total:
        nav.append(InlineKeyboardButton("NEXT ➡️", callback_data=f"kos_page_{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton("⬅️ BACK (MENU DESTINASI)", callback_data="back_after_dest")])
    return InlineKeyboardMarkup(rows)


def build_after_cost_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ LAST SUBMIT", callback_data="last_submit")],
        [InlineKeyboardButton("✏️ TUKAR KOS PENGHANTARAN", callback_data="kos_penghantaran")],
        [InlineKeyboardButton("🗺️ TUKAR DESTINASI", callback_data="destinasi")],
        [InlineKeyboardButton("⬅️ KEMBALI PRODUK", callback_data="back_produk")],
    ])


# ================= CALLBACKS =================
@bot.on_callback_query(filters.regex(r"^hantar_detail$"))
async def senarai_produk(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    await callback.message.edit_reply_markup(reply_markup=build_produk_keyboard(state["items"]))
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^back_produk$"))
async def back_produk(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    await callback.message.edit_reply_markup(reply_markup=build_produk_keyboard(state["items"]))
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^produk_"))
async def pilih_kuantiti(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    produk_key = callback.data.replace("produk_", "", 1)
    await callback.message.edit_reply_markup(reply_markup=build_qty_keyboard(produk_key))
    await callback.answer("Pilih kuantiti")


@bot.on_callback_query(filters.regex(r"^qty_"))
async def simpan_qty_repost(client, callback):
    msg = callback.message
    old_id = msg.id
    state = ORDER_STATE.get(old_id)
    if not await deny_if_locked(state, callback):
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

    new_msg = await repost_single_photo_message(client, msg, state, build_produk_keyboard(state["items"]))
    # update key
    state2 = clone_state_for_new_msg(state)
    state2["control_msg_id"] = new_msg.id
    ORDER_STATE[new_msg.id] = state2
    ORDER_STATE.pop(old_id, None)


@bot.on_callback_query(filters.regex(r"^submit$"))
async def submit_order(client, callback):
    msg = callback.message
    old_id = msg.id
    state = ORDER_STATE.get(old_id)
    if not await deny_if_locked(state, callback):
        return

    if not state["items"]:
        await callback.answer("Sila pilih sekurang-kurangnya 1 produk dulu.", show_alert=True)
        return

    await callback.answer("Submit...")

    kb = build_harga_keyboard(state["items"], state.get("prices", {}))
    new_msg = await repost_single_photo_message(client, msg, state, kb)

    state2 = clone_state_for_new_msg(state)
    state2["control_msg_id"] = new_msg.id
    ORDER_STATE[new_msg.id] = state2
    ORDER_STATE.pop(old_id, None)


@bot.on_callback_query(filters.regex(r"^harga_"))
async def buka_senarai_harga(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    produk_key = callback.data.replace("harga_", "", 1)
    await callback.message.edit_reply_markup(reply_markup=build_select_harga_keyboard(produk_key, page=0))
    await callback.answer("Pilih harga")


@bot.on_callback_query(filters.regex(r"^harga_page_"))
async def harga_pagination(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
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


@bot.on_callback_query(filters.regex(r"^back_harga_menu$"))
async def back_harga_menu(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    kb = build_harga_keyboard(state["items"], state.get("prices", {}))
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^setharga_"))
async def set_harga(client, callback):
    msg = callback.message
    old_id = msg.id
    state = ORDER_STATE.get(old_id)
    if not await deny_if_locked(state, callback):
        return

    payload = callback.data[len("setharga_"):]
    try:
        produk_key, harga_str = payload.rsplit("_", 1)
        harga = int(harga_str)
    except Exception:
        await callback.answer("Format harga tidak sah.", show_alert=True)
        return

    state["prices"][produk_key] = harga
    await callback.answer("Harga diset")

    kb = build_harga_keyboard(state["items"], state.get("prices", {}))
    new_msg = await repost_single_photo_message(client, msg, state, kb)

    state2 = clone_state_for_new_msg(state)
    state2["control_msg_id"] = new_msg.id
    ORDER_STATE[new_msg.id] = state2
    ORDER_STATE.pop(old_id, None)


@bot.on_callback_query(filters.regex(r"^destinasi$"))
async def buka_destinasi(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    if not is_all_prices_done(state.get("items", {}), state.get("prices", {})):
        await callback.answer("Sila lengkapkan harga dulu.", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=build_dest_keyboard())
    await callback.answer("Pilih destinasi")


@bot.on_callback_query(filters.regex(r"^setdest_"))
async def set_destinasi(client, callback):
    msg = callback.message
    old_id = msg.id
    state = ORDER_STATE.get(old_id)
    if not await deny_if_locked(state, callback):
        return

    try:
        idx = int(callback.data.replace("setdest_", "", 1))
        dest = DEST_LIST[idx]
    except Exception:
        await callback.answer("Destinasi tidak sah.", show_alert=True)
        return

    state["dest"] = dest
    state["ship_cost"] = None
    await callback.answer(f"Destinasi: {dest}")

    new_msg = await repost_single_photo_message(client, msg, state, build_after_dest_keyboard())
    state2 = clone_state_for_new_msg(state)
    state2["control_msg_id"] = new_msg.id
    ORDER_STATE[new_msg.id] = state2
    ORDER_STATE.pop(old_id, None)


@bot.on_callback_query(filters.regex(r"^back_after_dest$"))
async def back_after_dest(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    if state.get("ship_cost") is not None:
        await callback.message.edit_reply_markup(reply_markup=build_after_cost_keyboard())
    else:
        await callback.message.edit_reply_markup(reply_markup=build_after_dest_keyboard())
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^kos_penghantaran$"))
async def buka_kos_penghantaran(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    if not state.get("dest"):
        await callback.answer("Sila pilih DESTINASI dulu.", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=build_select_kos_keyboard(page=0))
    await callback.answer("Pilih kos penghantaran")


@bot.on_callback_query(filters.regex(r"^kos_page_"))
async def kos_pagination(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not await deny_if_locked(state, callback):
        return
    try:
        page = int(callback.data.replace("kos_page_", "", 1))
    except Exception:
        await callback.answer("Pagination tidak sah.", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=build_select_kos_keyboard(page=page))
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^setkos_"))
async def set_kos(client, callback):
    msg = callback.message
    old_id = msg.id
    state = ORDER_STATE.get(old_id)
    if not await deny_if_locked(state, callback):
        return

    try:
        kos = int(callback.data.replace("setkos_", "", 1))
    except Exception:
        await callback.answer("Kos tidak sah.", show_alert=True)
        return

    state["ship_cost"] = kos
    await callback.answer(f"Kos diset: {kos}")

    new_msg = await repost_single_photo_message(client, msg, state, build_after_cost_keyboard())
    state2 = clone_state_for_new_msg(state)
    state2["control_msg_id"] = new_msg.id
    ORDER_STATE[new_msg.id] = state2
    ORDER_STATE.pop(old_id, None)


# ====== LAST SUBMIT (LOCK) ======
@bot.on_callback_query(filters.regex(r"^last_submit$"))
async def last_submit(client, callback):
    msg = callback.message
    old_id = msg.id
    state = ORDER_STATE.get(old_id)

    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    if not state.get("items"):
        await callback.answer("Item kosong.", show_alert=True)
        return
    if not is_all_prices_done(state.get("items", {}), state.get("prices", {})):
        await callback.answer("Harga belum lengkap.", show_alert=True)
        return
    if not state.get("dest"):
        await callback.answer("Destinasi belum dipilih.", show_alert=True)
        return
    if state.get("ship_cost") is None:
        await callback.answer("Kos penghantaran belum dipilih.", show_alert=True)
        return

    state["locked"] = True
    state.setdefault("receipts", [])
    state.setdefault("paid", False)
    state.setdefault("paid_at", None)
    state.setdefault("paid_by", None)
    state["album_msg_ids"] = None
    state["album_first_id"] = None
    state["control_msg_id"] = old_id

    await callback.answer("Last submit ✅")

    # Kekal single-photo dulu (buttons ada). Bila resit masuk baru convert jadi album 2 gambar.
    new_msg = await repost_single_photo_message(client, msg, state, build_final_keyboard())
    state2 = clone_state_for_new_msg(state)
    state2["control_msg_id"] = new_msg.id
    ORDER_STATE[new_msg.id] = state2
    ORDER_STATE.pop(old_id, None)


# ====== PAYMENT SETTLE ======
@bot.on_callback_query(filters.regex(r"^pay_settle$"))
async def pay_settle(client, callback):
    control_id = callback.message.id
    state = ORDER_STATE.get(control_id)
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return
    if not state.get("locked"):
        await callback.answer("Sila LAST SUBMIT dulu.", show_alert=True)
        return

    tz = pytz.timezone("Asia/Kuala_Lumpur")
    now = datetime.now(tz)
    display = now.strftime("%d/%m/%Y %I:%M%p").lower()

    state["paid"] = True
    state["paid_at"] = display
    state["paid_by"] = callback.from_user.id if callback.from_user else None

    await callback.answer("Payment settled ✅")

    # Kalau dah album: edit caption album first
    if state.get("album_first_id"):
        await update_album_caption_only(client, state)
        # buttons sudah ada pada control msg ini (tak perlu ubah)
        return

    # Kalau belum album: update caption + buttons pada single message
    await refresh_single_caption_and_kb(client, callback.message, state, build_final_keyboard())


# ====== ADD RESIT (manual fallback ForceReply) ======
@bot.on_callback_query(filters.regex(r"^add_resit$"))
async def add_resit(client, callback):
    state = ORDER_STATE.get(callback.message.id)
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return
    if not state.get("locked"):
        await callback.answer("Sila LAST SUBMIT dulu.", show_alert=True)
        return

    WAITING_RECEIPT[(callback.message.chat.id, callback.from_user.id)] = callback.message.id
    await callback.answer()

    await client.send_message(
        chat_id=callback.message.chat.id,
        text="Sila REPLY gambar resit di mesej ini ya.",
        reply_markup=ForceReply(selective=True)
    )


# ================= PHOTO HANDLER =================
@bot.on_message(filters.photo & ~filters.bot)
async def handle_photo(client, message):
    """
    A) gambar order baru -> bot jadikan order UI
    B) gambar resit (SWIPE REPLY pada ORDER/ALBUM) -> bot padam semua dan repost sebagai ALBUM 2 gambar + detail + buttons
    C) gambar resit (manual selepas ADD RESIT / ForceReply) -> sama juga, convert jadi ALBUM 2 gambar
    """
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0

    # ---------- KES B: RESIT (SWIPE REPLY) ----------
    if message.reply_to_message:
        replied_id = message.reply_to_message.id

        # replied boleh jadi:
        # - control message (single-photo locked, ada buttons)
        # - album message (order/resit) => map ke control id
        control_id = None
        if replied_id in ORDER_STATE:
            control_id = replied_id
        elif replied_id in REPLY_MAP:
            control_id = REPLY_MAP[replied_id]

        if control_id:
            state = ORDER_STATE.get(control_id)
            if state and state.get("locked"):
                # padam gambar resit staff (kalau boleh)
                try:
                    await message.delete()
                except Exception:
                    pass

                # padam semua bundle lama:
                # - kalau sebelum ni single-photo: padam control message sahaja
                # - kalau dah album: padam album + control
                await delete_whole_order_bundle(client, state)

                # convert kepada album 2 gambar (order + resit)
                new_control_id = await convert_to_album_bundle(client, state, message.photo.file_id)

                # update ORDER_STATE key ke control baru
                state2 = clone_state_for_new_msg(state)
                state2["control_msg_id"] = new_control_id
                ORDER_STATE[new_control_id] = state2
                ORDER_STATE.pop(control_id, None)

                return

    # ---------- KES C: RESIT manual selepas ADD RESIT ----------
    key = (chat_id, user_id)
    if key in WAITING_RECEIPT:
        control_id = WAITING_RECEIPT.pop(key)
        state = ORDER_STATE.get(control_id)

        if state and state.get("locked"):
            # padam gambar resit staff (kalau boleh)
            try:
                await message.delete()
            except Exception:
                pass

            # padam bundle lama
            await delete_whole_order_bundle(client, state)

            # convert kepada album
            new_control_id = await convert_to_album_bundle(client, state, message.photo.file_id)

            # update ORDER_STATE key
            state2 = clone_state_for_new_msg(state)
            state2["control_msg_id"] = new_control_id
            ORDER_STATE[new_control_id] = state2
            ORDER_STATE.pop(control_id, None)

        return

    # ---------- KES A: ORDER BARU ----------
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
        chat_id=chat_id,
        photo=photo_id,
        caption=base_caption,
        reply_markup=keyboard_awal
    )

    # Simpan state. Key = message id (control message id pada fasa ini)
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
        "paid_at": None,
        "paid_by": None,
        "locked": False,
        "album_msg_ids": None,
        "album_first_id": None,
        "control_msg_id": sent.id,
    }


if __name__ == "__main__":
    bot.run()

