import logging
import asyncio
import aiohttp
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, BufferedInputFile
from aiogram.utils.keyboard import ReplyKeyboardBuilder

# --- КОНФИГУРАЦИЯ (ТВОИ ДАННЫЕ) ---
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

class Form(StatesGroup):
    choosing_course = State()
    choosing_group = State()
    choosing_day = State()
    waiting_for_teacher = State()
    admin_broadcast = State()
    admin_ban = State()
    admin_demote = State()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def get_all_users():
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{DB_TABLE_ID}/values/Sheet1!A:A?key={GOOGLE_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            rows = data.get("values", [])
            return [str(row[0]) for row in rows if row and str(row[0]).isdigit()]

def get_room_safe(rows, r_idx, c_idx):
    try:
        if r_idx < 0 or r_idx >= len(rows): return ""
        row = rows[r_idx]
        for offset in range(1, 4):
            if len(row) > c_idx + offset:
                val = str(row[c_idx + offset]).strip()
                if val and val.lower() not in ["-", ".", "каб", "пара"]: return val
    except: pass
    return ""

# --- ЛОГИКА ПАРСИНГА СТУДЕНТОВ ---
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
            # --- ЗАЩИТА ЛИНИИ 183 ---
            teacher = ""
            if i + 1 < len(rows):
                next_row = rows[i+1]
                if len(next_row) > col_idx:
                    t_val = str(next_row[col_idx]).strip()
                    if t_val: teacher = f" ({t_val})"
            room = get_room_safe(rows, i, col_idx)
            if curr_day not in res_dict: res_dict[curr_day] = []
            res_dict[curr_day].append(f"• {pair_num} пара: {content}{teacher} — каб. {room}")
    
    out = ""
    for d, lessons in res_dict.items(): out += f"\n📅 **{d}**\n" + "\n".join(lessons) + "\n"
    return out if out else "🎉 Занятий нет!"

# --- ЛОГИКА ПАРСИНГА ПРЕПОДАВАТЕЛЕЙ (ИСПРАВЛЕНА ЛИНИЯ 131) ---
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
                
                # --- ЗАЩИТА ЛИНИИ 131 ---
                for col_idx in range(2, len(row)):
                    cell_raw = row[col_idx] if col_idx < len(row) else None
                    if cell_raw is not None:
                        cell_val = str(cell_raw).strip().lower()
                        if t_name_lower in cell_val and len(cell_val) > 2:
                            p = row[1] if len(row) > 1 else "?"
                            s = str(rows[i-1][col_idx]).strip() if i > 0 and len(rows[i-1]) > col_idx else "?"
                            g = str(rows[1][col_idx]).strip() if len(rows) > 1 and len(rows[1]) > col_idx else "?"
                            r = get_room_safe(rows, i-1, col_idx)
                            all_lessons.append(f"📅 **{curr_day}**\n{p} пара: {s} — {g} [каб. {r}]")
    return "\n\n".join(all_lessons) if all_lessons else "🔍 Ничего не найдено."

# --- АДМИН-КЛАВИАТУРА (ТВОЙ СКРИНШОТ) ---
def get_admin_kb():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="📊 Статистика"))
    builder.row(KeyboardButton(text="🚫 Забанить"), KeyboardButton(text="✅ Разбанить"))
    builder.row(KeyboardButton(text="✅ Обяз. подписка: ВКЛ"))
    builder.row(KeyboardButton(text="➕ Назначить админа"), KeyboardButton(text="➖ Снять админа"))
    builder.row(KeyboardButton(text="➕ Добавить канал"), KeyboardButton(text="🗑 Удалить канал"))
    builder.row(KeyboardButton(text="📑 Список юзеров"))
    builder.row(KeyboardButton(text="⬅️ Назад к курсам"))
    return builder.as_markup(resize_keyboard=True)

# --- ОБРАБОТЧИКИ ---
@dp.message(Command("admin"))
async def admin_start(message: types.Message):
    if message.from_user.id == OWNER_ID:
        await message.answer("🔧 Панель управления", reply_markup=get_admin_kb())

@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: types.Message):
    if message.from_user.id == OWNER_ID:
        users = await get_all_users()
        await message.answer(f"📊 Всего в базе: {len(users)} чел.")

@dp.message(F.text == "📑 Список юзеров")
async def admin_list(message: types.Message):
    if message.from_user.id == OWNER_ID:
        users = await get_all_users()
        file = BufferedInputFile("\n".join(users).encode(), filename="users.txt")
        await message.answer_document(file, caption=f"Всего ID: {len(users)}")

@dp.message(F.text == "📢 Рассылка")
async def broadcast_start(message: types.Message, state: FSMContext):
    if message.from_user.id == OWNER_ID:
        await state.set_state(Form.admin_broadcast); await message.answer("Введите сообщение:")

@dp.message(Form.admin_broadcast)
async def broadcast_exec(message: types.Message, state: FSMContext):
    await state.clear(); users = await get_all_users()
    await message.answer(f"🚀 Рассылка на {len(users)} чел..."); c = 0
    for u in users:
        try: await bot.send_message(u, message.text); c += 1; await asyncio.sleep(0.05)
        кроме: проходить
    ждать сообщение.отвечать(ф"✅ Готово! Доставлено: {c}")

@dp.сообщение(Команда("старт"), Фильтр состояний('*'))
@dp.сообщение(Ф.текст == "⬅️ Назад к курсам")
@dp.сообщение(Ф.текст == "⬅️ Назад")
асинхронный деф start_cmd(сообщение: типы.Сообщение, состояние: FSMContext):
    ждать состояние.прозрачный()
 кб = ОтветитьKeyboardBuilder().ряд(КлавиатураКнопка(текст="🎓 Я студент"), КлавиатураКнопка(текст="👨‍🏫 Я преподаватель"))
    ждать сообщение.отвечать("Кто вы?", reply_markup=кб.как_разметка(изменить размер_клавиатуры=Истинный))

@dp.сообщение(Ф.текст == "👨‍🏫 Я преподаватель")
асинхронный деф режим_учителя(сообщение: типы.Сообщение, состояние: FSMContext):
    ждать состояние.установить_состояние(Форма.ожидание_учителя_)
    ждать сообщение.отвечать("📝 Фамилия:", ответ_разметка=ОтветКлавиатураРазметка(клавиатура=[[КлавиатураКнопка(текст="⬅️ Назад")]], изменить размер_клавиатуры=Истинный))

@dp.сообщение(Форма.ожидание_учителя_)
асинхронный деф учитель_поиск(сообщение: типы.Сообщение, состояние: FSMContext):
    если сообщение.текст == "⬅️ Назад": возвращаться ждать start_cmd(сообщение, состояние)
 м = ждать сообщение.отвечать("🔎 Поиск..."); рез = ждать расписание_учителя_принеси(сообщение.текст)
    ждать м.редактировать_текст(ф"👨‍🏫 {сообщение.текст}:\н\н{рез}", режим_анализа="Маркдаун")

@dp.сообщение(Ф.текст == "🎓 Я студент")
асинхронный деф режим_студента(сообщение: типы.Сообщение, состояние: FSMContext):
 кб = ОтветитьKeyboardBuilder()
    для c в ГРУППЫ_ПО_КУРСУ.ключи(): кб.добавлять(КлавиатураКнопка(текст=с))
 кб.ряд(КлавиатураКнопка(текст="⬅️ Назад"))
    ждать состояние.установить_состояние(Форма.выбор_курса)
    ждать сообщение.отвечать("Выберите курс:", reply_markup=кб.регулировать(2).как_разметка(изменить размер_клавиатуры=Истинный))

@dp.сообщение(Форма.выбор_курса)
асинхронный деф proc_course(сообщение: типы.Сообщение, состояние: FSMContext):
    если сообщение.текст == "⬅️ Назад": возвращаться ждать start_cmd(сообщение, состояние)
    если сообщение.текст нет в ГРУППЫ_ПО_КУРСУ: возвращаться
    ждать состояние.обновить_данные(с=сообщение.текст); ждать состояние.установить_состояние(Форма.выбираем_группу)
 кб = ОтветитьKeyboardBuilder()
    для g в ГРУППЫ_ПО_КУРСУ[сообщение.текст]: кб.добавлять(КлавиатураКнопка(текст=г))
 кб.ряд(КлавиатураКнопка(текст="⬅️ Назад"))
    ждать сообщение.отвечать(ф"📍 Группа:", reply_markup=кб.регулировать(2).как_разметка(изменить размер_клавиатуры=Истинный))

@dp.сообщение(Форма.выбираем_группу)
асинхронный деф proc_group(сообщение: типы.Сообщение, состояние: FSMContext):
    если сообщение.текст == "⬅️ Назад": возвращаться ждать start_cmd(сообщение, состояние)
    ждать состояние.обновить_данные(г=сообщение.текст); ждать состояние.установить_состояние(Форма.выбор_дня)
 кб = ОтветитьKeyboardBuilder().ряд(КлавиатураКнопка(текст="📅 Сегодня"), КлавиатураКнопка(текст="📅 Завтра")).ряд(КлавиатураКнопка(текст="🗓 На неделю"), КлавиатураКнопка(текст="⬅️ Назад"))
    ждать сообщение.отвечать(f"🕒 Перед:", reply_markup=кб.как_разметка(изменить размер_клавиатуры=Истинный))

@dp.сообщение(Форма.выбор_дня)
асинхронный деф proc_day(сообщение: типы.Сообщение, состояние: FSMContext):
    если сообщение.текст == "⬅️ Назад": возвращаться ждать start_cmd(сообщение, состояние)
 данные = ждать состояние.получить_данные(); дни = ['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА', 'СУББОТА', 'ВОСКРЕСЕНЬЕ']
 т = дни[дата и время.сейчас().будний день()] если "Сегодня" в сообщение.текст еще дней[(дата и время.сейчас() + timedelta(дней=1)).будний день()] если "Завтра" в сообщение.текст еще Нет
 рез = ждать расписание_студентов_принеси(данные.получать('с'), данные.получать('г'), т)
    ждать сообщение.отвечать(ф"📋 **{данные.получать('г')}**\н{рез}", режим_анализа="Маркдаун")

асинхронный деф основной():
    ждать бот.удалить_вебхук(drop_pending_updates=Истинный)
    ждать дп.старт_опроса(бот)

если __имя__ == "__основной__":
 асинсио.бегать(основной())
