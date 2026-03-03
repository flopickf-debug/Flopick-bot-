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
from aiogram.exceptions import TelegramBadRequest

# --- НАСТРОЙКИ ---
BOT_TOKEN = "7987454041:AAGU-DGvVqgN7rioySxL5zINEk60WSlkUW4"
GOOGLE_API_KEY = "AIzaSyDZUuMn8B8t_REygaEGpEI47hyLSQrDKDk"
SPREADSHEET_ID = "1X6YF54l1rgP7MFfkTa1b_L6f4f3aWuADZwF8wwTWKK4"
ADMIN_ID = 879365319
TABLE_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"

# СПИСОК КАНАЛОВ (Бот должен быть админом!)
CHANNELS = [
    {"id": "@loveshaverma", "url": "https://t.me/loveshaverma", "name": "Первый канал"},
    {"id": "@loveshaverma", "url": "https://t.me/loveshaverma", "name": "Второй канал"},
    {"id": "@loveshaverma", "url": "https://t.me/loveshaverma", "name": "Третий канал"}
]

DB_FILE = "users.txt"
BAN_FILE = "banned.txt"

# Создаем файлы, ТОЛЬКО если их нет, чтобы не стирать данные
for file in [DB_FILE, BAN_FILE]:
    if not os.path.exists(file):
        with open(file, "w") as f:
            pass

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

# --- ПРОВЕРКИ И БАЗА ---

async def check_all_subs(user_id):
    if user_id == ADMIN_ID: return True
    for ch in CHANNELS:
        try:
            m = await bot.get_chat_member(ch['id'], user_id)
            if m.status not in ["member", "administrator", "creator"]: return False
        except: return False
    return True

def save_user(user: types.User):
    uid = str(user.id)
    uname = f"@{user.username}" if user.username else "None"
    
    with open(DB_FILE, "r") as f:
        content = f.read()
    
    if uid not in content:
        with open(DB_FILE, "a") as f:
            f.write(f"{uid} | {uname}\n")

def is_banned(user_id: int):
    with open(BAN_FILE, "r") as f:
        return str(user_id) in [l.strip() for l in f]

# --- УВЕДОМЛЕНИЕ ПРИ ЗАПУСКЕ ---

async def send_startup_notify():
    with open(DB_FILE, "r") as f:
        uids = [l.split('|')[0].strip() for l in f if l.strip()]
    
    for uid in uids:
        try:
            await bot.send_message(uid, "⚡️ **Бот снова работает!**\nЧтобы обновить меню, напишите /start")
            await asyncio.sleep(0.05)
        except:
            pass

# --- ЛОГИКА ТАБЛИЦ ---

async def get_schedule(course, group, target_day=None):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{course}!A1:BG100?key={GOOGLE_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            rows = data.get("values", [])
    
    if not rows: return "⚠️ Ошибка доступа к таблице."
    
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

        if not pair_num and curr_day in schedule_dict and schedule_dict[curr_day]:
            schedule_dict[curr_day][-1] += f" — {content}"
            continue

        room = ""
        for off in range(1, 4):
            if len(row) > col + off:
                val = row[col+off].strip()
                if val and val.lower() != "каб":
                    room = f" (каб. {val})"; break

        if curr_day not in schedule_dict: schedule_dict[curr_day] = []
        schedule_dict[curr_day].append(f" - {pair_num if pair_num else '?'} пара: {content}{room}")

    if not schedule_dict: return "Занятий нет. 🎉"
    
    res = ""
    for day, lessons in schedule_dict.items():
        res += f"\n🟠 **{day}**\n" + "\n".join(lessons) + "\n"
    return res

# --- АДМИН-ПАНЕЛЬ ---

def get_admin_kb():
    kb = ReplyKeyboardBuilder()
    kb.row(types.KeyboardButton(text="📢 Рассылка"), types.KeyboardButton(text="👥 Список юзеров"))
    kb.row(types.KeyboardButton(text="🚫 Бан/Разбан"), types.KeyboardButton(text="📊 Статистика"))
    kb.row(types.KeyboardButton(text="🔄 Перезагрузить"), types.KeyboardButton(text="⬅️ Назад к курсам"))
    return kb.adjust(2).as_markup(resize_keyboard=True)

@dp.message(Command("admin"), F.from_user.id == ADMIN_ID, StateFilter('*'))
async def admin_main(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🛠 Панель администратора:", reply_markup=get_admin_kb())

@dp.message(F.text == "📢 Рассылка", F.from_user.id == ADMIN_ID)
async def ad_start(message: types.Message, state: FSMContext):
    await state.set_state(AdminState.waiting_for_ad_content)
    await message.answer("Отправьте сообщение для рассылки:")

@dp.message(AdminState.waiting_for_ad_content, F.from_user.id == ADMIN_ID)
async def ad_exec(message: types.Message, state: FSMContext):
    with open(DB_FILE, "r") as f: uids = [l.split('|')[0].strip() for l in f if l.strip()]
    c = 0
    for u in uids:
        try: await bot.copy_message(u, message.chat.id, message.message_id); c += 1
        except: pass
    await message.answer(f"✅ Готово! Получили: {c}", reply_markup=get_admin_kb())
    await state.clear()

@dp.message(F.text == "👥 Список юзеров", F.from_user.id == ADMIN_ID)
async def u_list(message: types.Message):
    await message.answer_document(FSInputFile(DB_FILE))

@dp.message(F.text == "🚫 Бан/Разбан", F.from_user.id == ADMIN_ID)
async def ban_start(message: types.Message, state: FSMContext):
    await state.set_state(AdminState.waiting_for_ban_id)
    await message.answer("Введите ID:")

@dp.message(AdminState.waiting_for_ban_id, F.from_user.id == ADMIN_ID)
async def ban_exec(message: types.Message, state: FSMContext):
    tid = message.text.strip()
    with open(BAN_FILE, "r") as f: bans = [l.strip() for l in f]
    if tid in bans: bans.remove(tid); res = f"✅ {tid} разбанен"
    else: bans.append(tid); res = f"🚫 {tid} забанен"
    with open(BAN_FILE, "w") as f: [f.write(x + "\n") for x in bans]
    await message.answer(res, reply_markup=get_admin_kb()); await state.clear()

# --- ЛОГИКА ПОЛЬЗОВАТЕЛЯ ---

@dp.message(StateFilter('*'))
async def global_handler(message: types.Message, state: FSMContext):
    if is_banned(message.from_user.id): return
    
    if not await check_all_subs(message.from_user.id):
        kb = InlineKeyboardBuilder()
        for i, ch in enumerate(CHANNELS, 1):
            kb.row(InlineKeyboardButton(text=f"📢 {ch['name']}", url=ch['url']))
        kb.row(InlineKeyboardButton(text="✅ Проверить подписку", callback_data="recheck"))
        return await message.answer("❗ **Для использования бота подпишитесь на каналы:**", reply_markup=kb.as_markup())

    if message.text in ["/start", "⬅️ Назад к курсам"]:
        save_user(message.from_user)
        await state.clear(); await state.set_state(UserState.choosing_course)
        kb = ReplyKeyboardBuilder()
        [kb.add(types.KeyboardButton(text=c)) for c in COURSES.keys()]
        return await message.answer("🎓 Выберите курс:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

    cur = await state.get_state()
    
    if cur == UserState.choosing_course and message.text in COURSES:
        await state.update_data(c=message.text); await state.set_state(UserState.choosing_group)
        kb = ReplyKeyboardBuilder()
        [kb.add(types.KeyboardButton(text=g)) for g in GROUPS_BY_COURSE[message.text]]
        kb.add(types.KeyboardButton(text="⬅️ Назад к курсам"))
        await message.answer("📍 Группа:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

    elif cur == UserState.choosing_group:
        data = await state.get_data()
        if message.text in GROUPS_BY_COURSE.get(data['c'], []):
            await state.update_data(g=message.text); await state.set_state(UserState.choosing_day)
            kb = ReplyKeyboardBuilder()
            kb.row(types.KeyboardButton(text="📅 На сегодня"), types.KeyboardButton(text="📅 На завтра"))
            kb.row(types.KeyboardButton(text="🗓 На неделю"), types.KeyboardButton(text="⬅️ Назад к курсам"))
            await message.answer(f"👥 Группа {message.text}:", reply_markup=kb.as_markup(resize_keyboard=True))

    elif cur == UserState.choosing_day:
        data = await state.get_data()
        d_list = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']
        target = d_list[datetime.now().weekday()] if "сегодня" in message.text.lower() else \
                 d_list[(datetime.now() + timedelta(days=1)).weekday()] if "завтра" in message.text.lower() else None
        
        res = await get_schedule(COURSES[data['c']], data['g'], target)
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="🔗 Открыть оригинал таблицы", url=TABLE_URL))
        await message.answer(f"🗓 **Расписание {data['g']}**:\n{res}", parse_mode="Markdown", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "recheck")
async def recheck_sub(call: types.CallbackQuery, state: FSMContext):
    if await check_all_subs(call.from_user.id):
        await call.message.delete()
        fake_msg = types.Message(message_id=0, date=datetime.now(), chat=call.message.chat, from_user=call.from_user, text="/start")
        await global_handler(fake_msg, state)
    else:
        await call.answer("❌ Вы не подписаны!", show_alert=True)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    asyncio.create_task(send_startup_notify())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
