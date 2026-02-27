import logging
import aiohttp
import asyncio
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, InlineKeyboardButton

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "7987454041:AAGU-DGvVqgN7rioySxL5zINEk60WSlkUW4")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "AIzaSyDZUuMn8B8t_REygaEGpEI47hyLSQrDKDk")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "1X6YF54l1rgP7MFfkTa1b_L6f4f3aWuADZwF8wwTWKK4")
ADMIN_ID = 879365319
CHANNEL_ID = "@loveshaverma"  # ЗАМЕНИ НА СВОЙ (с собачкой или ID)
CHANNEL_URL = "https://t.me/loveshaverma" # ЗАМЕНИ НА СВОЙ

DB_FILE = "users.txt"
BAN_FILE = "banned.txt"

GLOBAL_DELETE = False  
ADMIN_ONLY_DELETE = False  

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
    waiting_for_ad_content = State()
    waiting_for_ban_id = State()

# --- ПРОВЕРКИ ---

async def check_subscribe(user_id):
    """Проверка подписки на канал"""
    if user_id == ADMIN_ID: return True # Админу можно не подписываться
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            return True
    except Exception:
        return False
    return False

def save_user(user: types.User):
    user_id = str(user.id)
    username = f"@{user.username}" if user.username else "None"
    if not os.path.exists(DB_FILE): open(DB_FILE, "w").close()
    with open(DB_FILE, "r") as f: content = f.read()
    if user_id not in content:
        with open(DB_FILE, "a") as f: f.write(f"{user_id} | {username}\n")

def is_banned(user_id: int) -> bool:
    if not os.path.exists(BAN_FILE): return False
    with open(BAN_FILE, "r") as f: return str(user_id) in [l.strip() for l in f]

# --- АДМИН ПАНЕЛЬ ---

def get_admin_kb():
    kb = ReplyKeyboardBuilder()
    kb.row(types.KeyboardButton(text="📢 Рассылка"), types.KeyboardButton(text="👥 Список юзеров"))
    kb.row(types.KeyboardButton(text="🚫 Бан/Разбан"), types.KeyboardButton(text="📊 Статистика"))
    kb.row(types.KeyboardButton(text="🔄 Перезагрузить бота"), types.KeyboardButton(text="⬅️ Назад к курсам"))
    return kb.adjust(2).as_markup(resize_keyboard=True)

@dp.message(Command("admin"), F.from_user.id == ADMIN_ID, StateFilter('*'))
async def admin_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🛠 Админ-панель:", reply_markup=get_admin_kb())

@dp.message(F.text == "📢 Рассылка", F.from_user.id == ADMIN_ID, StateFilter('*'))
async def ad_start(message: types.Message, state: FSMContext):
    await state.set_state(AdminState.waiting_for_ad_content)
    await message.answer("Отправьте рекламный пост (текст/фото):")

@dp.message(AdminState.waiting_for_ad_content, F.from_user.id == ADMIN_ID)
async def ad_process(message: types.Message, state: FSMContext):
    with open(DB_FILE, "r") as f: uids = [l.split('|')[0].strip() for l in f if l.strip()]
    count = 0
    for uid in uids:
        try:
            await bot.copy_message(uid, message.chat.id, message.message_id)
            count += 1
            await asyncio.sleep(0.05)
        except: pass
    await message.answer(f"✅ Рассылка завершена ({count} чел.)", reply_markup=get_admin_kb())
    await state.clear()

@dp.message(F.text == "👥 Список юзеров", F.from_user.id == ADMIN_ID, StateFilter('*'))
async def user_list(message: types.Message):
    if os.path.exists(DB_FILE):
        await message.answer_document(FSInputFile(DB_FILE))
    else: await message.answer("База пуста.")

@dp.message(F.text == "🔄 Перезагрузить бота", F.from_user.id == ADMIN_ID, StateFilter('*'))
async def reboot(message: types.Message):
    await message.answer("♻️ Reboot...")
    os._exit(1)

# --- ЛОГИКА ТАБЛИЦ ---

async def get_schedule(course, group, target_day=None):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{course}!A1:BG100?key={GOOGLE_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json(); rows = data.get("values", [])
    if not rows: return "Ошибка таблицы."
    col = -1
    for i, cell in enumerate(rows[1]):
        if group.replace("-","").lower() in cell.replace("-","").lower() and cell: col = i; break
    if col == -1: return "Группа не найдена."
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
                        val = row[col+off].strip(); 
                        if val and val.lower() != "каб": room = val; break
                num = row[1] if len(row) > 1 else "?"
                if not target_day: text += f"\n🟠 **{curr_day.upper()}**\n"
                text += f" - {num} пара: {subj} (каб. {room if room else '?'})\n"
    return text if found else "Занятий нет."

# --- ХЕНДЛЕРЫ ПОЛЬЗОВАТЕЛЯ ---

@dp.message(StateFilter('*'))
async def main_logic(message: types.Message, state: FSMContext):
    if is_banned(message.from_user.id): return
    
    # ПРОВЕРКА ПОДПИСКИ ПЕРЕД ЛЮБЫМ ДЕЙСТВИЕМ
    subscribed = await check_subscribe(message.from_user.id)
    if not subscribed:
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="📢 Подписаться на канал", url=CHANNEL_URL))
        # Кнопка для повторной проверки
        kb.row(InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub"))
        return await message.answer("❌ **Для использования бота нужно подписаться на наш канал!**", reply_markup=kb.as_markup())

    if message.text in ["/start", "⬅️ Назад к курсам"]:
        save_user(message.from_user)
        await state.clear(); await state.set_state(UserState.choosing_course)
        kb = ReplyKeyboardBuilder()
        [kb.add(types.KeyboardButton(text=c)) for c in COURSES.keys()]
        return await message.answer("🎓 Выберите курс:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

    cur_state = await state.get_state()
    
    if cur_state == UserState.choosing_course and message.text in COURSES:
        await state.update_data(c=message.text); await state.set_state(UserState.choosing_group)
        kb = ReplyKeyboardBuilder()
        [kb.add(types.KeyboardButton(text=g)) for g in GROUPS_BY_COURSE[message.text]]
        kb.add(types.KeyboardButton(text="⬅️ Назад к курсам"))
        await message.answer("📍 Выберите группу:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

    elif cur_state == UserState.choosing_group:
        data = await state.get_data()
        if message.text in GROUPS_BY_COURSE.get(data.get('c'), []):
            await state.update_data(g=message.text); await state.set_state(UserState.choosing_day)
            kb = ReplyKeyboardBuilder()
            kb.row(types.KeyboardButton(text="📅 На сегодня"), types.KeyboardButton(text="📅 На завтра"))
            kb.row(types.KeyboardButton(text="🗓 На всю неделю"), types.KeyboardButton(text="⬅️ Назад к курсам"))
            await message.answer(f"👥 Группа {message.text}. Выберите период:", reply_markup=kb.as_markup(resize_keyboard=True))

    elif cur_state == UserState.choosing_day:
        data = await state.get_data()
        days = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']
        target = days[datetime.now().weekday()] if "сегодня" in message.text.lower() else \
                 days[(datetime.now() + timedelta(days=1)).weekday()] if "завтра" in message.text.lower() else None
        
        res = await get_schedule(COURSES[data['c']], data['g'], target)
        # Меню остается всегда!
        kb = ReplyKeyboardBuilder()
        kb.row(types.KeyboardButton(text="📅 На сегодня"), types.KeyboardButton(text="📅 На завтра"))
        kb.row(types.KeyboardButton(text="🗓 На всю неделю"), types.KeyboardButton(text="⬅️ Назад к курсам"))
        await message.answer(f"🗓 **Расписание**:\n{res}", parse_mode="Markdown", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.callback_query(F.data == "check_sub")
async def check_callback(call: types.CallbackQuery, state: FSMContext):
    if await check_subscribe(call.from_user.id):
        await call.answer("✅ Спасибо за подписку!")
        await call.message.delete()
        # Перекидываем на старт
        await start_cmd_manual(call.message, state, call.from_user)
    else:
        await call.answer("❌ Вы всё еще не подписаны!", show_alert=True)

async def start_cmd_manual(message, state, user):
    save_user(user)
    await state.clear(); await state.set_state(UserState.choosing_course)
    kb = ReplyKeyboardBuilder()
    [kb.add(types.KeyboardButton(text=c)) for c in COURSES.keys()]
    await message.answer("🎓 Доступ разрешен! Выберите курс:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
