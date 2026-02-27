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

# --- АДМИНКА (Вставь свой ID вместо 123456789) ---
ADMIN_ID = 123456789 
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

def save_user(user):
    user_id = str(user.id)
    username = f"@{user.username}" if user.username else "NoName"
    entry = f"{user_id} | {username}\n"
    if not os.path.exists(DB_FILE): open(DB_FILE, "w").close()
    with open(DB_FILE, "r") as f: lines = f.readlines()
    new_lines = [line for line in lines if not line.split(" | ")[0] == user_id]
    new_lines.append(entry)
    with open(DB_FILE, "w") as f: f.writelines(new_lines)

def is_banned(user_id):
    if not os.path.exists(BLACKLIST_FILE): return False
    with open(BLACKLIST_FILE, "r") as f: return str(user_id) in f.read().splitlines()

async def broadcast(text):
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
async def user_list(message: types.Message):
    if os.path.exists(DB_FILE):
        await message.answer_document(FSInputFile(DB_FILE), caption="📊 Список всех пользователей")

@dp.message(F.text == "📜 Список банов", F.from_user.id == ADMIN_ID)
async def ban_list(message: types.Message):
    if os.path.exists(BLACKLIST_FILE):
        content = open(BLACKLIST_FILE).read()
        await message.answer(f"🚫 Забаненные ID:\n{content if content else 'Пусто'}")

@dp.message(F.text.contains("🔔 Увед:"), F.from_user.id == ADMIN_ID)
async def toggle_notif(message: types.Message):
    global send_shutdown_notice
    send_shutdown_notice = not send_shutdown_notice
    await admin_menu(message)

@dp.message(F.text == "📢 Рассылка", F.from_user.id == ADMIN_ID)
async def ad_1(m, s: FSMContext):
    await s.set_state(AdminState.waiting_for_ad_text)
    await m.answer("Введите текст рассылки:")

@dp.message(AdminState.waiting_for_ad_text, F.from_user.id == ADMIN_ID)
async def ad_2(m, s: FSMContext):
    await broadcast(f"⚠️ ОБЪЯВЛЕНИЕ:\n\n{m.text}")
    await m.answer("✅ Готово!"); await s.clear()

@dp.message(F.text == "🚫 Забанить", F.from_user.id == ADMIN_ID)
async def ban_1(m, s: FSMContext):
    await m.answer("Введите ID для бана:"); await s.set_state(AdminState.waiting_for_ban_id)

@dp.message(AdminState.waiting_for_ban_id, F.from_user.id == ADMIN_ID)
async def ban_2(m, s: FSMContext):
    if not os.path.exists(BLACKLIST_FILE): open(BLACKLIST_FILE, "w").close()
    with open(BLACKLIST_FILE, "a") as f: f.write(f"{m.text.strip()}\n")
    await m.answer("✅ Забанен!"); await s.clear()

@dp.message(F.text == "🔓 Разбанить", F.from_user.id == ADMIN_ID)
async def unban_1(m, s: FSMContext):
    await m.answer("Введите ID для разбана:"); await s.set_state(AdminState.waiting_for_unban_id)

@dp.message(AdminState.waiting_for_unban_id, F.from_user.id == ADMIN_ID)
async def unban_2(m, s: FSMContext):
    if os.path.exists(BLACKLIST_FILE):
        lines = open(BLACKLIST_FILE).readlines()
        with open(BLACKLIST_FILE, "w") as f:
            f.writelines([l for l in lines if l.strip() != m.text.strip()])
    await m.answer("✅ Разбанен!"); await s.clear()

@dp.message(F.text == "✉️ Написать юзеру", F.from_user.id == ADMIN_ID)
async def ls_1(m, s: FSMContext):
    await m.answer("Введите ID:"); await s.set_state(AdminState.waiting_for_user_id_msg)

@dp.message(AdminState.waiting_for_user_id_msg, F.from_user.id == ADMIN_ID)
async def ls_2(m, s: FSMContext):
    await s.update_data(tid=m.text); await m.answer("Введите текст:"); await s.set_state(AdminState.waiting_for_msg_text)

@dp.message(AdminState.waiting_for_msg_text, F.from_user.id == ADMIN_ID)
async def ls_3(m, s: FSMContext):
    d = await s.get_data()
    try:
        await bot.send_message(d['tid'], f"👤 Сообщение от админа:\n\n{m.text}")
        await m.answer("✅ Отправлено")
    except Exception as e: await m.answer(f"❌ Ошибка: {e}")
    await s.clear()

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
            for offset in [1, 2, 3]:
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
async def start_cmd(m: types.Message, s: FSMContext):
    if is_banned(m.from_user.id): return
    save_user(m.from_user)
    kb = ReplyKeyboardBuilder()
    for c in COURSES.keys(): kb.add(types.KeyboardButton(text=c))
    kb.adjust(2)
    await s.set_state(UserState.choosing_course)
    await m.answer("Выберите ваш курс:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_course)
async def proc_course(m: types.Message, s: FSMContext):
    if m.text in COURSES:
        await s.update_data(course=m.text)
        await s.set_state(UserState.choosing_group)
        kb = ReplyKeyboardBuilder()
        for g in GROUPS_BY_COURSE.get(m.text, []): kb.add(types.KeyboardButton(text=g))
        kb.add(types.KeyboardButton(text="⬅️ Назад к курсам"))
        kb.adjust(2)
        await m.answer(f"Выбран {m.text}. Выберите группу:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_group)
async def proc_group(m: types.Message, s: FSMContext):
    data = await s.get_data()
    course = data.get("course")
    if m.text == "⬅️ Назад к курсам": return await start_cmd(m, s)
    if m.text in GROUPS_BY_COURSE.get(course, []):
        await s.update_data(group=m.text)
        await s.set_state(UserState.choosing_day)
        kb = ReplyKeyboardBuilder()
        kb.row(types.KeyboardButton(text="📅 На сегодня"), types.KeyboardButton(text="📅 На завтра"))
        kb.row(types.KeyboardButton(text="🗓 На всю неделю"), types.KeyboardButton(text="⬅️ Назад к группам"))
        await m.answer(f"Группа {m.text}. Выберите период:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_day)
async def proc_day(m: types.Message, s: FSMContext):
    if m.text == "⬅️ Назад к группам":
        data = await s.get_data()
        m.text = data.get("course")
        return await proc_course(m, s)
    
    await s.update_data(req=m.text)
    if await check_subscriptions(m.from_user.id):
        await send_sch(m, s)
    else:
        builder = InlineKeyboardBuilder()
        for i, ch in enumerate(CHANNELS, 1):
            builder.row(InlineKeyboardButton(text=f"📢 Канал {i}", url=f"https://t.me/{ch.replace('@', '')}"))
        builder.row(InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_subs"))
        await m.answer("🛑 Подпишитесь на каналы для доступа:", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "check_subs")
async def cb_check(c: CallbackQuery, s: FSMContext):
    if await check_subscriptions(c.from_user.id):
        await c.message.edit_text("✅ Доступ разрешен!")
        await send_sch(c.message, s)
    else: await c.answer("❌ Вы подписались не на всё!", show_alert=True)

async def send_sch(m, s: FSMContext):
    d = await s.get_data()
    cid = m.chat.id if isinstance(m, types.Message) else m.message.chat.id
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{COURSES[d['course']]}!A1:BG100?key={GOOGLE_API_KEY}"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            rows = data.get("values", [])

    col_idx = -1
    for i, cell in enumerate(rows[1]):
        if d['group'].replace("-","").lower() in cell.replace("-","").lower() and cell != "":
            col_idx = i; break

    days = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']
    req = d.get("req", "").lower()
    
    if "сегодня" in req:
        target = days[datetime.now().weekday()]
        res = format_schedule(rows, col_idx, target)
        await bot.send_message(cid, f"📅 **Сегодня ({target}):**\n{res}", parse_mode="Markdown")
    elif "завтра" in req:
        target = days[(datetime.now() + timedelta(days=1)).weekday()]
        res = format_schedule(rows, col_idx, target)
        await bot.send_message(cid, f"📅 **Завтра ({target}):**\n{res}", parse_mode="Markdown")
    else:
        res = format_schedule(rows, col_idx)
        await bot.send_message(cid, f"🗓 **Неделя для {d['group']}:**\n{res}", parse_mode="Markdown")

# --- ЗАПУСК ---

async def main():
    await broadcast("✅ Бот запущен!")
    try: await dp.start_polling(bot)
    finally:
        if send_shutdown_notice: await broadcast("⚠️ Бот уходит на тех. обслуживание.")
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
