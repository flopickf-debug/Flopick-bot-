import logging
import asyncio
import gspread
import aiohttp
import os
import json
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = "7987454041:AAGU-DGvVqgN7rioySxL5zINEk60WSlkUW4"
GOOGLE_API_KEY = "AIzaSyDZUuMn8B8t_REygaEGpEI47hyLSQrDKDk"
SCHEDULE_TABLE_ID = "1X6YF54l1rgP7MFfkTa1b_L6f4f3aWuADZwF8wwTWKK4"
DB_TABLE_ID = "11KbeilP1HRonHQAAZusBS1-ffNo4FxHXa239yZMKJm8"
OWNER_ID = 879365319 

GROUPS_BY_COURSE = {
    "1 курс": ["АВМ-110", "ИСП-104", "ИСП-105", "ДОУ-102", "СВП-111", "ОСД-134", "ПКП-121", "СЗС-133", "СРС-111", "ТГО-101", "ТМС-103", "ТОС-103", "ЭМР-107", "ЭМР-108"],
    "2 курс": ["АВМ-208", "ИСП-202", "МПР-202", "ОСД-233", "ПКП-219", "ПКП-220", "СЗС-232", "СРС-209", "ТМС-202", "ТОС-202", "ЭМР-205", "ЮСП-201"],
    "3 курс": ["ДОУ-301", "ИСП-301", "ПКП-317", "ПКП-318", "ПОС-301", "СВП-309", "СВП-310", "СЗС-331", "ТМС-302", "ТОС-301"],
    "4 курс": ["СВП-425", "ПКП-415", "СВП-426", "СЗС-427"]
}

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class UserState(StatesGroup):
    choosing_course = State()
    choosing_group = State()
    choosing_day = State()

# --- БЕЗОПАСНЫЙ ПОИСК КАБИНЕТА ---
def safe_get_cab(rows, r_idx, c_idx):
    try:
        # Проверяем ячейку справа в текущей строке
        if r_idx < len(rows) and len(rows[r_idx]) > c_idx + 1:
            val = rows[r_idx][c_idx + 1].strip()
            if val and val not in ["-", ".", "каб"]: return val
            
        # Проверяем ячейку справа в строке ниже (где учитель)
        if r_idx + 1 < len(rows) and len(rows[r_idx + 1]) > c_idx + 1:
            val = rows[r_idx + 1][c_idx + 1].strip()
            if val and val not in ["-", ".", "каб"]: return val
    except Exception:
        pass
    return ""

# --- ЛОГИКА ПАРСИНГА ---
async def fetch_schedule(course, group, target_day=None):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SCHEDULE_TABLE_ID}/values/{course}!A1:BG100?key={GOOGLE_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            rows = data.get("values", [])
    
    if not rows: return "⚠️ Таблица пуста."
    
    # Ищем колонку группы (строка 2 в таблице, индекс 1 в коде)
    col_idx = -1
    if len(rows) > 1:
        for i, cell in enumerate(rows[1]):
            if group.lower() in cell.lower():
                col_idx = i
                break
            
    if col_idx == -1: return f"⚠️ Группа {group} не найдена."
    
    res_dict, curr_day = {}, ""
    for i in range(2, len(rows)):
        row = rows[i]
        # Обработка дня недели (колонка A)
        if len(row) > 0 and row[0].strip():
            day_raw = row[0].replace('\n', ' ').strip().upper()
            if any(word in day_raw for word in ["ПОНЕДЕЛЬНИК", "ВТОРНИК", "СРЕДА", "ЧЕТВЕРГ", "ПЯТНИЦА", "СУББОТА"]):
                curr_day = day_raw
        
        if not curr_day or (target_day and target_day.upper() not in curr_day): continue
        
        # Номер пары (колонка B, индекс 1)
        pair_num = row[1].strip() if len(row) > 1 else ""
        content = row[col_idx].strip() if len(row) > col_idx else ""
        
        # Если нашли предмет
        if pair_num and content and content not in ["-", ".", "№", "Ден"]:
            teacher = ""
            # Учитель на строку ниже в той же колонке
            if i + 1 < len(rows) and len(rows[i+1]) > col_idx:
                t_val = rows[i+1][col_idx].strip()
                if t_val: teacher = f" ({t_val})"
            
            # Кабинет
            room = safe_get_cab(rows, i, col_idx)
            room_str = f" — **каб. {room}**" if room else ""
            
            if curr_day not in res_dict: res_dict[curr_day] = []
            res_dict[curr_day].append(f"• {pair_num} пара: {content}{teacher}{room_str}")

    output = ""
    for d, lessons in res_dict.items():
        output += f"\n📅 **{d}**\n" + "\n".join(lessons) + "\n"
    return output if output else "🎉 Занятий нет!"

# --- ОБРАБОТЧИКИ ---
@dp.message(Command("start"), StateFilter('*'))
@dp.message(F.text == "⬅️ Назад к курсам")
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    kb = ReplyKeyboardBuilder()
    for c in GROUPS_BY_COURSE.keys(): kb.add(KeyboardButton(text=c))
    kb.row(KeyboardButton(text="👨‍🏫 Я преподаватель"))
    await state.set_state(UserState.choosing_course)
    await message.answer("🎓 Выберите курс:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_course)
async def proc_course(message: types.Message, state: FSMContext):
    if message.text == "👨‍🏫 Я преподаватель":
        return await message.answer("📝 Введите фамилию (в разработке)")
    if message.text not in GROUPS_BY_COURSE: return
    await state.update_data(c=message.text); await state.set_state(UserState.choosing_group)
    kb = ReplyKeyboardBuilder()
    for g in GROUPS_BY_COURSE[message.text]: kb.add(KeyboardButton(text=g))
    kb.row(KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer(f"📍 {message.text}. Группа:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_group)
async def proc_group(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к курсам": return await start_cmd(message, state)
    await state.update_data(g=message.text); await state.set_state(UserState.choosing_day)
    kb = ReplyKeyboardBuilder().row(KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📅 Завтра"))
    kb.row(KeyboardButton(text="🗓 На всю неделю"), KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer(f"🕒 Группа {message.text}:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_day)
async def proc_day(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к курсам": return await start_cmd(message, state)
    data = await state.get_data()
    days = ['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА', 'СУББОТА', 'ВОСКРЕСЕНЬЕ']
    t = None
    if "Сегодня" in message.text: t = days[datetime.now().weekday()]
    elif "Завтра" in message.text: t = days[(datetime.now() + timedelta(days=1)).weekday()]
    
    res = await fetch_schedule(data['c'], data['g'], t)
    await message.answer(f"📋 **{data['g']}**\n{res}", parse_mode="Markdown")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
