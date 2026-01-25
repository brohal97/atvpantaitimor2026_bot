# =========================
# ATV PANTAI TIMOR BOT (NO OCR VERSION)
# + PAYMENT SETTLE ada password keypad (tanpa OCR)
# + SEMAK BAYARAN: hanya user tertentu + keypad password (tanpa OCR)
#   - betul -> COPY album (produk+resit) ke channel rasmi -> delete dalam group
# + BACK (GLOBAL): undo 1 langkah + padam selection 1 langkah
# + INPUT HARGA & KOS TRANSPORT: keypad nombor manual (0-9) + BACKSPACE + OKEY
#   - BACK pada keypad = padam 1 digit (kalau kosong, cancel balik 1 halaman)
#
# ✅ UPDATE (ikut request):
# - Harga produk TIDAK didarab dengan kuantiti.
# - Paparan RM ikut harga yang user masukkan sahaja.
# - TOTAL KESELURUHAN = jumlah semua harga yang user masukkan + kos transport.
#
# ✅ FIX STABIL:
# - Handle FloodWait (Telegram rate limit) untuk semua API penting
# - Debounce rebuild album bila banyak resit masuk laju-laju
# - State resolver bila message id bertukar (repost/edit fail)
# - Edit fail tak delete mesej lama (cuma disable button), elak “padam sendiri”
#
# ✅ NO OCR:
# - Semua fungsi Google Vision/OCR dibuang 100%.
# - PAYMENT SETTLE / SEMAK BAYARAN tidak buat OCR & tidak paparkan hasil OCR.
# =========================

import os, re, traceback, asyncio
from datetime import datetime
from typing import Dict, List, Optional, Set, Any, Tuple

import pytz
from pyrogram import Client, filters
from pyrogram.errors import (
    MessageDeleteForbidden,
    ChatAdminRequired,
    FloodWait,
    RPCError,
)
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto


# ================= ENV =================
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Missing API_ID / API_HASH / BOT_TOKEN in Railway Variables")


# ================= PASSWORD SETTINGS =================
PAYMENT_PIN = os.getenv("PAYMENT_PIN", "1234").strip()
MAX_PIN_TRIES = 5


# ================= SEMAK BAYARAN (ROLE + PIN + CHANNEL) =================
OFFICIAL_CHANNEL_ID = int(os.getenv("OFFICIAL_CHANNEL_ID", "-1003573894188"))  # contoh: -1001234567890
if not OFFICIAL_CHANNEL_ID:
    raise RuntimeError("Missing env var: OFFICIAL_CHANNEL_ID (channel rasmi)")

SEMAK_PIN = os.getenv("SEMAK_PIN", "4321").strip()
SEMAK_ALLOWED_IDS_RAW = os.getenv("SEMAK_ALLOWED_IDS", "1150078068").strip()


def parse_allowed_ids(raw: str) -> Set[int]:
    out: Set[int] = set()
    if not raw:
        return out
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except Exception:
            pass
    return out


SEMAK_ALLOWED_IDS = parse_allowed_ids(SEMAK_ALLOWED_IDS_RAW)


# ================= BOT =================
bot = Client(
    "atv_bot_2026",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


# ================= TEMP STATE (RAM) =================
# key = message_id (order msg sebelum lock) / control msg id (selepas rebuild)
ORDER_STATE: Dict[int, Dict[str, Any]] = {}
# album message id -> control msg id
REPLY_MAP: Dict[int, int] = {}


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

DEST_LIST = [
    "JOHOR", "KEDAH", "KELANTAN", "MELAKA", "NEGERI SEMBILAN", "PAHANG", "PERAK", "PERLIS",
    "PULAU PINANG", "SELANGOR", "TERENGGANU", "LANGKAWI", "PICKUP SENDIRI", "KITA HANTAR",
]

MAX_RECEIPTS_IN_ALBUM = 9

# input keypad limit (harga/kos) - boleh ubah kalau perlu
MAX_NUM_DIGITS = 6  # contoh: 999999

# Anti spam rebuild album (bila resit masuk laju-laju)
REBUILD_DEBOUNCE_SECONDS = float(os.getenv("REBUILD_DEBOUNCE_SECONDS", "2.2"))


# ================= TELEGRAM SAFE CALL (FLOODWAIT) =================
async def tg_call(fn, *args, **kwargs):
    """
    Wrapper untuk handle Telegram FloodWait supaya bot tak crash/restart.
    """
    while True:
        try:
            return await fn(*args, **kwargs)
        except FloodWait as e:
            wait_s = int(getattr(e, "value", 1))
            await asyncio.sleep(wait_s + 1)
        except RPCError:
            # RPC error lain: retry kecil (kadang-kadang sementara)
            await asyncio.sleep(0.8)
        except Exception:
            raise


def unregister_state(state: Dict[str, Any]):
    """
    Buang semua key yang point ke state yang sama.
    """
    for k in list(ORDER_STATE.keys()):
        if ORDER_STATE.get(k) is state:
            ORDER_STATE.pop(k, None)


def register_state(key: int, state: Dict[str, Any]):
    ORDER_STATE[key] = state


def resolve_state_by_msg_id(msg_id: int) -> Optional[Dict[str, Any]]:
    """
    Kalau ORDER_STATE tak jumpa ikut key, cuba cari dalam values:
    - anchor_msg_id
    - control_msg_id
    - album_msg_ids
    """
    st = ORDER_STATE.get(msg_id)
    if st:
        return st

    for s in ORDER_STATE.values():
        try:
            if s.get("anchor_msg_id") == msg_id:
                return s
            if s.get("control_msg_id") == msg_id:
                return s
            if msg_id in (s.get("album_msg_ids") or []):
                return s
        except Exception:
            continue
    return None


def ensure_state_lock(state: Dict[str, Any]) -> asyncio.Lock:
    lk = state.get("_lock")
    if isinstance(lk, asyncio.Lock):
        return lk
    lk = asyncio.Lock()
    state["_lock"] = lk
    return lk


# ================= TEXT STYLE =================
BOLD_MAP = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
    "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
    "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"
)


def bold(text: str) -> str:
    return (text or "").translate(BOLD_MAP)


# ================= CUSTOM TEXT (USER REQUEST) =================
TXT_PAYMENT_CONTROL = bold("Tekan butang sahkan bayaran")
TXT_SEMAK_CONTROL = bold("Semak pembayaran dengan segera")
TXT_SEMAK_PIN_TITLE = bold("ISI PASWORD JIKA BAYARAN TELAH DISEMAK")


# ================= UTIL (ORDER) =================
def is_all_prices_done(items_dict: Dict[str, int], prices_dict: Dict[str, int]) -> bool:
    if not items_dict:
        return False
    return all(k in prices_dict for k in items_dict.keys())


def calc_products_total(items_dict: Dict[str, int], prices_dict: Dict[str, int]) -> int:
    """
    ✅ UPDATE: total produk = jumlah harga yang user isi sahaja (TIDAK darab qty)
    """
    total = 0
    for k in items_dict.keys():
        v = prices_dict.get(k)
        if v is None:
            continue
        try:
            total += int(v)
        except Exception:
            pass
    return total


def build_caption(
    base_caption: str,
    items_dict: Dict[str, int],
    prices_dict: Optional[Dict[str, int]] = None,
    dest: Optional[str] = None,
    ship_cost: Optional[int] = None,
    locked: bool = False,
    receipts_count: int = 0,
    paid: bool = False,
    state: Optional[Dict[str, Any]] = None,
    extra_lines: Optional[List[str]] = None,
) -> str:
    prices_dict = prices_dict or {}
    lines = [bold(base_caption)]

    if items_dict:
        for k, q in items_dict.items():
            nama = PRODUK_LIST.get(k, k)
            unit_price = prices_dict.get(k)

            # ✅ UPDATE: Papar harga yang user masukkan sahaja (tidak darab qty)
            if unit_price is None:
                harga_display = "-"
            else:
                try:
                    harga_display = f"RM{int(unit_price)}"
                except Exception:
                    harga_display = f"RM{unit_price}"

            lines.append(bold(f"{nama} | {q} | {harga_display}"))

    if dest:
        if ship_cost is None:
            lines.append(f"Destinasi : {bold(dest)}")
        else:
            lines.append(f"Destinasi : {bold(f'{dest} | RM{int(ship_cost)}')}")

    if items_dict and is_all_prices_done(items_dict, prices_dict) and ship_cost is not None:
        prod_total = calc_products_total(items_dict, prices_dict)
        grand_total = prod_total + int(ship_cost)
        lines.append(f"TOTAL KESELURUHAN : {bold(f'RM{grand_total}')}")

    if extra_lines:
        lines.append("")
        lines.extend(extra_lines)

    if locked:
        lines.append("")
        if paid:
            # ✅ NO OCR: hanya tunjuk status paid
            paid_at = (state or {}).get("paid_at")
            if paid_at:
                lines.append(bold(f"✅ PAID | {paid_at}"))
            else:
                lines.append(bold("✅ PAID"))
        # arahan resit
        if receipts_count <= 0:
            lines.append("⬅️" + bold("SLIDE KIRI UPLOAD RESIT"))
        else:
            lines.append("⬅️" + bold("SLIDE KIRI TAMBAH RESIT"))

    cap = "\n".join(lines)
    # Telegram caption limit (safe)
    if len(cap) > 1024:
        cap = cap[:1000] + "\n...(caption terlalu panjang)"
    return cap


# ================= GLOBAL BACK (UNDO) =================
BACK_CB = "nav_back"


def push_history(state: Dict[str, Any], prev_view: str, prev_ctx: Dict[str, Any], undo: Optional[Dict[str, Any]] = None):
    state.setdefault("history", [])
    state["history"].append({
        "view": prev_view,
        "ctx": dict(prev_ctx or {}),
        "undo": undo
    })


def apply_undo(state: Dict[str, Any], undo: Dict[str, Any]):
    if not undo:
        return

    t = undo.get("type")

    if t == "set_qty":
        k = undo["produk_key"]
        prev = undo.get("prev")  # None => remove
        if prev is None:
            state.get("items", {}).pop(k, None)
            state.get("prices", {}).pop(k, None)  # bila item dipadam, harga item juga padam
        else:
            state.setdefault("items", {})[k] = int(prev)

    elif t == "set_price":
        k = undo["produk_key"]
        prev = undo.get("prev")
        if prev is None:
            state.get("prices", {}).pop(k, None)
        else:
            state.setdefault("prices", {})[k] = int(prev)

    elif t == "set_dest":
        state["dest"] = undo.get("prev_dest")
        state["ship_cost"] = undo.get("prev_ship_cost")

    elif t == "set_ship_cost":
        state["ship_cost"] = undo.get("prev")

    if not state.get("items"):
        state["items"] = {}
        state["prices"] = {}
        state["dest"] = None
        state["ship_cost"] = None


def pop_history_restore(state: Dict[str, Any]) -> bool:
    hist = state.get("history", [])
    if not hist:
        return False
    last = hist.pop()
    undo = last.get("undo")
    if undo:
        apply_undo(state, undo)
    state["view"] = last.get("view")
    state["ctx"] = last.get("ctx", {}) or {}
    return True


# ================= KEYBOARDS =================
def kb_back_row() -> List[InlineKeyboardButton]:
    return [InlineKeyboardButton("🔙 BACK", callback_data=BACK_CB)]


def build_payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("PAYMENT SETTLE", callback_data="pay_settle")]])


def build_semak_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("BUTANG SEMAK BAYARAN", callback_data="semak_bayaran")]])


def build_pin_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1", callback_data=f"{prefix}_1"),
            InlineKeyboardButton("2", callback_data=f"{prefix}_2"),
            InlineKeyboardButton("3", callback_data=f"{prefix}_3"),
        ],
        [
            InlineKeyboardButton("4", callback_data=f"{prefix}_4"),
            InlineKeyboardButton("5", callback_data=f"{prefix}_5"),
            InlineKeyboardButton("6", callback_data=f"{prefix}_6"),
        ],
        [
            InlineKeyboardButton("7", callback_data=f"{prefix}_7"),
            InlineKeyboardButton("8", callback_data=f"{prefix}_8"),
            InlineKeyboardButton("9", callback_data=f"{prefix}_9"),
        ],
        [InlineKeyboardButton("0", callback_data=f"{prefix}_0")],
        [
            InlineKeyboardButton("🔙 BACK", callback_data=f"{prefix}_back"),
            InlineKeyboardButton("✅ OKEY", callback_data=f"{prefix}_ok"),
        ],
    ])


def build_num_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1", callback_data=f"{prefix}_1"),
            InlineKeyboardButton("2", callback_data=f"{prefix}_2"),
            InlineKeyboardButton("3", callback_data=f"{prefix}_3"),
        ],
        [
            InlineKeyboardButton("4", callback_data=f"{prefix}_4"),
            InlineKeyboardButton("5", callback_data=f"{prefix}_5"),
            InlineKeyboardButton("6", callback_data=f"{prefix}_6"),
        ],
        [
            InlineKeyboardButton("7", callback_data=f"{prefix}_7"),
            InlineKeyboardButton("8", callback_data=f"{prefix}_8"),
            InlineKeyboardButton("9", callback_data=f"{prefix}_9"),
        ],
        [InlineKeyboardButton("0", callback_data=f"{prefix}_0")],
        [
            InlineKeyboardButton("🔙 BACK", callback_data=f"{prefix}_back"),
            InlineKeyboardButton("✅ OKEY", callback_data=f"{prefix}_ok"),
        ],
    ])


def mask_pin(buf: str) -> str:
    return "(kosong)" if not buf else ("•" * len(buf))


def pin_prompt_text(title: str, buf: str) -> str:
    return f"🔐 {title}\n\nPIN: {mask_pin(buf)}"


def semak_pin_prompt_text(buf: str) -> str:
    return f"{TXT_SEMAK_PIN_TITLE}\n\nPIN: {mask_pin(buf)}"


# ================= SAFE DELETE / SAFE EDIT =================
async def safe_delete(client: Client, chat_id: int, message_id: int):
    try:
        await tg_call(client.delete_messages, chat_id, message_id)
    except Exception:
        pass


async def delete_bundle(client: Client, state: Dict[str, Any]):
    chat_id = state["chat_id"]

    for mid in (state.get("album_msg_ids") or []):
        await safe_delete(client, chat_id, mid)
        REPLY_MAP.pop(mid, None)

    if state.get("control_msg_id"):
        await safe_delete(client, chat_id, state["control_msg_id"])

    if state.get("anchor_msg_id"):
        await safe_delete(client, chat_id, state["anchor_msg_id"])


async def disable_old_message_buttons(msg):
    """
    Jangan delete terus (elak rasa macam 'padam sendiri'), cuma buang buttons.
    """
    try:
        await tg_call(msg.edit_reply_markup, reply_markup=None)
    except Exception:
        pass


# ================= MESSAGE RENDER (EDIT / FALLBACK REPOST) =================
async def replace_order_message(client: Client, msg, state: Dict[str, Any], caption: str, keyboard: Optional[InlineKeyboardMarkup]):
    """
    Cuba edit caption. Kalau gagal (kadang Telegram tak bagi), kita:
    - disable button pada msg lama (supaya staff tak tekan lagi)
    - send message baru
    - update mapping state ke msg baru
    """
    try:
        await tg_call(msg.edit_caption, caption=caption, reply_markup=keyboard)
        state["anchor_msg_id"] = msg.id
        unregister_state(state)
        register_state(msg.id, state)
        return msg
    except Exception:
        pass

    await disable_old_message_buttons(msg)

    new_msg = await tg_call(
        client.send_photo,
        chat_id=state["chat_id"],
        photo=state["photo_id"],
        caption=caption,
        reply_markup=keyboard
    )

    state["anchor_msg_id"] = new_msg.id
    unregister_state(state)
    register_state(new_msg.id, state)

    # jangan delete msg lama (elak “padam sendiri”)
    return new_msg


# ================= FLOW VIEWS =================
VIEW_AWAL = "awal"
VIEW_PRODUK = "produk"
VIEW_QTY = "qty"
VIEW_HARGA_MENU = "harga_menu"
VIEW_HARGA_INPUT = "harga_input"
VIEW_DEST = "dest"
VIEW_AFTER_DEST = "after_dest"
VIEW_KOS_INPUT = "kos_input"
VIEW_AFTER_COST = "after_cost"

PRICE_PREFIX = "pr"
KOS_PREFIX = "tr"


def build_awal_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("NAMA PRODUK", callback_data="hantar_detail")],
    ])


def build_produk_keyboard(items_dict: Dict[str, int]) -> InlineKeyboardMarkup:
    rows = []
    for key, name in PRODUK_LIST.items():
        if key not in items_dict:
            rows.append([InlineKeyboardButton(name, callback_data=f"produk_{key}")])

    if items_dict:
        rows.append([InlineKeyboardButton("✅ SUBMIT", callback_data="submit")])

    rows.append(kb_back_row())
    return InlineKeyboardMarkup(rows)


def build_qty_keyboard(produk_key: str) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    nums = list(range(1, 16))
    for i in range(0, len(nums), 3):
        chunk = nums[i:i+3]
        rows.append([InlineKeyboardButton(str(n), callback_data=f"qty_{produk_key}_{n}") for n in chunk])
    rows.append(kb_back_row())
    return InlineKeyboardMarkup(rows)


def build_harga_menu_keyboard(items_dict: Dict[str, int], prices_dict: Dict[str, int]) -> InlineKeyboardMarkup:
    rows = []
    for k in items_dict.keys():
        if k in prices_dict:
            continue
        nama = PRODUK_LIST.get(k, k)
        rows.append([InlineKeyboardButton(f"HARGA - {nama}", callback_data=f"harga_{k}")])

    if items_dict and all(k in prices_dict for k in items_dict.keys()):
        rows.append([InlineKeyboardButton("📍 DESTINASI", callback_data="destinasi")])

    rows.append(kb_back_row())
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
    rows.append(kb_back_row())
    return InlineKeyboardMarkup(rows)


def build_after_dest_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚚 KOS TRANSPORT", callback_data="kos_transport")],
        [InlineKeyboardButton("🗺️ TUKAR DESTINASI", callback_data="destinasi")],
        kb_back_row()
    ])


def build_after_cost_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ LAST SUBMIT", callback_data="last_submit")],
        [InlineKeyboardButton("✏️ TUKAR KOS TRANSPORT", callback_data="kos_transport")],
        [InlineKeyboardButton("🗺️ TUKAR DESTINASI", callback_data="destinasi")],
        kb_back_row()
    ])


def get_keyboard_for_view(state: Dict[str, Any]) -> InlineKeyboardMarkup:
    view = state.get("view", VIEW_AWAL)
    ctx = state.get("ctx", {}) or {}
    items = state.get("items", {}) or {}
    prices = state.get("prices", {}) or {}

    if view == VIEW_AWAL:
        return build_awal_keyboard()
    if view == VIEW_PRODUK:
        return build_produk_keyboard(items)
    if view == VIEW_QTY:
        return build_qty_keyboard(ctx.get("produk_key", ""))
    if view == VIEW_HARGA_MENU:
        return build_harga_menu_keyboard(items, prices)
    if view == VIEW_HARGA_INPUT:
        return build_num_keyboard(PRICE_PREFIX)
    if view == VIEW_DEST:
        return build_dest_keyboard()
    if view == VIEW_AFTER_DEST:
        return build_after_dest_keyboard()
    if view == VIEW_KOS_INPUT:
        return build_num_keyboard(KOS_PREFIX)
    if view == VIEW_AFTER_COST:
        return build_after_cost_keyboard()

    return build_awal_keyboard()


def build_extra_lines_for_input(state: Dict[str, Any]) -> Optional[List[str]]:
    view = state.get("view")
    ctx = state.get("ctx", {}) or {}
    buf = (ctx.get("num_buf") or "").strip()

    if view == VIEW_HARGA_INPUT:
        pk = ctx.get("produk_key", "")
        nama = PRODUK_LIST.get(pk, pk) or "PRODUK"
        shown = buf if buf else "-"
        return [
            bold("MASUKKAN HARGA PRODUK"),
            f"{nama}",
            f"HARGA: {bold('RM' + shown)}",
        ]

    if view == VIEW_KOS_INPUT:
        shown = buf if buf else "-"
        return [
            bold("MASUKKAN KOS TRANSPORT"),
            f"KOS: {bold('RM' + shown)}",
        ]

    return None


async def render_order(client: Client, callback, state: Dict[str, Any]):
    lk = ensure_state_lock(state)
    async with lk:
        extra = build_extra_lines_for_input(state)
        caption = build_caption(
            state["base_caption"],
            state.get("items", {}),
            state.get("prices", {}),
            state.get("dest"),
            state.get("ship_cost"),
            locked=False,
            receipts_count=len(state.get("receipts", [])),
            paid=bool(state.get("paid")),
            state=state,
            extra_lines=extra
        )
        kb = get_keyboard_for_view(state)
        new_msg = await replace_order_message(client, callback.message, state, caption, kb)
        return new_msg


async def deny_if_locked(state: Optional[Dict[str, Any]], callback) -> bool:
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return False
    if state.get("locked"):
        await callback.answer("Order ini sudah LAST SUBMIT (LOCK).", show_alert=True)
        return False
    return True


# ================= ALBUM SENDER =================
async def send_or_rebuild_album(client: Client, state: Dict[str, Any]) -> int:
    chat_id = state["chat_id"]

    receipts_album = list(state.get("receipts", []))[-MAX_RECEIPTS_IN_ALBUM:]
    state["receipts_album"] = receipts_album

    caption = build_caption(
        state["base_caption"],
        state.get("items", {}),
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=True,
        receipts_count=len(receipts_album),
        paid=bool(state.get("paid")),
        state=state,
    )

    media = [InputMediaPhoto(media=state["photo_id"], caption=caption)]
    for r in receipts_album:
        media.append(InputMediaPhoto(media=r))

    album_msgs = await tg_call(client.send_media_group, chat_id=chat_id, media=media)
    album_ids = [m.id for m in album_msgs]

    if state.get("paid"):
        control_text = TXT_SEMAK_CONTROL
        control_markup = build_semak_keyboard()
    else:
        control_text = TXT_PAYMENT_CONTROL
        control_markup = build_payment_keyboard()

    control = await tg_call(client.send_message, chat_id=chat_id, text=control_text, reply_markup=control_markup)

    for mid in album_ids:
        REPLY_MAP[mid] = control.id

    state["album_msg_ids"] = album_ids
    state["control_msg_id"] = control.id
    state["anchor_msg_id"] = None

    return control.id


# ================= TRANSFER TO CHANNEL =================
async def copy_album_to_channel(client: Client, state: Dict[str, Any]) -> None:
    receipts_album = list(state.get("receipts", []))[-MAX_RECEIPTS_IN_ALBUM:]
    state["receipts_album"] = receipts_album

    caption = build_caption(
        state["base_caption"],
        state.get("items", {}),
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=True,
        receipts_count=len(receipts_album),
        paid=True,
        state=state,
    )

    media = [InputMediaPhoto(media=state["photo_id"], caption=caption)]
    for r in receipts_album:
        media.append(InputMediaPhoto(media=r))

    await tg_call(client.send_media_group, chat_id=OFFICIAL_CHANNEL_ID, media=media)


# ================= DEBOUNCE REBUILD (ANTI FLOOD) =================
async def _rebuild_after_delay(client: Client, state: Dict[str, Any], delay: float):
    try:
        await asyncio.sleep(delay)
        lk = ensure_state_lock(state)
        async with lk:
            if state not in ORDER_STATE.values():
                return
            await delete_bundle(client, state)
            new_control_id = await send_or_rebuild_album(client, state)

            unregister_state(state)
            register_state(new_control_id, state)
    except Exception:
        pass


def schedule_rebuild_album(client: Client, state: Dict[str, Any], delay: float = REBUILD_DEBOUNCE_SECONDS):
    task: Optional[asyncio.Task] = state.get("_rebuild_task")
    if task and not task.done():
        task.cancel()
    state["_rebuild_task"] = asyncio.create_task(_rebuild_after_delay(client, state, delay))


async def rebuild_album_now(client: Client, state: Dict[str, Any]):
    task: Optional[asyncio.Task] = state.get("_rebuild_task")
    if task and not task.done():
        task.cancel()

    lk = ensure_state_lock(state)
    async with lk:
        await delete_bundle(client, state)
        new_control_id = await send_or_rebuild_album(client, state)

        unregister_state(state)
        register_state(new_control_id, state)


# ================= CALLBACKS: GLOBAL BACK =================
@bot.on_callback_query(filters.regex(rf"^{BACK_CB}$"))
async def nav_back(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    lk = ensure_state_lock(state)
    async with lk:
        if not pop_history_restore(state):
            await callback.answer("Tiada langkah untuk undur.", show_alert=True)
            return

    await render_order(client, callback, state)
    await callback.answer("Undo ✅")


# ================= CALLBACKS: ORDER FLOW =================
@bot.on_callback_query(filters.regex(r"^hantar_detail$"))
async def senarai_produk(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    lk = ensure_state_lock(state)
    async with lk:
        push_history(state, prev_view=VIEW_AWAL, prev_ctx=state.get("ctx", {}) or {}, undo=None)
        state["view"] = VIEW_PRODUK
        state["ctx"] = {}

    await render_order(client, callback, state)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^produk_"))
async def pilih_kuantiti(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    produk_key = callback.data.replace("produk_", "", 1)

    lk = ensure_state_lock(state)
    async with lk:
        push_history(state, prev_view=VIEW_PRODUK, prev_ctx=state.get("ctx", {}) or {}, undo=None)
        state["view"] = VIEW_QTY
        state["ctx"] = {"produk_key": produk_key}

    await render_order(client, callback, state)
    await callback.answer("Pilih kuantiti")


@bot.on_callback_query(filters.regex(r"^qty_"))
async def simpan_qty(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    payload = callback.data[len("qty_"):]
    try:
        produk_key, qty_str = payload.rsplit("_", 1)
        qty = int(qty_str)
    except Exception:
        await callback.answer("Format kuantiti tidak sah.", show_alert=True)
        return

    if qty < 1 or qty > 15:
        await callback.answer("Kuantiti mesti 1 hingga 15.", show_alert=True)
        return

    lk = ensure_state_lock(state)
    async with lk:
        prev_qty = state.get("items", {}).get(produk_key)
        push_history(
            state,
            prev_view=VIEW_QTY,
            prev_ctx=state.get("ctx", {}) or {},
            undo={"type": "set_qty", "produk_key": produk_key, "prev": prev_qty}
        )
        state.setdefault("items", {})[produk_key] = qty
        state["view"] = VIEW_PRODUK
        state["ctx"] = {}

    await render_order(client, callback, state)
    await callback.answer("Disimpan")


@bot.on_callback_query(filters.regex(r"^submit$"))
async def submit_order(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    lk = ensure_state_lock(state)
    async with lk:
        if not state.get("items"):
            await callback.answer("Sila pilih sekurang-kurangnya 1 produk dulu.", show_alert=True)
            return

        push_history(state, prev_view=VIEW_PRODUK, prev_ctx=state.get("ctx", {}) or {}, undo=None)
        state["view"] = VIEW_HARGA_MENU
        state["ctx"] = {}

    await render_order(client, callback, state)
    await callback.answer("Set harga")


@bot.on_callback_query(filters.regex(r"^harga_"))
async def buka_harga_keypad(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    produk_key = callback.data.replace("harga_", "", 1)

    lk = ensure_state_lock(state)
    async with lk:
        push_history(state, prev_view=VIEW_HARGA_MENU, prev_ctx=state.get("ctx", {}) or {}, undo=None)
        state["view"] = VIEW_HARGA_INPUT
        state["ctx"] = {"produk_key": produk_key, "num_buf": ""}

    await render_order(client, callback, state)
    await callback.answer("Masukkan harga")


@bot.on_callback_query(filters.regex(rf"^{PRICE_PREFIX}_[0-9]$"))
async def harga_digit(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    lk = ensure_state_lock(state)
    async with lk:
        if state.get("view") != VIEW_HARGA_INPUT:
            await callback.answer("Bukan halaman harga.", show_alert=True)
            return

        digit = callback.data.split("_", 1)[1]
        ctx = state.get("ctx", {}) or {}
        buf = (ctx.get("num_buf") or "")

        if len(buf) >= MAX_NUM_DIGITS:
            await callback.answer("Digit sudah maksimum.", show_alert=True)
            return

        ctx["num_buf"] = buf + digit
        state["ctx"] = ctx

    await render_order(client, callback, state)
    await callback.answer()


@bot.on_callback_query(filters.regex(rf"^{PRICE_PREFIX}_back$"))
async def harga_backspace_or_cancel(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    lk = ensure_state_lock(state)
    async with lk:
        if state.get("view") != VIEW_HARGA_INPUT:
            await callback.answer("Bukan halaman harga.", show_alert=True)
            return

        ctx = state.get("ctx", {}) or {}
        buf = (ctx.get("num_buf") or "")
        if buf:
            ctx["num_buf"] = buf[:-1]
            state["ctx"] = ctx
            action = "Padam 1 digit"
        else:
            if pop_history_restore(state):
                action = "Kembali"
            else:
                await callback.answer("Tiada langkah untuk undur.", show_alert=True)
                return

    await render_order(client, callback, state)
    await callback.answer(action)


@bot.on_callback_query(filters.regex(rf"^{PRICE_PREFIX}_ok$"))
async def harga_okey_set(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    lk = ensure_state_lock(state)
    async with lk:
        if state.get("view") != VIEW_HARGA_INPUT:
            await callback.answer("Bukan halaman harga.", show_alert=True)
            return

        ctx = state.get("ctx", {}) or {}
        buf = (ctx.get("num_buf") or "").strip()
        produk_key = ctx.get("produk_key", "")

        if not buf:
            await callback.answer("Sila masukkan nombor harga.", show_alert=True)
            return

        try:
            harga = int(buf)
        except Exception:
            await callback.answer("Harga tidak sah.", show_alert=True)
            return

        prev_price = state.get("prices", {}).get(produk_key)
        push_history(
            state,
            prev_view=VIEW_HARGA_INPUT,
            prev_ctx=dict(ctx),
            undo={"type": "set_price", "produk_key": produk_key, "prev": prev_price}
        )

        state.setdefault("prices", {})[produk_key] = harga
        state["view"] = VIEW_HARGA_MENU
        state["ctx"] = {}

    await render_order(client, callback, state)
    await callback.answer("Harga diset ✅")


@bot.on_callback_query(filters.regex(r"^destinasi$"))
async def buka_destinasi(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    lk = ensure_state_lock(state)
    async with lk:
        if not is_all_prices_done(state.get("items", {}), state.get("prices", {})):
            await callback.answer("Sila lengkapkan harga dulu.", show_alert=True)
            return

        push_history(state, prev_view=VIEW_HARGA_MENU, prev_ctx=state.get("ctx", {}) or {}, undo=None)
        state["view"] = VIEW_DEST
        state["ctx"] = {}

    await render_order(client, callback, state)
    await callback.answer("Pilih destinasi")


@bot.on_callback_query(filters.regex(r"^setdest_"))
async def set_destinasi(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    try:
        idx = int(callback.data.replace("setdest_", "", 1))
        dest = DEST_LIST[idx]
    except Exception:
        await callback.answer("Destinasi tidak sah.", show_alert=True)
        return

    lk = ensure_state_lock(state)
    async with lk:
        prev_dest = state.get("dest")
        prev_ship = state.get("ship_cost")
        push_history(
            state,
            prev_view=VIEW_DEST,
            prev_ctx=state.get("ctx", {}) or {},
            undo={"type": "set_dest", "prev_dest": prev_dest, "prev_ship_cost": prev_ship}
        )

        state["dest"] = dest
        state["ship_cost"] = None
        state["view"] = VIEW_AFTER_DEST
        state["ctx"] = {}

    await render_order(client, callback, state)
    await callback.answer(f"Destinasi: {dest}")


@bot.on_callback_query(filters.regex(r"^kos_transport$"))
async def buka_kos_transport_keypad(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    lk = ensure_state_lock(state)
    async with lk:
        if not state.get("dest"):
            await callback.answer("Sila pilih DESTINASI dulu.", show_alert=True)
            return

        push_history(state, prev_view=state.get("view", VIEW_AFTER_DEST), prev_ctx=state.get("ctx", {}) or {}, undo=None)
        state["view"] = VIEW_KOS_INPUT
        state["ctx"] = {"num_buf": ""}

    await render_order(client, callback, state)
    await callback.answer("Masukkan kos transport")


@bot.on_callback_query(filters.regex(rf"^{KOS_PREFIX}_[0-9]$"))
async def kos_digit(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    lk = ensure_state_lock(state)
    async with lk:
        if state.get("view") != VIEW_KOS_INPUT:
            await callback.answer("Bukan halaman kos.", show_alert=True)
            return

        digit = callback.data.split("_", 1)[1]
        ctx = state.get("ctx", {}) or {}
        buf = (ctx.get("num_buf") or "")

        if len(buf) >= MAX_NUM_DIGITS:
            await callback.answer("Digit sudah maksimum.", show_alert=True)
            return

        ctx["num_buf"] = buf + digit
        state["ctx"] = ctx

    await render_order(client, callback, state)
    await callback.answer()


@bot.on_callback_query(filters.regex(rf"^{KOS_PREFIX}_back$"))
async def kos_backspace_or_cancel(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    lk = ensure_state_lock(state)
    async with lk:
        if state.get("view") != VIEW_KOS_INPUT:
            await callback.answer("Bukan halaman kos.", show_alert=True)
            return

        ctx = state.get("ctx", {}) or {}
        buf = (ctx.get("num_buf") or "")
        if buf:
            ctx["num_buf"] = buf[:-1]
            state["ctx"] = ctx
            action = "Padam 1 digit"
        else:
            if pop_history_restore(state):
                action = "Kembali"
            else:
                await callback.answer("Tiada langkah untuk undur.", show_alert=True)
                return

    await render_order(client, callback, state)
    await callback.answer(action)


@bot.on_callback_query(filters.regex(rf"^{KOS_PREFIX}_ok$"))
async def kos_okey_set(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not await deny_if_locked(state, callback):
        return

    lk = ensure_state_lock(state)
    async with lk:
        if state.get("view") != VIEW_KOS_INPUT:
            await callback.answer("Bukan halaman kos.", show_alert=True)
            return

        ctx = state.get("ctx", {}) or {}
        buf = (ctx.get("num_buf") or "").strip()

        if not buf:
            await callback.answer("Sila masukkan nombor kos.", show_alert=True)
            return

        try:
            kos = int(buf)
        except Exception:
            await callback.answer("Kos tidak sah.", show_alert=True)
            return

        prev_cost = state.get("ship_cost")
        push_history(
            state,
            prev_view=VIEW_KOS_INPUT,
            prev_ctx=dict(ctx),
            undo={"type": "set_ship_cost", "prev": prev_cost}
        )

        state["ship_cost"] = kos
        state["view"] = VIEW_AFTER_COST
        state["ctx"] = {}

    await render_order(client, callback, state)
    await callback.answer("Kos diset ✅")


@bot.on_callback_query(filters.regex(r"^last_submit$"))
async def last_submit(client, callback):
    msg = callback.message
    state = resolve_state_by_msg_id(msg.id)

    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    lk = ensure_state_lock(state)
    async with lk:
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
            await callback.answer("Kos transport belum dipilih.", show_alert=True)
            return

        state["locked"] = True
        state.setdefault("receipts", [])
        state.setdefault("paid", False)
        state.setdefault("paid_at", None)
        state.setdefault("paid_by", None)

        # reset view/history
        state["view"] = VIEW_AWAL
        state["ctx"] = {}
        state["history"] = []

        # reset pin modes
        state["pin_mode"] = False
        state["pin_active_user"] = None
        state["pin_buffer"] = ""
        state["pin_tries"] = 0

        state["sp_mode"] = False
        state["sp_active_user"] = None
        state["sp_buffer"] = ""
        state["sp_tries"] = 0

        state["album_msg_ids"] = None
        state["control_msg_id"] = None
        state["anchor_msg_id"] = msg.id

    await callback.answer("Last submit ✅")

    caption_baru = build_caption(
        state["base_caption"],
        state.get("items", {}),
        state.get("prices", {}),
        state.get("dest"),
        state.get("ship_cost"),
        locked=True,
        receipts_count=len(state.get("receipts", [])),
        paid=False,
        state=state,
    )

    try:
        await tg_call(msg.edit_caption, caption=caption_baru, reply_markup=None)
        state["anchor_msg_id"] = msg.id
        unregister_state(state)
        register_state(msg.id, state)
    except Exception:
        await disable_old_message_buttons(msg)
        new_msg = await tg_call(client.send_photo, chat_id=state["chat_id"], photo=state["photo_id"], caption=caption_baru)
        state["anchor_msg_id"] = new_msg.id
        unregister_state(state)
        register_state(new_msg.id, state)


# ================= PAYMENT SETTLE (PASSWORD FLOW) =================
async def do_payment_settle_after_pin(client: Client, callback, state: Dict[str, Any]):
    receipts = state.get("receipts") or []
    if not receipts:
        await callback.answer("Tiada resit. Sila upload resit dulu.", show_alert=True)
        return

    # ✅ NO OCR: terus mark PAID & rebuild album
    await callback.answer("Settle bayaran...")

    tz = pytz.timezone("Asia/Kuala_Lumpur")
    now = datetime.now(tz)
    state["paid"] = True
    state["paid_at"] = now.strftime("%d/%m/%Y %I:%M%p").lower()
    state["paid_by"] = callback.from_user.id if callback.from_user else None

    state["pin_mode"] = False
    state["pin_active_user"] = None
    state["pin_buffer"] = ""
    state["pin_tries"] = 0

    await rebuild_album_now(client, state)


@bot.on_callback_query(filters.regex(r"^pay_settle$"))
async def pay_settle_password_start(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)

    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return
    if not state.get("locked"):
        await callback.answer("Sila LAST SUBMIT dulu.", show_alert=True)
        return
    if state.get("paid"):
        await callback.answer("Order ini sudah PAID ✅", show_alert=True)
        return

    user_id = callback.from_user.id if callback.from_user else None
    if not user_id:
        await callback.answer("User tidak sah.", show_alert=True)
        return

    active = state.get("pin_active_user")
    if active and active != user_id:
        await callback.answer("Keypad sedang digunakan oleh user lain.", show_alert=True)
        return

    state["pin_mode"] = True
    state["pin_active_user"] = user_id
    state["pin_buffer"] = ""
    state["pin_tries"] = 0

    try:
        await tg_call(
            callback.message.edit_text,
            pin_prompt_text("Sila masukkan PASSWORD untuk PAYMENT SETTLE", state["pin_buffer"]),
            reply_markup=build_pin_keyboard("pin")
        )
    except Exception:
        pass

    await callback.answer("Masukkan password")


@bot.on_callback_query(filters.regex(r"^pin_[0-9]$"))
async def pin_press_digit(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not state or not state.get("pin_mode"):
        await callback.answer("Sila tekan PAYMENT SETTLE dulu.", show_alert=True)
        return
    user_id = callback.from_user.id if callback.from_user else None
    if state.get("pin_active_user") != user_id:
        await callback.answer("Ini bukan keypad anda.", show_alert=True)
        return

    digit = callback.data.split("_", 1)[1]
    buf = state.get("pin_buffer", "")
    if len(buf) >= max(4, len(PAYMENT_PIN)):
        await callback.answer("PIN sudah cukup, tekan OKEY.", show_alert=True)
        return

    state["pin_buffer"] = buf + digit
    try:
        await tg_call(
            callback.message.edit_text,
            pin_prompt_text("Sila masukkan PASSWORD untuk PAYMENT SETTLE", state["pin_buffer"]),
            reply_markup=build_pin_keyboard("pin")
        )
    except Exception:
        pass
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^pin_back$"))
async def pin_back(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return
    user_id = callback.from_user.id if callback.from_user else None
    if state.get("pin_active_user") and state.get("pin_active_user") != user_id:
        await callback.answer("Ini bukan keypad anda.", show_alert=True)
        return

    state["pin_mode"] = False
    state["pin_active_user"] = None
    state["pin_buffer"] = ""
    state["pin_tries"] = 0

    try:
        await tg_call(callback.message.edit_text, TXT_PAYMENT_CONTROL, reply_markup=build_payment_keyboard())
    except Exception:
        pass
    await callback.answer("Kembali")


@bot.on_callback_query(filters.regex(r"^pin_ok$"))
async def pin_ok(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not state or not state.get("pin_mode"):
        await callback.answer("Sila tekan PAYMENT SETTLE dulu.", show_alert=True)
        return
    user_id = callback.from_user.id if callback.from_user else None
    if state.get("pin_active_user") != user_id:
        await callback.answer("Ini bukan keypad anda.", show_alert=True)
        return

    buf = state.get("pin_buffer", "")
    if not buf:
        await callback.answer("PIN kosong. Sila tekan nombor.", show_alert=True)
        return

    if buf == PAYMENT_PIN:
        await do_payment_settle_after_pin(client, callback, state)
        return

    state["pin_tries"] = int(state.get("pin_tries", 0)) + 1
    state["pin_buffer"] = ""

    if state["pin_tries"] >= MAX_PIN_TRIES:
        state["pin_mode"] = False
        state["pin_active_user"] = None
        state["pin_tries"] = 0
        state["pin_buffer"] = ""
        try:
            await tg_call(
                callback.message.edit_text,
                "❌ Password salah terlalu banyak kali.\n\n" + TXT_PAYMENT_CONTROL,
                reply_markup=build_payment_keyboard()
            )
        except Exception:
            pass
        await callback.answer("Salah banyak kali. Reset.", show_alert=True)
        return

    try:
        await tg_call(
            callback.message.edit_text,
            "❌ Password salah. Cuba lagi.\n\n" + pin_prompt_text("Sila masukkan PASSWORD untuk PAYMENT SETTLE", ""),
            reply_markup=build_pin_keyboard("pin")
        )
    except Exception:
        pass
    await callback.answer("Password salah", show_alert=True)


# ================= SEMAK BAYARAN (AUTH + PIN + MOVE CHANNEL) =================
def is_semak_allowed(user_id: Optional[int]) -> bool:
    if not user_id:
        return False
    if not SEMAK_ALLOWED_IDS:
        return True
    return user_id in SEMAK_ALLOWED_IDS


async def back_to_semak_page(callback, state: Dict[str, Any]):
    try:
        await tg_call(callback.message.edit_text, TXT_SEMAK_CONTROL, reply_markup=build_semak_keyboard())
    except Exception:
        pass


@bot.on_callback_query(filters.regex(r"^semak_bayaran$"))
async def semak_bayaran_start_pin(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)

    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    user_id = callback.from_user.id if callback.from_user else None
    if not is_semak_allowed(user_id):
        await callback.answer("❌ Anda tidak dibenarkan tekan butang ini.", show_alert=True)
        return

    if not (state.get("receipts") or []):
        await callback.answer("Tiada resit untuk disemak.", show_alert=True)
        return

    active = state.get("sp_active_user")
    if active and active != user_id:
        await callback.answer("Keypad sedang digunakan oleh user lain.", show_alert=True)
        return

    state["sp_mode"] = True
    state["sp_active_user"] = user_id
    state["sp_buffer"] = ""
    state["sp_tries"] = 0

    try:
        await tg_call(
            callback.message.edit_text,
            semak_pin_prompt_text(state["sp_buffer"]),
            reply_markup=build_pin_keyboard("sp")
        )
    except Exception:
        pass

    await callback.answer("Masukkan password")


@bot.on_callback_query(filters.regex(r"^sp_[0-9]$"))
async def sp_press_digit(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not state or not state.get("sp_mode"):
        await callback.answer("Sila tekan BUTANG SEMAK BAYARAN dulu.", show_alert=True)
        return

    user_id = callback.from_user.id if callback.from_user else None
    if state.get("sp_active_user") != user_id:
        await callback.answer("Ini bukan keypad anda.", show_alert=True)
        return

    digit = callback.data.split("_", 1)[1]
    buf = state.get("sp_buffer", "")
    if len(buf) >= max(4, len(SEMAK_PIN)):
        await callback.answer("PIN sudah cukup, tekan OKEY.", show_alert=True)
        return

    state["sp_buffer"] = buf + digit
    try:
        await tg_call(
            callback.message.edit_text,
            semak_pin_prompt_text(state["sp_buffer"]),
            reply_markup=build_pin_keyboard("sp")
        )
    except Exception:
        pass
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^sp_back$"))
async def sp_back(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not state:
        await callback.answer("Rekod tidak dijumpai.", show_alert=True)
        return

    user_id = callback.from_user.id if callback.from_user else None
    if state.get("sp_active_user") and state.get("sp_active_user") != user_id:
        await callback.answer("Ini bukan keypad anda.", show_alert=True)
        return

    state["sp_mode"] = False
    state["sp_active_user"] = None
    state["sp_buffer"] = ""
    state["sp_tries"] = 0

    await back_to_semak_page(callback, state)
    await callback.answer("Kembali")


@bot.on_callback_query(filters.regex(r"^sp_ok$"))
async def sp_ok_move(client, callback):
    state = resolve_state_by_msg_id(callback.message.id)
    if not state or not state.get("sp_mode"):
        await callback.answer("Sila tekan BUTANG SEMAK BAYARAN dulu.", show_alert=True)
        return

    user_id = callback.from_user.id if callback.from_user else None
    if state.get("sp_active_user") != user_id:
        await callback.answer("Ini bukan keypad anda.", show_alert=True)
        return

    buf = (state.get("sp_buffer", "") or "").strip()
    if not buf:
        await callback.answer("PIN kosong. Sila tekan nombor.", show_alert=True)
        return

    if buf != SEMAK_PIN:
        state["sp_tries"] = int(state.get("sp_tries", 0)) + 1
        state["sp_buffer"] = ""
        if state["sp_tries"] >= MAX_PIN_TRIES:
            state["sp_mode"] = False
            state["sp_active_user"] = None
            state["sp_tries"] = 0
            state["sp_buffer"] = ""
            await back_to_semak_page(callback, state)
            await callback.answer("❌ Salah banyak kali. Reset.", show_alert=True)
            return

        try:
            await tg_call(
                callback.message.edit_text,
                "❌ Password salah. Cuba lagi.\n\n" + semak_pin_prompt_text(""),
                reply_markup=build_pin_keyboard("sp")
            )
        except Exception:
            pass
        await callback.answer("Password salah", show_alert=True)
        return

    await callback.answer("Proses pindah ke channel...")

    try:
        # check akses channel
        try:
            await tg_call(client.get_chat, OFFICIAL_CHANNEL_ID)
        except Exception as e:
            await tg_call(
                client.send_message,
                chat_id=state["chat_id"],
                text=f"❌ DEBUG: Bot tak dapat akses channel OFFICIAL_CHANNEL_ID={OFFICIAL_CHANNEL_ID}\n{type(e).__name__}: {e}"
            )
            await back_to_semak_page(callback, state)
            return

        # ✅ NO OCR: terus move album
        state["sp_mode"] = False
        state["sp_active_user"] = None
        state["sp_buffer"] = ""
        state["sp_tries"] = 0

        try:
            await copy_album_to_channel(client, state)
        except Exception as e:
            await tg_call(
                client.send_message,
                chat_id=state["chat_id"],
                text=f"❌ DEBUG: Gagal hantar ke channel OFFICIAL_CHANNEL_ID={OFFICIAL_CHANNEL_ID}\n{type(e).__name__}: {e}"
            )
            await back_to_semak_page(callback, state)
            return

        # delete dalam group
        try:
            await delete_bundle(client, state)
        except Exception as e:
            await tg_call(
                client.send_message,
                chat_id=state["chat_id"],
                text=f"⚠️ DEBUG: Hantar channel berjaya, tapi gagal delete dalam group.\nPastikan bot admin group + Delete messages ON.\n{type(e).__name__}: {e}"
            )

        unregister_state(state)
        return

    except Exception as e:
        try:
            tb = traceback.format_exc()
            await tg_call(
                client.send_message,
                chat_id=state["chat_id"],
                text=f"❌ DEBUG CRASH sp_ok_move\n{type(e).__name__}: {e}\n\n{tb[-1500:]}"
            )
        except Exception:
            pass
        await back_to_semak_page(callback, state)


# ================= PHOTO HANDLER =================
@bot.on_message(filters.photo & ~filters.bot)
async def handle_photo(client, message):
    chat_id = message.chat.id

    # ====== Kalau reply pada album/control: dianggap upload resit ======
    if message.reply_to_message:
        replied_id = message.reply_to_message.id

        control_id = None
        state = None

        # direct
        if replied_id in ORDER_STATE:
            state = ORDER_STATE.get(replied_id)
            control_id = replied_id
        # reply pada album photo -> map ke control id
        elif replied_id in REPLY_MAP:
            control_id = REPLY_MAP[replied_id]
            state = ORDER_STATE.get(control_id)

        # fallback resolver
        if not state:
            state = resolve_state_by_msg_id(replied_id)

        if state and state.get("locked"):
            # delete gambar resit dalam group (kemas)
            try:
                await tg_call(message.delete)
            except Exception:
                pass

            lk = ensure_state_lock(state)
            async with lk:
                state.setdefault("receipts", [])
                state["receipts"].append(message.photo.file_id)

                # kalau dah paid, bila tambah resit -> reset paid supaya semak semula
                if state.get("paid"):
                    state["paid"] = False
                    state["paid_at"] = None
                    state["paid_by"] = None

            # ✅ debounce rebuild: tak rebuild setiap resit (anti floodwait)
            schedule_rebuild_album(client, state)
            return

    # ====== Jika bukan reply: ini order baru ======
    photo_id = message.photo.file_id

    tz = pytz.timezone("Asia/Kuala_Lumpur")
    now = datetime.now(tz)

    hari = ["Isnin", "Selasa", "Rabu", "Khamis", "Jumaat", "Sabtu", "Ahad"][now.weekday()]
    tarikh = f"{now.day}/{now.month}/{now.year}"
    jam = now.strftime("%I:%M%p").lower()
    base_caption = f"{hari} | {tarikh} | {jam}"

    try:
        await tg_call(message.delete)
    except (MessageDeleteForbidden, ChatAdminRequired):
        pass
    except Exception:
        pass

    sent = await tg_call(
        client.send_photo,
        chat_id=chat_id,
        photo=photo_id,
        caption=bold(base_caption),
        reply_markup=build_awal_keyboard()
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
        "receipts_album": [],
        "paid": False,
        "paid_at": None,
        "paid_by": None,
        "locked": False,

        "anchor_msg_id": sent.id,
        "album_msg_ids": None,
        "control_msg_id": None,

        "view": VIEW_AWAL,
        "ctx": {},
        "history": [],

        "pin_mode": False,
        "pin_active_user": None,
        "pin_buffer": "",
        "pin_tries": 0,

        "sp_mode": False,
        "sp_active_user": None,
        "sp_buffer": "",
        "sp_tries": 0,

        "_lock": asyncio.Lock(),
        "_rebuild_task": None,
    }


if __name__ == "__main__":
    bot.run()

