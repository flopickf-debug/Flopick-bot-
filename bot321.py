import logging
import asyncio
import gspread
import aiohttp
import os
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# --- НАСТРОЙКИ ---
BOT_TOKEN = "7987454041:AAGU-DGvVqgN7rioySxL5zINEk60WSlkUW4"
GOOGLE_API_KEY = "AIzaSyDZUuMn8B8t_REygaEGpEI47hyLSQrDKDk"
ADMIN_ID = 879365319

# ID ТАБЛИЦ
SCHEDULE_TABLE_ID = "1X6YF54l1rgP7MFfkTa1b_L6f4f3aWuADZwF8wwTWKK4" # Чужая
DB_TABLE_ID = "11KbeilP1HRonHQAAZusBS1-ffNo4FxHXa239yZMKJm8"       # Твоя

TABLE_URL = f"https://docs.google.com/spreadsheets/d/{SCHEDULE_TABLE_ID}/edit"

# СПИСОК КАНАЛОВ
CHANNELS = [
    {"id": "@loveshaverma", "url": "https://t.me/loveshaverma", "name": "Первый канал"},
    {"id": "@loveshaverma", "url": "https://t.me/loveshaverma", "name": "Второй канал"},
    {"id": "@loveshaverma", "url": "https://t.me/loveshaverma", "name": "Третий канал"}
]

# --- ПОДКЛЮЧЕНИЕ К GOOGLE SHEETS (Твоя база) ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)
db_sheet = client.open_by_key(DB_TABLE_ID)
users_worksheet = db_sheet.worksheet("Users") 

COURSES = ["1 курс", "2 курс", "3 курс", "4 курс"]
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

# --- ФУНКЦИИ БАЗЫ (GOOGLE SHEETS) ---

def save_user_to_google(user: types.User):
    try:
        uid = str(user.id)
        uname = f"@{user.username}" if user.username else "None"
        # Читаем ID из первой колонки (A)
        existing_ids = users_worksheet.col_values(1)
        if uid not in existing_ids:
            users_worksheet.append_row([uid, uname, datetime.now().strftime("%d.%m.%Y %H:%M")])
            print(f"✅ Юзер {uid} добавлен в таблицу.")
    except Exception as e:
        logging.error(f"Ошибка записи в Google Таблицу: {e}")

async def check_all_subs(user_id):
    if user_id == ADMIN_ID: return True
    for ch in CHANNELS:
        try:
            m = await bot.get_chat_member(ch['id'], user_id)
            if m.status not in ["member", "administrator", "creator"]: return False
        except: return False
    return True

# --- ЛОГИКА ТАБЛИЦ (ЧТЕНИЕ РАСПИСАНИЯ) ---

async def get_schedule(course, group, target_day=None):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SCHEDULE_TABLE_ID}/values/{course}!A1:BG100?key={GOOGLE_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            rows = data.get("values", [])
    
    if not rows: return "⚠️ Ошибка доступа к таблице расписания."
    
    col = -1
    for i, cell in enumerate(rows[1]):
        if group.replace("-","").lower() in cell.replace("-","").lower():
            col = i; break
    if col == -1: return f"⚠️ Группа {group} не найдена."

    schedule_dict = {}
    curr_day = ""

    for row in rows[2:]:
        day_val = row[0].strip().upper() if len(row) > 0 and row[0].strip() else ""
        if day_val: curr_day = day_val
        if not curr_day or (target_day and target_day.upper() not in curr_day): continue

        pair_num = row[1].strip() if len(row) > 1 else ""
        content = row[col].strip() if len(row) > col else ""
        if not content: continue

        # Склейка предмета и преподавателя
        if not pair_num and curr_day in schedule_dict and schedule_dict[curr_day]:
            schedule_dict[curr_day][-1] += f" — {content}"
            continue

        # Поиск кабинета
        room = ""
        if len(row) > col + 1 and row[col+1].strip():
            room = f" (каб. {row[col+1]})"

        if curr_day not in schedule_dict: schedule_dict[curr_day] = []
        schedule_dict[curr_day].append(f" - {pair_num if pair_num else '?'} пара: {content}{room}")

    if not schedule_dict: return "Занятий нет. 🎉"
    
    res = ""
    for day, lessons in schedule_dict.items():
        res += f"\n🟠 **{day}**\n" + "\n".join(lessons) + "\n"
    return res

# --- ЛОГИКА ПОЛЬЗОВАТЕЛЯ ---

@dp.message(StateFilter('*'))
async def global_handler(message: types.Message, state: FSMContext):
    # Проверка подписки
    if not await check_all_subs(message.from_user.id):
        kb = InlineKeyboardBuilder()
        for ch in CHANNELS: kb.row(InlineKeyboardButton(text=f"📢 {ch['name']}", url=ch['url']))
        kb.row(InlineKeyboardButton(text="✅ Проверить подписку", callback_data="recheck"))
        return await message.answer("❗ **Для использования бота подпишитесь на каналы:**", reply_markup=kb.as_markup())

    # Старт или Назад
    if message.text in ["/start", "⬅️ Назад к курсам"]:
        save_user_to_google(message.from_user) # Пишем в Google Таблицу
        await state.clear()
        await state.set_state(UserState.choosing_course)
        kb = ReplyKeyboardBuilder()
        [kb.add(types.KeyboardButton(text=c)) for c in COURSES]
        return await message.answer("🎓 Выберите курс:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

    cur = await state.get_state()
    
    # Выбор курса
    if cur == UserState.choosing_course and message.text in COURSES:
        await state.update_data(c=message.text)
        await state.set_state(UserState.choosing_group)
        kb = ReplyKeyboardBuilder()
        [kb.add(types.KeyboardButton(text=g)) for g in GROUPS_BY_COURSE[message.text]]
        kb.add(types.KeyboardButton(text="⬅️ Назад к курсам"))
        await message.answer(f"📍 Курс {message.text}. Выберите группу:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

    # Выбор группы
    elif cur == UserState.choosing_group:
        data = await state.get_data()
        if message.text in GROUPS_BY_COURSE.get(data['c'], []):
            await state.update_data(g=message.text)
            await state.set_state(UserState.choosing_day)
            kb = ReplyKeyboardBuilder()
            kb.row(types.KeyboardButton(text="📅 На сегодня"), types.KeyboardButton(text="📅 На завтра"))
            kb.row(types.KeyboardButton(text="🗓 На неделю"), types.KeyboardButton(text="⬅️ Назад к курсам"))
            await message.answer(f"👥 Группа {message.text}:", reply_markup=kb.as_markup(resize_keyboard=True))

    # Вывод расписания
    elif cur == UserState.choosing_day:
        data = await state.get_data()
        d_list = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']
        
        target = None
        if "сегодня" in message.text.lower():
            target = d_list[datetime.now().weekday()]
        elif "завтра" in message.text.lower():
            target = d_list[(datetime.now() + timedelta(days=1)).weekday()]
        
        res = await get_schedule(data['c'], data['g'], target)
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="🔗 Оригинал таблицы", url=TABLE_URL))
        await message.answer(f"🗓 **Расписание {data['g']}**:\n{res}", parse_mode="Markdown", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "recheck")
async def recheck_sub(call: types.CallbackQuery, state: FSMContext):
    if await check_all_subs(call.from_user.id):
        await call.message.delete()
        # Имитируем команду старт
        fake_msg = types.Message(message_id=0, date=datetime.now(), chat=call.message.chat, from_user=call.from_user, text="/start")
        await global_handler(fake_msg, state)
    else:
        await call.answer("❌ Вы не подписаны!", show_alert=True)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    print("🚀 Бот запущен! Юзеры пишутся в Google Таблицу.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

