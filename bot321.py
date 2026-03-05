import logging
import asyncio
import gspread
import aiohttp
import os
import json
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, KeyboardButton, FSInputFile
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

# --- СОСТОЯНИЯ ---
class UserState(StatesGroup):
    choosing_course = State()
    choosing_group = State()
    choosing_day = State()

class AdminState(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_ban = State()
    waiting_for_unban = State()

# --- ПОДКЛЮЧЕНИЕ К БАЗЕ ---
users_worksheet = None
blacklist_worksheet = None

try:
    creds_raw = os.environ.get("GOOGLE_CREDS")
    if creds_raw:
        creds_info = json.loads(creds_raw)
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        client = gspread.authorize(creds)
        db_sheet = client.open_by_key(DB_TABLE_ID)
        users_worksheet = db_sheet.worksheet("Users")
        blacklist_worksheet = db_sheet.worksheet("Blacklist")
        print("✅ БАЗА ДАННЫХ ПОДКЛЮЧЕНА")
    else:
        print("⚠️ ОШИБКА: Переменная GOOGLE_CREDS не найдена!")
except Exception as e:
    print(f"❌ ОШИБКА ПОДКЛЮЧЕНИЯ: {e}")

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def is_banned(user: types.User):
    if blacklist_worksheet is None: return False
    try:
        all_banned = blacklist_worksheet.col_values(1)
        uid = str(user.id)
        username = f"@{user.username}".lower() if user.username else "none"
        return uid in all_banned or username in [u.lower() for u in all_banned]
    except: return False

def save_user(user: types.User):
    if users_worksheet is None: return
    try:
        uid = str(user.id)
        if uid not in users_worksheet.col_values(1):
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

        room = ""
        for offset in range(1, 4):
            if len(row) > col + offset:
                val = row[col+offset].strip()
                if val and (val.isdigit() or "каб" in val.lower() or len(val) < 6):
                    room = f" (каб. {val})"
                    break

        if not pair_num and curr_day in schedule_dict:
            schedule_dict[curr_day][-1] += f" — {content}{room}"
            continue
        if curr_day not in schedule_dict: schedule_dict[curr_day] = []
        schedule_dict[curr_day].append(f" - {pair_num if pair_num else '?'} пара: {content}{room}")

    res = ""
    for day, lessons in schedule_dict.items():
        res += f"\n🟠 **{day}**\n" + "\n".join(lessons) + "\n"
    return res if res else "Занятий нет. 🎉"

# --- АДМИН ПАНЕЛЬ ---
@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def admin_panel(message: types.Message):
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="📊 Статистика"))
    kb.row(KeyboardButton(text="🚫 Забанить"), KeyboardButton(text="✅ Разбанить"))
    kb.row(KeyboardButton(text="📁 Список юзеров"), KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer("🛠 **Панель администратора**", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "🚫 Забанить", F.from_user.id == ADMIN_ID)
async def admin_ban_start(message: types.Message, state: FSMContext):
    await state.set_state(AdminState.waiting_for_ban)
    await message.answer("Введите **ID** или **Username** (с @) для бана:")

@dp.message(AdminState.waiting_for_ban, F.from_user.id == ADMIN_ID)
async def admin_ban_finish(message: types.Message, state: FSMContext):
    if blacklist_worksheet:
        target = message.text.strip()
        blacklist_worksheet.append_row([target])
        await message.answer(f"🚫 Пользователь `{target}` заблокирован.")
    await state.clear()

@dp.message(F.text == "✅ Разбанить", F.from_user.id == ADMIN_ID)
async def admin_unban_start(message: types.Message, state: FSMContext):
    await state.set_state(AdminState.waiting_for_unban)
    await message.answer("Введите **ID** или **Username** для разбана:")

@dp.message(AdminState.waiting_for_unban, F.from_user.id == ADMIN_ID)
async def admin_unban_finish(message: types.Message, state: FSMContext):
    if blacklist_worksheet:
        target = message.text.strip()
        try:
            cell = blacklist_worksheet.find(target)
            if cell:
                blacklist_worksheet.delete_rows(cell.row)
                await message.answer(f"✅ Пользователь `{target}` разблокирован.")
            else:
                await message.answer("Не найден в списке.")
        except: await message.answer("Ошибка таблицы.")
    await state.clear()

@dp.message(F.text == "📁 Список юзеров", F.from_user.id == ADMIN_ID)
async def export_users(message: types.Message):
    if users_worksheet:
        data = users_worksheet.get_all_values()
        with open("users.txt", "w", encoding="utf-8") as f:
            for r in data: f.write(" | ".join(r) + "\n")
        await message.answer_document(FSInputFile("users.txt"))

@dp.message(F.text == "📊 Статистика", F.from_user.id == ADMIN_ID)
async def show_stats(message: types.Message):
    if users_worksheet:
        count = len(users_worksheet.col_values(1)) - 1
        await message.answer(f"📈 Всего пользователей: {count}")

@dp.message(F.text == "📢 Рассылка", F.from_user.id == ADMIN_ID)
async def start_broadcast(message: types.Message, state: FSMContext):
    await state.set_state(AdminState.waiting_for_broadcast)
    await message.answer("Отправьте сообщение для рассылки:")

@dp.message(AdminState.waiting_for_broadcast, F.from_user.id == ADMIN_ID)
async def do_broadcast(message: types.Message, state: FSMContext):
    uids = users_worksheet.col_values(1)[1:] 
    count = 0
    for uid in uids:
        try:
            await bot.copy_message(chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id)
            count += 1
            await asyncio.sleep(0.05)
        except: pass
    await message.answer(f"✅ Отправлено: {count}")
    await state.clear()

# --- ОСНОВНЫЕ ОБРАБОТЧИКИ ---
@dp.message(Command("start"), StateFilter('*'))
async def cmd_start(message: types.Message, state: FSMContext):
    if await is_banned(message.from_user):
        return await message.answer("🚫 Вы заблокированы.")
    
    save_user(message.from_user)
    if not await check_subs(message.from_user.id):
        kb = InlineKeyboardBuilder()
        for ch in CHANNELS: kb.row(InlineKeyboardButton(text=ch['name'], url=ch['url']))
        kb.row(InlineKeyboardButton(text="✅ Проверить", callback_data="recheck"))
        return await message.answer("❗ Подпишитесь на канал:", reply_markup=kb.as_markup())

    await state.clear()
    await state.set_state(UserState.choosing_course)
    kb = ReplyKeyboardBuilder()
    for c in GROUPS_BY_COURSE.keys(): kb.add(KeyboardButton(text=c))
    await message.answer("🎓 Курс:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(F.text == "⬅️ Назад к курсам")
async def back_to_start(message: types.Message, state: FSMContext):
    await cmd_start(message, state)

@dp.message(UserState.choosing_course)
async def choose_course(message: types.Message, state: FSMContext):
    if await is_banned(message.from_user): return
    if message.text not in GROUPS_BY_COURSE: return
    await state.update_data(c=message.text)
    await state.set_state(UserState.choosing_group)
    kb = ReplyKeyboardBuilder()
    for g in GROUPS_BY_COURSE[message.text]: kb.add(KeyboardButton(text=g))
    kb.add(KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer(f"📍 Группа:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_group)
async def choose_group(message: types.Message, state: FSMContext):
    if await is_banned(message.from_user): return
    if message.text == "⬅️ Назад к курсам": return await cmd_start(message, state)
    await state.update_data(g=message.text)
    await state.set_state(UserState.choosing_day)
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📅 Завтра"))
    kb.row(KeyboardButton(text="🗓 На неделю"), KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer(f"📅 День:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_day)
async def show_res(message: types.Message, state: FSMContext):
    if await is_banned(message.from_user): return
    if message.text == "⬅️ Назад к курсам": return await cmd_start(message, state)
    data = await state.get_data()
    days = ['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА', 'СУББОТА', 'ВОСКРЕСЕНЬЕ']
    target = None
    if "Сегодня" in message.text: target = days[datetime.now().weekday()]
    elif "Завтра" in message.text: target = days[(datetime.now() + timedelta(days=1)).weekday()]

    res = await get_schedule(data['c'], data['g'], target)
    url_kb = InlineKeyboardBuilder().row(InlineKeyboardButton(text="🔗 Таблица", url=TABLE_URL))
    await message.answer(f"🗓 **{data['g']}**\n{res}", parse_mode="Markdown", reply_markup=url_kb.as_markup())

@dp.callback_query(F.data == "recheck")
async def recheck(call: types.CallbackQuery, state: FSMContext):
    if await check_subs(call.from_user.id):
        await call.message.delete()
        await cmd_start(call.message, state)
    else: await call.answer("❌ Нет подписки!", show_alert=True)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
