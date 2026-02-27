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
from aiogram.types import InlineKeyboardButton, CallbackQuery, FSInputFile

# --- НАСТРОЙКИ (Railway Variables) ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "7987454041:AAGU-DGvVqgN7rioySxL5zINEk60WSlkUW4")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "AIzaSyDZUuMn8B8t_REygaEGpEI47hyLSQrDKDk")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "1X6YF54l1rgP7MFfkTa1b_L6f4f3aWuADZwF8wwTWKK4")

# --- АДМИНКА (Замени 123456789 на свой реальный ID) ---
ADMIN_ID = 879365319
CHANNELS = ["@channel1", "@channel2", "@channel3"] 
DB_FILE = "users.txt"
BLACKLIST_FILE = "blacklist.txt"
send_shutdown_notice = True 

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
    waiting_for_unban_id = State()

# --- ФУНКЦИИ БАЗЫ ---

def save_user(user: types.User):
    user_id = str(user.id)
    username = f"@{user.username}" if user.username else "NoName"
    if not os.path.exists(DB_FILE): open(DB_FILE, "w").close()
    with open(DB_FILE, "r") as f: lines = f.readlines()
    new_lines = [l for l in lines if not l.startswith(user_id)]
    new_lines.append(f"{user_id} | {username}\n")
    with open(DB_FILE, "w") as f: f.writelines(new_lines)

def is_banned(user_id: int):
    if not os.path.exists(BLACKLIST_FILE): return False
    with open(BLACKLIST_FILE, "r") as f: return str(user_id) in f.read().splitlines()

async def broadcast(text: str):
    if not os.path.exists(DB_FILE): return
    with open(DB_FILE, "r") as f: lines = f.readlines()
    for line in lines:
        try:
            uid = line.split(" | ")[0].strip()
            await bot.send_message(uid, text)
            await asyncio.sleep(0.05)
        except: continue

async def check_subscriptions(user_id: int):
    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ['left', 'kicked']: return False
        except: continue
    return True

# --- АДМИН-ХЕНДЛЕРЫ ---

@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def admin_menu(message: types.Message):
    status = "✅ ВКЛ" if send_shutdown_notice else "❌ ВЫКЛ"
    kb = ReplyKeyboardBuilder()
    kb.row(types.KeyboardButton(text="📢 Рассылка"), types.KeyboardButton(text="📊 Статистика"))
    kb.row(types.KeyboardButton(text="👥 Список юзеров"), types.KeyboardButton(text="✉️ Написать юзеру"))
    kb.row(types.KeyboardButton(text="🚫 Забанить"), types.KeyboardButton(text="🔓 Разбанить"))
    kb.row(types.KeyboardButton(text="📜 Список банов"), types.KeyboardButton(text=f"🔔 Увед: {status}"))
    kb.row(types.KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer("🛠 Панель администратора", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "📊 Статистика", F.from_user.id == ADMIN_ID)
async def stats(message: types.Message):
    count = len(open(DB_FILE).readlines()) if os.path.exists(DB_FILE) else 0
    await message.answer(f"👥 Всего пользователей: {count}")

@dp.message(F.text == "👥 Список юзеров", F.from_user.id == ADMIN_ID)
async def user_list_file(message: types.Message):
    if os.path.exists(DB_FILE):
        await message.answer_document(FSInputFile(DB_FILE), caption="📊 База ID | Username")

@dp.message(F.text.contains("🔔 Увед:"), F.from_user.id == ADMIN_ID)
async def toggle_notif(message: types.Message):
    global send_shutdown_notice
    send_shutdown_notice = not send_shutdown_notice
    await admin_menu(message)

# Рассылка, Бан, Разбан, ЛС (Логика)
@dp.message(F.text == "📢 Рассылка", F.from_user.id == ADMIN_ID)
async def ad_start(message: types.Message, state: FSMContext):
    await state.set_state(AdminState.waiting_for_ad_text)
    await message.answer("Введите текст для всех:")

@dp.message(AdminState.waiting_for_ad_text, F.from_user.id == ADMIN_ID)
async def ad_done(message: types.Message, state: FSMContext):
    await broadcast(f"⚠️ ОБЪЯВЛЕНИЕ:\n\n{message.text}")
    await message.answer("✅ Рассылка завершена!"); await state.clear()

@dp.message(F.text == "🚫 Забанить", F.from_user.id == ADMIN_ID)
async def ban_start(message: types.Message, state: FSMContext):
    await message.answer("Введите ID для бана:"); await state.set_state(AdminState.waiting_for_ban_id)

@dp.message(AdminState.waiting_for_ban_id, F.from_user.id == ADMIN_ID)
async def ban_done(message: types.Message, state: FSMContext):
    with open(BLACKLIST_FILE, "a") as f: f.write(f"{message.text.strip()}\n")
    await message.answer("✅ Забанен!"); await state.clear()

# --- ЛОГИКА ТАБЛИЦ ---

def format_schedule(rows, col, target_day=None):
    text, curr_day, found = "", "", False
    for row in rows[2:]:
        day = row[0].strip().lower() if len(row) > 0 and row[0].strip() else ""
        if day: curr_day = day
        if not target_day or target_day.lower() in curr_day:
            subj = row[col] if len(row) > col else ""
            if subj.strip() and subj.lower() != "предмет":
                found = True
                room = ""
                for off in [1,2,3]:
                    if len(row) > col+off:
                        val = row[col+off].strip()
                        if val and val.lower() != "каб": room = val; break
                if day and not target_day: text += f"\n🟠 **{curr_day.upper()}**\n"
                num = row[1] if len(row) > 1 else "?"
                text += f" - {num} пара: {subj} (каб. {room if room else '?'})\n"
    return text if found else "Занятий нет."

# --- ОСНОВНЫЕ ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
@dp.message(F.text == "⬅️ Назад к курсам")
async def start_cmd(message: types.Message, state: FSMContext):
    if is_banned(message.from_user.id): return
    save_user(message.from_user)
    await state.set_state(UserState.choosing_course)
    kb = ReplyKeyboardBuilder()
    for c in COURSES.keys(): kb.add(types.KeyboardButton(text=c))
    kb.adjust(2)
    await message.answer("Выберите курс:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_course)
async def course_step(message: types.Message, state: FSMContext):
    if message.text in COURSES:
        await state.update_data(c=message.text)
        await state.set_state(UserState.choosing_group)
        kb = ReplyKeyboardBuilder()
        for g in GROUPS_BY_COURSE[message.text]: kb.add(types.KeyboardButton(text=g))
        kb.add(types.KeyboardButton(text="⬅️ Назад к курсам"))
        kb.adjust(2)
        await message.answer("Выберите группу:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_group)
async def group_step(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if message.text in GROUPS_BY_COURSE.get(data.get('c'), []):
        await state.update_data(g=message.text)
        await state.set_state(UserState.choosing_day)
        kb = ReplyKeyboardBuilder()
        kb.row(types.KeyboardButton(text="📅 На сегодня"), types.KeyboardButton(text="📅 На завтра"))
        kb.row(types.KeyboardButton(text="🗓 На всю неделю"), types.KeyboardButton(text="⬅️ Назад к группам"))
        await message.answer("Период:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_day)
async def day_step(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к группам":
        # Возврат к списку групп
        data = await state.get_data()
        await state.set_state(UserState.choosing_group)
        kb = ReplyKeyboardBuilder()
        for g in GROUPS_BY_COURSE[data['c']]: kb.add(types.KeyboardButton(text=g))
        kb.add(types.KeyboardButton(text="⬅️ Назад к курсам"))
        return await message.answer("Выберите группу:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))
    
    await state.update_data(req=message.text)
    if await check_subscriptions(message.from_user.id):
        await send_final(message, state)
    else:
        ikb = InlineKeyboardBuilder()
        for i, ch in enumerate(CHANNELS, 1): ikb.row(InlineKeyboardButton(text=f"📢 Канал {i}", url=f"https://t.me/{ch.replace('@','') }"))
        ikb.row(InlineKeyboardButton(text="🔄 Проверить", callback_data="check"))
        await message.answer("Подпишитесь для доступа:", reply_markup=ikb.as_markup())

@dp.callback_query(F.data == "check")
async def cb_check(callback: CallbackQuery, state: FSMContext):
    if await check_subscriptions(callback.from_user.id):
        await callback.message.edit_text("✅ Доступ разрешен!")
        await send_final(callback.message, state)
    else: await callback.answer("❌ Подпишитесь на всё!", show_alert=True)

async def send_final(message_or_call, state: FSMContext):
    data = await state.get_data()
    cid = message_or_call.chat.id if isinstance(message_or_call, types.Message) else message_or_call.message.chat.id
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{COURSES[data['c']]}!A1:BG100?key={GOOGLE_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            raw = await resp.json(); rows = raw.get("values", [])
    col = -1
    for i, cell in enumerate(rows[1]):
        if data['g'].replace("-","").lower() in cell.replace("-","").lower() and cell: col = i; break
    
    days = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']
    req = data['req'].lower()
    if "сегодня" in req:
        t = days[datetime.now().weekday()]; res = format_schedule(rows, col, t)
        await bot.send_message(cid, f"📅 Сегодня ({t}):\n{res}", parse_mode="Markdown")
    elif "завтра" in req:
        t = days[(datetime.now() + timedelta(days=1)).weekday()]; res = format_schedule(rows, col, t)
        await bot.send_message(cid, f"📅 Завтра ({t}):\n{res}", parse_mode="Markdown")
    else:
        res = format_schedule(rows, col)
        await bot.send_message(cid, f"🗓 Неделя для {data['g']}:\n{res}", parse_mode="Markdown")

# --- ЗАПУСК ---

async def main():
    logging.info("Starting bot...")
    await bot.delete_webhook(drop_pending_updates=True) # Очистка очереди
    try:
        await dp.start_polling(bot)
    finally:
        if send_shutdown_notice: await broadcast("⚠️ Бот временно отключен.")
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
