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
from aiogram.types import InlineKeyboardButton, KeyboardButton, FSInputFile
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

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

# =========================================================
# БЛОК 2: СОСТОЯНИЯ (FSM)
# =========================================================
class UserState(StatesGroup):
    choosing_course = State()
    choosing_group = State()
    choosing_day = State()
    waiting_for_teacher_name = State()

class AdminState(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_new_admin = State()
    waiting_for_del_admin = State()
    waiting_for_channel = State()
    waiting_for_del_channel = State()

# =========================================================
# БЛОК 3: РАБОТА С ТАБЛИЦАМИ
# =========================================================
users_ws = None; settings_ws = None; channels_ws = None; admins_ws = None

def init_sheets():
    global users_ws, settings_ws, channels_ws, admins_ws
    try:
        creds_json = os.environ.get("GOOGLE_CREDS")
        if not creds_json: return
        creds_dict = json.loads(creds_json)
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        db_sheet = client.open_by_key(DB_TABLE_ID)
        users_ws = db_sheet.worksheet("Users")
        settings_ws = db_sheet.worksheet("Settings")
        channels_ws = db_sheet.worksheet("Channels")
        admins_ws = db_sheet.worksheet("Admins")
    except Exception as e: logging.error(f"Sheets error: {e}")

init_sheets()

async def get_admins():
    try: return [int(i) for i in admins_ws.col_values(1) if i.isdigit()] if admins_ws else [OWNER_ID]
    except: return [OWNER_ID]

async def is_sub_on():
    try: return settings_ws.cell(1, 2).value == "on" if settings_ws else True
    except: return True

# =========================================================
# БЛОК 4: ГЛАВНАЯ ЛОГИКА РАСПИСАНИЯ
# =========================================================
async def fetch_schedule(course, group, target_day=None):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SCHEDULE_TABLE_ID}/values/{course}!A1:BG100?key={GOOGLE_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            rows = data.get("values", [])
    
    if not rows: return "⚠️ Таблица пуста."
    col = next((i for i, cell in enumerate(rows[1]) if group.lower() in cell.lower()), -1)
    if col == -1: return f"⚠️ Группа {group} не найдена."
    
    res_dict, curr_day = {}, ""
    for row in rows[2:]:
        if len(row) > 0 and row[0].strip():
            curr_day = row[0].strip().upper()
        
        # Если ищем конкретный день
        if target_day and curr_day and target_day.upper() not in curr_day:
            continue
            
        content = row[col].strip() if len(row) > col else ""
        if content:
            pair = row[1] if len(row) > 1 else "?"
            room = f" [каб. {row[col+1]}]" if len(row) > col+1 and row[col+1] else ""
            if curr_day not in res_dict: res_dict[curr_day] = []
            res_dict[curr_day].append(f"• {pair} пара: {content}{room}")
    
    if not res_dict: return "🎉 Занятий не найдено!"
    
    output = ""
    for day, lessons in res_dict.items():
        output += f"\n📅 **{day}**\n" + "\n".join(lessons) + "\n"
    return output

# =========================================================
# БЛОК 5: ОБРАБОТКА ПОЛЬЗОВАТЕЛЬСКОГО ПУТИ
# =========================================================
@dp.message(Command("start"), StateFilter('*'))
@dp.message(F.text == "⬅️ Назад к курсам")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    # Сохранение юзера в БД (упрощенно)
    try:
        if users_ws and not users_ws.find(str(message.from_user.id)):
            users_ws.append_row([str(message.from_user.id), message.from_user.full_name, datetime.now().strftime("%d.%m.%Y")])
    except: pass

    kb = ReplyKeyboardBuilder()
    for c in GROUPS_BY_COURSE.keys(): kb.add(KeyboardButton(text=c))
    kb.row(KeyboardButton(text="👨‍🏫 Я преподаватель"))
    await state.set_state(UserState.choosing_course)
    await message.answer("🎓 Выберите ваш курс:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_course)
async def process_course(message: types.Message, state: FSMContext):
    if message.text == "👨‍🏫 Я преподаватель":
        await state.set_state(UserState.waiting_for_teacher_name)
        return await message.answer("📝 Введите фамилию (Пример: Иванов И.И.):", 
                             reply_markup=ReplyKeyboardBuilder().add(KeyboardButton(text="⬅️ Назад к курсам")).as_markup(resize_keyboard=True))
    
    if message.text not in GROUPS_BY_COURSE: return
    await state.update_data(c=message.text)
    kb = ReplyKeyboardBuilder()
    for g in GROUPS_BY_COURSE[message.text]: kb.add(KeyboardButton(text=g))
    kb.row(KeyboardButton(text="⬅️ Назад к курсам"))
    await state.set_state(UserState.choosing_group)
    await message.answer(f"📍 Курс {message.text}. Выберите группу:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_group)
async def process_group(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к курсам": return await cmd_start(message, state)
    await state.update_data(g=message.text)
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📅 Завтра"))
    kb.row(KeyboardButton(text="🗓 На всю неделю"))
    kb.row(KeyboardButton(text="⬅️ Назад к курсам"))
    await state.set_state(UserState.choosing_day)
    await message.answer(f"🕒 Группа {message.text}. Выберите период:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_day)
async def process_day(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к курсам": return await cmd_start(message, state)
    data = await state.get_data()
    days = ['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА', 'СУББОТА', 'ВОСКРЕСЕНЬЕ']
    
    target = None
    if "Сегодня" in message.text:
        target = days[datetime.now().weekday()]
    elif "Завтра" in message.text:
        target = days[(datetime.now() + timedelta(days=1)).weekday()]
    elif "На всю неделю" in message.text:
        target = None # fetch_schedule поймет, что нужно всё
        
    res = await fetch_schedule(data['c'], data['g'], target)
    await message.answer(f"📋 **Расписание {data['g']}**\n{res}", parse_mode="Markdown")

# =========================================================
# БЛОК 6: ПАНЕЛЬ АДМИНА (ПОЛНАЯ)
# =========================================================
@dp.message(Command("admin"))
async def admin_panel(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in await get_admins(): return
    await state.clear()
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="📊 Статистика"))
    kb.row(KeyboardButton(text="🚫 Забанить"), KeyboardButton(text="✅ Разбанить"))
    
    if user_id == OWNER_ID:
        status = "ВКЛ" if await is_sub_on() else "ВЫКЛ"
        kb.row(KeyboardButton(text=f"✅ Обяз. подписка: {status}"))
        kb.row(KeyboardButton(text="➕ Назначить админа"), KeyboardButton(text="➖ Снять админа"))
        kb.row(KeyboardButton(text="➕ Добавить канал"), KeyboardButton(text="🗑 Удалить канал"))
        kb.row(KeyboardButton(text="📁 Список юзеров"))
    kb.row(KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer("🛠 **Панель управления**", reply_markup=kb.as_markup(resize_keyboard=True))

# Логика рассылки
@dp.message(F.text == "📢 Рассылка")
async def start_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id not in await get_admins(): return
    await state.set_state(AdminState.waiting_for_broadcast)
    await message.answer("📝 Введите текст рассылки (или 'Отмена'):", reply_markup=ReplyKeyboardBuilder().add(KeyboardButton(text="Отмена")).as_markup(resize_keyboard=True))

@dp.message(AdminState.waiting_for_broadcast)
async def do_broadcast(message: types.Message, state: FSMContext):
    if message.text == "Отмена": return await admin_panel(message, state)
    ids = users_ws.col_values(1) if users_ws else []
    count = 0
    for uid in ids:
        try:
            await bot.send_message(uid, message.text)
            count += 1
            await asyncio.sleep(0.05)
        except: pass
    await message.answer(f"✅ Рассылка завершена. Получили {count} чел.")
    await admin_panel(message, state)

# Статистика
@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    if message.from_user.id not in await get_admins(): return
    count = len(users_ws.col_values(1)) if users_ws else 0
    await message.answer(f"📈 Всего пользователей в базе: **{count}**", parse_mode="Markdown")

# =========================================================
# БЛОК 7: ЗАПУСК
# =========================================================
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
