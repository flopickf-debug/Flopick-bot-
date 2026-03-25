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
    admin_demote = State()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def get_all_users():
    """Получает список ID из твоей DB таблицы"""
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{DB_TABLE_ID}/values/Sheet1!A:A?key={GOOGLE_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            rows = data.get("values", [])
            return [str(row[0]) for row in rows if row and str(row[0]).isdigit()]

def get_room_safe(rows, r_idx, c_idx):
    """Безопасный поиск кабинета в соседних ячейках"""
    try:
        if r_idx < 0 or r_idx >= len(rows): return ""
        row = rows[r_idx]
        for offset in range(1, 4):
            if len(row) > c_idx + offset:
                val = str(row[c_idx + offset]).strip()
                if val and val.lower() not in ["-", ".", "каб", "пара"]: return val
    except: pass
    return ""

# --- ЛОГИКА ПАРСИНГА СТУДЕНТОВ (ИСПРАВЛЕНА 183 ЛИНИЯ) ---
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
            # --- ИСПРАВЛЕННЫЙ БЛОК (БЫВШАЯ 183 ЛИНИЯ) ---
            teacher = ""
            if i + 1 < len(rows):
                next_row = rows[i+1]
                if len(next_row) > col_idx:
                    t_val = str(next_row[col_idx]).strip()
                    if t_val: teacher = f" ({t_val})"
            # --------------------------------------------
            room = get_room_safe(rows, i, col_idx)
            if curr_day not in res_dict: res_dict[curr_day] = []
            res_dict[curr_day].append(f"• {pair_num} пара: {content}{teacher} — каб. {room}")
    
    out = ""
    for d, lessons in res_dict.items(): out += f"\n📅 **{d}**\n" + "\n".join(lessons) + "\n"
    return out if out else "🎉 Занятий нет!"

# --- ЛОГИКА ПАРСИНГА ПРЕПОДАВАТЕЛЕЙ ---
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
                        s = rows[i-1][col_idx] if i > 0 and len(rows[i-1]) > col_idx else "?"
                        g = rows[1][col_idx] if len(rows[1]) > col_idx else "?"
                        r = get_room_safe(rows, i-1, col_idx)
 все_уроки.добавить(ф"📅 **{текущий_день}**\н{p} пара: {s} — {g} [каб. {r}]")
 возвращаться "\н\н".присоединиться(все_уроки) если все_уроки еще "🔍 Ничего не найдено."

# --- АДМИН-КЛАВИАТУРА (КАК НА ФОТО) ---
деф получить_админ_кб():
 строитель = ОтветитьKeyboardBuilder()
 строитель.ряд(КлавиатураКнопка(текст="📢 Рассылка"), КлавиатураКнопка(текст="📊 Статистика"))
 строитель.ряд(КлавиатураКнопка(текст="🚫 Забанить"), КлавиатураКнопка(текст="✅ Разбанить"))
 строитель.ряд(КлавиатураКнопка(текст="✅ Обяз. подписка: ВКЛ"))
 строитель.ряд(КлавиатураКнопка(текст="➕ Назначить админа"), КлавиатураКнопка(текст="➖ Снять админа"))
 строитель.ряд(КлавиатураКнопка(текст="➕ Добавить канал"), КлавиатураКнопка(текст="🗑 Удалить канал"))
 строитель.ряд(КлавиатураКнопка(текст="📑 Список юзеров"))
 строитель.ряд(КлавиатураКнопка(текст="⬅️ Назад к курсам"))
 возвращаться строитель.как_разметка(изменить размер_клавиатуры=Истинный)

# --- ОБРАБОТЧИКИ АДМИНКИ ---
@дп.сообщенье(Команда("админ"))
асинхронный деф админ_старт(сообщение: типы.Сообщение):
 если сообщение.от_пользователя.идентификатор == ИДЕНТИФИКАТОР_ВЛАДЕЛЬЦА:
 ждать сообщение.отвечать("🔧 **ПАНЕЛЬ АДМИНИСТРАТОРА**", ответ_разметка=получить_админ_кб())

@дп.сообщенье(Ф.текст == "📊 Статистика")
асинхронный деф admin_stats(сообщение: типы.Сообщение):
 если сообщение.от_пользователя.идентификатор == ИДЕНТИФИКАТОР_ВЛАДЕЛЬЦА:
 пользователи = ждать получить_всех_пользователей()
 ждать сообщение.отвечать(ф"📊 Всего пользователя в базе: **{лен(пользователи)}**")

@дп.сообщенье(Ф.текст == "📑 Список юзеров")
асинхронный деф список_администраторов(сообщение: типы.Сообщение):
 если сообщение.от_пользователя.идентификатор == ИДЕНТИФИКАТОР_ВЛАДЕЛЬЦА:
 пользователи = ждать получить_всех_пользователей()
 содержимое_файла = "\н".присоединиться(пользователи)
 файл = БуферизованныйВходнойФайл(содержимое_файла.кодировать(), имя файла="пользователи.txt")
 ждать сообщение.ответ_документ(фаил, постпись=ф"📁 Список всех ID ({лен(пользователи)} чел.)")

@дп.сообщенье(Ф.текст == "📢 Рассылка")
асинхронный деф начало_трансляции(сообщение: типы.Сообщение, сообщение: FSMContext):
 если сообщение.от_пользователя.идентификатор == ИДЕНТИФИКАТОР_ВЛАДЕЛЬЦА:
 ждать состояние.установить_состояние(Форма.admin_broadcast)
 ждать сообщение.отвечать("📝 Введите текст для рассылки:")

@дп.сообщенье(Форма.admin_broadcast)
асинхронный деф broadcast_exec(сообщение: типы.Сообщение, сообщение: FSMContext):
 ждать состояние.прозрачный()
 пользователи = ждать получить_всех_пользователей()
 ждать сообщение.отвечать(ф"🚀 Рассылк на {лен(пользователи)} чел...")
 с = 0
 для u в пользователи:
 пытаться:
 ждать бот.отправить_сообщение(у, сообщение.текст)
 с += 1
 ждать асинсио.спать(0,05)
 кроме: проходить
 ждать сообщение.отвечать(ф"✅ РассслкѰ завѵршшѵна! Дстостлено: {c}")

@дп.сообщенье(Ф.текст == "➖ Снять админа")
асинхронный деф понизить_старт(сообщение: типы.Сообщение, сообщение: FSMContext):
 если сообщение.от_пользователя.идентификатор == ИДЕНТИФИКАТОР_ВЛАДЕЛЬЦА:
 ждать состояние.установить_состояние(Форма.admin_demote)
 ждать сообщение.отвечать("Кого снять? Идентификатор Введите:")

@дп.сообщенье(Форма.admin_demote)
асинхронный деф понизить_исполнитель
