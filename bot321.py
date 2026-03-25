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

# --- НАСТРОЙКИ (ЗАПОЛНИ СВОИ ID) ---
BOT_TOKEN = "7987454041:AAGU-DGvVqgN7rioySxL5zINEk60WSlkUW4"
GOOGLE_API_KEY = "AIzaSyDZUuMn8B8t_REygaEGpEI47hyLSQrDKDk"
SCHEDULE_TABLE_ID = "1X6YF54l1rgP7MFfkTa1b_L6f4f3aWuADZwF8wwTWKK4"
DB_TABLE_ID = "11KbeilP1HRonHQAAZusBS1-ffNo4FxHXa239yZMKJm8"

OWNER_ID = 879365319 # ТВОЙ ID
TABLE_URL = f"https://docs.google.com/spreadsheets/d/{SCHEDULE_TABLE_ID}/edit"

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
    waiting_for_teacher_name = State()

class AdminState(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_ban = State()
    waiting_for_unban = State()
    waiting_for_channel = State()
    waiting_for_new_admin = State()

# --- ПОДКЛЮЧЕНИЕ К GOOGLE SHEETS ---
users_worksheet = None
blacklist_worksheet = None
settings_worksheet = None
channels_worksheet = None
admins_worksheet = None

try:
    creds_raw = os.environ.get("GOOGLE_CREDS")
    if creds_raw:
        creds_info = json.loads(creds_raw)
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        client = gspread.authorize(creds)
        db_sheet = client.open_by_key(DB_TABLE_ID)
        
        def get_ws(name):
            try: return db_sheet.worksheet(name)
            except: return None

        users_worksheet = get_ws("Users")
        blacklist_worksheet = get_ws("Blacklist")
        settings_worksheet = get_ws("Settings")
        channels_worksheet = get_ws("Channels")
        admins_worksheet = get_ws("Admins")
        print("✅ БАЗА ДАННЫХ ПОДКЛЮЧЕНА")
except Exception as e:
    print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")

# --- ФУНКЦИИ ПРОВЕРКИ ---
async def get_admins_ids():
    try:
        if admins_worksheet:
            return [int(uid) for uid in admins_worksheet.col_values(1) if uid.isdigit()]
    except: pass
    return [OWNER_ID]

async def get_sub_settings():
    try:
        if settings_worksheet: return settings_worksheet.cell(1, 2).value == "on"
    except: pass
    return True

async def get_channels():
    try:
        if channels_worksheet: return channels_worksheet.get_all_values()
    except: pass
    return []

async def is_banned(user: types.User):
    try:
        if blacklist_worksheet:
            banned = blacklist_worksheet.col_values(1)
            uid = str(user.id)
            return uid in banned or (user.username and f"@{user.username}".lower() in [u.lower() for u in banned])
    except: pass
    return False

async def check_subs(user_id):
    if user_id in await get_admins_ids(): return True
    if not await get_sub_settings(): return True
    channels = await get_channels()
    for row in channels:
        try:
            m = await bot.get_chat_member(row[0], user_id)
            if m.status not in ["member", "administrator", "creator"]: return False
        except: continue
    return True

# --- ЛОГИКА ПОИСКА РАСПИСАНИЯ ---
async def get_schedule(course, group, target_day=None):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SCHEDULE_TABLE_ID}/values/{course}!A1:BG100?key={GOOGLE_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            rows = data.get("values", [])
    if not rows: return "⚠️ Таблица пуста."
    
    col = -1
    for i, cell in enumerate(rows[1]):
        if group.lower() in cell.lower(): col = i; break
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
                    room = f" (каб. {val})"; break
        
        if curr_day not in schedule_dict: schedule_dict[curr_day] = []
        schedule_dict[curr_day].append(f" - {pair_num if pair_num else '?'} пара: {content}{room}")
    
    res = ""
    for day, lessons in schedule_dict.items():
        res += f"\n🟠 **{day}**\n" + "\n".join(lessons) + "\n"
    return res if res else "Занятий нет. 🎉"

async def get_teacher_schedule(teacher_name):
    teacher_name = teacher_name.lower().strip()
    courses = ["1 курс", "2 курс", "3 курс", "4 курс"]
    results = []

    async with aiohttp.ClientSession() as session:
        for course in courses:
            url = f"https://sheets.googleapis.com/v4/spreadsheets/{SCHEDULE_TABLE_ID}/values/{course}!A1:BG100?key={GOOGLE_API_KEY}"
            async with session.get(url) as resp:
                data = await resp.json()
                rows = data.get("values", [])
            
            if not rows: continue
            
            for r_idx, row in enumerate(rows[2:], start=2):
                day = ""
                for i in range(r_idx, 1, -1):
                    if len(rows[i]) > 0 and rows[i][0].strip():
                        day = rows[i][0].strip().upper()
                        break
                
                pair_num = row[1] if len(row) > 1 else "?"
                for c_idx, cell in enumerate(row):
                    if teacher_name in cell.lower():
                        group_name = rows[1][c_idx] if len(rows[1]) > c_idx else "Неизвестна"
                        room = f" (каб. {row[c_idx+1]})" if len(row) > c_idx + 1 and row[c_idx+1].isdigit() else ""
                        results.append(f"📅 {day} | {pair_num} пара | Гр: {group_name}{room}")
    
    return "🔍 **Ваше расписание:**\n\n" + "\n".join(results) if results else "❌ Ничего не найдено. Проверьте фамилию."

# --- ХЕНДЛЕРЫ ПРЕПОДАВАТЕЛЯ ---
@dp.message(F.text == "👨‍🏫 Я преподаватель")
async def teacher_start(message: types.Message, state: FSMContext):
    await state.set_state(UserState.waiting_for_teacher_name)
    kb = ReplyKeyboardBuilder().add(KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer("📝 **Режим преподавателя**\n\nНапишите свою фамилию по примеру:\n`Петров А.В.` или просто `Петров`", 
                         parse_mode="Markdown", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.waiting_for_teacher_name)
async def teacher_search(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к курсам": return await cmd_start(message, state)
    msg = await message.answer("⏳ Ищу ваше расписание...")
    res = await get_teacher_schedule(message.text)
    await msg.edit_text(res, parse_mode="Markdown")

# --- АДМИН ПАНЕЛЬ ---
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id not in await get_admins_ids(): return
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="📊 Статистика"))
    kb.row(KeyboardButton(text="🚫 Забанить"), KeyboardButton(text="✅ Разбанить"))
    if message.from_user.id == OWNER_ID:
        status = "ВКЛ" if await get_sub_settings() else "ВЫКЛ"
        kb.row(KeyboardButton(text=f"{'✅' if status == 'ВКЛ' else '❌'} Обяз. подписка: {status}"))
        kb.row(KeyboardButton(text="➕ Назначить админа"), KeyboardButton(text="➖ Снять админа"))
        kb.row(KeyboardButton(text="➕ Добавить канал"), KeyboardButton(text="🗑 Удалить канал"))
    kb.row(KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer("🛠 **Панель управления**", reply_markup=kb.as_markup(resize_keyboard=True))

# --- ОБЩАЯ ЛОГИКА (START / КУРСЫ) ---
@dp.message(Command("start"), StateFilter('*'))
async def cmd_start(message: types.Message, state: FSMContext):
    if await is_banned(message.from_user): return await message.answer("🚫 Доступ заблокирован.")
    
    # Сохранение юзера
    try:
        if users_worksheet and str(message.from_user.id) not in users_worksheet.col_values(1):
            users_worksheet.append_row([str(message.from_user.id), f"@{message.from_user.username}", datetime.now().strftime("%d.%m.%Y %H:%M")])
    except: pass

    if not await check_subs(message.from_user.id):
        chs = await get_channels()
        kb = InlineKeyboardBuilder()
        for r in chs: kb.row(InlineKeyboardButton(text=r[2], url=r[1]))
        kb.row(InlineKeyboardButton(text="✅ Проверить", callback_data="recheck"))
        return await message.answer("❗ Подпишитесь на каналы:", reply_markup=kb.as_markup())
    
    await state.clear(); await state.set_state(UserState.choosing_course)
    kb = ReplyKeyboardBuilder()
    for c in GROUPS_BY_COURSE.keys(): kb.add(KeyboardButton(text=c))
    kb.row(KeyboardButton(text="👨‍🏫 Я преподаватель"))
    await message.answer("🎓 Выберите курс или режим:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

# --- АДМИН-ФУНКЦИИ (ПОДПИСКА, БАН, РАССЫЛКА) ---
@dp.message(F.text.contains("Обяз. подписка:"), F.from_user.id == OWNER_ID)
async def toggle_subs(message: types.Message):
    if settings_worksheet:
        new_val = "off" if await get_sub_settings() else "on"
        settings_worksheet.update_cell(1, 2, new_val)
        await admin_panel(message)

@dp.message(F.text == "📢 Рассылка", F.from_user.id.in_(await get_admins_ids()))
async def br_start(message: types.Message, state: FSMContext):
    await state.set_state(AdminState.waiting_for_broadcast)
    await message.answer("Текст сообщения:")

@dp.message(AdminState.waiting_for_broadcast)
async def br_end(message: types.Message, state: FSMContext):
    uids = users_worksheet.col_values(1)[1:]
    for uid in uids:
        try: await bot.copy_message(uid, message.chat.id, message.message_id); await asyncio.sleep(0.05)
        except: pass
    await message.answer("✅ Готово!"); await state.clear()

# [Остальные хендлеры выбора курса, группы и дня остаются идентичными...]
@dp.message(UserState.choosing_course)
async def course(message: types.Message, state: FSMContext):
    if message.text not in GROUPS_BY_COURSE: return
    await state.update_data(c=message.text); await state.set_state(UserState.choosing_group)
    kb = ReplyKeyboardBuilder()
    for g in GROUPS_BY_COURSE[message.text]: kb.add(KeyboardButton(text=g))
    kb.add(KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer("📍 Выберите группу:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_group)
async def group(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к курсам": return await cmd_start(message, state)
    await state.update_data(g=message.text); await state.set_state(UserState.choosing_day)
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📅 Завтра"))
    kb.row(KeyboardButton(text="🗓 На неделю"), KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer("🕒 Период:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_day)
async def result(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к курсам": return await cmd_start(message, state)
    data = await state.get_data(); days = ['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА', 'СУББОТА', 'ВОСКРЕСЕНЬЕ']
    target = days[datetime.now().weekday()] if "Сегодня" in message.text else days[(datetime.now() + timedelta(days=1)).weekday()] if "Завтра" in message.text else None
    res = await get_schedule(data['c'], data['g'], target)
    kb = InlineKeyboardBuilder().row(InlineKeyboardButton(text="🔗 Таблица", url=TABLE_URL))
    await message.answer(f"🗓 **{data['g']}**\n{res}", parse_mode="Markdown", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "recheck")
async def recheck(call: types.CallbackQuery, state: FSMContext):
    if await check_subs(call.from_user.id): await call.message.delete(); await cmd_start(call.message, state)
    else: await call.answer("❌ Подписка не найдена!", show_alert=True)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
