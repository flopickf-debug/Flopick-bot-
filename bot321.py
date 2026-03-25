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

# --- СОСТОЯНИЯ ---
class UserState(StatesGroup):
    choosing_course = State()
    choosing_group = State()
    choosing_day = State()
    waiting_for_teacher_name = State()

class AdminState(StatesGroup):
    waiting_for_new_admin = State()
    waiting_for_del_admin = State()
    waiting_for_channel = State()
    waiting_for_del_channel = State()
    waiting_for_broadcast = State()

# --- ТАБЛИЦЫ ---
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

# --- АДМИН ПАНЕЛЬ ---
@dp.message(Command("admin"))
async def admin_menu(message: types.Message, state: FSMContext):
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
    await message.answer("🛠 **Панель администратора**", reply_markup=kb.as_markup(resize_keyboard=True))

# --- ЛОГИКА УПРАВЛЕНИЯ АДМИНАМИ И КАНАЛАМИ ---

# 1. Добавить админа
@dp.message(F.text == "➕ Назначить админа", F.from_user.id == OWNER_ID)
async def add_admin_step1(message: types.Message, state: FSMContext):
    await state.set_state(AdminState.waiting_for_new_admin)
    await message.answer("👤 Пришлите ID пользователя, которого хотите сделать админом:", 
                         reply_markup=ReplyKeyboardBuilder().add(KeyboardButton(text="❌ Отмена")).as_markup(resize_keyboard=True))

@dp.message(AdminState.waiting_for_new_admin)
async def add_admin_step2(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена": return await admin_menu(message, state)
    if message.text.isdigit():
        admins_ws.append_row([message.text])
        await message.answer(f"✅ Пользователь {message.text} назначен админом!")
        await admin_menu(message, state)
    else:
        await message.answer("⚠️ Ошибка! ID должен состоять только из цифр.")

# 2. Удалить админа
@dp.message(F.text == "➖ Снять админа", F.from_user.id == OWNER_ID)
async def del_admin_step1(message: types.Message, state: FSMContext):
    await state.set_state(AdminState.waiting_for_del_admin)
    current_admins = admins_ws.col_values(1)
    await message.answer(f"Список текущих админов:\n`{', '.join(current_admins)}` \n\nПришлите ID для удаления:", 
                         parse_mode="Markdown", reply_markup=ReplyKeyboardBuilder().add(KeyboardButton(text="❌ Отмена")).as_markup(resize_keyboard=True))

@dp.message(AdminState.waiting_for_del_admin)
async def del_admin_step2(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена": return await admin_menu(message, state)
    try:
        cell = admins_ws.find(message.text)
        admins_ws.delete_rows(cell.row)
        await message.answer(f"✅ Админ {message.text} успешно снят!")
    except:
        await message.answer("❌ Такой ID не найден в списке админов.")
    await admin_menu(message, state)

# 3. Добавить канал
@dp.message(F.text == "➕ Добавить канал", F.from_user.id == OWNER_ID)
async def add_chan_step1(message: types.Message, state: FSMContext):
    await state.set_state(AdminState.waiting_for_channel)
    await message.answer("📢 Пришлите данные канала в формате:\n`ID_канала | Ссылка | Название` \n\nПример:\n`-1001234567 | https://t.me/my_chan | Мой Канал`", 
                         parse_mode="Markdown", reply_markup=ReplyKeyboardBuilder().add(KeyboardButton(text="❌ Отмена")).as_markup(resize_keyboard=True))

@dp.message(AdminState.waiting_for_channel)
async def add_chan_step2(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена": return await admin_menu(message, state)
    try:
        data = [i.strip() for i in message.text.split("|")]
        if len(data) == 3:
            channels_ws.append_row(data)
            await message.answer("✅ Канал успешно добавлен в список проверки подписки!")
            await admin_menu(message, state)
        else:
            await message.answer("⚠️ Неверный формат! Используйте разделитель '|' (вертикальная черта).")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# 4. Удалить канал
@dp.message(F.text == "🗑 Удалить канал", F.from_user.id == OWNER_ID)
async def del_chan_step1(message: types.Message, state: FSMContext):
    await state.set_state(AdminState.waiting_for_del_channel)
    current_chans = channels_ws.col_values(3) # Список названий каналов
    await message.answer(f"Список каналов: {', '.join(current_chans)}\n\nПришлите ТОЧНОЕ название канала для удаления:", 
                         reply_markup=ReplyKeyboardBuilder().add(KeyboardButton(text="❌ Отмена")).as_markup(resize_keyboard=True))

@dp.message(AdminState.waiting_for_del_channel)
async def del_chan_step2(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена": return await admin_menu(message, state)
    try:
        cell = channels_ws.find(message.text)
        channels_ws.delete_rows(cell.row)
        await message.answer(f"✅ Канал '{message.text}' удален!")
    except:
        await message.answer("❌ Канал с таким названием не найден.")
    await admin_menu(message, state)

# --- ОСТАЛЬНАЯ ЛОГИКА (START, TEACHER, КУРСЫ) ---
@dp.message(F.text == "⬅️ Назад к курсам")
@dp.message(Command("start"), StateFilter('*'))
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    kb = ReplyKeyboardBuilder()
    for c in GROUPS_BY_COURSE.keys(): kb.add(KeyboardButton(text=c))
    kb.row(KeyboardButton(text="👨‍🏫 Я преподаватель"))
    await message.answer("🎓 Выберите ваш курс или режим:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(F.text == "👨‍🏫 Я преподаватель")
async def teacher_mode(message: types.Message, state: FSMContext):
    await state.set_state(UserState.waiting_for_teacher_name)
    await message.answer("📝 Введите вашу фамилию (например: Петров А.В.):", 
                         reply_markup=ReplyKeyboardBuilder().add(KeyboardButton(text="⬅️ Назад к курсам")).as_markup(resize_keyboard=True))

# [Здесь должны быть остальные хендлеры выбора курса и группы, как в предыдущих сообщениях]

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
