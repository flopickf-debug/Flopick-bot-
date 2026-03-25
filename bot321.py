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
    waiting_for_teacher = State()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_room_safe(rows, r_idx, c_idx):
    try:
        if r_idx < 0 or r_idx >= len(rows): return ""
        for offset in range(1, 4):
            if len(rows[r_idx]) > c_idx + offset:
                val = rows[r_idx][c_idx + offset].strip()
                if val and val.lower() not in ["-", ".", "каб", "пара"]: return val
        if r_idx + 1 < len(rows):
            for offset in range(1, 4):
                if len(rows[r_idx+1]) > c_idx + offset:
                    val = rows[r_idx+1][c_idx + offset].strip()
                    if val and val.lower() not in ["-", ".", "каб", "пара"]: return val
    except: pass
    return ""

# --- ЛОГИКА СТУДЕНТА ---
async def fetch_student_schedule(course, group, target_day=None):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SCHEDULE_TABLE_ID}/values/{course}!A1:BG100?key={GOOGLE_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            rows = data.get("values", [])
    
    if not rows: return "⚠️ Таблица пуста."
    
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
        if row[0].strip():
            day_val = row[0].replace('\n', ' ').strip().upper()
            if any(d in day_val for d in ["ПОНЕДЕЛЬНИК", "ВТОРНИК", "СРЕДА", "ЧЕТВЕРГ", "ПЯТНИЦА", "СУББОТА"]):
                curr_day = day_val
        
        if not curr_day or (target_day and target_day.upper() not in curr_day): continue
        
        pair_num = row[1].strip() if len(row) > 1 else ""
        content = row[col_idx].strip() if len(row) > col_idx else ""
        
        if pair_num and content and content not in ["-", ".", "№", "Ден", "Пара"]:
            teacher = ""
            if i + 1 < len(rows) and len(rows[i+1]) > col_idx:
                t_val = rows[i+1][col_idx].strip()
                if t_val: teacher = f" ({t_val})"
            
            room = get_room_safe(rows, i, col_idx)
            room_str = f" — **каб. {room}**" if room else ""
            
            if curr_day not in res_dict: res_dict[curr_day] = []
            res_dict[curr_day].append(f"• {pair_num} пара: {content}{teacher}{room_str}")

    output = ""
    for d, lessons in res_dict.items():
        output += f"\n📅 **{d}**\n" + "\n".join(lessons) + "\n"
    return output if output else "🎉 Занятий нет!"

# --- ЛОГИКА ПРЕПОДАВАТЕЛЯ ---
async def fetch_teacher_schedule(teacher_name):
    all_lessons = []
    t_name_lower = teacher_name.lower()
    async with aiohttp.ClientSession() as session:
        for course in GROUPS_BY_COURSE.keys():
            url = f"https://sheets.googleapis.com/v4/spreadsheets/{SCHEDULE_TABLE_ID}/values/{course}!A1:BG100?key={GOOGLE_API_KEY}"
            async with session.get(url) as resp:
                data = await resp.json()
                rows = data.get("values", [])
            
            if len(rows) < 3: continue
            curr_day = ""
            for i in range(2, len(rows)):
                row = rows[i]
                if not row or not row[0:1]: continue
                if row[0].strip():
                    day_cand = row[0].replace('\n', ' ').strip().upper()
                    if any(d in day_cand for d in ["ПОНЕДЕЛЬНИК", "ВТОРНИК", "СРЕДА", "ЧЕТВЕРГ", "ПЯТНИЦА", "СУББОТА"]):
                        curr_day = day_cand
                if not curr_day: continue
                for col_idx in range(2, len(row)):
                    if t_name_lower in row[col_idx].lower() and len(row[col_idx]) > 2:
                        pair_num = row[1].strip() if len(row) > 1 else "?"
                        subject = rows[i-1][col_idx].strip() if i > 0 and len(rows[i-1]) > col_idx else "Предмет?"
                        group_name = rows[1][col_idx].strip() if len(rows[1]) > col_idx else "Группа?"
                        room = get_room_safe(rows, i-1, col_idx)
                        all_lessons.append(f"📅 **{curr_day}**\n{pair_num} пара: {subject} — {group_name} [каб. {room}]")
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
    await message.answer("📝 Введите фамилию:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True))

@dp.message(UserState.waiting_for_teacher)
async def teacher_search(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад": return await start_cmd(message, state)
    m = await message.answer("⏳ Поиск...")
    res = await fetch_teacher_schedule(message.text)
    await m.edit_text(f"👨‍🏫 Расписание {message.text}:\n\n{res}", parse_mode="Markdown")

@dp.message(F.text == "🎓 Я студент")
async def student_mode(message: types.Message, state: FSMContext):
    kb = ReplyKeyboardBuilder()
    for c in GROUPS_BY_COURSE.keys(): kb.add(KeyboardButton(text=c))
    kb.row(KeyboardButton(text="⬅️ Назад"))
    await state.set_state(UserState.choosing_course)
    await message.answer("Выберите курс:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_course)
async def proc_course(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад": return await start_cmd(message, state)
    if message.text not in GROUPS_BY_COURSE: return
    await state.update_data(c=message.text); await state.set_state(UserState.choosing_group)
    kb = ReplyKeyboardBuilder()
    for g in GROUPS_BY_COURSE[message.text]: kb.add(KeyboardButton(text=g))
    kb.row(KeyboardButton(text="⬅️ Назад"))
    await message.answer(f"📍 Группа:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_group)
async def proc_group(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад": return await start_cmd(message, state)
    await state.update_data(g=message.text); await state.set_state(UserState.choosing_day)
    kb = ReplyKeyboardBuilder().row(KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📅 Завтра"))
    kb.row(KeyboardButton(text="🗓 На неделю"), KeyboardButton(text="⬅️ Назад"))
    await message.answer(f"🕒 Период:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_day)
async def proc_day(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад": return await start_cmd(message, state)
    data = await state.get_data()
    days = ['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА', 'СУББОТА', 'ВОСКРЕСЕНЬЕ']
    t = days[datetime.now().weekday()] if "Сегодня" in message.text else days[(datetime.now() + timedelta(days=1)).weekday()] if "Завтра" in message.text else None
    res = await fetch_student_schedule(data.get('c'), data.get('g'), t)
    await message.answer(f"📋 **{data.get('g')}**\n{res}", parse_mode="Markdown")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
