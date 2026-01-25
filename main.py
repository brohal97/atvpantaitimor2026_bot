import os, asyncio, traceback
from datetime import datetime
from typing import Dict, Any, Optional, Set

import pytz
from pyrogram import Client, filters
from pyrogram.errors import FloodWait, RPCError, MessageDeleteForbidden, ChatAdminRequired
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ForceReply, InputMediaPhoto
)

# ================= ENV =================
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

OFFICIAL_CHANNEL_ID = int(os.getenv("OFFICIAL_CHANNEL_ID", "-1003573894188"))

PAYMENT_PIN = os.getenv("PAYMENT_PIN", "1234").strip()
SEMAK_PIN = os.getenv("SEMAK_PIN", "4321").strip()
MAX_PIN_TRIES = 5

SEMAK_ALLOWED_IDS_RAW = os.getenv("SEMAK_ALLOWED_IDS", "1150078068").strip()

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Missing API_ID / API_HASH / BOT_TOKEN")
if not OFFICIAL_CHANNEL_ID:
    raise RuntimeError("Missing OFFICIAL_CHANNEL_ID")

def parse_allowed_ids(raw: str) -> Set[int]:
    out: Set[int] = set()
    if not raw:
        return out
    for p in raw.split(","):
        p = p.strip()
        if p:
            try: out.add(int(p))
            except: pass
    return out

SEMAK_ALLOWED_IDS = parse_allowed_ids(SEMAK_ALLOWED_IDS_RAW)

# ================= BOT =================
bot = Client("atv_bot_simple", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

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

MAX_RECEIPTS = 9

# ================= STATE =================
# key: order_msg_id (photo order)
STATE: Dict[int, Dict[str, Any]] = {}

# ================= SAFE TG CALL =================
async def tg_call(fn, *args, **kwargs):
    retry = 0
    while True:
        try:
            return await fn(*args, **kwargs)
        except FloodWait as e:
            await asyncio.sleep(int(getattr(e, "value", 1)) + 1)
        except RPCError:
            retry += 1
            if retry >= 5:
                raise
            await asyncio.sleep(0.2 * retry)

async def fast_answer(cb, text: str = "", alert: bool = False):
    try:
        await cb.answer(text or "", show_alert=alert)
    except:
        pass

# ================= TEXT =================
def now_stamp() -> str:
    tz = pytz.timezone("Asia/Kuala_Lumpur")
    now = datetime.now(tz)
    hari = ["Isnin", "Selasa", "Rabu", "Khamis", "Jumaat", "Sabtu", "Ahad"][now.weekday()]
    tarikh = f"{now.day}/{now.month}/{now.year}"
    jam = now.strftime("%I:%M%p").lower()
    return f"{hari} | {tarikh} | {jam}"

def build_caption(st: Dict[str, Any], locked: bool = False, paid: bool = False) -> str:
    lines = [st["base"]]

    # items
    for k, v in st.get("items", {}).items():
        nama = PRODUK_LIST.get(k, k)
        harga = st.get("prices", {}).get(k)
        harga_str = "-" if harga is None else f"RM{int(harga)}"
        lines.append(f"{nama} | {v} | {harga_str}")

    # dest + ship
    if st.get("dest"):
        if st.get("ship_cost") is None:
            lines.append(f"Destinasi : {st['dest']}")
        else:
            lines.append(f"Destinasi : {st['dest']} | RM{int(st['ship_cost'])}")

    # total
    if st.get("items") and st.get("prices") and st.get("ship_cost") is not None:
        if all(k in st["prices"] for k in st["items"].keys()):
            total_prod = sum(int(st["prices"][k]) for k in st["items"].keys())
            total_all = total_prod + int(st["ship_cost"])
            lines.append(f"TOTAL KESELURUHAN : RM{total_all}")

    if locked:
        lines.append("")
        if paid:
            paid_at = st.get("paid_at") or ""
            lines.append(f"✅ PAID {paid_at}".strip())
        if len(st.get("receipts", [])) == 0:
            lines.append("⬅️ SLIDE KIRI UPLOAD RESIT (reply sini)")
        else:
            lines.append("⬅️ SLIDE KIRI TAMBAH RESIT (reply sini)")

    cap = "\n".join(lines)
    return cap[:1024]

# ================= KEYBOARDS =================
def kb_produk(st: Dict[str, Any]) -> InlineKeyboardMarkup:
    rows = []
    for k, name in PRODUK_LIST.items():
        rows.append([InlineKeyboardButton(name, callback_data=f"p_{k}")])
    rows.append([InlineKeyboardButton("✅ SET DESTINASI", callback_data="dest")])
    rows.append([InlineKeyboardButton("🔒 LOCK ORDER", callback_data="lock")])
    return InlineKeyboardMarkup(rows)

def kb_qty(produk_key: str) -> InlineKeyboardMarkup:
    rows = []
    nums = list(range(1, 16))
    for i in range(0, len(nums), 3):
        chunk = nums[i:i+3]
        rows.append([InlineKeyboardButton(str(n), callback_data=f"q_{produk_key}_{n}") for n in chunk])
    rows.append([InlineKeyboardButton("🔙 BACK", callback_data="back_produk")])
    return InlineKeyboardMarkup(rows)

def kb_dest() -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(DEST_LIST), 2):
        left = InlineKeyboardButton(DEST_LIST[i], callback_data=f"d_{i}")
        if i+1 < len(DEST_LIST):
            right = InlineKeyboardButton(DEST_LIST[i+1], callback_data=f"d_{i+1}")
            rows.append([left, right])
        else:
            rows.append([left])
    rows.append([InlineKeyboardButton("🔙 BACK", callback_data="back_produk")])
    return InlineKeyboardMarkup(rows)

def kb_lock_controls(paid: bool) -> InlineKeyboardMarkup:
    if not paid:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("PAYMENT SETTLE", callback_data="pay")],
            [InlineKeyboardButton("🔓 UNLOCK (edit balik)", callback_data="unlock")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("BUTANG SEMAK BAYARAN", callback_data="semak")],
    ])

def kb_pin(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1", callback_data=f"{prefix}_1"),
         InlineKeyboardButton("2", callback_data=f"{prefix}_2"),
         InlineKeyboardButton("3", callback_data=f"{prefix}_3")],
        [InlineKeyboardButton("4", callback_data=f"{prefix}_4"),
         InlineKeyboardButton("5", callback_data=f"{prefix}_5"),
         InlineKeyboardButton("6", callback_data=f"{prefix}_6")],
        [InlineKeyboardButton("7", callback_data=f"{prefix}_7"),
         InlineKeyboardButton("8", callback_data=f"{prefix}_8"),
         InlineKeyboardButton("9", callback_data=f"{prefix}_9")],
        [InlineKeyboardButton("0", callback_data=f"{prefix}_0")],
        [InlineKeyboardButton("🔙 BACK", callback_data=f"{prefix}_back"),
         InlineKeyboardButton("✅ OKEY", callback_data=f"{prefix}_ok")],
    ])

# ================= HELPERS =================
def get_order_id_from_message(msg) -> Optional[int]:
    # order is the photo message itself (anchor)
    if msg and msg.id in STATE:
        return msg.id
    # if user clicks buttons on the photo message -> msg.id is order id
    # if other message, ignore
    return None

async def ask_text(client: Client, chat_id: int, prompt: str, order_id: int, field: str):
    sent = await tg_call(client.send_message, chat_id=chat_id, text=prompt,
                         reply_markup=ForceReply(selective=True))
    STATE[order_id]["await"] = {"msg_id": sent.id, "field": field}

# ================= START ORDER (photo) =================
@bot.on_message(filters.photo & ~filters.bot)
async def on_new_order(client, message):
    chat_id = message.chat.id
    photo_id = message.photo.file_id

    # try delete original photo to keep group clean
    try:
        await tg_call(message.delete)
    except (MessageDeleteForbidden, ChatAdminRequired):
        pass
    except:
        pass

    base = now_stamp()

    order_msg = await tg_call(
        client.send_photo,
        chat_id=chat_id,
        photo=photo_id,
        caption=base,
        reply_markup=kb_produk({})
    )

    STATE[order_msg.id] = {
        "chat_id": chat_id,
        "photo_id": photo_id,
        "base": base,
        "items": {},
        "prices": {},
        "dest": None,
        "ship_cost": None,
        "receipts": [],
        "locked": False,
        "paid": False,
        "paid_at": None,
        "await": None,         # force reply waiting
        "pin": None,           # {"mode":"pay/semak","buf":"","tries":0,"user":id,"msg_id":...}
    }

# ================= FORCE REPLY INPUT =================
@bot.on_message(filters.text & ~filters.bot)
async def on_text_reply(client, message):
    if not message.reply_to_message:
        return

    # find which order waiting
    for order_id, st in list(STATE.items()):
        aw = st.get("await")
        if not aw:
            continue
        if aw.get("msg_id") == message.reply_to_message.id and st["chat_id"] == message.chat.id:
            field = aw.get("field")
            txt = (message.text or "").strip()

            # cleanup user text + prompt msg
            try: await tg_call(message.delete)
            except: pass
            try: await tg_call(client.delete_messages, message.chat.id, aw["msg_id"])
            except: pass

            st["await"] = None

            # parse
            try:
                val = int("".join([c for c in txt if c.isdigit()]))
            except:
                await tg_call(client.send_message, message.chat.id, "❌ Input tak sah. Sila cuba semula.")
                return

            if field.startswith("price:"):
                pk = field.split(":", 1)[1]
                st["prices"][pk] = val
            elif field == "ship_cost":
                st["ship_cost"] = val

            # render update ONCE sahaja
            cap = build_caption(st, locked=False, paid=st["paid"])
            await tg_call(client.edit_message_caption, st["chat_id"], order_id, caption=cap, reply_markup=kb_produk(st))

            return

# ================= CALLBACKS (simple, low edit) =================
@bot.on_callback_query()
async def on_cb(client, cb):
    await fast_answer(cb)  # spinner off
    msg = cb.message
    data = cb.data

    order_id = get_order_id_from_message(msg)
    if not order_id:
        return

    st = STATE.get(order_id)
    if not st:
        return

    if data == "back_produk":
        if st["locked"]:
            return
        cap = build_caption(st, locked=False, paid=st["paid"])
        await tg_call(msg.edit_caption, caption=cap, reply_markup=kb_produk(st))
        return

    if data.startswith("p_"):
        if st["locked"]:
            return
        pk = data.split("_", 1)[1]
        # go qty menu (no caption edit needed, just keyboard)
        await tg_call(msg.edit_reply_markup, reply_markup=kb_qty(pk))
        return

    if data.startswith("q_"):
        if st["locked"]:
            return
        _, pk, q = data.split("_", 2)
        qty = int(q)
        st["items"][pk] = qty

        # ask price via ForceReply (NO keypad = super laju)
        await ask_text(client, st["chat_id"], f"Masukkan HARGA untuk {PRODUK_LIST.get(pk, pk)} (contoh 2500):",
                       order_id, f"price:{pk}")

        # render once (caption) and back to produk keyboard
        cap = build_caption(st, locked=False, paid=st["paid"])
        await tg_call(msg.edit_caption, caption=cap, reply_markup=kb_produk(st))
        return

    if data == "dest":
        if st["locked"]:
            return
        await tg_call(msg.edit_reply_markup, reply_markup=kb_dest())
        return

    if data.startswith("d_"):
        if st["locked"]:
            return
        idx = int(data.split("_", 1)[1])
        st["dest"] = DEST_LIST[idx]
        st["ship_cost"] = None

        await ask_text(client, st["chat_id"], f"Masukkan KOS TRANSPORT untuk {st['dest']} (contoh 150):",
                       order_id, "ship_cost")

        cap = build_caption(st, locked=False, paid=st["paid"])
        await tg_call(msg.edit_caption, caption=cap, reply_markup=kb_produk(st))
        return

    if data == "lock":
        # validate minimal
        if not st["items"]:
            await fast_answer(cb, "Sila pilih produk dulu.", True)
            return
        if not all(k in st["prices"] for k in st["items"].keys()):
            await fast_answer(cb, "Harga belum lengkap.", True)
            return
        if not st["dest"] or st["ship_cost"] is None:
            await fast_answer(cb, "Destinasi / kos belum lengkap.", True)
            return

        st["locked"] = True
        cap = build_caption(st, locked=True, paid=False)
        await tg_call(msg.edit_caption, caption=cap, reply_markup=kb_lock_controls(False))
        return

    if data == "unlock":
        st["locked"] = False
        st["paid"] = False
        st["paid_at"] = None
        cap = build_caption(st, locked=False, paid=False)
        await tg_call(msg.edit_caption, caption=cap, reply_markup=kb_produk(st))
        return

    # ===== PIN FLOW (PAY / SEMAK) =====
    if data == "pay":
        if not st["locked"]:
            await fast_answer(cb, "Lock dulu.", True)
            return
        if len(st["receipts"]) == 0:
            await fast_answer(cb, "Upload resit dulu (reply pada ORDER).", True)
            return

        st["pin"] = {"mode": "pay", "buf": "", "tries": 0, "user": cb.from_user.id, "msg_id": msg.id}
        await tg_call(msg.edit_text, "🔐 Masukkan PASSWORD untuk PAYMENT SETTLE\n\nPIN: (kosong)", reply_markup=kb_pin("paypin"))
        return

    if data == "semak":
        # only allowed
        uid = cb.from_user.id if cb.from_user else None
        if SEMAK_ALLOWED_IDS and uid not in SEMAK_ALLOWED_IDS:
            await fast_answer(cb, "❌ Anda tidak dibenarkan.", True)
            return
        if len(st["receipts"]) == 0:
            await fast_answer(cb, "Tiada resit.", True)
            return

        st["pin"] = {"mode": "semak", "buf": "", "tries": 0, "user": uid, "msg_id": msg.id}
        await tg_call(msg.edit_text, "🔐 ISI PASSWORD JIKA BAYARAN TELAH DISEMAK\n\nPIN: (kosong)", reply_markup=kb_pin("sp"))
        return

    # digit pin
    if data.startswith("paypin_") or data.startswith("sp_"):
        pin = st.get("pin")
        if not pin:
            return
        if pin.get("user") != (cb.from_user.id if cb.from_user else None):
            await fast_answer(cb, "Ini bukan keypad anda.", True)
            return

        prefix = "paypin_" if data.startswith("paypin_") else "sp_"
        action = data.replace(prefix, "", 1)

        if action.isdigit():
            if len(pin["buf"]) < 8:
                pin["buf"] += action
        elif action == "back":
            pin["buf"] = pin["buf"][:-1]
        elif action == "ok":
            entered = pin["buf"].strip()
            true_pin = PAYMENT_PIN if pin["mode"] == "pay" else SEMAK_PIN

            if entered != true_pin:
                pin["tries"] += 1
                pin["buf"] = ""
                if pin["tries"] >= MAX_PIN_TRIES:
                    st["pin"] = None
                    await tg_call(msg.edit_text, "❌ Salah banyak kali. Reset.", reply_markup=None)
                    # return to order card
                    cap = build_caption(st, locked=True, paid=st["paid"])
                    await tg_call(client.send_photo, st["chat_id"], st["photo_id"], caption=cap, reply_markup=kb_lock_controls(st["paid"]))
                    return
            else:
                # success
                if pin["mode"] == "pay":
                    tz = pytz.timezone("Asia/Kuala_Lumpur")
                    now = datetime.now(tz)
                    st["paid"] = True
                    st["paid_at"] = now.strftime("%d/%m/%Y %I:%M%p").lower()
                    st["pin"] = None

                    # back to order card
                    cap = build_caption(st, locked=True, paid=True)
                    await tg_call(client.send_photo, st["chat_id"], st["photo_id"], caption=cap, reply_markup=kb_lock_controls(True))
                    return

                # semak => hantar album ke channel & delete order message
                try:
                    await tg_call(client.get_chat, OFFICIAL_CHANNEL_ID)
                except Exception as e:
                    st["pin"] = None
                    await tg_call(msg.edit_text, f"❌ Bot tak dapat akses channel.\n{type(e).__name__}: {e}", reply_markup=None)
                    return

                # send album
                caption = build_caption(st, locked=True, paid=True)
                media = [InputMediaPhoto(media=st["photo_id"], caption=caption)]
                for r in st["receipts"][-MAX_RECEIPTS:]:
                    media.append(InputMediaPhoto(media=r))
                await tg_call(client.send_media_group, OFFICIAL_CHANNEL_ID, media=media)

                # delete order card
                try:
                    await tg_call(client.delete_messages, st["chat_id"], order_id)
                except Exception:
                    pass

                STATE.pop(order_id, None)
                return

        # update masked pin text
        masked = "(kosong)" if not pin["buf"] else ("•" * len(pin["buf"]))
        title = "🔐 Masukkan PASSWORD untuk PAYMENT SETTLE" if pin["mode"] == "pay" else "🔐 ISI PASSWORD JIKA BAYARAN TELAH DISEMAK"
        try:
            await tg_call(msg.edit_text, f"{title}\n\nPIN: {masked}", reply_markup=kb_pin(prefix[:-1]))
        except Exception:
            pass

# ================= RECEIPT UPLOAD (reply on order photo) =================
@bot.on_message(filters.photo & ~filters.bot)
async def on_receipt(client, message):
    # if this photo is reply to an order photo, treat as receipt
    if not message.reply_to_message:
        return
    order_id = message.reply_to_message.id
    st = STATE.get(order_id)
    if not st:
        return
    if not st.get("locked"):
        return

    # store receipt
    st.setdefault("receipts", [])
    st["receipts"].append(message.photo.file_id)

    # keep clean
    try:
        await tg_call(message.delete)
    except Exception:
        pass

    # update caption once
    cap = build_caption(st, locked=True, paid=st["paid"])
    try:
        await tg_call(client.edit_message_caption, st["chat_id"], order_id, caption=cap, reply_markup=kb_lock_controls(st["paid"]))
    except Exception:
        pass

# ================= RUN =================
if __name__ == "__main__":
    bot.run()

