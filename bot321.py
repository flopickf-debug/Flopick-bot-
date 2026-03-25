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
# БЛОК 1: НАСТРОЙКИ И ДАННЫЕ
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
    waiting_for_new_admin = State()
    waiting_for_del_admin = State()
    waiting_for_channel = State()
    waiting_for_del_channel = State()
    waiting_for_broadcast = State()

# =========================================================
# БЛОК 3: РАБОТА С GOOGLE TABLES
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

# =========================================================
# БЛОК 4: ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================================================
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

# =========================================================
# БЛОК 5: ЛОГИКА ПОИСКА РАСПИСАНИЯ
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
        if len(row) > 0 and row[0].strip(): curr_day = row[0].strip().upper()
        if not curr_day or (target_day and target_day.upper() not in curr_day): continue
        content = row[col].strip() if len(row) > col else ""
        if content:
            pair = row[1] if len(row) > 1 else "?"
            room = f" (каб. {row[col+1]})" if len(row) > col+1 and row[col+1].isdigit() else ""
            if curr_day not in res_dict: res_dict[curr_day] = []
            res_dict[curr_day].append(f" - {pair} пара: {content}{room}")
    
    output = ""
    for d, lessons in res_dict.items(): output += f"\n🟠 **{d}**\n" + "\n".join(lessons) + "\n"
    return output if output else "Занятий нет. 🎉"

async def search_teacher(name):
    name, res = name.lower().strip(), []
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
                        res.append(f"📅 {day} | {pair} пара | {grp}")
    return "\n".join(res) if res else "❌ Не найдено."

# =========================================================
# БЛОК 6: ПАНЕЛЬ АДМИНИСТРАТОРА И ЕЁ ФУНКЦИИ
# =========================================================
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

@dp.message(F.text.contains("Обяз. подписка:"), F.from_user.id == OWNER_ID)
async def toggle_sub(message: types.Message, state: FSMContext):
    if settings_ws:
        new_status = "off" if await is_sub_on() else "on"
        settings_ws.update_cell(1, 2, new_status)
        await admin_menu(message, state)

@dp.message(F.text == "➕ Назначить админа", F.from_user.id == OWNER_ID)
async def admin_add_start(message: types.Message, state: FSMContext):
    await state.set_state(AdminState.waiting_for_new_admin)
    await message.answer("Пришлите ID нового админа:", reply_markup=ReplyKeyboardBuilder().add(KeyboardButton(text="❌ Отмена")).as_markup(resize_keyboard=True))

@dp.message(AdminState.waiting_for_new_admin)
async def admin_add_finish(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена": return await admin_menu(message, state)
    if message.text.isdigit():
        admins_ws.append_row([message.text])
        await message.answer(f"✅ {message.text} теперь админ.")
    await admin_menu(message, state)

# =========================================================
# БЛОК 7: ХЕНДЛЕРЫ ДЛЯ СТУДЕНТОВ И УЧИТЕЛЕЙ
# =========================================================
@dp.message(Command("start"), StateFilter('*'))
@dp.message(F.text == "⬅️ Назад к курсам")
async def start(message: types.Message, state: FSMContext):
    if not await check_subs(message.from_user.id):
        kb = InlineKeyboardBuilder()
        for r in (channels_ws.get_all_values() if channels_ws else []): kb.row(InlineKeyboardButton(text=r[2], url=r[1]))
        kb.row(InlineKeyboardButton(text="✅ Проверить", callback_data="check"))
        return await message.answer("❗ Подпишитесь:", reply_markup=kb.as_markup())
    
    await state.clear(); await state.set_state(UserState.choosing_course)
    kb = ReplyKeyboardBuilder()
    for c in GROUPS_BY_COURSE.keys(): kb.add(KeyboardButton(text=c))
    kb.row(KeyboardButton(text="👨‍🏫 Я преподаватель"))
    await message.answer("🎓 Выберите курс:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_course)
async def select_course(message: types.Message, state: FSMContext):
    if message.text == "👨‍🏫 Я преподаватель":
        await state.set_state(UserState.waiting_for_teacher_name)
        return await message.answer("📝 Введите фамилию учителя:", 
                             reply_markup=ReplyKeyboardBuilder().add(KeyboardButton(text="⬅️ Назад к курсам")).as_markup(resize_keyboard=True))
    if message.text not in GROUPS_BY_COURSE: return
    await state.update_data(c=message.text); await state.set_state(UserState.choosing_group)
    kb = ReplyKeyboardBuilder()
    for g in GROUPS_BY_COURSE[message.text]: kb.add(KeyboardButton(text=g))
    kb.add(KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer(f"Группы {message.text}:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_group)
async def select_group(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к курсам": return await start(message, state)
    await state.update_data(g=message.text); await state.set_state(UserState.choosing_day)
    kb = ReplyKeyboardBuilder().row(KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📅 Завтра"))
    kb.row(KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer(f"Группа {message.text}:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_day)
async def show_schedule(message: types.Message, state: FSMContext):
    if "Назад" in message.text: return await start(message, state)
    data = await state.get_data(); days = ['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА', 'СУББОТА', 'ВОСКРЕСЕНЬЕ']
    target = days[datetime.now().weekday()] if "Сегодня" in message.text else days[(datetime.now() + timedelta(days=1)).weekday()]
    res = await fetch_schedule(data['c'], data['g'], target)
    await message.answer(f"🗓 **{data['g']} ({target})**\n{res}", parse_mode="Markdown")

@dp.message(UserState.waiting_for_teacher_name)
async def teacher_search_result(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к курсам": return await start(message, state)
    res = await search_teacher(message.text)
    await message.answer(f"👨‍🏫 **Расписание {message.text}:**\n\n{res}", parse_mode="Markdown")

# =========================================================
# БЛОК 8: ЗАПУСК
# =========================================================
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
