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

# --- CONFIG ---
BOT_TOKEN = "7987454041:AAGU-DGvVqgN7rioySxL5zINEk60WSlkUW4"
GOOGLE_API_KEY = "AIzaSyDZUuMn8B8t_REygaEGpEI47hyLSQrDKDk"
SCHEDULE_TABLE_ID = "1X6YF54l1rgP7MFfkTa1b_L6f4f3aWuADZwF8wwTWKK4"
DB_TABLE_ID = "11KbeilP1HRonHQAAZusBS1-ffNo4FxHXa239yZMKJm8"
OWNER_ID = 879365319 
TABLE_URL = f"https://docs.google.com/spreadsheets/d/{SCHEDULE_TABLE_ID}/edit"

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

class AdminState(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_ban = State()
    waiting_for_new_admin = State()

# --- SHEETS CONNECT ---
users_ws = None; blacklist_ws = None; settings_ws = None; channels_ws = None; admins_ws = None

def init_sheets():
    global users_ws, blacklist_ws, settings_ws, channels_ws, admins_ws
    try:
        creds_json = os.environ.get("GOOGLE_CREDS")
        if not creds_json:
            logging.error("GOOGLE_CREDS NOT FOUND")
            return
        creds_dict = json.loads(creds_json)
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        db_sheet = client.open_by_key(DB_TABLE_ID)
        
        users_ws = db_sheet.worksheet("Users")
        blacklist_ws = db_sheet.worksheet("Blacklist")
        settings_ws = db_sheet.worksheet("Settings")
        channels_ws = db_sheet.worksheet("Channels")
        admins_ws = db_sheet.worksheet("Admins")
        logging.info("Sheets connected!")
    except Exception as e:
        logging.error(f"Error init sheets: {e}")

init_sheets()

# --- HELPERS ---
async def get_admins():
    try: return [int(i) for i in admins_ws.col_values(1) if i.isdigit()] if admins_ws else [OWNER_ID]
    except: return [OWNER_ID]

async def is_sub_on():
    try: return settings_ws.cell(1, 2).value == "on" if settings_ws else True
    except: return True

async def check_subs(uid):
    if uid == OWNER_ID or uid in await get_admins(): return True
    if not await is_sub_on(): return True
    try:
        chs = channels_ws.get_all_values() if channels_ws else []
        for r in chs:
            m = await bot.get_chat_member(r[0], uid)
            if m.status not in ["member", "administrator", "creator"]: return False
    except: pass
    return True

# --- TEACHER SEARCH ---
async def search_teacher(name):
    name = name.lower().strip()
    res = []
    async with aiohttp.ClientSession() as session:
        for c in ["1 курс", "2 курс", "3 курс", "4 курс"]:
            url = f"https://sheets.googleapis.com/v4/spreadsheets/{SCHEDULE_TABLE_ID}/values/{c}!A1:BG100?key={GOOGLE_API_KEY}"
            async with session.get(url) as r:
                data = await r.json()
                rows = data.get("values", [])
            if not rows: continue
            for r_idx, row in enumerate(rows[2:], 2):
                day = next((rows[i][0] for i in range(r_idx, 1, -1) if len(rows[i]) > 0 and rows[i][0].strip()), "???")
                pair = row[1] if len(row) > 1 else "?"
                for c_idx, cell in enumerate(row):
                    if name in cell.lower():
                        grp = rows[1][c_idx] if len(rows[1]) > c_idx else "???"
                        cab = f" (каб. {row[c_idx+1]})" if len(row) > c_idx+1 and row[c_idx+1].isdigit() else ""
                        res.append(f"📅 {day} | {pair} пара | {grp}{cab}")
    return "\n".join(res) if res else "❌ Не найдено."

# --- HANDLERS ---
@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    try:
        if users_ws and str(uid) not in users_ws.col_values(1):
            users_ws.append_row([str(uid), f"@{message.from_user.username}", datetime.now().strftime("%d.%m.%Y")])
    except: pass

    if not await check_subs(uid):
        kb = InlineKeyboardBuilder()
        chs = channels_ws.get_all_values() if channels_ws else []
        for r in chs: kb.row(InlineKeyboardButton(text=r[2], url=r[1]))
        kb.row(InlineKeyboardButton(text="✅ Проверить", callback_data="check"))
        return await message.answer("📢 Подпишитесь для доступа:", reply_markup=kb.as_markup())

    await state.clear()
    kb = ReplyKeyboardBuilder()
    for c in GROUPS_BY_COURSE.keys(): kb.add(KeyboardButton(text=c))
    kb.row(KeyboardButton(text="👨‍🏫 Я преподаватель"))
    await message.answer("🎓 Выберите курс или режим:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(F.text == "👨‍🏫 Я преподаватель")
async def t_mode(message: types.Message, state: FSMContext):
    await state.set_state(UserState.waiting_for_teacher_name)
    await message.answer("📝 Введите фамилию (Пример: Петров А.В.):", 
                         reply_markup=ReplyKeyboardBuilder().add(KeyboardButton(text="⬅️ Назад")).as_markup(resize_keyboard=True))

@dp.message(UserState.waiting_for_teacher_name)
async def t_search(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад": return await start(message, state)
    m = await message.answer("🔍 Ищу...")
    res = await search_teacher(message.text)
    await m.edit_text(f"👨‍🏫 Расписание для: **{message.text}**\n\n{res}", parse_mode="Markdown")

@dp.message(Command("admin"))
async def admin(message: types.Message):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="📊 Статистика"))
    if message.from_user.id == OWNER_ID:
        on = await is_sub_on()
        kb.row(KeyboardButton(text=f"{'✅' if on else '❌'} Подписка: {'ВКЛ' if on else 'ВЫКЛ'}"))
        kb.row(KeyboardButton(text="➕ Админ"), KeyboardButton(text="➖ Админ"))
    kb.row(KeyboardButton(text="⬅️ Назад"))
    await message.answer("🛠 Админка:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "⬅️ Назад")
async def back_btn(message: types.Message, state: FSMContext):
    await start(message, state)

@dp.message(UserState.choosing_course)
async def course_sel(message: types.Message, state: FSMContext):
    if message.text not in GROUPS_BY_COURSE: return
    await state.update_data(c=message.text)
    await state.set_state(UserState.choosing_group)
    kb = ReplyKeyboardBuilder()
    for g in GROUPS_BY_COURSE[message.text]: kb.add(KeyboardButton(text=g))
    kb.add(KeyboardButton(text="⬅️ Назад"))
    await message.answer("📍 Группа:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_group)
async def group_sel(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад": return await start(message, state)
    await state.update_data(g=message.text)
    await state.set_state(UserState.choosing_day)
    kb = ReplyKeyboardBuilder().row(KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📅 Завтра"))
    kb.row(KeyboardButton(text="⬅️ Назад"))
    await message.answer("🕒 Период:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_day)
async def final_res(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад": return await start(message, state)
    data = await state.get_data()
    # Logic for schedule fetch here (get_schedule function from previous version)
    await message.answer(f"Запрос для {data['g']} на {message.text}")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
