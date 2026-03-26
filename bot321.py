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

# --- ИНИЦИАЛИЗАЦИЯ ТАБЛИЦ ---
users_ws = None; blacklist_ws = None; settings_ws = None; channels_ws = None; admins_ws = None

def init_sheets():
    global users_ws, blacklist_ws, settings_ws, channels_ws, admins_ws
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_json = os.environ.get("GOOGLE_CREDS")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), scope) if creds_json else ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
        client = gspread.authorize(creds)
        db = client.open_by_key(DB_TABLE_ID)
        users_ws = db.worksheet("Users")
        blacklist_ws = db.worksheet("Blacklist")
        settings_ws = db.worksheet("Settings")
        channels_ws = db.worksheet("Channels")
        admins_ws = db.worksheet("Admins")
        logging.info("✅ База данных подключена успешно!")
    except Exception as e:
        logging.error(f"❌ Ошибка подключения: {e}")

init_sheets()

# --- ФУНКЦИИ ПРОВЕРКИ ---
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
        for ch in chans:
            try:
                member = await bot.get_chat_member(ch[0], user_id)
                if member.status in ["left", "kicked"]: return False
            except: continue
        return True
    except: return True

def get_room_safe(rows, r_idx, c_idx):
    """Ищет кабинет в ячейках справа от предмета"""
    try:
        row = rows[r_idx]
        for offset in range(1, 4):
            if len(row) > c_idx + offset:
                val = str(row[c_idx + offset]).strip()
                if val and val.lower() not in ["-", ".", "каб", "пара"]: return val
    except: pass
    return ""

# --- ПАРСИНГ РАСПИСАНИЯ ---
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
        if not row or not row[0:1]: continue
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
            
            # --- ИСПРАВЛЕНО: Теперь кабинеты добавляются в вывод ---
            room = get_room_safe(rows, i, col_idx)
            room_str = f" [каб. {room}]" if room else ""

            if curr_day not in res_dict: res_dict[curr_day] = []
            res_dict[curr_day].append(f"• {pair_num} пара: {content}{teacher}{room_str}")
    
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
                if not row or not row[0:1]: continue
                day_cand = str(row[0]).replace('\n', ' ').strip().upper()
                if any(d in day_cand for d in ["ПОНЕДЕЛЬНИК", "ВТОРНИК", "СРЕДА", "ЧЕТВЕРГ", "ПЯТНИЦА", "СУББОТА"]): curr_day = day_cand
                if not curr_day: continue
                for col_idx in range(2, len(row)):
                    cell_val = str(row[col_idx]).strip().lower()
                    if t_name_lower in cell_val and len(cell_val) > 2:
                        p = row[1] if len(row) > 1 else "?"
                        g = str(rows[1][col_idx]).strip() if len(rows) > 1 and len(rows[1]) > col_idx else "?"
                        r = get_room_safe(rows, i-1, col_idx)
                        all_lessons.append(f"📅 **{curr_day}**\n{p} пара: {g} [каб. {r}]")
    return "\n\n".join(all_lessons) if all_lessons else "🔍 Преподаватель не найден или пар нет."

# --- АДМИН-ПАНЕЛЬ ---
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id not in await get_admins(): return
    sub_status = "ВКЛ" if await is_sub_required() else "ВЫКЛ"
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="📊 Статистика"))
    kb.row(KeyboardButton(text="🚫 Забанить"), KeyboardButton(text="✅ Разбанить"))
    kb.row(KeyboardButton(text=f"✅ Обяз. подписка: {sub_status}"))
    kb.row(KeyboardButton(text="➕ Назначить админа"), KeyboardButton(text="➖ Снять админа"))
    kb.row(KeyboardButton(text="➕ Добавить канал"), KeyboardButton(text="🗑 Удалить канал"))
    kb.row(KeyboardButton(text="📁 Список юзеров"), KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer("🛠 **Панель управления**", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text.contains("Обяз. подписка:"))
async def toggle_sub(message: types.Message):
    if message.from_user.id != OWNER_ID: return
    new_val = "off" if "ВКЛ" in message.text else "on"
    settings_ws.update_cell(1, 2, new_val)
    await admin_panel(message)

@dp.message(F.text == "📢 Рассылка")
async def broad_start(message: types.Message, state: FSMContext):
    await message.answer("Введите сообщение для всех:"); await state.set_state(AdminState.broadcast)

@dp.message(AdminState.broadcast)
async def broad_exec(message: types.Message, state: FSMContext):
    u_ids = users_ws.col_values(1)[1:]
    await message.answer(f"🚀 Рассылаю на {len(u_ids)} чел...")
    for uid in u_ids:
        try: await bot.send_message(uid, message.text); await asyncio.sleep(0.05)
        except: pass
    await message.answer("✅ Готово!"); await state.clear()

@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    u = len(users_ws.col_values(1)) - 1
    b = len(blacklist_ws.col_values(1))
    await message.answer(f"📊 Всего юзеров: {u}\n🚫 В бане: {b}")

@dp.message(F.text == "🚫 Забанить")
async def ban_s(message: types.Message, state: FSMContext):
    await message.answer("Введите ID для бана:"); await state.set_state(AdminState.ban)

@dp.message(AdminState.ban)
async def ban_e(message: types.Message, state: FSMContext):
    blacklist_ws.append_row([message.text.strip()])
    await message.answer("✅ Забанен."); await state.clear()

@dp.message(F.text == "✅ Разбанить")
async def unban_s(message: types.Message, state: FSMContext):
    await message.answer("Введите ID для разбана:"); await state.set_state(AdminState.unban)

@dp.message(AdminState.unban)
async def unban_e(message: types.Message, state: FSMContext):
    try:
        cell = blacklist_ws.find(message.text.strip())
        blacklist_ws.delete_rows(cell.row); await message.answer("✅ Разбанен.")
    except: await message.answer("❌ Нет в списке."); await state.clear()

@dp.message(F.text == "➕ Добавить канал")
async def add_ch_s(message: types.Message, state: FSMContext):
    await message.answer("Формат: `ID | Ссылка | Название`", parse_mode="Markdown"); await state.set_state(AdminState.add_channel)

@dp.message(AdminState.add_channel)
async def add_ch_e(message: types.Message, state: FSMContext):
    try:
        channels_ws.append_row([i.strip() for i in message.text.split("|")])
        await message.answer("✅ Добавлен."); await state.clear()
    except: await message.answer("❌ Ошибка формата.")

@dp.message(F.text == "🗑 Удалить канал")
async def del_ch_s(message: types.Message, state: FSMContext):
    await message.answer("Введите название канала:"); await state.set_state(AdminState.del_channel)

@dp.message(AdminState.del_channel)
async def del_ch_e(message: types.Message, state: FSMContext):
    try:
        cell = channels_ws.find(message.text.strip())
        channels_ws.delete_rows(cell.row); await message.answer("✅ Удален."); await state.clear()
    except: await message.answer("❌ Не найден."); await state.clear()

@dp.message(F.text == "📁 Список юзеров")
async def send_u_list(message: types.Message):
    u_ids = users_ws.col_values(1)[1:]
    file = BufferedInputFile("\n".join(u_ids).encode(), filename="users.txt")
    await message.answer_document(file, caption="Список всех пользователей")

# --- ПОЛЬЗОВАТЕЛЬСКАЯ ЧАСТЬ ---
@dp.сообщение(Команда("старт"), Фильтр состояний('*'))
@dp.сообщение(Ф.текст == "⬅️ Назад к курсам")
асинхронный деф cmd_start(сообщение: типы.Сообщение, состояние: FSMContext):
    если ждать is_banned(сообщение.от_пользователя.идентификатор): возвращаться
 uid = стр(сообщение.от_пользователя.идентификатор)
    пытаться:
        если нет пользователи_ws.находить(уид): пользователи_ws.добавить_строку([uid, дата и время.сейчас().время страйфтайма("%д.%м.%Y")])
    кроме: проходить
    
    если нет ждать проверить_под(сообщение.от_пользователя.идентификатор):
 кб = InlineKeyboardBuilder()
        для ч в каналы_ws.получить_все_значения(): кб.ряд(Кнопка встроенной клавиатуры(текст=ч[2], URL=ch[1]))
        возвращаться ждать сообщение.отвечать("⚠️ Для работы бота нужно подписаться:", reply_markup=кб.как_разметка())

    ждать состояние.прозрачный()
 кб = ОтветитьKeyboardBuilder()
    для c в ГРУППЫ_ПО_КУРСУ.ключи(): кб.добавлять(КлавиатураКнопка(текст=с))
 кб.ряд(КлавиатураКнопка(текст="👨‍🏫 Я преподаватель"))
    ждать сообщение.отвечать("🎓 Выберите ваш курс:", reply_markup=кб.регулировать(2).как_разметка(изменить размер_клавиатуры=Истинный))

@dp.сообщение(Ф.текст.в_(ГРУППЫ_ПО_КУРСУ.ключи()))
асинхронный деф set_course(сообщение: типы.Сообщение, состояние: FSMContext):
    ждать состояние.обновить_данные(с=сообщение.текст); ждать состояние.установить_состояние(Состояние пользователя.группа)
 кб = ОтветитьKeyboardBuilder()
    для g в ГРУППЫ_ПО_КУРСУ[сообщение.текст]: кб.добавлять(КлавиатураКнопка(текст=г))
 кб.ряд(КлавиатураКнопка(текст="⬅️ Назад к курсам"))
    ждать сообщение.отвечать(f"📍 Список групп {сообщение.текст}:", reply_markup=кб.регулировать(2).как_разметка(изменить размер_клавиатуры=Истинный))

@dp.сообщение(Состояние пользователя.группа)
асинхронный деф установить_группу(сообщение: типы.Сообщение, состояние: FSMContext):
    если сообщение.текст == "⬅️ Назад к курсам": возвращаться ждать cmd_start(сообщение, состояние)
    ждать состояние.обновить_данные(г=сообщение.текст); ждать состояние.установить_состояние(Состояние пользователя.день)
 кб = ОтветитьKeyboardBuilder().ряд(КлавиатураКнопка(текст="📅 Сегодня"), КлавиатураКнопка(текст="📅 Завтра")).ряд(КлавиатураКнопка(текст="🗓 На неделю"), КлавиатураКнопка(текст="⬅️ Назад к курсам"))
    ждать сообщение.отвечать("🕒 Выберите период расписания:", reply_markup=кб.как_разметка(изменить размер_клавиатуры=Истинный))

@dp.сообщение(Состояние пользователя.день)
асинхронный деф показать_res(сообщение: типы.Сообщение, состояние: FSMContext):
    если "Назад" в сообщение.текст: возвращаться ждать cmd_start(сообщение, состояние)
 данные = ждать состояние.получить_данные(); дни = ['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА', 'СУББОТА', 'ВОСКРЕСЕНЬЕ']
 т = дни[дата и время.сейчас().будний день()] если "Сегодня" в сообщение.текст еще дней[(дата и время.сейчас() + timedelta(дней=1)).будний день()] если "Завтра" в сообщение.текст еще Нет
 рез = ждать расписание_студентов_принеси(данные.получать('с'), данные.получать('г'), т)
    ждать сообщение.отвечать(f"📋 **Расписание {данные.получать('г')}**\н{рез}", режим_анализа="Маркдаун")

@dp.сообщение(Ф.текст == "👨‍🏫 Я преподаватель")
асинхронный деф t_режим(сообщение: типы.Сообщение, состояние: FSMContext):
    ждать состояние.установить_состояние(Состояние пользователя.учитель)
    ждать сообщение.отвечать("📝 Введите вашу фамилию:", ответ_разметка=ОтветитьKeyboardBuilder().добавлять(КлавиатураКнопка(текст="⬅️ Назад к курсам")).как_разметка(изменить размер_клавиатуры=Истинный))

@dp.сообщение(Состояние пользователя.учитель)
асинхронный деф t_поиск(сообщение: типы.Сообщение, состояние: FSMContext):
    если "Назад" в сообщение.текст: возвращаться ждать cmd_start(сообщение, состояние)
 м = ждать сообщение.отвечать("🔎 Ищу пары..."); рез = ждать расписание_учителя_принеси(сообщение.текст)
    ждать м.редактировать_текст(ф"👨‍🏫 Переподать: {сообщение.текст}\н\н{рез}", режим_анализа="Маркдаун")

асинхронный деф основной():
    ждать бот.удалить_вебхук(drop_pending_updates=Истинный)
    ждать дп.старт_опроса(бот)

если __имя__ == "__основной__":
 асинсио.бегать(основной())
