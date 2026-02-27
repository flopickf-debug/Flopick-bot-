import logging
import aiohttp
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- НАСТРОЙКИ (ОБЯЗАТЕЛЬНО ЗАПОЛНИ) ---
BOT_TOKEN = "7987454041:AAGU-DGvVqgN7rioySxL5zINEk60WSlkUW4"
GOOGLE_API_KEY = "AIzaSyDZUuMn8B8t_REygaEGpEI47hyLSQrDKDk"
SPREADSHEET_ID = "1X6YF54l1rgP7MFfkTa1b_L6f4f3aWuADZwF8wwTWKK4"

# Соответствие: Кнопка курса -> Название листа в Google Таблице
COURSES = {
    "1 курс": "1 курс",
    "2 курс": "2 курс",
    "3 курс": "3 курс",
    "4 курс": "4 курс"
}

# Распределение групп по курсам для кнопок
GROUPS_BY_COURSE = {
    "1 курс": ["АВМ-110", "ИСП-104", "ИСП-105", "АВМ-110", "ДОУ-102", "СВП-111", "ОСД-134", "ПКП-121", "СЗС-133", "СРС-111", "ТГО-101", "ТМС-103", "ТОС-103", "ЭМР-107", "ЭМР-108"],
    "2 курс": ["АВМ-208", "ИСП-202", "МПР-202", "ОСД-233", "ПКП-219", "ПКП-220", "СЗС-232", "СРС-209", "ТМС-202", "ТОС-202", "ЭМР-205", "ЮСП-201"],
    "3 курс": ["ДОУ-301", "ИСП-301", "ПКП-317", "ПКП-318", "ПОС-301", "СВП-309", "СВП-310", "СЗС-331", "ТМС-302", "ТОС-301"],
    "4 курс": ["СВП-425", "ПКП-415", "СВП-426", "СЗС-427"]
}
# ---------------------------------------

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Состояния бота
class UserState(StatesGroup):
    choosing_course = State()
    choosing_group = State()
    choosing_day = State()

async def get_data_from_google(sheet_name):
    """Получение данных с конкретного листа таблицы"""
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{sheet_name}!A1:BG100?key={GOOGLE_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            res = await response.json()
            return res.get("values", [])

def format_schedule(rows, col_index, target_day=None):
    """Логика парсинга строк и поиска кабинетов"""
    schedule = ""
    current_day_in_table = ""
    found_any = False
    
    # Пропускаем первые 2 строки (заголовок и названия групп)
    for row in rows[2:]:
        day_cell = row[0].strip().lower() if len(row) > 0 and row[0].strip() else ""
        if day_cell:
            current_day_in_table = day_cell
        
        # Если ищем конкретный день, проверяем совпадение
        is_target_day = True if not target_day else target_day.lower() in current_day_in_table.lower()
        
        if is_target_day:
            subject = row[col_index] if len(row) > col_index else ""
            
            # Поиск кабинета (проверяем 2 ячейки справа от предмета)
            room = ""
            for offset in [1, 2]:
                if len(row) > col_index + offset:
                    val = row[col_index + offset].strip()
                    if val and val.lower() != "каб":
                        room = val
                        break
            
            if subject.strip() and subject.lower() != "предмет":
                found_any = True
                # Добавляем название дня только при выводе всей недели
                if day_cell and not target_day:
                    schedule += f"\n🟠 **{current_day_in_table.upper()}**\n"
                
                lesson_num = row[1] if len(row) > 1 else "?"
                room_str = f" (каб. {room})" if room else ""
                schedule += f" - {lesson_num} пара: {subject}{room_str}\n"
                
    return schedule if found_any else "На этот период занятий не найдено."

# --- КЛАВИАТУРЫ ---
def kb_courses():
    builder = ReplyKeyboardBuilder()
    for course in COURSES.keys():
        builder.add(types.KeyboardButton(text=course))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def kb_groups(course_name):
    builder = ReplyKeyboardBuilder()
    groups = GROUPS_BY_COURSE.get(course_name, [])
    for group in groups:
        builder.add(types.KeyboardButton(text=group))
    builder.add(types.KeyboardButton(text="⬅️ Назад к курсам"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def kb_days():
    builder = ReplyKeyboardBuilder()
    builder.row(types.KeyboardButton(text="📅 На сегодня"), types.KeyboardButton(text="📅 На завтра"))
    builder.row(types.KeyboardButton(text="🗓 На всю неделю"))
    builder.row(types.KeyboardButton(text="⬅️ Назад к группам"))
    return builder.as_markup(resize_keyboard=True)

# --- ОБРАБОТЧИКИ (ХЕНДЛЕРЫ) ---

@dp.message(Command("start"))
@dp.message(F.text == "⬅️ Назад к курсам")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.set_state(UserState.choosing_course)
    await message.answer("Выберите ваш курс:", reply_markup=kb_courses())

@dp.message(UserState.choosing_course)
async def process_course(message: types.Message, state: FSMContext):
    if message.text in COURSES:
        await state.update_data(selected_course=message.text)
        await state.set_state(UserState.choosing_group)
        await message.answer(f"Выбран {message.text}. Теперь выберите группу:", reply_markup=kb_groups(message.text))
    else:
        await message.answer("Пожалуйста, используйте кнопки на клавиатуре.")

@dp.message(UserState.choosing_group)
async def process_group(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к курсам":
        return # Этот случай обработает хендлер выше
        
    user_data = await state.get_data()
    course = user_data.get("selected_course")
    
    if message.text in GROUPS_BY_COURSE.get(course, []):
        await state.update_data(selected_group=message.text)
        await state.set_state(UserState.choosing_day)
        await message.answer(f"Выбрана группа {message.text}. Какое расписание показать?", reply_markup=kb_days())
    else:
        await message.answer("Выберите группу из списка на кнопках.")

@dp.message(F.text == "⬅️ Назад к группам")
async def back_to_groups(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    course = user_data.get("selected_course")
    await state.set_state(UserState.choosing_group)
    await message.answer("Выберите группу:", reply_markup=kb_groups(course))

@dp.message(UserState.choosing_day)
async def process_schedule(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    course = user_data.get("selected_course")
    group = user_data.get("selected_group")
    sheet_name = COURSES[course]
    
    await bot.send_chat_action(message.chat.id, "typing")
    rows = await get_data_from_google(sheet_name)
    
    if not rows:
        await message.answer("❌ Ошибка: не удалось получить данные из таблицы.")
        return

    # Ищем колонку группы (в 2-й строке)
    header = rows[1]
    col_idx = -1
    for i, cell in enumerate(header):
        clean_cell = cell.replace("-","").replace(" ","").lower()
        clean_group = group.replace("-","").replace(" ","").lower()
        if clean_group in clean_cell and clean_cell != "":
            col_idx = i
            break
    
    if col_idx == -1:
        await message.answer("❌ Ошибка: группа не найдена на листе таблицы.")
        return

    days_ru = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']
    
    if "сегодня" in message.text.lower():
        target = days_ru[datetime.now().weekday()]
        result = format_schedule(rows, col_idx, target)
        await message.answer(f"📅 **Расписание на сегодня ({target}):**\n{result}", parse_mode="Markdown")
        
    elif "завтра" in message.text.lower():
        target = days_ru[(datetime.now() + timedelta(days=1)).weekday()]
        result = format_schedule(rows, col_idx, target)
        await message.answer(f"📅 **Расписание на завтра ({target}):**\n{result}", parse_mode="Markdown")
        
    elif "неделю" in message.text.lower():
        result = format_schedule(rows, col_idx)
        await message.answer(f"🗓 **Расписание на неделю для {group}:**\n{result}", parse_mode="Markdown")

async def main():
    print("--- БОТ ЗАПУЩЕН И ГОТОВ К РАБОТЕ ---")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass