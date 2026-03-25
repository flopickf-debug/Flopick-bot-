import logging
import asyncio
import aiohttp
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = "7987454041:AAGU-DGvVqgN7rioySxL5zINEk60WSlkUW4"
GOOGLE_API_KEY = "AIzaSyDZUuMn8B8t_REygaEGpEI47hyLSQrDKDk"
SCHEDULE_TABLE_ID = "1X6YF54l1rgP7MFfkTa1b_L6f4f3aWuADZwF8wwTWKK4"

COURSES = ["1 курс", "2 курс", "3 курс", "4 курс"]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class UserState(StatesGroup):
    choosing_course = State()
    choosing_group = State()
    choosing_day = State()
    waiting_for_teacher = State()

# --- БЕЗОПАСНЫЙ ГЕТТЕР КАБИНЕТА ---
def get_room_safe(rows, r_idx, c_idx):
    try:
        if r_idx < 0 or r_idx >= len(rows): return ""
        current_row = rows[r_idx]
        # Проверяем 3 ячейки справа
        for offset in range(1, 4):
            if len(current_row) > c_idx + offset:
                val = current_row[c_idx + offset].strip()
                if val and val.lower() not in ["-", ".", "каб", "пара"]:
                    return val
        # Проверяем строку ниже
        if r_idx + 1 < len(rows):
            next_row = rows[r_idx + 1]
            for offset in range(1, 4):
                if len(next_row) > c_idx + offset:
                    val = next_row[c_idx + offset].strip()
                    if val and val.lower() not in ["-", ".", "каб", "пара"]:
                        return val
    except: pass
    return ""

# --- ПОИСК ДЛЯ ПРЕПОДАВАТЕЛЯ ---
async def fetch_teacher_schedule(teacher_name):
    all_lessons = []
    t_name_lower = teacher_name.lower()

    async with aiohttp.ClientSession() as session:
        for course in COURSES:
            url = f"https://sheets.googleapis.com/v4/spreadsheets/{SCHEDULE_TABLE_ID}/values/{course}!A1:BG100?key={GOOGLE_API_KEY}"
            async with session.get(url) as resp:
                if resp.status != 200: continue
                data = await resp.json()
                rows = data.get("values", [])
            
            if len(rows) < 3: continue

            curr_day = ""
            for i in range(2, len(rows)):
                row = rows[i]
                if not row: continue
                
                # День недели (Колонка A)
                if len(row) > 0 and row[0].strip():
                    day_cand = row[0].replace('\n', ' ').strip().upper()
                    if any(d in day_cand for d in ["ПОНЕДЕЛЬНИК", "ВТОРНИК", "СРЕДА", "ЧЕТВЕРГ", "ПЯТНИЦА", "СУББОТА"]):
                        curr_day = day_cand
                
                if not curr_day: continue

                # Сканируем колонки
                for col_idx in range(2, len(row)):
                    cell_val = row[col_idx].strip().lower()
                    
                    if t_name_lower in cell_val and len(cell_val) > 2:
                        pair_num = row[1].strip() if len(row) > 1 else "?"
                        
                        # БЕЗОПАСНОЕ ПОЛУЧЕНИЕ ПРЕДМЕТА (Строка выше)
                        subject = "Предмет?"
                        if i > 0 and len(rows[i-1]) > col_idx:
                            subject = rows[i-1][col_idx].strip()
                        
                        # БЕЗОПАСНОЕ ПОЛУЧЕНИЕ ГРУППЫ (Строка 2)
                        group_name = "Группа?"
                        if len(rows) > 1 and len(rows[1]) > col_idx:
                            group_name = rows[1][col_idx].strip()
                        
                        # БЕЗОПАСНОЕ ПОЛУЧЕНИЕ КАБИНЕТА
                        room = get_room_safe(rows, i-1, col_idx)
                        room_str = f" [каб. {room}]" if room else ""
                        
                        all_lessons.append(f"📅 **{curr_day}**\n{pair_num} пара: {subject} — {group_name}{room_str}")

    return "\n\n".join(all_lessons) if all_lessons else "🔍 Ничего не найдено."

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"), StateFilter('*'))
@dp.message(F.text == "⬅️ Назад")
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="🎓 Я студент"), KeyboardButton(text="👨‍🏫 Я преподаватель"))
    await message.answer("Кто вы?", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "👨‍🏫 Я преподаватель")
async def teacher_mode(message: types.Message, state: FSMContext):
    await state.set_state(UserState.waiting_for_teacher)
    await message.answer("📝 Введите вашу фамилию:", 
                         reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True))

@dp.message(UserState.waiting_for_teacher)
async def teacher_search(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад": return await start_cmd(message, state)
    
    wait_msg = await message.answer("⏳ Проверяю все курсы...")
    try:
        result = await fetch_teacher_schedule(message.text)
        await wait_msg.edit_text(f"👨‍🏫 **Расписание для {message.text}:**\n\n{result}", parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Teacher search error: {e}")
        await wait_msg.edit_text("⚠️ Произошла ошибка при поиске. Проверьте правильность фамилии.")

@dp.message(F.text == "🎓 Я студент")
async def student_mode(message: types.Message, state: FSMContext):
    kb = ReplyKeyboardBuilder()
    for c in COURSES: kb.add(KeyboardButton(text=c))
    kb.row(KeyboardButton(text="⬅️ Назад"))
    await state.set_state(UserState.choosing_course)
    await message.answer("Выберите ваш курс:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

# (Здесь твои старые обработчики выбора групп для студентов...)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
