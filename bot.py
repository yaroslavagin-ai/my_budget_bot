import asyncio
import logging
import sqlite3
import os
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command

# -------------------- НАСТРОЙКИ --------------------
API_TOKEN = os.getenv("BOT_TOKEN")
logging.basicConfig(level=logging.INFO)

# SQLite
conn = sqlite3.connect("bot_data.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    income REAL,
    method TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT,
    amount REAL
)
""")
conn.commit()

# -------------------- СОСТОЯНИЯ --------------------
class BudgetStates(StatesGroup):
    income = State()
    expenses = State()
    confirm_expenses = State()
    method = State()
    reflection = State()

# -------------------- КНОПКИ --------------------
def start_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Поехали", callback_data="start_income")]
    ])

def confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Всё верно", callback_data="confirm_expenses")],
        [InlineKeyboardButton(text="✏️ Изменить", callback_data="edit_expenses")],
        [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart")]
    ])

def next_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Далее", callback_data="next")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back")],
        [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart")]
    ])

def method_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="50/30/20", callback_data="method_50_30_20")],
        [InlineKeyboardButton(text="60/20/20", callback_data="method_60_20_20")],
        [InlineKeyboardButton(text="40/20/40", callback_data="method_40_20_40")],
        [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart")]
    ])

def reflection_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да", callback_data="reflection_yes")],
        [InlineKeyboardButton(text="Нет", callback_data="reflection_no")],
        [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart")]
    ])

# -------------------- ЛОГИКА --------------------
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Старт
@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Привет! Я помогу распределить твой бюджет!", reply_markup=start_keyboard())

# Ввод дохода
@dp.callback_query(lambda c: c.data == "start_income")
async def ask_income(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введи сумму дохода. В формате: 100000", reply_markup=next_keyboard())
    await state.set_state(BudgetStates.income)

@dp.message(BudgetStates.income)
async def save_income(message: types.Message, state: FSMContext):
    try:
        income = float(message.text.replace(" ", "").replace(",", "."))
    except ValueError:
        await message.answer("Неверный формат. Введи число, например: 100000")
        return
    user_id = message.from_user.id
    username = message.from_user.username or "unknown"

    cursor.execute("INSERT OR REPLACE INTO users (user_id, username, income) VALUES (?, ?, ?)",
                   (user_id, username, income))
    conn.commit()

    await state.set_state(BudgetStates.expenses)
    await message.answer(
        "Какие у тебя обязательные платежи?\n"
        "Введи каждый платёж с новой строки в формате: название - сумма\n"
        "Пример:\nАренда - 25 000\nКредит - 10 000",
        reply_markup=next_keyboard()
    )

# Ввод расходов с поддержкой нескольких строк и формата 25 000
@dp.message(BudgetStates.expenses)
async def save_expenses(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lines = message.text.strip().split("\n")
    errors = []

    for line in lines:
        if "-" not in line:
            errors.append(line)
            continue
        try:
            name, amount = line.split("-", 1)
            name = name.strip()
            amount = float(amount.strip().replace(" ", "").replace(",", "."))
            cursor.execute("INSERT INTO expenses (user_id, name, amount) VALUES (?, ?, ?)",
                           (user_id, name, amount))
        except:
            errors.append(line)

    conn.commit()

    if errors:
        await message.answer("Некоторые строки не удалось распознать:\n" + "\n".join(errors) +
                             "\nИспользуй формат: Название - сумма")
        return

    # Подтверждение
    cursor.execute("SELECT name, amount FROM expenses WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    text = "📋 Я записал твои платежи:\n"
    total = 0
    for r in rows:
        text += f"- {r[0]}: {r[1]}\n"
        total += r[1]
    text += f"Итого: {total}"
    await message.answer(text, reply_markup=confirm_keyboard())
    await state.set_state(BudgetStates.confirm_expenses)

# (Остальная логика без изменений)
# Подтверждение расходов
@dp.callback_query(lambda c: c.data in ["confirm_expenses", "edit_expenses", "restart"])
async def confirm_expenses(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if callback.data == "confirm_expenses":
        cursor.execute("SELECT income FROM users WHERE user_id = ?", (user_id,))
        income = cursor.fetchone()[0]
        cursor.execute("SELECT SUM(amount) FROM expenses WHERE user_id = ?", (user_id,))
        expenses = cursor.fetchone()[0] or 0
        leftover = income - expenses
        sign = "🟢" if leftover >= 0 else "🔴"
        await callback.message.answer(
            f"💰 Доход: {income}\n"
            f"💸 Обязательные платежи: {expenses}\n"
            f"{sign} Остаток: {leftover}",
            reply_markup=method_keyboard()
        )
        await state.set_state(BudgetStates.method)
    elif callback.data == "edit_expenses":
        cursor.execute("DELETE FROM expenses WHERE user_id = ?", (user_id,))
        conn.commit()
        await callback.message.answer("Введи платежи заново:", reply_markup=next_keyboard())
        await state.set_state(BudgetStates.expenses)
    elif callback.data == "restart":
        cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM expenses WHERE user_id = ?", (user_id,))
        conn.commit()
        await state.clear()
        await callback.message.answer("🔄 Начнём заново!", reply_markup=start_keyboard())

# Выбор метода
@dp.callback_query(lambda c: c.data.startswith("method"))
async def choose_method(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    cursor.execute("SELECT income FROM users WHERE user_id = ?", (user_id,))
    income = cursor.fetchone()[0]
    cursor.execute("SELECT SUM(amount) FROM expenses WHERE user_id = ?", (user_id,))
    expenses = cursor.fetchone()[0] or 0
    leftover = income - expenses

    method = callback.data.split("_")[1:]
    parts = [int(x) for x in method]
    chosen = f"{parts[0]}/{parts[1]}/{parts[2]}"

    cursor.execute("UPDATE users SET method = ? WHERE user_id = ?", (chosen, user_id))
    conn.commit()

    fact_percent = round(expenses / income * 100, 1)
    text = f"📊 Твои расходы = {fact_percent}% от дохода\n"
    text += f"Ты выбрал метод {chosen}\n\n"

    must_pay = round(income * parts[0] / 100)
    wants = round(income * parts[1] / 100)
    savings = round(income * parts[2] / 100)

    text += "✅ Итоговое распределение:\n"
    text += f"- Обязательные платежи: {expenses} (по методу допускается {must_pay})\n"
    text += f"- Желания: {wants}\n"
    text += f"- Накопления: {savings}\n"
    if leftover >= 0:
        text += f"🟢 У тебя остаётся {leftover}\n"
    else:
        text += f"🔴 Расходы превышают доходы на {abs(leftover)}\n"

    await callback.message.answer(text, reply_markup=reflection_keyboard())
    await state.set_state(BudgetStates.reflection)

# Мини-рефлексия
@dp.callback_query(lambda c: c.data.startswith("reflection"))
async def reflection(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "reflection_yes":
        await callback.message.answer("🚀 Данный раздел в разработке. Мы обязательно оповестим тебя о новом функционале!")
    else:
        await callback.message.answer("👍 Главное — ты сделал первый шаг к управлению финансами. Возвращайся, когда захочешь снова распределить бюджет 💰")
    await state.clear()

# -------------------- ЗАПУСК --------------------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
