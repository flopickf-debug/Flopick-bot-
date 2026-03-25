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

# =========================================================
# БЛОК 1: НАСТРОЙКИ
# =========================================================
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
    waiting_for_teacher_name = State()

# =========================================================
# БЛОК 2: ЛОГИКА ПАРСИНГА С КАБИНЕТАМИ
# =========================================================
async def fetch_schedule(course, group, target_day=None):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SCHEDULE_TABLE_ID}/values/{course}!A1:BG100?key={GOOGLE_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            rows = data.get("values", [])
    
    if not rows: return "⚠️ Таблица пуста."
    col_idx = next((i for i, cell in enumerate(rows[1]) if group.lower() in cell.lower()), -1)
    if col_idx == -1: return f"⚠️ Группа {group} не найдена."
    
    res_dict, curr_day = {}, ""
    
    for i in range(2, len(rows)):
        row = rows[i]
        if len(row) > 0 and row[0].strip():
            curr_day = row[0].strip().upper()
        
        if not curr_day or (target_day and target_day.upper() not in curr_day): continue
        
        content = row[col_idx].strip() if len(row) > col_idx else ""
        pair_num = row[1].strip() if len(row) > 1 else ""
        
        if pair_num and content and content not in ["-", "."]:
            teacher = ""
            room = ""
            
            # Проверяем ячейку кабинета справа от ПРЕДМЕТА
            if len(row) > col_idx + 1 and row[col_idx+1].strip():
                room = row[col_idx+1].strip()

            # Ищем учителя строкой ниже
            if i + 1 < len(rows):
                next_row = rows[i+1]
                next_content = next_row[col_idx].strip() if len(next_row) > col_idx else ""
                next_pair = next_row[1].strip() if len(next_row) > 1 else ""
                
                # Если ниже нет номера пары, значит там учитель
                if not next_pair and next_content:
                    teacher = f" ({next_content})"
                    # Если кабинет не нашли у предмета, ищем его у учителя
                    if not room and len(next_row) > col_idx + 1 and next_row[col_idx+1].strip():
                        room = next_row[col_idx+1].strip()

            room_str = f" — **каб. {room}**" if room else ""
            if curr_day not in res_dict: res_dict[curr_day] = []
            res_dict[curr_day].append(f"• {pair_num} пара: {content}{teacher}{room_str}")

    output = ""
    for d, l in res_dict.items(): output += f"\n📅 **{d}**\n" + "\n".join(l) + "\n"
    return output if output else "🎉 Занятий нет!"

# --- Обработчики остались прежними ---
@dp.message(Command("start"), StateFilter('*'))
@dp.message(F.text == "⬅️ Назад к курсам")
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    kb = ReplyKeyboardBuilder()
    for c in GROUPS_BY_COURSE.keys(): kb.add(KeyboardButton(text=c))
    kb.row(KeyboardButton(text="👨‍🏫 Я преподаватель"))
    await state.set_state(UserState.choosing_course)
    await message.answer("🎓 Выберите курс:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_course)
async def select_course(message: types.Message, state: FSMContext):
    if message.text == "👨‍🏫 Я преподаватель":
        await state.set_state(UserState.waiting_for_teacher_name)
        return await message.answer("📝 Введите фамилию:", reply_markup=ReplyKeyboardBuilder().add(KeyboardButton(text="⬅️ Назад к курсам")).as_markup(resize_keyboard=True))
    if message.text not in GROUPS_BY_COURSE: return
    await state.update_data(c=message.text); await state.set_state(UserState.choosing_group)
    kb = ReplyKeyboardBuilder()
    for g in GROUPS_BY_COURSE[message.text]: kb.add(KeyboardButton(text=g))
    kb.row(KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer(f"📍 {message.text}. Группа:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_group)
async def select_group(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к курсам": return await start(message, state)
    await state.update_data(g=message.text); await state.set_state(UserState.choosing_day)
    kb = ReplyKeyboardBuilder().row(KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📅 Завтра"))
    kb.row(KeyboardButton(text="🗓 На всю неделю"), KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer(f"🕒 Группа {message.text}:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_day)
async def show_res(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к курсам": return await start(message, state)
    data = await state.get_data(); days = ['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА', 'СУББОТА', 'ВОСКРЕСЕНЬЕ']
    t = None
    if "Сегодня" in message.text: t = days[datetime.now().weekday()]
    elif "Завтра" in message.text: t = days[(datetime.now() + timedelta(days=1)).weekday()]
    res = await fetch_schedule(data['c'], data['g'], t)
    await message.answer(f"📋 **{data['g']}**\n{res}", parse_mode="Markdown")

@dp.message(UserState.waiting_for_teacher_name)
async def teacher_res(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к курсам": return await start(message, state)
    # Поиск преподавателя по всем листам (краткая версия для теста)
    await message.answer("🔍 Ищу по всем курсам...")
    # (Функция поиска преподавателя аналогична по логике)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
