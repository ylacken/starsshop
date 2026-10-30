import asyncio
import logging
import os
import re
import secrets
import time

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("starsbot")

# ---------- Конфиг (.env) ----------
BOT_TOKEN = os.environ["BOT_TOKEN"]
MANAGER_LIST = [int(x) for x in os.environ["MANAGER_IDS"].split(",") if x.strip()]
MANAGER_IDS = set(MANAGER_LIST)
NOTIFY_CHAT_ID = int(os.getenv("NOTIFY_CHAT_ID") or MANAGER_LIST[0])
CARD_NUMBER = os.environ["CARD_NUMBER"]
CARD_HOLDER = os.getenv("CARD_HOLDER", "")
PRICE_UAH_PER_STAR = float(os.getenv("PRICE_UAH_PER_STAR", "0.8"))
PACKS = [int(x) for x in os.getenv("PACKS", "50,100,250,500,1000").split(",")]
ORDER_TTL_MIN = int(os.getenv("ORDER_TTL_MIN", "60"))
SUPPORT = os.getenv("SUPPORT_USERNAME", "")
BRAND = os.getenv("BRAND_NAME", "lckn stars")
DB_PATH = os.getenv("DB_PATH", "orders.db")

router = Router()
USERNAME_RE = re.compile(r"^@?([A-Za-z0-9_]{5,32})$")
LANGS = {"uk": "🇺🇦 Українська", "ru": "🇷🇺 Русский", "en": "🇬🇧 English"}
CHOOSE_LANG = "Оберіть мову / Выберите язык / Choose language:"

# ---------- Переводы ----------
TEXTS = {
    "ru": {
        "greeting": "👋 Приветствуем в <b>{brand}</b>!\nДля покупки звёзд нажмите кнопку ниже.",
        "btn_buy": "⭐️ Купить звезды",
        "btn_support": "🧑‍💻 Служба поддержки",
        "support_none": "Контакт поддержки пока не указан.",
        "support_msg": "Если вы захотели связаться с нами, пишите на {s}",
        "btn_write": "Написать",
        "pick_pack": "⭐ Выберите количество звёзд и получателя.\nНачните с выбора пакета:",
        "ask_recipient_btn": "Отправьте @username получателя звёзд или нажмите кнопку.",
        "ask_recipient": "Отправьте @username получателя звёзд.",
        "self_btn": "Себе (@{u})",
        "bad_username": "Неверный username. Пример: @durov",
        "pack_unavailable": "Пакет недоступен",
        "order": (
            "<b>Заказ #{id}</b>\n"
            "⭐ {stars} звёзд для @{rec}\n\n"
            "Переведите <b>{amount} ₴</b> на карту:\n"
            "<code>{card}</code>\n{holder}\n\n"
            "После оплаты нажмите «Я оплатил» и отправьте скриншот чека."
        ),
        "btn_paid": "✅ Я оплатил",
        "btn_cancel": "❌ Отменить",
        "cancelled": "Заказ отменён",
        "cant_cancel": "Нельзя отменить",
        "unavailable": "Заказ уже обработан или недоступен.",
        "send_proof": "Отправьте скриншот чека по заказу #{id} (фото или файлом).",
        "already": "Заказ уже обработан.",
        "proof_sent": "Чек по заказу #{id} отправлен менеджеру. Обычно проверка занимает несколько минут.",
        "proof_wrong": "Отправьте скриншот чека фото или файлом. Для отмены нажмите /start.",
        "confirmed": "✅ Оплата по заказу #{id} подтверждена. Звёзды отправляются.",
        "rejected": "❌ Оплату по заказу #{id} подтвердить не удалось.{support}",
        "support_line": " Напишите в поддержку {s}.",
        "delivered": "🌟 Заказ #{id}: {stars} звёзд отправлено на @{rec}. Спасибо!",
    },
    "uk": {
        "greeting": "👋 Вітаємо в <b>{brand}</b>!\nДля купівлі зірок натисніть кнопку нижче.",
        "btn_buy": "⭐️ Купити зірки",
        "btn_support": "🧑‍💻 Служба підтримки",
        "support_none": "Контакт підтримки поки не вказано.",
        "support_msg": "Якщо ви захотіли зв'язатися з нами, пишіть на {s}",
        "btn_write": "Написати",
        "pick_pack": "⭐ Оберіть кількість зірок і отримувача.\nПочніть з вибору пакета:",
        "ask_recipient_btn": "Надішліть @username отримувача зірок або натисніть кнопку.",
        "ask_recipient": "Надішліть @username отримувача зірок.",
        "self_btn": "Собі (@{u})",
        "bad_username": "Невірний username. Приклад: @durov",
        "pack_unavailable": "Пакет недоступний",
        "order": (
            "<b>Замовлення #{id}</b>\n"
            "⭐ {stars} зірок для @{rec}\n\n"
            "Переведіть <b>{amount} ₴</b> на картку:\n"
            "<code>{card}</code>\n{holder}\n\n"
            "Після оплати натисніть «Я сплатив(ла)» і надішліть скріншот чека."
        ),
        "btn_paid": "✅ Я сплатив(ла)",
        "btn_cancel": "❌ Скасувати",
        "cancelled": "Замовлення скасовано",
        "cant_cancel": "Неможливо скасувати",
        "unavailable": "Замовлення вже оброблено або недоступне.",
        "send_proof": "Надішліть скріншот чека за замовленням #{id} (фото або файлом).",
        "already": "Замовлення вже оброблено.",
        "proof_sent": "Чек за замовленням #{id} надіслано менеджеру. Зазвичай перевірка займає кілька хвилин.",
        "proof_wrong": "Надішліть скріншот чека фото або файлом. Для скасування натисніть /start.",
        "confirmed": "✅ Оплату за замовленням #{id} підтверджено. Зірки надсилаються.",
        "rejected": "❌ Оплату за замовленням #{id} підтвердити не вдалося.{support}",
        "support_line": " Напишіть у підтримку {s}.",
        "delivered": "🌟 Замовлення #{id}: {stars} зірок надіслано на @{rec}. Дякуємо!",
    },
    "en": {
        "greeting": "👋 Welcome to <b>{brand}</b>!\nTo buy stars, tap the button below.",
        "btn_buy": "⭐️ Buy stars",
        "btn_support": "🧑‍💻 Support",
        "support_none": "Support contact is not set yet.",
        "support_msg": "If you'd like to contact us, write to {s}",
        "btn_write": "Write",
        "pick_pack": "⭐ Choose the number of stars and the recipient.\nStart by picking a pack:",
        "ask_recipient_btn": "Send the @username of the stars recipient or tap the button.",
        "ask_recipient": "Send the @username of the stars recipient.",
        "self_btn": "Myself (@{u})",
        "bad_username": "Invalid username. Example: @durov",
        "pack_unavailable": "Pack unavailable",
        "order": (
            "<b>Order #{id}</b>\n"
            "⭐ {stars} stars for @{rec}\n\n"
            "Transfer <b>{amount} ₴</b> to the card:\n"
            "<code>{card}</code>\n{holder}\n\n"
            "After paying, tap “I paid” and send a screenshot of the receipt."
        ),
        "btn_paid": "✅ I paid",
        "btn_cancel": "❌ Cancel",
        "cancelled": "Order cancelled",
        "cant_cancel": "Cannot cancel",
        "unavailable": "The order is already processed or unavailable.",
        "send_proof": "Send a screenshot of the receipt for order #{id} (photo or file).",
        "already": "The order is already processed.",
        "proof_sent": "The receipt for order #{id} was sent to a manager. Checking usually takes a few minutes.",
        "proof_wrong": "Send the receipt screenshot as a photo or file. Press /start to cancel.",
        "confirmed": "✅ Payment for order #{id} confirmed. Stars are being sent.",
        "rejected": "❌ We could not confirm the payment for order #{id}.{support}",
        "support_line": " Contact support {s}.",
        "delivered": "🌟 Order #{id}: {stars} stars sent to @{rec}. Thank you!",
    },
}


def tr(lang: str, key: str, **kw) -> str:
    return TEXTS.get(lang, TEXTS["ru"])[key].format(**kw)


class BuyFlow(StatesGroup):
    waiting_recipient = State()


class ProofFlow(StatesGroup):
    waiting_proof = State()


# ---------- База ----------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                user_name TEXT,
                recipient TEXT NOT NULL,
                stars INTEGER NOT NULL,
                amount_kop INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                proof_file_id TEXT,
                handled_by INTEGER,
                created_at INTEGER NOT NULL,
                paid_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                lang TEXT NOT NULL
            );
            """
        )
        await db.commit()


async def db_exec(sql, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(sql, params)
        await db.commit()
        return cur.rowcount, cur.lastrowid


async def db_one(sql, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(sql, params)
        return await cur.fetchone()


async def db_all(sql, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(sql, params)
        return await cur.fetchall()


async def get_lang(user_id: int):
    r = await db_one("SELECT lang FROM users WHERE user_id=?", (user_id,))
    return r["lang"] if r else None


async def lang_of(user_id: int) -> str:
    return await get_lang(user_id) or "ru"


# ---------- Клавиатуры ----------
def lang_kb(nxt: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=name, callback_data=f"lang:{code}:{nxt}")] for code, name in LANGS.items()]
    )


def menu_kb(lang: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang, "btn_buy"), callback_data="menu_buy")],
            [InlineKeyboardButton(text=tr(lang, "btn_support"), callback_data="support")],
        ]
    )


def packs_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"⭐ {p} — {p * PRICE_UAH_PER_STAR:.2f} ₴", callback_data=f"buy:{p}")]
            for p in PACKS
        ]
    )


def support_line(lang: str) -> str:
    return tr(lang, "support_line", s=SUPPORT) if SUPPORT else ""


# ---------- Команды /start и /stars ----------
@router.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(CHOOSE_LANG, reply_markup=lang_kb("menu"))


@router.message(Command("stars"))
async def cmd_stars(m: Message, state: FSMContext):
    await state.clear()
    lang = await get_lang(m.from_user.id)
    if not lang:
        return await m.answer(CHOOSE_LANG, reply_markup=lang_kb("buy"))
    await m.answer(tr(lang, "pick_pack"), reply_markup=packs_kb())


@router.message(Command("orders"))
async def mgr_orders(m: Message):
    if m.from_user.id not in MANAGER_IDS:
        return
    rows = await db_all("SELECT * FROM orders ORDER BY id DESC LIMIT 15")
    if not rows:
        return await m.answer("Заказов нет.")
    await m.answer("\n".join(f"#{r['id']} {r['status']} — {r['stars']}⭐ → @{r['recipient']}" for r in rows))


@router.message(Command("stats"))
async def mgr_stats(m: Message):
    if m.from_user.id not in MANAGER_IDS:
        return
    r = await db_one(
        "SELECT COUNT(*) n, COALESCE(SUM(stars),0) s, COALESCE(SUM(amount_kop),0) t "
        "FROM orders WHERE status IN ('paid','delivered')"
    )
    await m.answer(f"Оплаченных заказов: {r['n']}\nЗвёзд: {r['s']}\nПолучено: {r['t'] / 100:.2f} ₴")


# ---------- Язык и меню ----------
@router.callback_query(F.data.startswith("lang:"))
async def set_lang(c: CallbackQuery, state: FSMContext):
    _, code, nxt = c.data.split(":")
    if code not in LANGS:
        return await c.answer()
    await db_exec("INSERT OR REPLACE INTO users(user_id, lang) VALUES (?, ?)", (c.from_user.id, code))
    await state.clear()
    try:
        await c.message.delete()
    except Exception:
        pass
    if nxt == "buy":
        await c.message.answer(tr(code, "pick_pack"), reply_markup=packs_kb())
    else:
        await c.message.answer(tr(code, "greeting", brand=BRAND), reply_markup=menu_kb(code))
    await c.answer()


@router.callback_query(F.data == "menu_buy")
async def menu_buy(c: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = await lang_of(c.from_user.id)
    await c.message.answer(tr(lang, "pick_pack"), reply_markup=packs_kb())
    await c.answer()


@router.callback_query(F.data == "support")
async def support_cb(c: CallbackQuery):
    lang = await lang_of(c.from_user.id)
    if SUPPORT:
        handle = SUPPORT if SUPPORT.startswith("@") else "@" + SUPPORT
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=tr(lang, "btn_write"), url=f"https://t.me/{handle.lstrip('@')}")]
            ]
        )
        await c.message.answer(tr(lang, "support_msg", s=handle), reply_markup=kb)
    else:
        await c.message.answer(tr(lang, "support_none"))
    await c.answer()


# ---------- Покупка ----------
@router.callback_query(F.data.startswith("buy:"))
async def choose_pack(c: CallbackQuery, state: FSMContext):
    lang = await lang_of(c.from_user.id)
    stars = int(c.data.split(":")[1])
    if stars not in PACKS:
        return await c.answer(tr(lang, "pack_unavailable"), show_alert=True)
    await state.clear()
    await state.update_data(stars=stars)
    await state.set_state(BuyFlow.waiting_recipient)
    rows = []
    if c.from_user.username:
        rows.append(
            [InlineKeyboardButton(text=tr(lang, "self_btn", u=c.from_user.username), callback_data="self")]
        )
    await c.message.answer(
        tr(lang, "ask_recipient_btn" if rows else "ask_recipient"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None,
    )
    await c.answer()


async def create_order(target: Message, user, recipient: str, stars: int, state: FSMContext):
    lang = await lang_of(user.id)
    amount_kop = int(round(stars * PRICE_UAH_PER_STAR * 100))
    code = "ST" + secrets.token_hex(3).upper()
    _, order_id = await db_exec(
        "INSERT INTO orders(code,user_id,user_name,recipient,stars,amount_kop,created_at) VALUES (?,?,?,?,?,?,?)",
        (code, user.id, f"@{user.username}" if user.username else user.full_name, recipient, stars, amount_kop, int(time.time())),
    )
    await state.clear()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang, "btn_paid"), callback_data=f"paid:{order_id}")],
            [InlineKeyboardButton(text=tr(lang, "btn_cancel"), callback_data=f"cancel:{order_id}")],
        ]
    )
    await target.answer(
        tr(
            lang,
            "order",
            id=order_id,
            stars=stars,
            rec=recipient,
            amount=f"{amount_kop / 100:.2f}",
            card=CARD_NUMBER,
            holder=CARD_HOLDER,
            code=code,
        ),
        reply_markup=kb,
    )


@router.callback_query(F.data == "self", BuyFlow.waiting_recipient)
async def recipient_self(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await create_order(c.message, c.from_user, c.from_user.username, data["stars"], state)
    await c.answer()


@router.message(BuyFlow.waiting_recipient)
async def recipient_input(m: Message, state: FSMContext):
    lang = await lang_of(m.from_user.id)
    match = USERNAME_RE.match((m.text or "").strip())
    if not match:
        return await m.answer(tr(lang, "bad_username"))
    data = await state.get_data()
    await create_order(m, m.from_user, match.group(1), data["stars"], state)


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_order(c: CallbackQuery):
    lang = await lang_of(c.from_user.id)
    n, _ = await db_exec(
        "UPDATE orders SET status='cancelled' WHERE id=? AND user_id=? AND status='pending'",
        (int(c.data.split(":")[1]), c.from_user.id),
    )
    await c.answer(tr(lang, "cancelled" if n else "cant_cancel"), show_alert=True)
    if n:
        await c.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("paid:"))
async def claim_paid(c: CallbackQuery, state: FSMContext):
    lang = await lang_of(c.from_user.id)
    order_id = int(c.data.split(":")[1])
    order = await db_one("SELECT * FROM orders WHERE id=? AND user_id=?", (order_id, c.from_user.id))
    if not order or order["status"] not in ("pending", "expired"):
        return await c.answer(tr(lang, "unavailable"), show_alert=True)
    await state.set_state(ProofFlow.waiting_proof)
    await state.update_data(order_id=order_id)
    await c.message.answer(tr(lang, "send_proof", id=order_id))
    await c.answer()


@router.message(ProofFlow.waiting_proof, F.photo | F.document)
async def got_proof(m: Message, state: FSMContext, bot: Bot):
    lang = await lang_of(m.from_user.id)
    order_id = (await state.get_data())["order_id"]
    is_photo = bool(m.photo)
    file_id = m.photo[-1].file_id if is_photo else m.document.file_id
    n, _ = await db_exec(
        "UPDATE orders SET status='review', proof_file_id=? "
        "WHERE id=? AND user_id=? AND status IN ('pending','expired')",
        (file_id, order_id, m.from_user.id),
    )
    await state.clear()
    if not n:
        return await m.answer(tr(lang, "already"))
    o = await db_one("SELECT * FROM orders WHERE id=?", (order_id,))
    caption = (
        f"🧾 <b>Заказ #{o['id']}</b> на проверку\n"
        f"Покупатель: {o['user_name']} (id {o['user_id']}, язык: {lang})\n"
        f"Звёзд: <b>{o['stars']}</b> → @{o['recipient']}\n"
        f"Сумма: <b>{o['amount_kop'] / 100:.2f} ₴</b>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Оплата пришла", callback_data=f"ok:{o['id']}"),
                InlineKeyboardButton(text="❌ Не пришла", callback_data=f"no:{o['id']}"),
            ]
        ]
    )
    if is_photo:
        await bot.send_photo(NOTIFY_CHAT_ID, file_id, caption=caption, reply_markup=kb)
    else:
        await bot.send_document(NOTIFY_CHAT_ID, file_id, caption=caption, reply_markup=kb)
    await m.answer(tr(lang, "proof_sent", id=order_id))


@router.message(ProofFlow.waiting_proof)
async def proof_wrong(m: Message):
    lang = await lang_of(m.from_user.id)
    await m.answer(tr(lang, "proof_wrong"))


# ---------- Менеджеры ----------
def is_manager(user_id: int) -> bool:
    return user_id in MANAGER_IDS


@router.callback_query(F.data.startswith("ok:"))
async def mgr_confirm(c: CallbackQuery, bot: Bot):
    if not is_manager(c.from_user.id):
        return await c.answer("Нет доступа", show_alert=True)
    order_id = int(c.data.split(":")[1])
    n, _ = await db_exec(
        "UPDATE orders SET status='paid', handled_by=?, paid_at=? WHERE id=? AND status='review'",
        (c.from_user.id, int(time.time()), order_id),
    )
    if not n:
        return await c.answer("Уже обработан другим менеджером", show_alert=True)
    o = await db_one("SELECT * FROM orders WHERE id=?", (order_id,))
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🌟 Выдано", callback_data=f"done:{order_id}")]]
    )
    await c.message.edit_caption(
        caption=c.message.html_text
        + f"\n\n✅ Оплата подтверждена: {c.from_user.full_name}\nОтправьте звёзды и нажмите «Выдано».",
        reply_markup=kb,
    )
    await bot.send_message(o["user_id"], tr(await lang_of(o["user_id"]), "confirmed", id=order_id))
    await c.answer()


@router.callback_query(F.data.startswith("no:"))
async def mgr_reject(c: CallbackQuery, bot: Bot):
    if not is_manager(c.from_user.id):
        return await c.answer("Нет доступа", show_alert=True)
    order_id = int(c.data.split(":")[1])
    n, _ = await db_exec(
        "UPDATE orders SET status='rejected', handled_by=? WHERE id=? AND status='review'",
        (
