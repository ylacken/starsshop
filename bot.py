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
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("starsbot")

# ---------- Конфиг (.env) ----------
BOT_TOKEN = os.environ["BOT_TOKEN"]
MANAGER_LIST = [int(x) for x in os.environ["MANAGER_IDS"].split(",") if x.strip()]
MANAGER_IDS = set(MANAGER_LIST)  # кто может подтверждать оплату и выдавать
NOTIFY_CHAT_ID = int(os.getenv("NOTIFY_CHAT_ID") or MANAGER_LIST[0])  # группа или личка менеджера
CARD_NUMBER = os.environ["CARD_NUMBER"]
CARD_HOLDER = os.getenv("CARD_HOLDER", "")
PRICE_UAH_PER_STAR = float(os.getenv("PRICE_UAH_PER_STAR", "0.85"))
PACKS = [int(x) for x in os.getenv("PACKS", "50,100,250,500,1000").split(",")]
ORDER_TTL_MIN = int(os.getenv("ORDER_TTL_MIN", "60"))
SUPPORT = os.getenv("SUPPORT_USERNAME", "")  # например @my_support
DB_PATH = os.getenv("DB_PATH", "orders.db")

router = Router()
USERNAME_RE = re.compile(r"^@?([A-Za-z0-9_]{5,32})$")


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


def support_line() -> str:
    return f" Напишите в поддержку {SUPPORT}." if SUPPORT else ""


# ---------- Покупатель ----------
def packs_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"⭐ {p} — {p * PRICE_UAH_PER_STAR:.2f} ₴", callback_data=f"buy:{p}")]
            for p in PACKS
        ]
    )


@router.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Привет! Здесь можно купить Telegram Stars за гривны.\nВыберите пакет:", reply_markup=packs_kb())


@router.callback_query(F.data.startswith("buy:"))
async def choose_pack(c: CallbackQuery, state: FSMContext):
    stars = int(c.data.split(":")[1])
    if stars not in PACKS:
        return await c.answer("Пакет недоступен", show_alert=True)
    await state.clear()
    await state.update_data(stars=stars)
    await state.set_state(BuyFlow.waiting_recipient)
    rows = []
    if c.from_user.username:
        rows.append([InlineKeyboardButton(text=f"Себе (@{c.from_user.username})", callback_data="self")])
    await c.message.answer(
        "Отправьте @username получателя звёзд" + (" или нажмите кнопку." if rows else "."),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None,
    )
    await c.answer()


async def create_order(target: Message, user, recipient: str, stars: int, state: FSMContext):
    amount_kop = int(round(stars * PRICE_UAH_PER_STAR * 100))
    code = "ST" + secrets.token_hex(3).upper()
    _, order_id = await db_exec(
        "INSERT INTO orders(code,user_id,user_name,recipient,stars,amount_kop,created_at) VALUES (?,?,?,?,?,?,?)",
        (code, user.id, f"@{user.username}" if user.username else user.full_name, recipient, stars, amount_kop, int(time.time())),
    )
    await state.clear()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid:{order_id}")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel:{order_id}")],
        ]
    )
    await target.answer(
        f"<b>Заказ #{order_id}</b>\n"
        f"⭐ {stars} звёзд для @{recipient}\n\n"
        f"Переведите <b>{amount_kop / 100:.2f} ₴</b> на карту:\n"
        f"<code>{CARD_NUMBER}</code>\n{CARD_HOLDER}\n\n"
        f"В комментарии к переводу укажите: <code>{code}</code>\n\n"
        "После оплаты нажмите «Я оплатил» и отправьте скриншот чека.",
        reply_markup=kb,
    )


@router.callback_query(F.data == "self", BuyFlow.waiting_recipient)
async def recipient_self(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await create_order(c.message, c.from_user, c.from_user.username, data["stars"], state)
    await c.answer()


@router.message(BuyFlow.waiting_recipient)
async def recipient_input(m: Message, state: FSMContext):
    match = USERNAME_RE.match((m.text or "").strip())
    if not match:
        return await m.answer("Неверный username. Пример: @durov")
    data = await state.get_data()
    await create_order(m, m.from_user, match.group(1), data["stars"], state)


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_order(c: CallbackQuery):
    n, _ = await db_exec(
        "UPDATE orders SET status='cancelled' WHERE id=? AND user_id=? AND status='pending'",
        (int(c.data.split(":")[1]), c.from_user.id),
    )
    await c.answer("Заказ отменён" if n else "Нельзя отменить", show_alert=True)
    if n:
        await c.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("paid:"))
async def claim_paid(c: CallbackQuery, state: FSMContext):
    order_id = int(c.data.split(":")[1])
    order = await db_one("SELECT * FROM orders WHERE id=? AND user_id=?", (order_id, c.from_user.id))
    if not order or order["status"] not in ("pending", "expired"):
        return await c.answer("Заказ уже обработан или недоступен.", show_alert=True)
    await state.set_state(ProofFlow.waiting_proof)
    await state.update_data(order_id=order_id)
    await c.message.answer(f"Отправьте скриншот чека по заказу #{order_id} (фото или файлом).")
    await c.answer()


@router.message(ProofFlow.waiting_proof, F.photo | F.document)
async def got_proof(m: Message, state: FSMContext, bot: Bot):
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
        return await m.answer("Заказ уже обработан.")
    o = await db_one("SELECT * FROM orders WHERE id=?", (order_id,))
    caption = (
        f"🧾 <b>Заказ #{o['id']}</b> на проверку\n"
        f"Покупатель: {o['user_name']} (id {o['user_id']})\n"
        f"Звёзд: <b>{o['stars']}</b> → @{o['recipient']}\n"
        f"Сумма: <b>{o['amount_kop'] / 100:.2f} ₴</b>\n"
        f"Комментарий в переводе: <code>{o['code']}</code>"
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
    await m.answer(f"Чек по заказу #{order_id} отправлен менеджеру. Обычно проверка занимает несколько минут.")


@router.message(ProofFlow.waiting_proof)
async def proof_wrong(m: Message):
    await m.answer("Отправьте скриншот чека фото или файлом. Для отмены нажмите /start.")


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
    await bot.send_message(o["user_id"], f"✅ Оплата по заказу #{order_id} подтверждена. Звёзды отправляются.")
    await c.answer()


@router.callback_query(F.data.startswith("no:"))
async def mgr_reject(c: CallbackQuery, bot: Bot):
    if not is_manager(c.from_user.id):
        return await c.answer("Нет доступа", show_alert=True)
    order_id = int(c.data.split(":")[1])
    n, _ = await db_exec(
        "UPDATE orders SET status='rejected', handled_by=? WHERE id=? AND status='review'",
        (c.from_user.id, order_id),
    )
    if not n:
        return await c.answer("Уже обработан другим менеджером", show_alert=True)
    o = await db_one("SELECT * FROM orders WHERE id=?", (order_id,))
    await c.message.edit_caption(
        caption=c.message.html_text + f"\n\n❌ Оплата не найдена: {c.from_user.full_name}", reply_markup=None
    )
    await bot.send_message(
        o["user_id"], f"❌ Оплату по заказу #{order_id} подтвердить не удалось.{support_line()}"
    )
    await c.answer()


@router.callback_query(F.data.startswith("done:"))
async def mgr_done(c: CallbackQuery, bot: Bot):
    if not is_manager(c.from_user.id):
        return await c.answer("Нет доступа", show_alert=True)
    order_id = int(c.data.split(":")[1])
    n, _ = await db_exec("UPDATE orders SET status='delivered' WHERE id=? AND status='paid'", (order_id,))
    if not n:
        return await c.answer("Уже выдан", show_alert=True)
    o = await db_one("SELECT * FROM orders WHERE id=?", (order_id,))
    await c.message.edit_caption(
        caption=c.message.html_text + f"\n\n🌟 Выдано: {c.from_user.full_name}", reply_markup=None
    )
    await bot.send_message(
        o["user_id"], f"🌟 Заказ #{order_id}: {o['stars']} звёзд отправлено на @{o['recipient']}. Спасибо!"
    )
    await c.answer()


@router.message(Command("orders"))
async def mgr_orders(m: Message):
    if not is_manager(m.from_user.id):
        return
    rows = await db_all("SELECT * FROM orders ORDER BY id DESC LIMIT 15")
    if not rows:
        return await m.answer("Заказов нет.")
    await m.answer("\n".join(f"#{r['id']} {r['status']} — {r['stars']}⭐ → @{r['recipient']}" for r in rows))


@router.message(Command("stats"))
async def mgr_stats(m: Message):
    if not is_manager(m.from_user.id):
        return
    r = await db_one(
        "SELECT COUNT(*) n, COALESCE(SUM(stars),0) s, COALESCE(SUM(amount_kop),0) t "
        "FROM orders WHERE status IN ('paid','delivered')"
    )
    await m.answer(f"Оплаченных заказов: {r['n']}\nЗвёзд: {r['s']}\nПолучено: {r['t'] / 100:.2f} ₴")


# ---------- Фоновые задачи ----------
async def expirer():
    while True:
        try:
            limit = int(time.time()) - ORDER_TTL_MIN * 60
            await db_exec("UPDATE orders SET status='expired' WHERE status='pending' AND created_at<?", (limit,))
        except Exception:
            log.exception("Ошибка expirer")
        await asyncio.sleep(60)


async def main():
    await init_db()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    asyncio.create_task(expirer())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
      
