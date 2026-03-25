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

OWNER_ID = 879365319 # ГЛАВНЫЙ АДМИН
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
        
        # Безопасное получение листов
        def get_ws(name):
            try: return db_sheet.worksheet(name)
            except: 
                logging.error(f"Лист '{name}' не найден!")
                return None

        users_worksheet = get_ws("Users")
        blacklist_worksheet = get_ws("Blacklist")
        settings_worksheet = get_ws("Settings")
        channels_worksheet = get_ws("Channels")
        admins_worksheet = get_ws("Admins")
        print("✅ ПОДКЛЮЧЕНИЕ К БАЗЕ ЗАВЕРШЕНО")
    else:
        print("❌ ОШИБКА: GOOGLE_CREDS не найден!")
except Exception as e:
    print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")

# --- ФУНКЦИИ ПРОВЕРКИ ---
async def get_admins_ids():
    try:
        if admins_worksheet:
            uids = admins_worksheet.col_values(1)
            return [int(uid) for uid in uids if uid.isdigit()]
    except: pass
    return [OWNER_ID]

async def get_sub_settings():
    try:
        if settings_worksheet:
            return settings_worksheet.cell(1, 2).value == "on"
    except: pass
    return True

async def get_channels():
    try:
        if channels_worksheet:
            return channels_worksheet.get_all_values()
    except: pass
    return []

async def is_banned(user: types.User):
    try:
        if blacklist_worksheet:
            banned = blacklist_worksheet.col_values(1)
            uid = str(user.id)
            uname = f"@{user.username}".lower() if user.username else "none"
            return uid in banned or uname in [u.lower() for u in banned]
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
        if not pair_num and curr_day in schedule_dict:
            schedule_dict[curr_day][-1] += f" — {content}{room}"
        else:
            if curr_day not in schedule_dict: schedule_dict[curr_day] = []
            schedule_dict[curr_day].append(f" - {pair_num if pair_num else '?'} пара: {content}{room}")
    res = ""
    for day, lessons in schedule_dict.items():
        res += f"\n🟠 **{day}**\n" + "\n".join(lessons) + "\n"
    return res if res else "Занятий нет. 🎉"

# --- АДМИН-ПАНЕЛЬ ---
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    all_admins = await get_admins_ids()
    if message.from_user.id not in all_admins: return

    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="📊 Статистика"))
    kb.row(KeyboardButton(text="🚫 Забанить"), KeyboardButton(text="✅ Разбанить"))
    
    if message.from_user.id == OWNER_ID:
        is_on = await get_sub_settings()
        sub_btn = "✅ Обяз. подписка: ВКЛ" if is_on else "❌ Обяз. подписка: ВЫКЛ"
        kb.row(KeyboardButton(text=sub_btn))
        kb.row(KeyboardButton(text="➕ Назначить админа"), KeyboardButton(text="➖ Снять админа"))
        kb.row(KeyboardButton(text="➕ Добавить канал"), KeyboardButton(text="🗑 Удалить канал"))
        kb.row(KeyboardButton(text="📁 Список юзеров"))
    
    kb.row(KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer("🛠 **Панель управления**", reply_markup=kb.as_markup(resize_keyboard=True))

# --- ОБРАБОТЧИКИ OWNER ---
@dp.message(F.text.contains("Обяз. подписка:"), F.from_user.id == OWNER_ID)
async def toggle_subs(message: types.Message):
    if settings_worksheet:
        current = await get_sub_settings()
        settings_worksheet.update_cell(1, 2, "off" if current else "on")
        await admin_panel(message)

@dp.message(F.text == "➕ Назначить админа", F.from_user.id == OWNER_ID)
async def add_adm_start(message: types.Message, state: FSMContext):
    await state.set_state(AdminState.waiting_for_new_admin)
    await message.answer("Введите ID нового админа:")

@dp.message(AdminState.waiting_for_new_admin, F.from_user.id == OWNER_ID)
async def add_adm_end(message: types.Message, state: FSMContext):
    if message.text.isdigit() and admins_worksheet:
        admins_worksheet.append_row([message.text])
        await message.answer(f"✅ {message.text} теперь админ.")
    await state.clear()

@dp.message(F.text == "➖ Снять админа", F.from_user.id == OWNER_ID)
async def rem_adm_menu(message: types.Message):
    ids = await get_admins_ids()
    kb = InlineKeyboardBuilder()
    for uid in ids:
        if uid != OWNER_ID: kb.row(InlineKeyboardButton(text=f"Удалить {uid}", callback_data=f"ra:{uid}"))
    await message.answer("Кого снять?", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("ra:"), F.from_user.id == OWNER_ID)
async def rem_adm_confirm(call: types.CallbackQuery):
    if admins_worksheet:
        try:
            cell = admins_worksheet.find(call.data.split(":")[1])
            admins_worksheet.delete_rows(cell.row)
            await call.answer("Удалено")
            await call.message.edit_text("Админ удален.")
        except: await call.answer("Ошибка")

@dp.message(F.text == "➕ Добавить канал", F.from_user.id == OWNER_ID)
async def add_ch_start(message: types.Message, state: FSMContext):
    await state.set_state(AdminState.waiting_for_channel)
    await message.answer("Формат: `@id | ссылка | Название`")

@dp.message(AdminState.waiting_for_channel, F.from_user.id == OWNER_ID)
async def add_ch_end(message: types.Message, state: FSMContext):
    if channels_worksheet:
        try:
            channels_worksheet.append_row([p.strip() for p in message.text.split("|")])
            await message.answer("✅ Добавлено")
        except: await message.answer("❌ Ошибка формата")
    await state.clear()

@dp.message(F.text == "🗑 Удалить канал", F.from_user.id == OWNER_ID)
async def del_ch_menu(message: types.Message):
    chs = await get_channels()
    kb = InlineKeyboardBuilder()
    for i, r in enumerate(chs): kb.row(InlineKeyboardButton(text=f"Удалить {r[2]}", callback_data=f"dc:{i+1}"))
    await message.answer("Что удалить?", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("dc:"), F.from_user.id == OWNER_ID)
async def del_ch_confirm(call: types.CallbackQuery):
    if channels_worksheet:
        channels_worksheet.delete_rows(int(call.data.split(":")[1]))
        await call.answer("Удалено")
        await call.message.edit_text("Канал удален.")

@dp.message(F.text == "📁 Список юзеров", F.from_user.id == OWNER_ID)
async def export_users(message: types.Message):
    if users_worksheet:
        data = users_worksheet.get_all_values()
        with open("users.txt", "w", encoding="utf-8") as f:
            for r in data: f.write(" | ".join(r) + "\n")
        await message.answer_document(FSInputFile("users.txt"))

# --- ОБРАБОТЧИКИ ДЛЯ ВСЕХ АДМИНОВ ---
@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    if message.from_user.id in await get_admins_ids() and users_worksheet:
        count = len(users_worksheet.col_values(1)) - 1
        await message.answer(f"📈 Пользователей: {count}")

@dp.message(F.text == "🚫 Забанить")
async def ban_start(message: types.Message, state: FSMContext):
    if message.from_user.id in await get_admins_ids():
        await state.set_state(AdminState.waiting_for_ban)
        await message.answer("Введите ID или @username для бана:")

@dp.message(AdminState.waiting_for_ban)
async def ban_end(message: types.Message, state: FSMContext):
    if blacklist_worksheet:
        blacklist_worksheet.append_row([message.text.strip()])
        await message.answer("🚫 Забанен")
    await state.clear()

@dp.message(F.text == "✅ Разбанить")
async def unban_start(message: types.Message, state: FSMContext):
    if message.from_user.id in await get_admins_ids():
        await state.set_state(AdminState.waiting_for_unban)
        await message.answer("Введите ID/@username для разбана:")

@dp.message(AdminState.waiting_for_unban)
async def unban_end(message: types.Message, state: FSMContext):
    if blacklist_worksheet:
        try:
            cell = blacklist_worksheet.find(message.text.strip())
            blacklist_worksheet.delete_rows(cell.row)
            await message.answer("✅ Разбанен")
        except: await message.answer("Не найден в ЧС")
    await state.clear()

@dp.message(F.text == "📢 Рассылка")
async def br_start(message: types.Message, state: FSMContext):
    if message.from_user.id in await get_admins_ids():
        await state.set_state(AdminState.waiting_for_broadcast)
        await message.answer("Текст рассылки:")

@dp.message(AdminState.waiting_for_broadcast)
async def br_end(message: types.Message, state: FSMContext):
    if users_worksheet:
        uids = users_worksheet.col_values(1)[1:]
        for uid in uids:
            try: await bot.copy_message(uid, message.chat.id, message.message_id); await asyncio.sleep(0.05)
            except: pass
        await message.answer("📢 Готово!")
    await state.clear()

# --- СТАРТ И ОСНОВНОЕ ---
@dp.message(Command("start"), StateFilter('*'))
async def cmd_start(message: types.Message, state: FSMContext):
    if await is_banned(message.from_user): return await message.answer("🚫 Вы в ЧС.")
    try:
        if users_worksheet and str(message.from_user.id) not in users_worksheet.col_values(1):
            users_worksheet.append_row([str(message.from_user.id), f"@{message.from_user.username}", datetime.now().strftime("%d.%m.%Y %H:%M")])
    except: pass
    if not await check_subs(message.from_user.id):
        chs = await get_channels()
        kb = InlineKeyboardBuilder()
        for r in chs: kb.row(InlineKeyboardButton(text=r[2], url=r[1]))
        kb.row(InlineKeyboardButton(text="✅ Проверить", callback_data="recheck"))
        return await message.answer("❗ Для работы бота подпишись:", reply_markup=kb.as_markup())
    await state.clear(); await state.set_state(UserState.choosing_course)
    kb = ReplyKeyboardBuilder()
    for c in GROUPS_BY_COURSE.keys(): kb.add(KeyboardButton(text=c))
    await message.answer("🎓 Выберите ваш курс:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(F.text == "⬅️ Назад к курсам")
async def back(message: types.Message, state: FSMContext): await cmd_start(message, state)

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
    await message.answer("📅 Выберите период:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.choosing_day)
async def result(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к курсам": return await cmd_start(message, state)
    data = await state.get_data(); days = ['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА', 'СУББОТА', 'ВОСКРЕСЕНЬЕ']
    target = None
    if "Сегодня" in message.text: target = days[datetime.now().weekday()]
    elif "Завтра" in message.text: target = days[(datetime.now() + timedelta(days=1)).weekday()]
    res = await get_schedule(data['c'], data['g'], target)
    kb = InlineKeyboardBuilder().row(InlineKeyboardButton(text="🔗 Оригинал таблицы", url=TABLE_URL))
    await message.answer(f"🗓 **Расписание {data['g']}**\n{res}", parse_mode="Markdown", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "recheck")
async def recheck(call: types.CallbackQuery, state: FSMContext):
    if await check_subs(call.from_user.id): await call.message.delete(); await cmd_start(call.message, state)
    else: await call.answer("❌ Подписки не найдены!", show_alert=True)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
