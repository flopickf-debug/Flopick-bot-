import logging
import asyncio
import gspread
import aiohttp
import os
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

# --- НАСТРОЙКИ ---
BOT_TOKEN = "7987454041:AAGU-DGvVqgN7rioySxL5zINEk60WSlkUW4"
GOOGLE_API_KEY = "AIzaSyDZUuMn8B8t_REygaEGpEI47hyLSQrDKDk"
SCHEDULE_TABLE_ID = "1X6YF54l1rgP7MFfkTa1b_L6f4f3aWuADZwF8wwTWKK4"
DB_TABLE_ID = "11KbeilP1HRonHQAAZusBS1-ffNo4FxHXa239yZMKJm8"
ADMIN_ID = 879365319 
TABLE_URL = f"https://docs.google.com/spreadsheets/d/{SCHEDULE_TABLE_ID}/edit"

CHANNELS = [{"id": "@loveshaverma", "url": "https://t.me/loveshaverma", "name": "Подпишись на канал"}]

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
    waiting_for_broadcast = State()

# --- ПОДКЛЮЧЕНИЕ К ТАБЛИЦЕ ---
users_worksheet = None
try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    db_sheet = client.open_by_key(DB_TABLE_ID)
    users_worksheet = db_sheet.worksheet("Users")
except Exception as e:
    logging.error(f"Ошибка Google Sheets: {e}")

# --- ФУНКЦИИ ---
def save_user(user: types.User):
    if users_worksheet is None: return
    try:
        uid = str(user.id)
        existing_ids = users_worksheet.col_values(1)
        if uid not in existing_ids:
            users_worksheet.append_row([uid, f"@{user.username}", datetime.now().strftime("%d.%m.%Y %H:%M")])
    except: pass

async def check_subs(user_id):
    if user_id == ADMIN_ID: return True
    for ch in CHANNELS:
        try:
            m = await bot.get_chat_member(ch['id'], user_id)
            if m.status not in ["member", "administrator", "creator"]: return False
        except: return False
    return True

async def get_schedule(course, group, target_day=None):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SCHEDULE_TABLE_ID}/values/{course}!A1:BG100?key={GOOGLE_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            rows = data.get("values", [])
    
    if not rows: return "⚠️ Таблица пуста."
    
    col = -1
    for i, cell in enumerate(rows[1]):
        if group.lower() in cell.lower():
            col = i; break
    if col == -1: return f"⚠️ Группа {group} не найдена."

    schedule_dict, curr_day = {}, ""
    for row in rows[2:]:
        day_val = row[0].strip().upper() if len(row) > 0 and row[0].strip() else ""
        if day_val: curr_day = day_val
        if not curr_day or (target_day and target_day.upper() not in curr_day): continue

        pair_num = row[1].strip() if len(row) > 1 else ""
        content = row[col].strip() if len(row) > col else ""
        if not content: continue

        # ПОИСК КАБИНЕТА
        room = ""
        if len(row) > col + 1 and row[col+1].strip():
            room = f" (каб. {row[col+1].strip()})"

        if not pair_num and curr_day in schedule_dict:
            schedule_dict[curr_day][-1] += f" — {content}{room}"
            continue

        if curr_day not in schedule_dict: schedule_dict[curr_day] = []
        schedule_dict[curr_day].append(f" - {pair_num if pair_num else '?'} пара: {content}{room}")

    res = ""
    for day, lessons in schedule_dict.items():
        res += f"\n🟠 **{day}**\n" + "\n".join(lessons) + "\n"
    return res if res else "Занятий нет. 🎉"

# --- АДМИН МЕНЮ ---
@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def admin_panel(message: types.Message):
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="📊 Статистика"))
    kb.row(KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer("🛠 Админ-панель:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "📢 Рассылка", F.from_user.id == ADMIN_ID)
async def start_broadcast(message: types.Message, state: FSMContext):
    await state.set_state(AdminState.waiting_for_broadcast)
    await message.answer("Введите текст для рассылки всем пользователям:")

@dp.message(AdminState.waiting_for_broadcast, F.from_user.id == ADMIN_ID)
async def do_broadcast(message: types.Message, state: FSMContext):
    uids = users_worksheet.col_values(1)[1:] 
    count = 0
    for uid in uids:
        try:
            await bot.send_message(uid, f"🔔 **Объявление:**\n\n{message.text}")
            count += 1
            await asyncio.sleep(0.05)
        except: pass
    await message.answer(f"✅ Рассылка завершена. Получили: {count} чел.")
    await state.clear()

@dp.message(F.text == "📊 Статистика", F.from_user.id == ADMIN_ID)
async def show_stats(message: types.Message):
    count = len(users_worksheet.col_values(1)) - 1
    await message.answer(f"👥 Всего пользователей в базе: {count}")

# --- ОБЫЧНЫЕ ХЕНДЛЕРЫ ---
@dp.message(Command("start"), StateFilter('*'))
async def cmd_start(message: types.Message, state: FSMContext):
    save_user(message.from_user)
    if not await check_subs(message.from_user.id):
        kb = InlineKeyboardBuilder()
        [kb.row(InlineKeyboardButton(text=ch['name'], url=ch['url'])) for ch in CHANNELS]
        kb.row(InlineKeyboardButton(text="✅ Проверить", callback_data="recheck"))
        return await message.answer("Подпишитесь на канал!", reply_markup=kb.as_markup())

    await state.clear()
    await state.set_state(UserState.choosing_course)
    kb = ReplyKeyboardBuilder()
    [kb.add(KeyboardButton(text=c)) for c in GROUPS_BY_COURSE.keys()]
    await message.answer("🎓 Выберите курс:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(F.text == "⬅️ Назад к курсам")
async def back_to_start(message: types.Message, state: FSMContext):
    await cmd_start(message, state)

@dp.message(UserState.choosing_course)
async def choose_course(message: types.Message, state: FSMContext):
    if message.text not in GROUPS_BY_COURSE: return
    await state.update_data(c=message.text)
    await state.set_state(UserState.choosing_group)
    kb = ReplyKeyboardBuilder()
    [kb.add(KeyboardButton(text=g)) for g in GROUPS_BY_COURSE[message.text]]
    kb.add(KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer(f"📍 {message.text}. Выберите группу:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_group)
async def choose_group(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к курсам": return await cmd_start(message, state)
    await state.update_data(g=message.text)
    await state.set_state(UserState.choosing_day)
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📅 Завтра"))
    kb.row(KeyboardButton(text="🗓 На неделю"), KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer(f"Группа {message.text}:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_day)
async def show_res(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к курсам": return await cmd_start(message, state)
    data = await state.get_data()
    days = ['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА', 'СУББОТА', 'ВОСКРЕСЕНЬЕ']
    target = None
    if "Сегодня" in message.text: target = days[datetime.now().weekday()]
    elif "Завтра" in message.text: target = days[(datetime.now() + timedelta(days=1)).weekday()]

    res = await get_schedule(data['c'], data['g'], target)
    
    # КНОПКА ОРИГИНАЛА ТАБЛИЦЫ
    url_kb = InlineKeyboardBuilder()
    url_kb.row(InlineKeyboardButton(text="🔗 Оригинал таблицы", url=TABLE_URL))
    
    await message.answer(f"🗓 **{data['g']}**\n{res}", parse_mode="Markdown", reply_markup=url_kb.as_markup())

@dp.callback_query(F.data == "recheck")
async def recheck(call: types.CallbackQuery, state: FSMContext):
    if await check_subs(call.from_user.id):
        await call.message.delete()
        await cmd_start(call.message, state)
    else: await call.answer("❌ Подписка не найдена!", show_alert=True)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
