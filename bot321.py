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

# --- ЛОГИКА ПАРСИНГА СТУДЕНТОВ (ИСПРАВЛЕНА ЛИНИЯ 178) ---
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
            # --- ИСПРАВЛЕННЫЙ БЛОК (БЫВШАЯ 178 ЛИНИЯ) ---
            teacher = ""
            if i + 1 < len(rows):
                next_row = rows[i+1]
                if len(next_row) > col_idx:
                    t_val = next_row[col_idx]
                    if t_val: teacher = f" ({str(t_val).strip()})"
            # --------------------------------------------
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

# --- ОБРАБОТЧИКИ АДМИНКИ ---
@dp.message(Command("admin"))
async def admin_start(message: types.Message):
    if message.from_user.id == OWNER_ID:
        await message.answer("🔧 **ПАНЕЛЬ АДМИНИСТРАТОРА**", reply_markup=get_admin_kb())

@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: types.Message):
    if message.from_user.id == OWNER_ID:
        users = await get_all_users()
        await message.answer(f"📊 Всего пользователей в базе: **{len(users)}**")

@dp.message(F.text == "📑 Список юзеров")
async def admin_list(message: types.Message):
    if message.from_user.id == OWNER_ID:
        users = await get_all_users()
        file = BufferedInputFile("\n".join(users).encode(), filename="users.txt")
        await message.answer_document(file, caption=f"📁 Список всех ID ({len(users)} чел.)")

@dp.message(F.text == "📢 Рассылка")
async def broadcast_start(message: types.Message, state: FSMContext):
    if message.from_user.id == OWNER_ID:
        await state.set_state(Form.admin_broadcast); await message.answer("📝 Текст рассылки:")

@dp.message(Form.admin_broadcast)
async def broadcast_exec(message: types.Message, state: FSMContext):
    await state.clear(); users = await get_all_users()
    await message.answer(f"🚀 Рассылка на {len(users)} чел..."); c = 0
    for u in users:
        try: await bot.send_message(u, message.text); c += 1; await asyncio.sleep(0.05)
        except: pass
    await message.answer(f"✅ Готово! Доставлено: {c}")

# --- ОБЫЧНЫЕ ОБРАБОТЧИКИ ---
@dp.message(Command("start"), StateFilter('*'))
@dp.message(F.text == "⬅️ Назад к курсам")
@dp.message(F.text == "⬅️ Назад")
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    kb = ReplyKeyboardBuilder().row(KeyboardButton(text="🎓 Я студент"), KeyboardButton(text="👨‍🏫 Я преподаватель"))
    await message.answer("Добро пожаловать! Кто вы?", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "👨‍🏫 Я преподаватель")
async def teacher_mode(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_for_teacher)
    await message.answer("📝 Фамилия:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True))

@dp.message(Form.waiting_for_teacher)
async def teacher_search(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад": return await start_cmd(message, state)
    m = await message.answer("🔎 Поиск..."); res = await fetch_teacher_schedule(message.text)
    await m.edit_text(f"👨‍🏫 {message.text}:\n\n{res}", parse_mode="Markdown")

@dp.message(F.text == "🎓 Я студент")
async def student_mode(message: types.Message, state: FSMContext):
    kb = ReplyKeyboardBuilder()
    for c in GROUPS_BY_COURSE.keys(): kb.add(KeyboardButton(text=c))
    kb.row(KeyboardButton(text="⬅️ Назад"))
    await state.set_state(Form.choosing_course)
    await message.answer("Выберите курс:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(Form.choosing_course)
async def proc_course(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад": return await start_cmd(message, state)
    if message.text not in GROUPS_BY_COURSE: return
    await state.update_data(c=message.text); await state.set_state(Form.choosing_group)
    kb = ReplyKeyboardBuilder()
    for g in GROUPS_BY_COURSE[message.text]: kb.add(KeyboardButton(text=g))
    kb.row(KeyboardButton(text="⬅️ Назад"))
    await message.answer(f"📍 Группа:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(Form.choosing_group)
async def proc_group(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад": return await start_cmd(message, state)
    await state.update_data(g=message.text); await state.set_state(Form.choosing_day)
    kb = ReplyKeyboardBuilder().row(KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📅 Завтра")).row(KeyboardButton(text="🗓 На неделю"), KeyboardButton(text="⬅️ Назад"))
    await message.answer(f"🕒 Период:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(Form.choosing_day)
async def proc_day(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад": return await start_cmd(message, state)
    data = await state.get_data(); days = ['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА', 'СУББОТА', 'ВОСКРЕСЕНЬЕ']
    t = days[datetime.now().weekday()] if "Сегодня" in message.text else days[(datetime.now() + timedelta(days=1)).weekday()] if "Завтра" in message.text else None
    res = await fetch_student_schedule(data.get('c'), data.get('g'), t)
    await message.answer(f"📋 **{data.get('g')}**\n{res}", parse_mode="Markdown")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
