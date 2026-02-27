import logging
import aiohttp
import asyncio
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, CallbackQuery

# --- НАСТРОЙКИ ---
BOT_TOKEN = "7987454041:AAGU-DGvVqgN7rioySxL5zINEk60WSlkUW4"
GOOGLE_API_KEY = "AIzaSyDZUuMn8B8t_REygaEGpEI47hyLSQrDKDk"
SPREADSHEET_ID = "1X6YF54l1rgP7MFfkTa1b_L6f4f3aWuADZwF8wwTWKK4"
CHANNELS = ["@channel1", "@channel2", "@channel3"] 
DB_FILE = "users.txt"  # Файл, где хранятся ID пользователей

COURSES = {"1 курс": "1 курс", "2 курс": "2 курс", "3 курс": "3 курс", "4 курс": "4 курс"}

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

# --- РАБОТА С БАЗОЙ ПОЛЬЗОВАТЕЛЕЙ ---

def save_user(user_id):
    """Сохраняет ID пользователя в файл, если его там нет"""
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w") as f: f.write("")
    
    with open(DB_FILE, "r") as f:
        users = f.read().splitlines()
    
    if str(user_id) not in users:
        with open(DB_FILE, "a") as f:
            f.write(f"{user_id}\n")

def get_all_users():
    """Возвращает список всех ID пользователей"""
    if not os.path.exists(DB_FILE): return []
    with open(DB_FILE, "r") as f:
        return f.read().splitlines()

async def broadcast(text):
    """Рассылка сообщения всем пользователям"""
    users = get_all_users()
    for user_id in users:
        try:
            await bot.send_message(user_id, text)
            await asyncio.sleep(0.05) # Защита от спам-фильтра Telegram
        except Exception:
            pass

# --- ПРОВЕРКИ И ТАБЛИЦЫ ---

async def check_subscriptions(user_id: int):
    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ['left', 'kicked']: return False
        except Exception: continue
    return True

async def get_data_from_google(sheet_name):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{sheet_name}!A1:BG100?key={GOOGLE_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            res = await response.json()
            return res.get("values", [])

def format_schedule(rows, col_index, target_day=None):
    schedule = ""
    current_day_in_table = ""
    found_any = False
    for row in rows[2:]:
        day_cell = row[0].strip().lower() if len(row) > 0 and row[0].strip() else ""
        if day_cell: current_day_in_table = day_cell
        is_target_day = True if not target_day else target_day.lower() in current_day_in_table.lower()
        if is_target_day:
            subject = row[col_index] if len(row) > col_index else ""
            room = ""
            for offset in [1, 2]:
                if len(row) > col_index + offset:
                    val = row[col_index + offset].strip()
                    if val and val.lower() != "каб":
                        room = val
                        break
            if subject.strip() and subject.lower() != "предмет":
                found_any = True
                if day_cell and not target_day:
                    schedule += f"\n🟠 **{current_day_in_table.upper()}**\n"
                lesson_num = row[1] if len(row) > 1 else "?"
                room_str = f" (каб. {room})" if room else ""
                schedule += f" - {lesson_num} пара: {subject}{room_str}\n"
    return schedule if found_any else "На этот период занятий не найдено."

# --- КЛАВИАТУРЫ ---
def kb_courses():
    builder = ReplyKeyboardBuilder()
    for course in COURSES.keys(): builder.add(types.KeyboardButton(text=course))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def kb_groups(course_name):
    builder = ReplyKeyboardBuilder()
    groups = GROUPS_BY_COURSE.get(course_name, [])
    for group in groups: builder.add(types.KeyboardButton(text=group))
    builder.add(types.KeyboardButton(text="⬅️ Назад к курсам"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def kb_days():
    builder = ReplyKeyboardBuilder()
    builder.row(types.KeyboardButton(text="📅 На сегодня"), types.KeyboardButton(text="📅 На завтра"))
    builder.row(types.KeyboardButton(text="🗓 На всю неделю"))
    builder.row(types.KeyboardButton(text="⬅️ Назад к группам"))
    return builder.as_markup(resize_keyboard=True)

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
@dp.message(F.text == "⬅️ Назад к курсам")
async def cmd_start(message: types.Message, state: FSMContext):
    save_user(message.from_user.id) # Сохраняем пользователя в базу
    await state.set_state(UserState.choosing_course)
    await message.answer("Выберите ваш курс:", reply_markup=kb_courses())

@dp.message(UserState.choosing_course)
async def process_course(message: types.Message, state: FSMContext):
    if message.text in COURSES:
        await state.update_data(selected_course=message.text)
        await state.set_state(UserState.choosing_group)
        await message.answer(f"Выбран {message.text}. Теперь выберите группу:", reply_markup=kb_groups(message.text))
    else:
        await message.answer("Пожалуйста, используйте кнопки.")

@dp.message(UserState.choosing_group)
async def process_group(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    course = user_data.get("selected_course")
    if message.text in GROUPS_BY_COURSE.get(course, []):
        await state.update_data(selected_group=message.text)
        await state.set_state(UserState.choosing_day)
        await message.answer(f"Выбрана группа {message.text}. Какое расписание показать?", reply_markup=kb_days())
    else:
        await message.answer("Выберите группу из списка.")

@dp.message(UserState.choosing_day)
async def process_schedule(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к группам":
        user_data = await state.get_data()
        course = user_data.get("selected_course")
        await state.set_state(UserState.choosing_group)
        return await message.answer("Выберите группу:", reply_markup=kb_groups(course))

    await state.update_data(last_request=message.text)
    if await check_subscriptions(message.from_user.id):
        await send_schedule_data(message, state)
    else:
        builder = InlineKeyboardBuilder()
        for i, ch in enumerate(CHANNELS, 1):
            url = f"https://t.me/{ch.replace('@', '')}"
            builder.row(InlineKeyboardButton(text=f"Подписаться на Канал {i}", url=url))
        builder.row(InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_subs"))
        await message.answer("🛑 Для доступа подпишитесь на каналы:", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "check_subs")
async def callback_check_subs(callback: CallbackQuery, state: FSMContext):
    if await check_subscriptions(callback.from_user.id):
        await callback.message.edit_text("✅ Успешно! Загружаю расписание...")
        await send_schedule_data(callback.message, state)
    else:
        await callback.answer("❌ Вы подписались не на все каналы!", show_alert=True)

async def send_schedule_data(message_or_callback, state: FSMContext):
    user_data = await state.get_data()
    course, group, request_text = user_data.get("selected_course"), user_data.get("selected_group"), user_data.get("last_request", "неделю")
    sheet_name = COURSES[course]
    chat_id = message_or_callback.chat.id if isinstance(message_or_callback, types.Message) else message_or_callback.message.chat.id
    
    await bot.send_chat_action(chat_id, "typing")
    rows = await get_data_from_google(sheet_name)
    if not rows: return await bot.send_message(chat_id, "❌ Ошибка данных.")

    col_idx = -1
    for i, cell in enumerate(rows[1]):
        if group.replace("-","").lower() in cell.replace("-","").lower() and cell != "":
            col_idx = i; break
    
    if col_idx == -1: return await bot.send_message(chat_id, "❌ Группа не найдена.")

    days_ru = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']
    if "сегодня" in request_text.lower():
        target = days_ru[datetime.now().weekday()]
        res = format_schedule(rows, col_idx, target)
        await bot.send_message(chat_id, f"📅 **На сегодня ({target}):**\n{res}", parse_mode="Markdown")
    elif "завтра" in request_text.lower():
        target = days_ru[(datetime.now() + timedelta(days=1)).weekday()]
        res = format_schedule(rows, col_idx, target)
        await bot.send_message(chat_id, f"📅 **На завтра ({target}):**\n{res}", parse_mode="Markdown")
    else:
        res = format_schedule(rows, col_idx)
        await bot.send_message(chat_id, f"🗓 **На неделю для {group}:**\n{res}", parse_mode="Markdown")

# --- СТАРТ И СТОП ---

async def main():
    print("--- БОТ ЗАПУЩЕН ---")
    # Оповещение при включении
    await broadcast("✅ Бот снова работает! Можете проверять расписание.")
    
    try:
        await dp.start_polling(bot)
    finally:
        # Оповещение при выключении
        print("--- ОПОВЕЩЕНИЕ ОБ ОТКЛЮЧЕНИИ ---")
        await broadcast("⚠️ Бот временно уходит на тех. обслуживание и скоро вернется.")
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): pass
