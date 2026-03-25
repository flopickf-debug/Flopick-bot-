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
# БЛОК 3: ТАБЛИЦЫ
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
# БЛОК 4: ЛОГИКА ПАРСИНГА (ИСПРАВЛЕНО)
# =========================================================
async def fetch_schedule(course, group, target_day=None):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SCHEDULE_TABLE_ID}/values/{course}!A1:BG100?key={GOOGLE_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            rows = data.get("values", [])
    
    if not rows: return "⚠️ Таблица пуста."
    
    # Ищем колонку группы (строка 2)
    col_idx = -1
    for i, cell in enumerate(rows[1]):
        if group.lower() in cell.lower():
            col_idx = i
            break
            
    if col_idx == -1: return f"⚠️ Группа {group} не найдена."
    
    res_dict, curr_day = {}, ""
    for r_idx, row in enumerate(rows[2:], 2):
        # Определяем день недели (колонка A)
        if len(row) > 0 and row[0].strip():
            curr_day = row[0].strip().upper()
        
        if not curr_day: continue
        if target_day and target_day.upper() not in curr_day: continue
            
        content = row[col_idx].strip() if len(row) > col_idx else ""
        if content and content != "-":
            pair_num = row[1] if len(row) > 1 else "?"
            # Кабинет обычно в следующей колонке после предмета
            room = ""
            if len(row) > col_idx + 1:
                potential_room = row[col_idx+1].strip()
                if potential_room: room = f" [каб. {potential_room}]"
            
            if curr_day not in res_dict: res_dict[curr_day] = []
            res_dict[curr_day].append(f"• {pair_num} пара: {content}{room}")
    
    if not res_dict: return "🎉 Занятий не найдено!"
    
    output = ""
    for day, lessons in res_dict.items():
        output += f"\n📅 **{day}**\n" + "\n".join(lessons) + "\n"
    return output

async def search_teacher(name):
    name = name.lower().strip()
    results = []
    async with aiohttp.ClientSession() as session:
        for course in ["1 курс", "2 курс", "3 курс", "4 курс"]:
            url = f"https://sheets.googleapis.com/v4/spreadsheets/{SCHEDULE_TABLE_ID}/values/{course}!A1:BG100?key={GOOGLE_API_KEY}"
            async with session.get(url) as r:
                data = await r.json()
                rows = data.get("values", [])
            
            if not rows: continue
            groups_row = rows[1]
            
            curr_day = ""
            for r_idx, row in enumerate(rows[2:], 2):
                if len(row) > 0 and row[0].strip():
                    curr_day = row[0].strip()
                
                pair_num = row[1] if len(row) > 1 else "?"
                
                for c_idx, cell in enumerate(row):
                    if c_idx < 2: continue # Пропускаем День и Номер пары
                    if name in cell.lower():
                        grp_name = groups_row[c_idx] if len(groups_row) > c_idx else "Неизв."
                        # Ищем кабинет рядом
                        room = ""
                        if len(row) > c_idx + 1 and row[c_idx+1].strip():
                            room = f" (каб. {row[c_idx+1]})"
                        
                        results.append(f"📅 {curr_day} | {pair_num} пара | Гр: {grp_name}{room}")
    
    return "\n".join(results) if results else "❌ Преподаватель не найден."

# =========================================================
# БЛОК 5: ОБРАБОТЧИКИ (ОСТАЛЬНОЕ БЕЗ ИЗМЕНЕНИЙ)
# =========================================================
@dp.message(Command("start"), StateFilter('*'))
@dp.message(F.text == "⬅️ Назад к курсам")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    kb = ReplyKeyboardBuilder()
    for c in GROUPS_BY_COURSE.keys(): kb.add(KeyboardButton(text=c))
    kb.row(KeyboardButton(text="👨‍🏫 Я преподаватель"))
    await state.set_state(UserState.choosing_course)
    await message.answer("🎓 Выберите ваш курс:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.сообщение(Состояние пользователя.выбор_курса)
асинхронный деф процесс_курс(сообщение: типы.Сообщение, состояние: FSMContext):
    если сообщение.текст == "👨‍🏫 Я преподаватель":
        ждать состояние.установить_состояние(Состояние пользователя.ожидание_имени_учителя)
        возвращаться ждать сообщение.отвечать("📝 Введите фамилию (Пример: Иванов):", 
 ответ_разметка=ОтветитьKeyboardBuilder().добавлять(КлавиатураКнопка(текст="⬅️ Назад к курсам")).как_разметка(изменить размер_клавиатуры=Истинный))
    если сообщение.текст нет в ГРУППЫ_ПО_КУРСУ: возвращаться
    ждать состояние.обновить_данные(с=сообщение.текст)
 кб = ОтветитьKeyboardBuilder()
    для g в ГРУППЫ_ПО_КУРСУ[сообщение.текст]: кб.добавлять(КлавиатураКнопка(текст=г))
 кб.ряд(КлавиатураКнопка(текст="⬅️ Назад к курсам"))
    ждать состояние.установить_состояние(Состояние пользователя.выбираем_группу)
    ждать сообщение.отвечать(ф"📍 {сообщение.текст}. . Выберите группу:", reply_markup=кб.регулировать(2).как_разметка(изменить размер_клавиатуры=Истинный))

@dp.сообщение(Состояние пользователя.выбираем_группу)
асинхронный деф группа_процесса(сообщение: типы.Сообщение, состояние: FSMContext):
    если сообщение.текст == "⬅️ Назад к курсам": возвращаться ждать cmd_start(сообщение, состояние)
    ждать состояние.обновить_данные(г=сообщение.текст)
 кб = ОтветитьKeyboardBuilder()
 кб.ряд(КлавиатураКнопка(текст="📅 Сегодня"), КлавиатураКнопка(текст="📅 Завтра"))
 кб.ряд(КлавиатураКнопка(текст="🗓 На всю неделю"))
 кб.ряд(КлавиатураКнопка(текст="⬅️ Назад к курсам"))
    ждать состояние.установить_состояние(Состояние пользователя.выбор_дня)
    ждать сообщение.отвечать(ф"🕒 Группа {сообщение.текст}:", reply_markup=кб.как_разметка(изменить размер_клавиатуры=Истинный))

@dp.сообщение(Состояние пользователя.выбор_дня)
асинхронный деф процесс_день(сообщение: типы.Сообщение, состояние: FSMContext):
    если сообщение.текст == "⬅️ Назад к курсам": возвращаться ждать cmd_start(сообщение, состояние)
 данные = ждать состояние.получить_данные()
 дней = ['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА', 'СУББОТА', 'ВОСКРЕСЕНЬЕ']
    
 цель = Нет
    если "Сегодня" в сообщение.текст:
 цель = дни[дата и время.сейчас().будний день()]
    Элиф "Завтра" в сообщение.текст:
 цель = дни[(дата и время.сейчас() + timedelta(дней=1)).будний день()]
        
 рез = ждать fetch_schedule(данные['с'], данные['г'], цель)
    ждать сообщение.отвечать(f"📋 **Расписание {данные['г']}**\н{рез}", режим_анализа="Маркдаун")

@dp.сообщение(Состояние пользователя.ожидание_имени_учителя)
асинхронный деф учитель_поиск(сообщение: типы.Сообщение, состояние: FSMContext):
    если сообщение.текст == "⬅️ Назад к курсам": возвращаться ждать cmd_start(сообщение, состояние)
 м = ждать сообщение.отвечать("🔍 Ищу в таблицах...")
 рез = ждать поиск_учителя(сообщение.текст)
    ждать м.редактировать_текст(f"👨‍🏫 **Результы поиска:**\n\n{рез}", режим_анализа="Маркдаун")

@dp.сообщение(Команда("админ"))
асинхронный деф админ_панель(сообщение: типы.Сообщение, состояние: FSMContext):
    если сообщение.от_пользователя.идентификатор нет в ждать get_admins(): возвращаться
    ждать состояние.прозрачный()
 кб = ОтветитьKeyboardBuilder()
 кб.ряд(КлавиатураКнопка(текст="📢 Рассылка"), КлавиатураКнопка(текст="📊 Статистика"))
    если сообщение.от_пользователя.идентификатор == ИДЕНТИФИКАТОР_ВЛАДЕЛЬЦА:
 кб.ряд(КлавиатураКнопка(текст="📁 Список юзеров"), КлавиатураКнопка(текст="⬅️ Назад к курсам"))
    ждать сообщение.отвечать("🛠 Админ-панель", reply_markup=кб.как_разметка(изменить размер_клавиатуры=Истинный))

асинхронный деф основной():
    ждать бот.удалить_вебхук(drop_pending_updates=Истинный)
    ждать дп.старт_опроса(бот)

если __имя__ == "__основной__":
 асинсио.бегать(основной())
