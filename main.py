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
# KEY ORDER_STATE:
# - sebelum album: key = anchor_msg_id (photo order selepas dipost)
# - selepas album: key = album_first_id (photo pertama album yang ada caption + button)
#
# state = {
#   "chat_id": int,
#   "photo_id": str,
#   "base_caption": str,
#   "items": {produk_key: qty_int},
#   "prices": {produk_key: unit_price_int},
#   "dest": str | None,
#   "ship_cost": int | None,
#
#   "receipts": [file_id, ...],     # resit file_id (max last 9 utk album)
#   "paid": bool,
#   "paid_at": str | None,
#   "paid_by": int | None,
#   "locked": bool,
#
#   "anchor_msg_id": int | None,    # mesej order single (masa belum album)
#   "album_msg_ids": [int, ...] | None,
#   "album_first_id": int | None,
# }
ORDER_STATE = {}

# Mapping reply untuk mana-mana message album -> album_first_id (key)
# key = album_message_id -> value = album_first_id
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
HARGA_PER_PAGE = 15  # 3 baris x 5 butang

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
KOS_PER_PAGE = 15  # 3 baris x 5 butang

# Telegram album max 10 media: 1 order + max 9 resit
MAX_RECEIPTS_IN_ALBUM = 9


# ================= UTIL (BOLD + CAPTION RINGKAS) =================
BOLD_MAP = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
    "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
    "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"
)

def bold(text: str) -> str:
    return text.translate(BOLD_MAP)


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
    receipts_count: int = 0,
) -> str:
    """
    Ikut kehendak:
    - Ayat ringkas sahaja
    - Tiada info '3 keping resit'
    - Tiada status paid dalam caption (paid hanya pada butang)
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
                    total_line = int(unit_price) * int(q)
                    harga_display = f"RM{total_line}"
                except Exception:
                    harga_display = f"RM{unit_price}"
            lines.append(f"{nama} | {q} | {harga_display}")

    if dest:
        lines.append("")
        if ship_cost is None:
            lines.append(f"Destinasi : {dest}")
        else:
            lines.append(f"Destinasi : {dest} | RM{int(ship_cost)}")

    if items_dict and is_all_prices_done(items_dict, prices_dict) and ship_cost is not None:
        prod_total = calc_products_total(items_dict, prices_dict)
        grand_total = prod_total + int(ship_cost)
        lines.append("")
        lines.append(f"TOTAL KESELURUHAN : RM{grand_total}")

    if locked:
        lines.append("")
        if receipts_count <= 0:
            lines.append("⬅️" + bold("SLIDE KIRI UPLOAD RESIT"))
        else:
            lines.append("⬅️" + bold("SLIDE KIRI TAMBAH RESIT"))

    return "\n".join(lines)


def build_payment_keyboard(paid: bool) -> InlineKeyboardMarkup:
    # ikut kehendak: tiada emoji tambahan
    if paid:
        return InlineKeyboardMarkup([[InlineKeyboardButton("PAYMENT SETTLED", callback_data="noop")]])
    return InlineKeyboardMarkup([[InlineKeyboardButton("PAYMENT SETTLE", callback_data="pay_settle")]])


async def safe_delete(client: Client, chat_id: int, message_id: int):
    try:
        await client.delete_messages(chat_id, message_id)
    except Exception:
        pass


async def delete_bundle(client: Client, state: dict):
    """
    Padam SEMUA bundle semasa:
    - album (jika ada)
    - anchor single photo (jika ada)
    """
    chat_id = state["chat_id"]

    for mid in (state.get("album_msg_ids") or []):
        await safe_delete(client, chat_id, mid)
        REPLY_MAP.pop(mid, None)

    if state.get("anchor_msg_id"):
        await safe_delete(client, chat_id, state["anchor_msg_id"])


async def send_or_rebuild_album(client: Client, state: dict) -> int:
    """
    Hantar/rebuild album:
    - order + semua resit (last 9)
    - caption ringkas pada gambar pertama album
    - BUTANG PAYMENT dilekatkan TERUS pada gambar pertama album
      (TIADA control message -> tiada kotak merah/ayat tambahan bawah)
    Return: album_first_id (jadi key ORDER_STATE)
    """
    chat_id = state["chat_id"]

    receipts = list(state.get("receipts", []))[-MAX_RECEIPTS_IN_ALBUM:]
    state["receipts"] = receipts

    caption = build_caption(
        state["base_caption"],
        state.get("items", {}),
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=True,
        receipts_count=len(receipts),
    )

    media = [InputMediaPhoto(media=state["photo_id"], caption=caption)]
    for r in receipts:
        media.append(InputMediaPhoto(media=r))

    album_msgs = await client.send_media_group(chat_id=chat_id, media=media)
    album_ids = [m.id for m in album_msgs]
    album_first_id = album_msgs[0].id

    # lekatkan button pada gambar pertama album
    try:
        await client.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=album_first_id,
            reply_markup=build_payment_keyboard(bool(state.get("paid")))
        )
    except Exception:
        pass

    # reply mana2 gambar album -> kita map ke album_first_id
    for mid in album_ids:
        REPLY_MAP[mid] = album_first_id

    state["album_msg_ids"] = album_ids
    state["album_first_id"] = album_first_id
    state["anchor_msg_id"] = None

    return album_first_id


async def update_album_caption_only(client: Client, state: dict):
    """
    Bila tambah resit, caption perlu update ayat:
    - upload -> tambah
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
        receipts_count=len(state.get("receipts", [])),
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

    caption_baru = build_caption(
        state["base_caption"],
        state["items"],
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=bool(state.get("locked")),
        receipts_count=len(state.get("receipts", [])),
    )

    try:
        await msg.delete()
    except Exception:
        pass

    new_msg = await client.send_photo(
        chat_id=state["chat_id"],
        photo=state["photo_id"],
        caption=caption_baru,
        reply_markup=build_produk_keyboard(state["items"]),
    )

    ORDER_STATE[new_msg.id] = {
        **state,
        "anchor_msg_id": new_msg.id if not state.get("locked") else state.get("anchor_msg_id"),
    }
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

    caption_baru = build_caption(
        state["base_caption"],
        state["items"],
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=bool(state.get("locked")),
        receipts_count=len(state.get("receipts", [])),
    )

    kb = build_harga_keyboard(state["items"], state.get("prices", {}))

    try:
        await msg.delete()
    except Exception:
        pass

    new_msg = await client.send_photo(
        chat_id=state["chat_id"],
        photo=state["photo_id"],
        caption=caption_baru,
        reply_markup=kb
    )

    ORDER_STATE[new_msg.id] = {**state, "anchor_msg_id": new_msg.id}
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

    caption_baru = build_caption(
        state["base_caption"],
        state["items"],
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=bool(state.get("locked")),
        receipts_count=len(state.get("receipts", [])),
    )

    kb = build_harga_keyboard(state["items"], state.get("prices", {}))

    try:
        await msg.delete()
    except Exception:
        pass

    new_msg = await client.send_photo(
        chat_id=state["chat_id"],
        photo=state["photo_id"],
        caption=caption_baru,
        reply_markup=kb
    )

    ORDER_STATE[new_msg.id] = {**state, "anchor_msg_id": new_msg.id}
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

    caption_baru = build_caption(
        state["base_caption"],
        state["items"],
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=bool(state.get("locked")),
        receipts_count=len(state.get("receipts", [])),
    )

    try:
        await msg.delete()
    except Exception:
        pass

    new_msg = await client.send_photo(
        chat_id=state["chat_id"],
        photo=state["photo_id"],
        caption=caption_baru,
        reply_markup=build_after_dest_keyboard()
    )

    ORDER_STATE[new_msg.id] = {**state, "anchor_msg_id": new_msg.id}
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

    caption_baru = build_caption(
        state["base_caption"],
        state["items"],
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=bool(state.get("locked")),
        receipts_count=len(state.get("receipts", [])),
    )

    try:
        await msg.delete()
    except Exception:
        pass

    new_msg = await client.send_photo(
        chat_id=state["chat_id"],
        photo=state["photo_id"],
        caption=caption_baru,
        reply_markup=build_after_cost_keyboard()
    )

    ORDER_STATE[new_msg.id] = {**state, "anchor_msg_id": new_msg.id}
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
    state["anchor_msg_id"] = old_id

    await callback.answer("Last submit ✅")

    # Lepas lock: TIADA button (muncul hanya selepas resit pertama -> album)
    caption_baru = build_caption(
        state["base_caption"],
        state["items"],
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=True,
        receipts_count=0,
    )

    try:
        await msg.edit_caption(caption=caption_baru, reply_markup=None)
    except Exception:
        # fallback: repost tanpa keyboard
        try:
            await msg.delete()
        except Exception:
            pass
        new_msg = await client.send_photo(
            chat_id=state["chat_id"],
            photo=state["photo_id"],
            caption=caption_baru
        )
        state["anchor_msg_id"] = new_msg.id
        ORDER_STATE[new_msg.id] = state
        ORDER_STATE.pop(old_id, None)
        return

    ORDER_STATE[old_id] = state


# ====== PAYMENT SETTLE (butang berada pada album_first_id) ======
@bot.on_callback_query(filters.regex(r"^pay_settle$"))
async def pay_settle(client, callback):
    key_id = callback.message.id  # album_first_id
    state = ORDER_STATE.get(key_id)
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

    # tukar label butang sahaja
    try:
        await callback.message.edit_reply_markup(reply_markup=build_payment_keyboard(True))
    except Exception:
        pass


@bot.on_callback_query(filters.regex(r"^noop$"))
async def noop(client, callback):
    await callback.answer("Dah settle ✅", show_alert=False)


# ================= PHOTO HANDLER =================
@bot.on_message(filters.photo & ~filters.bot)
async def handle_photo(client, message):
    """
    A) gambar order baru -> bot jadikan order UI
    B) gambar resit (SWIPE REPLY pada anchor / mana-mana gambar album) ->
       bot padam resit staff, padam bundle lama, kemudian hantar semula album:
       order + semua resit (last 9) + butang PAYMENT di bawah caption (tanpa mesej tambahan).
    """
    chat_id = message.chat.id

    # ---------- KES B: RESIT (SWIPE REPLY) ----------
    if message.reply_to_message:
        replied_id = message.reply_to_message.id

        key_id = None
        state = None

        # reply kepada anchor (single order locked)
        if replied_id in ORDER_STATE:
            state = ORDER_STATE.get(replied_id)
            key_id = replied_id

        # reply kepada mana-mana gambar album
        elif replied_id in REPLY_MAP:
            key_id = REPLY_MAP[replied_id]
            state = ORDER_STATE.get(key_id)

        if state and state.get("locked"):
            # padam gambar resit staff (kalau boleh)
            try:
                await message.delete()
            except Exception:
                pass

            # tambah resit file_id
            state.setdefault("receipts", [])
            state["receipts"].append(message.photo.file_id)

            # padam bundle lama (anchor/album)
            await delete_bundle(client, state)

            # rebuild album (order + resit...) => butang muncul pada gambar pertama album
            new_key = await send_or_rebuild_album(client, state)

            # pindah key ORDER_STATE
            if key_id is not None:
                ORDER_STATE.pop(key_id, None)
            ORDER_STATE[new_key] = state
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
        "anchor_msg_id": sent.id,
        "album_msg_ids": None,
        "album_first_id": None,
    }


if __name__ == "__main__":
    bot.run()
