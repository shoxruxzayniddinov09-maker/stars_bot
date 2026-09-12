import asyncio
import logging
import os
from decimal import Decimal

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dotenv import load_dotenv

from paystars import PayStars, PayStarsError

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
PAYSTARS_API_KEY = os.environ["PAYSTARS_API_KEY"]
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
MARKUP = Decimal(os.environ.get("MARKUP_PERCENT", "20"))
PAYMENT_HINT = os.environ.get("PAYMENT_HINT", "To'lov chekini rasm qilib yuboring.")

logging.basicConfig(level=logging.INFO)
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
api = PayStars(PAYSTARS_API_KEY)

STAR_PACKS = [50, 100, 250, 500, 1000]
PREMIUM_MONTHS = [3, 6, 12]
PENDING = {}


class Order(StatesGroup):
    wait_user = State()
    wait_check = State()


def sell_price(wholesale):
    raw = Decimal(wholesale) * (Decimal(1) + MARKUP / Decimal(100))
    return int((raw / Decimal(500)).to_integral_value() * 500)


def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Stars", callback_data="cat:stars")],
        [InlineKeyboardButton(text="Premium", callback_data="cat:premium")],
        [InlineKeyboardButton(text="Narxlar", callback_data="prices")],
    ])


def packs_kb():
    rows = [[InlineKeyboardButton(text=str(n) + " Stars", callback_data="stars:" + str(n))] for n in STAR_PACKS]
    rows.append([InlineKeyboardButton(text="Orqaga", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def premium_kb():
    rows = [[InlineKeyboardButton(text=str(m) + " oy", callback_data="prem:" + str(m))] for m in PREMIUM_MONTHS]
    rows.append([InlineKeyboardButton(text="Orqaga", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Stars va Premium savdosi. Tanlang.", reply_markup=main_kb())


@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Tanlang.", reply_markup=main_kb())
    await call.answer()


@dp.callback_query(F.data == "prices")
async def prices(call: CallbackQuery):
    try:
        acc = await api.account()
        p = acc["pricing"]
        text = (
            "Sotuv narxi:\n"
            + "1 Star ~ " + str(sell_price(p["star_price"])) + " som\n"
            + "Premium 3 oy — " + str(sell_price(p["premium_3_price"])) + " som\n"
            + "Premium 6 oy — " + str(sell_price(p["premium_6_price"])) + " som\n"
            + "Premium 12 oy — " + str(sell_price(p["premium_12_price"])) + " som"
        )
    except Exception:
        text = "Narx olinmadi."
    await call.message.edit_text(text, reply_markup=main_kb())
    await call.answer()


@dp.callback_query(F.data == "cat:stars")
async def cat_stars(call: CallbackQuery):
    await call.message.edit_text("Nechta Stars?", reply_markup=packs_kb())
    await call.answer()


@dp.callback_query(F.data == "cat:premium")
async def cat_prem(call: CallbackQuery):
    await call.message.edit_text("Premium muddati?", reply_markup=premium_kb())
    await call.answer()


@dp.callback_query(F.data.startswith("stars:"))
async def pick_stars(call: CallbackQuery, state: FSMContext):
    qty = int(call.data.split(":")[1])
    acc = await api.account()
    price = sell_price(acc["pricing"]["star_price"] * qty)
    await state.update_data(kind="stars", qty=qty, months=0, price=price)
    await state.set_state(Order.wait_user)
    await call.message.edit_text(str(qty) + " Stars — " + str(price) + " som.\nUsername yozing. Masalan: @username")
    await call.answer()


@dp.callback_query(F.data.startswith("prem:"))
async def pick_prem(call: CallbackQuery, state: FSMContext):
    months = int(call.data.split(":")[1])
    acc = await api.account()
    key = {3: "premium_3_price", 6: "premium_6_price", 12: "premium_12_price"}[months]
    price = sell_price(acc["pricing"][key])
    await state.update_data(kind="premium", qty=0, months=months, price=price)
    await state.set_state(Order.wait_user)
    await call.message.edit_text("Premium " + str(months) + " oy — " + str(price) + " som.\nUsername yozing.")
    await call.answer()


@dp.message(Order.wait_user)
async def got_user(message: Message, state: FSMContext):
    username = (message.text or "").strip().lstrip("@")
    if not username or " " in username:
        await message.answer("Username notogri.")
        return
    data = await state.get_data()
    kind = "stars" if data["kind"] == "stars" else "premium"
    try:
        check = await api.check_username(username, kind)
    except PayStarsError as e:
        await message.answer("Tekshirib bolmadi. " + str(e.status))
        return
    if not check.get("valid"):
        await message.answer("Bu usernamega yuborib bolmaydi.")
        return
    await state.update_data(username=username)
    await state.set_state(Order.wait_check)
    await message.answer("Qabul qiluvchi: @" + username + "\nSumma: " + str(data["price"]) + " som\n" + PAYMENT_HINT)


@dp.message(Order.wait_check, F.photo)
async def got_check(message: Message, state: FSMContext):
    data = await state.get_data()
    buyer_id = message.from_user.id
    PENDING[buyer_id] = {
        "kind": data["kind"],
        "qty": data.get("qty") or 0,
        "months": data.get("months") or 0,
        "price": data["price"],
        "username": data["username"],
    }
    caption = "Buyurtma " + str(buyer_id) + " @" + str(message.from_user.username) + "\n" + data["kind"] + " @" + data["username"] + " " + str(data["price"]) + " som"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Tasdiqlash", callback_data="ok:" + str(buyer_id))],
        [InlineKeyboardButton(text="Rad etish", callback_data="no:" + str(buyer_id))],
    ])
    if ADMIN_ID:
        await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=caption, reply_markup=kb)
    await message.answer("Chek yuborildi. Admin tekshiradi.")
    await state.clear()


@dp.callback_query(F.data.startswith("ok:"))
async def admin_ok(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Faqat admin", show_alert=True)
        return
    buyer_id = int(call.data.split(":")[1])
    data = PENDING.get(buyer_id)
    if not data:
        await call.answer("Buyurtma topilmadi", show_alert=True)
        return
    kind = "stars" if data["kind"] == "stars" else "premium"
    try:
        check = await api.check_username(data["username"], kind)
        if not check.get("valid") or not check.get("verification_token"):
            raise PayStarsError(422, "invalid")
        token = check["verification_token"]
        if data["kind"] == "stars":
            res = await api.buy_stars(data["username"], data["qty"], token)
        else:
            res = await api.buy_premium(data["username"], data["months"], token)
        text = "Yuborildi. " + str(res.get("status"))
        await bot.send_message(buyer_id, "Tolov qabul qilindi. " + text)
        PENDING.pop(buyer_id, None)
    except PayStarsError as e:
        text = "Balans yetarli emas." if e.status == 402 else "Yuborilmadi. " + str(e.status)
    await call.message.answer(text)
    await call.answer()


@dp.callback_query(F.data.startswith("no:"))
async def admin_no(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Faqat admin", show_alert=True)
        return
    buyer_id = int(call.data.split(":")[1])
    PENDING.pop(buyer_id, None)
    try:
        await bot.send_message(buyer_id, "Tolov tasdiqlanmadi.")
    except Exception:
        pass
    await call.message.answer("Rad etildi.")
    await call.answer()


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
