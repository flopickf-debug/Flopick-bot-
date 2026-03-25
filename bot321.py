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

# --- НАСТРОЙКИ ---
BOT_TOKEN = "7987454041:AAGU-DGvVqgN7rioySxL5zINEk60WSlkUW4"
GOOGLE_API_KEY = "AIzaSyDZUuMn8B8t_REygaEGpEI47hyLSQrDKDk"
SCHEDULE_TABLE_ID = "1X6YF54l1rgP7MFfkTa1b_L6f4f3aWuADZwF8wwTWKK4"

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

# --- ФУНКЦИЯ «СКАНЕР» КАБИНЕТА ---
def find_room_in_area(rows, r_idx, col_idx):
    """
    Проверяет ячейки справа от предмета и учителя. 
    Ищет любую ячейку, которая похожа на номер кабинета.
    """
    try:
        # Проверяем 3 ячейки справа в строке предмета и строке учителя
        for row_to_check in [rows[r_idx], rows[r_idx+1] if r_idx+1 < len(rows) else []]:
            if not row_to_check: continue
            # Берем срез ячеек справа от колонки предмета
            for offset in range(1, 4): 
                if len(row_to_check) > col_idx + offset:
                    val = row_to_check[col_idx + offset].strip()
                    # Если ячейка не пустая и не содержит мусор
                    if val and val.lower() not in ["-", ".", "каб", "пара", "№"]:
                        return val
    except: pass
    return ""

# --- ЛОГИКА ПАРСИНГА ---
async def fetch_schedule(course, group, target_day=None):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SCHEDULE_TABLE_ID}/values/{course}!A1:BG100?key={GOOGLE_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            rows = data.get("values", [])
    
    if not rows: return "⚠️ Таблица пуста."
    
    # Находим колонку группы
    col_idx = -1
    for r in range(min(5, len(rows))):
        for i, cell in enumerate(rows[r]):
            if group.lower() in cell.lower():
                col_idx = i; break
        if col_idx != -1: break
            
    if col_idx == -1: return f"⚠️ Группа {group} не найдена."
    
    res_dict, curr_day = {}, ""
    for i in range(len(rows)):
        row = rows[i]
        if not row: continue
        
        # Определяем день
        if row[0].strip():
            day_val = row[0].replace('\n', ' ').strip().upper()
            if any(d in day_val for d in ["ПОНЕДЕЛЬНИК", "ВТОРНИК", "СРЕДА", "ЧЕТВЕРГ", "ПЯТНИЦА", "СУББОТА"]):
                curr_day = day_val
        
        if not curr_day or (target_day and target_day.upper() not in curr_day): continue
        
        # Берем номер пары и предмет
        pair_num = row[1].strip() if len(row) > 1 else ""
        content = row[col_idx].strip() if len(row) > col_idx else ""
        
        if pair_num and content and content not in ["-", ".", "№", "Ден", "Пара"]:
            teacher = ""
            # Учитель строкой ниже
            if i + 1 < len(rows) and len(rows[i+1]) > col_idx:
                t_val = rows[i+1][col_idx].strip()
                if t_val: teacher = f" ({t_val})"
            
            # Ищем кабинет «сканером»
            room = find_room_in_area(rows, i, col_idx)
            room_str = f" — **каб. {room}**" if room else ""
            
            if curr_day not in res_dict: res_dict[curr_day] = []
            res_dict[curr_day].append(f"• {pair_num} пара: {content}{teacher}{room_str}")

    output = ""
    for d, lessons in res_dict.items():
        output += f"\n📅 **{d}**\n" + "\n".join(lessons) + "\n"
    return output if output else "🎉 Занятий нет!"

# --- ОБРАБОТЧИКИ (УПРОЩЕННО ДЛЯ ТЕСТА) ---
@dp.message(Command("start"), StateFilter('*'))
@dp.message(F.text == "⬅️ Назад к курсам")
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    kb = ReplyKeyboardBuilder()
    for c in GROUPS_BY_COURSE.keys(): kb.add(KeyboardButton(text=c))
    await state.set_state(UserState.choosing_course)
    await message.answer("🎓 Выберите курс:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_course)
async def proc_course(message: types.Message, state: FSMContext):
    if message.text not in GROUPS_BY_COURSE: return
    await state.update_data(c=message.text); await state.set_state(UserState.choosing_group)
    kb = ReplyKeyboardBuilder()
    for g in GROUPS_BY_COURSE[message.text]: kb.add(KeyboardButton(text=g))
    kb.row(KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer(f"📍 Группа:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_group)
async def proc_group(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к курсам": return await start_cmd(message, state)
    await state.update_data(g=message.text); await state.set_state(UserState.choosing_day)
    kb = ReplyKeyboardBuilder().row(KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📅 Завтра"))
    kb.row(KeyboardButton(text="🗓 На неделю"), KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer(f"🕒 Выберите период:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_day)
async def proc_day(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к курсам": return await start_cmd(message, state)
    data = await state.get_data()
    days = ['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА', 'СУББОТА', 'ВОСКРЕСЕНЬЕ']
    t = days[datetime.now().weekday()] if "Сегодня" in message.text else days[(datetime.now() + timedelta(days=1)).weekday()] if "Завтра" in message.text else None
    
    try:
        res = await fetch_schedule(data.get('c'), data.get('g'), t)
        await message.answer(f"📋 **{data.get('g')}**\n{res}", parse_mode="Markdown")
    except Exception as e:
        await message.answer("⚠️ Ошибка парсинга.")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
