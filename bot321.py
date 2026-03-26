import logging
import asyncio
import gspread
import os
import json
import aiohttp
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, BufferedInputFile, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

# --- НАСТРОЙКИ (ПРОВЕРЬ ТОКЕНЫ) ---
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

# --- СОСТОЯНИЯ FSM ---
class AdminState(StatesGroup):
    broadcast = State()
    ban = State()
    unban = State()
    new_admin = State()
    del_admin = State()
    add_channel = State()
    del_channel = State()

class UserState(StatesGroup):
    course = State()
    group = State()
    day = State()
    teacher = State()

# --- ИНИЦИАЛИЗАЦИЯ ГУГЛ ТАБЛИЦ ---
users_ws = None; blacklist_ws = None; settings_ws = None; channels_ws = None; admins_ws = None

def init_sheets():
    global users_ws, blacklist_ws, settings_ws, channels_ws, admins_ws
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_json = os.environ.get("GOOGLE_CREDS")
        if creds_json:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
        
        client = gspread.authorize(creds)
        db = client.open_by_key(DB_TABLE_ID)
        users_ws = db.worksheet("Users")
        blacklist_ws = db.worksheet("Blacklist")
        settings_ws = db.worksheet("Settings")
        channels_ws = db.worksheet("Channels")
        admins_ws = db.worksheet("Admins")
        logging.info("✅ Все листы базы данных подключены!")
    except Exception as e:
        logging.error(f"❌ Ошибка подключения к Таблицам: {e}")

init_sheets()

# --- ПРОВЕРКИ И ФУНКЦИИ ---
async def get_admins():
    try: return [int(i) for i in admins_ws.col_values(1) if i.isdigit()]
    except: return [OWNER_ID]

async def is_banned(user_id):
    try: return str(user_id) in blacklist_ws.col_values(1)
    except: return False

async def is_sub_required():
    try: 
        val = settings_ws.cell(1, 2).value.lower()
        return val in ["вкл", "on", "yes"]
    except: return False

async def check_sub(user_id):
    if not await is_sub_required(): return True
    try:
        chans = channels_ws.get_all_values()
        for ch in chans: # ch[0] - ID канала (например @loveshaverma)
            member = await bot.get_chat_member(ch[0], user_id)
            if member.status in ["left", "kicked"]: return False
        return True
    except Exception: return True # Если ошибка доступа к каналу, пускаем

# (Функции парсинга расписания fetch_student_schedule и fetch_teacher_schedule остаются без изменений)
async def fetch_student_schedule(course, group, target_day=None):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SCHEDULE_TABLE_ID}/values/{course}!A1:BG100?key={GOOGLE_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json(); rows = data.get("values", [])
    if not rows: return "⚠️ Таблица пуста."
    col_idx = -1
    for r in range(min(5, len(rows))):
        for i, cell in enumerate(rows[r]):
            if group.lower() in str(cell).lower(): col_idx = i; break
        if col_idx != -1: break
    if col_idx == -1: return f"⚠️ Группа {group} не найдена."
    res_dict, curr_day = {}, ""
    for i in range(len(rows)):
        row = rows[i]
        if not row: continue
        if len(row) > 0 and str(row[0]).strip():
            day_val = str(row[0]).replace('\n', ' ').strip().upper()
            if any(d in day_val for d in ["ПОНЕДЕЛЬНИК", "ВТОРНИК", "СРЕДА", "ЧЕТВЕРГ", "ПЯТНИЦА", "СУББОТА"]): curr_day = day_val
        if not curr_day or (target_day and target_day.upper() not in curr_day): continue
        pair_num = row[1].strip() if len(row) > 1 else ""
        content = str(row[col_idx]).strip() if len(row) > col_idx else ""
        if pair_num and content and content not in ["-", ".", "№", "Ден"]:
            teacher = ""
            if i + 1 < len(rows) and len(rows[i+1]) > col_idx:
                t_val = rows[i+1][col_idx]
                if t_val: teacher = f" ({str(t_val).strip()})"
            if curr_day not in res_dict: res_dict[curr_day] = []
            res_dict[curr_day].append(f"• {pair_num} пара: {content}{teacher}")
    out = ""
    for d, lessons in res_dict.items(): out += f"\n📅 **{d}**\n" + "\n".join(lessons) + "\n"
    return out if out else "🎉 Занятий нет!"

async def fetch_teacher_schedule(teacher_name):
    all_lessons = []
    t_name_lower = teacher_name.lower()
    async with aiohttp.ClientSession() as session:
        for course in GROUPS_BY_COURSE.keys():
            url = f"https://sheets.googleapis.com/v4/spreadsheets/{SCHEDULE_TABLE_ID}/values/{course}!A1:BG100?key={GOOGLE_API_KEY}"
            async with session.get(url) as resp:
                data = await resp.json(); rows = data.get("values", [])
            if len(rows) < 3: continue
            curr_day = ""
            for i in range(2, len(rows)):
                row = rows[i]
                if not row: continue
                if len(row) > 0 and str(row[0]).strip():
                    day_cand = str(row[0]).replace('\n', ' ').strip().upper()
                    if any(d in day_cand for d in ["ПОНЕДЕЛЬНИК", "ВТОРНИК", "СРЕДА", "ЧЕТВЕРГ", "ПЯТНИЦА", "СУББОТА"]): curr_day = day_cand
                if not curr_day: continue
                for col_idx in range(2, len(row)):
                    cell_val = str(row[col_idx]).strip().lower()
                    if t_name_lower in cell_val and len(cell_val) > 2:
                        p = row[1] if len(row) > 1 else "?"
                        g = str(rows[1][col_idx]).strip() if len(rows) > 1 and len(rows[1]) > col_idx else "?"
                        all_lessons.append(f"📅 **{curr_day}**\n{p} пара: {g}")
    return "\n\n".join(all_lessons) if all_lessons else "🔍 Ничего не найдено."

# --- АДМИН-ХЕНДЛЕРЫ ---
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id not in await get_admins(): return
    status = "ВКЛ" if await is_sub_required() else "ВЫКЛ"
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="📊 Статистика"))
    kb.row(KeyboardButton(text="🚫 Забанить"), KeyboardButton(text="✅ Разбанить"))
    kb.row(KeyboardButton(text=f"✅ Обяз. подписка: {status}"))
    kb.row(KeyboardButton(text="➕ Назначить админа"), KeyboardButton(text="➖ Снять админа"))
    kb.row(KeyboardButton(text="➕ Добавить канал"), KeyboardButton(text="🗑 Удалить канал"))
    kb.row(KeyboardButton(text="📁 Список юзеров"), KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer("🔧 **Админ-панель**", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text.contains("Обяз. подписка:"))
async def toggle_sub(message: types.Message):
    if message.from_user.id != OWNER_ID: return
    new_val = "off" if "ВКЛ" in message.text else "on"
    settings_ws.update_cell(1, 2, new_val)
    await admin_panel(message)

@dp.message(F.text == "📢 Рассылка")
async def broad_start(message: types.Message, state: FSMContext):
    await message.answer("Введите текст:"); await state.set_state(AdminState.broadcast)

@dp.message(AdminState.broadcast)
async def broad_exec(message: types.Message, state: FSMContext):
    ids = users_ws.col_values(1)[1:]
    await message.answer(f"🚀 Рассылка на {len(ids)} чел...")
    for uid in ids:
        try: await bot.send_message(uid, message.text); await asyncio.sleep(0.05)
        except: pass
    await message.answer("✅ Готово!"); await state.clear()

@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    u = len(users_ws.col_values(1)) - 1
    b = len(blacklist_ws.col_values(1))
    await message.answer(f"📊 Пользователей: {u}\n🚫 В бане: {b}")

@dp.message(F.text == "🚫 Забанить")
async def ban_s(message: types.Message, state: FSMContext):
    await message.answer("Введите ID:"); await state.set_state(AdminState.ban)

@dp.message(AdminState.ban)
async def ban_e(message: types.Message, state: FSMContext):
    blacklist_ws.append_row([message.text.strip()])
    await message.answer("✅ Забанен"); await state.clear()

@dp.message(F.text == "✅ Разбанить")
async def unban_s(message: types.Message, state: FSMContext):
    await message.answer("Введите ID:"); await state.set_state(AdminState.unban)

@dp.message(AdminState.unban)
async def unban_e(message: types.Message, state: FSMContext):
    try:
        cell = blacklist_ws.find(message.text.strip())
        blacklist_ws.delete_rows(cell.row); await message.answer("✅ Разбанен")
    except: await message.answer("❌ Не найден")
    await state.clear()

@dp.message(F.text == "➕ Добавить канал")
async def add_c_s(message: types.Message, state: FSMContext):
    await message.answer("Формат: `ID | Ссылка | Название`", parse_mode="Markdown"); await state.set_state(AdminState.add_channel)

@dp.message(AdminState.add_channel)
async def add_c_e(message: types.Message, state: FSMContext):
    try:
        channels_ws.append_row([i.strip() for i in message.text.split("|")])
        await message.answer("✅ Добавлен"); await state.clear()
    except: await message.answer("❌ Ошибка формата")

@dp.message(F.text == "🗑 Удалить канал")
async def del_c_s(message: types.Message, state: FSMContext):
    await message.answer("Введите название канала:"); await state.set_state(AdminState.del_channel)

@dp.message(AdminState.del_channel)
async def del_c_e(message: types.Message, state: FSMContext):
    try:
        cell = channels_ws.find(message.text.strip())
        channels_ws.delete_rows(cell.row); await message.answer("✅ Удален")
    except: await message.answer("❌ Не найден")
    await state.clear()

@dp.message(F.text == "📁 Список юзеров")
async def send_u_list(message: types.Message):
    ids = users_ws.col_values(1)[1:]
    file = BufferedInputFile("\n".join(ids).encode(), filename="users.txt")
    await message.answer_document(file, caption="Список ID")

# --- ПОЛЬЗОВАТЕЛЬСКИЕ ХЕНДЛЕРЫ ---
@dp.message(Command("start"), StateFilter('*'))
@dp.message(F.text == "⬅️ Назад к курсам")
async def cmd_start(message: types.Message, state: FSMContext):
    if await is_banned(message.from_user.id): return
    uid = str(message.from_user.id)
    try:
        if not users_ws.find(uid): users_ws.append_row([uid, datetime.now().strftime("%d.%m.%Y")])
    except: users_ws.append_row([uid, datetime.now().strftime("%d.%m.%Y")])
    
    if not await check_sub(message.from_user.id):
        kb = InlineKeyboardBuilder()
        for ch in channels_ws.get_all_values(): kb.row(InlineKeyboardButton(text=ch[2], url=ch[1]))
        return await message.answer("⚠️ Подпишитесь на каналы:", reply_markup=kb.as_markup())

    await state.clear()
    kb = ReplyKeyboardBuilder()
    for c in GROUPS_BY_COURSE.keys(): kb.add(KeyboardButton(text=c))
    kb.row(KeyboardButton(text="👨‍🏫 Я преподаватель"))
    await message.answer("🎓 Выберите курс:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(F.text.in_(GROUPS_BY_COURSE.keys()))
async def set_course(message: types.Message, state: FSMContext):
    await state.update_data(c=message.text); await state.set_state(UserState.group)
    kb = ReplyKeyboardBuilder()
    for g in GROUPS_BY_COURSE[message.text]: kb.add(KeyboardButton(text=g))
    kb.row(KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer(f"📍 Группы {message.text}:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(UserState.group)
async def set_group(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к курсам": return await cmd_start(message, state)
    await state.update_data(g=message.text); await state.set_state(UserState.day)
    kb = ReplyKeyboardBuilder().row(KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📅 Завтра")).row(KeyboardButton(text="🗓 На неделю"), KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer("🕒 Выберите период:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.day)
async def show_res(message: types.Message, state: FSMContext):
    if "Назад" in message.text: return await cmd_start(message, state)
    data = await state.get_data(); days = ['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА', 'СУББОТА', 'ВОСКРЕСЕНЬЕ']
    t = days[datetime.now().weekday()] if "Сегодня" in message.text else days[(datetime.now() + timedelta(days=1)).weekday()] if "Завтра" in message.text else None
    res = await fetch_student_schedule(data.get('c'), data.get('g'), t)
    await message.answer(f"📋 **{data.get('g')}**\n{res}", parse_mode="Markdown")

@dp.message(F.text == "👨‍🏫 Я преподаватель")
async def t_mode(message: types.Message, state: FSMContext):
    await state.set_state(UserState.teacher)
    await message.answer("📝 Фамилия преподавателя:", reply_markup=ReplyKeyboardBuilder().add(KeyboardButton(text="⬅️ Назад к курсам")).as_markup(resize_keyboard=True))

@dp.message(UserState.teacher)
async def t_search(message: types.Message, state: FSMContext):
    if "Назад" in message.text: return await start_cmd(message, state)
    m = await message.answer("🔎 Поиск..."); res = await fetch_teacher_schedule(message.text)
    await m.edit_text(f"👨‍🏫 {message.text}:\n\n{res}", parse_mode="Markdown")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
