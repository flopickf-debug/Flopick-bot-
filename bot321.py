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

# --- НАСТРОЙКИ (Railway Variables) ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "7987454041:AAGU-DGvVqgN7rioySxL5zINEk60WSlkUW4")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "AIzaSyDZUuMn8B8t_REygaEGpEI47hyLSQrDKDk")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "1X6YF54l1rgP7MFfkTa1b_L6f4f3aWuADZwF8wwTWKK4")

# --- НАСТРОЙКИ АДМИНКИ И ФАЙЛОВ ---
ADMIN_ID = 879365319  # !!! ОБЯЗАТЕЛЬНО ЗАМЕНИ НА СВОЙ ID !!!
CHANNELS = ["@channel1", "@channel2", "@channel3"] 
DB_FILE = "users.txt"
BLACKLIST_FILE = "blacklist.txt"
send_shutdown_notice = True # Флаг уведомлений

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

class AdminState(StatesGroup):
    waiting_for_ad_text = State()
    waiting_for_user_id_msg = State()
    waiting_for_msg_text = State()
    waiting_for_ban_id = State()

# --- ФУНКЦИИ БАЗЫ И ПРОВЕРОК ---

def save_user(user_id):
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w") as f: f.write("")
    with open(DB_FILE, "r") as f:
        users = f.read().splitlines()
    if str(user_id) not in users:
        with open(DB_FILE, "a") as f: f.write(f"{user_id}\n")

def is_banned(user_id):
    if not os.path.exists(BLACKLIST_FILE): return False
    with open(BLACKLIST_FILE, "r") as f:
        return str(user_id) in f.read().splitlines()

async def broadcast(text):
    if not os.path.exists(DB_FILE): return
    with open(DB_FILE, "r") as f:
        users = f.read().splitlines()
    for user_id in users:
        try:
            await bot.send_message(user_id, text)
            await asyncio.sleep(0.05) # Защита от спам-фильтра
        except Exception: continue

async def check_subscriptions(user_id: int):
    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ['left', 'kicked']: return False
        except Exception: continue
    return True

# --- АДМИН-ХЕНДЛЕРЫ ---

@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def admin_menu(message: types.Message):
    notif_status = "✅ ВКЛ" if send_shutdown_notice else "❌ ВЫКЛ"
    kb = [
        [types.KeyboardButton(text="📢 Рассылка"), types.KeyboardButton(text="📊 Статистика")],
        [types.KeyboardButton(text="✉️ Написать юзеру"), types.KeyboardButton(text="🚫 Забанить")],
        [types.KeyboardButton(text=f"🔔 Уведомления: {notif_status}")],
        [types.KeyboardButton(text="⬅️ Назад к курсам")]
    ]
    keyboard = types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    await message.answer(f"🛠 Админ-панель\nУведомления при выключении: {notif_status}", reply_markup=keyboard)

@dp.message(F.text == "📊 Статистика", F.from_user.id == ADMIN_ID)
async def show_stats(message: types.Message):
    count = len(open(DB_FILE).readlines()) if os.path.exists(DB_FILE) else 0
    await message.answer(f"📊 Всего пользователей в базе: {count}")

@dp.message(F.text.contains("🔔 Уведомления:"), F.from_user.id == ADMIN_ID)
async def toggle_notif(message: types.Message):
    global send_shutdown_notice
    send_shutdown_notice = not send_shutdown_notice
    await admin_menu(message)

# Рассылка всем
@dp.message(F.text == "📢 Рассылка", F.from_user.id == ADMIN_ID)
async def ad_start(message: types.Message, state: FSMContext):
    await state.set_state(AdminState.waiting_for_ad_text)
    await message.answer("Введите текст для рассылки всем:")

@dp.message(AdminState.waiting_for_ad_text, F.from_user.id == ADMIN_ID)
async def ad_perform(message: types.Message, state: FSMContext):
    await broadcast(f"⚠️ **ОБЪЯВЛЕНИЕ**\n\n{message.text}")
    await message.answer("✅ Рассылка выполнена!")
    await state.clear()

# Личное сообщение
@dp.message(F.text == "✉️ Написать юзеру", F.from_user.id == ADMIN_ID)
async def pm_start(message: types.Message, state: FSMContext):
    await message.answer("Введите ID пользователя:")
    await state.set_state(AdminState.waiting_for_user_id_msg)

@dp.message(AdminState.waiting_for_user_id_msg, F.from_user.id == ADMIN_ID)
async def pm_id(message: types.Message, state: FSMContext):
    await state.update_data(target_id=message.text)
    await message.answer("Введите текст сообщения:")
    await state.set_state(AdminState.waiting_for_msg_text)

@dp.message(AdminState.waiting_for_msg_text, F.from_user.id == ADMIN_ID)
async def pm_send(message: types.Message, state: FSMContext):
    data = await state.get_data()
    try:
        await bot.send_message(data['target_id'], f"👤 **Сообщение от администратора:**\n\n{message.text}")
        await message.answer("✅ Отправлено!")
    except Exception as e: await message.answer(f"❌ Ошибка: {e}")
    await state.clear()

# Бан
@dp.message(F.text == "🚫 Забанить", F.from_user.id == ADMIN_ID)
async def ban_start(message: types.Message, state: FSMContext):
    await message.answer("Введите ID для бана:")
    await state.set_state(AdminState.waiting_for_ban_id)

@dp.message(AdminState.waiting_for_ban_id, F.from_user.id == ADMIN_ID)
async def ban_done(message: types.Message, state: FSMContext):
    with open(BLACKLIST_FILE, "a") as f: f.write(f"{message.text}\n")
    await message.answer(f"✅ Юзер {message.text} в бане.")
    await state.clear()

# --- ЛОГИКА ТАБЛИЦ ---

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
            for offset in [1, 2, 3]: # Поиск кабинета
                if len(row) > col_index + offset:
                    val = row[col_index + offset].strip()
                    if val and val.lower() != "каб" and val != "":
                        room = val; break
            if subject.strip() and subject.lower() != "предмет":
                found_any = True
                if day_cell and not target_day:
                    schedule += f"\n🟠 **{current_day_in_table.upper()}**\n"
                lesson_num = row[1] if len(row) > 1 else "?"
                room_str = f" (🚪 каб. {room})" if room else " (🚪 каб. не указан)"
                schedule += f" - {lesson_num} пара: {subject}{room_str}\n"
    return schedule if found_any else "Занятий не найдено."

# --- ОСНОВНЫЕ ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
@dp.message(F.text == "⬅️ Назад к курсам")
async def cmd_start(message: types.Message, state: FSMContext):
    if is_banned(message.from_user.id): return # Проверка бана
    save_user(message.from_user.id)
    builder = ReplyKeyboardBuilder()
    for course in COURSES.keys(): builder.add(types.KeyboardButton(text=course))
    builder.adjust(2)
    await state.set_state(UserState.choosing_course)
    await message.answer("Выберите ваш курс:", reply_markup=builder.as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_course)
async def process_course(message: types.Message, state: FSMContext):
    if message.text in COURSES:
        await state.update_data(selected_course=message.text)
        await state.set_state(UserState.choosing_group)
        builder = ReplyKeyboardBuilder()
        for g in GROUPS_BY_COURSE.get(message.text, []): builder.add(types.KeyboardButton(text=g))
        builder.add(types.KeyboardButton(text="⬅️ Назад к курсам"))
        builder.adjust(2)
        await message.answer(f"Выбран {message.text}. Выберите группу:", reply_markup=builder.as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_group)
async def process_group(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    course = user_data.get("selected_course")
    if message.text in GROUPS_BY_COURSE.get(course, []):
        await state.update_data(selected_group=message.text)
        await state.set_state(UserState.choosing_day)
        kb = ReplyKeyboardBuilder()
        kb.row(types.KeyboardButton(text="📅 На сегодня"), types.KeyboardButton(text="📅 На завтра"))
        kb.row(types.KeyboardButton(text="🗓 На всю неделю"), types.KeyboardButton(text="⬅️ Назад к группам"))
        await message.answer(f"Группа {message.text}. Выберите период:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_day)
async def process_day(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к группам":
        user_data = await state.get_data()
        return await process_course(types.Message(text=user_data.get("selected_course")), state)
    
    await state.update_data(last_request=message.text)
    if await check_subscriptions(message.from_user.id):
        await send_schedule(message, state)
    else:
        builder = InlineKeyboardBuilder()
        for i, ch in enumerate(CHANNELS, 1):
            builder.row(InlineKeyboardButton(text=f"📢 Канал {i}", url=f"https://t.me/{ch.replace('@', '')}"))
        builder.row(InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_subs"))
        await message.answer("🛑 Подпишитесь на каналы для доступа:", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "check_subs")
async def cb_check(callback: CallbackQuery, state: FSMContext):
    if await check_subscriptions(callback.from_user.id):
        await callback.message.edit_text("✅ Доступ разрешен!")
        await send_schedule(callback.message, state)
    else: await callback.answer("❌ Вы подписались не на всё!", show_alert=True)

async def send_schedule(message_or_callback, state: FSMContext):
    user_data = await state.get_data()
    chat_id = message_or_callback.chat.id if isinstance(message_or_callback, types.Message) else message_or_callback.message.chat.id
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{COURSES[user_data['selected_course']]}!A1:BG100?key={GOOGLE_API_KEY}"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            rows = data.get("values", [])

    col_idx = -1
    for i, cell in enumerate(rows[1]):
        if user_data['selected_group'].replace("-","").lower() in cell.replace("-","").lower() and cell != "":
            col_idx = i; break

    days = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']
    req = user_data.get("last_request", "").lower()
    
    if "сегодня" in req:
        target = days[datetime.now().weekday()]
        res = format_schedule(rows, col_idx, target)
        await bot.send_message(chat_id, f"📅 **Сегодня ({target}):**\n{res}", parse_mode="Markdown")
    elif "завтра" in req:
        target = days[(datetime.now() + timedelta(days=1)).weekday()]
        res = format_schedule(rows, col_idx, target)
        await bot.send_message(chat_id, f"📅 **Завтра ({target}):**\n{res}", parse_mode="Markdown")
    else:
        res = format_schedule(rows, col_idx)
        await bot.send_message(chat_id, f"🗓 **Неделя для {user_data['selected_group']}:**\n{res}", parse_mode="Markdown")

# --- ЗАПУСК ---

async def main():
    await broadcast("✅ Бот запущен и готов к работе!")
    try: await dp.start_polling(bot)
    finally:
        if send_shutdown_notice: # Проверка флага
            await broadcast("⚠️ Бот уходит на тех. обслуживание. Скоро вернемся!")
        await bot.session.close()

if __name__ == "__main__":
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): pass

