import logging
import asyncio
import aiohttp
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = "7987454041:AAGU-DGvVqgN7rioySxL5zINEk60WSlkUW4"
GOOGLE_API_KEY = "AIzaSyDZUuMn8B8t_REygaEGpEI47hyLSQrDKDk"
SCHEDULE_TABLE_ID = "1X6YF54l1rgP7MFfkTa1b_L6f4f3aWuADZwF8wwTWKK4"

COURSES = ["1 курс", "2 курс", "3 курс", "4 курс"]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class UserState(StatesGroup):
    choosing_course = State()
    choosing_group = State()
    choosing_day = State()
    waiting_for_teacher = State()

# --- МАКСИМАЛЬНО БЕЗОПАСНЫЙ ПОИСК КАБИНЕТА ---
def get_room_safe(rows, r_idx, c_idx):
    try:
        # Проверяем, что индекс строки вообще существует в таблице
        if r_idx < 0 or r_idx >= len(rows): return ""
        
        # Проверяем 3 ячейки справа (на случай скрытых столбцов)
        for offset in range(1, 4):
            if len(rows[r_idx]) > c_idx + offset:
                val = rows[r_idx][c_idx + offset].strip()
                if val and val.lower() not in ["-", ".", "каб", "пара"]:
                    return val
        
        # Если в этой строке нет, проверим строку ниже (вдруг кабинет там)
        next_r = r_idx + 1
        if next_r < len(rows):
            for offset in range(1, 4):
                if len(rows[next_r]) > c_idx + offset:
                    val = rows[next_r][c_idx + offset].strip()
                    if val and val.lower() not in ["-", ".", "каб", "пара"]:
                        return val
    except: pass
    return ""

# --- ПОИСК ДЛЯ ПРЕПОДАВАТЕЛЯ ---
async def fetch_teacher_schedule(teacher_name):
    all_lessons = []
    t_name_lower = teacher_name.lower()

    async with aiohttp.ClientSession() as session:
        for course in COURSES:
            url = f"https://sheets.googleapis.com/v4/spreadsheets/{SCHEDULE_TABLE_ID}/values/{course}!A1:BG100?key={GOOGLE_API_KEY}"
            async with session.get(url) as resp:
                if resp.status != 200: continue
                data = await resp.json()
                rows = data.get("values", [])
            
            if len(rows) < 3: continue

            curr_day = ""
            for i in range(2, len(rows)):
                row = rows[i]
                if not row: continue
                
                # Ищем день недели в колонке A
                if row[0].strip():
                    day_cand = row[0].replace('\n', ' ').strip().upper()
                    if any(d in day_cand for d in ["ПОНЕДЕЛЬНИК", "ВТОРНИК", "СРЕДА", "ЧЕТВЕРГ", "ПЯТНИЦА", "СУББОТА"]):
                        curr_day = day_cand
                
                if not curr_day: continue

                # Сканируем колонки групп (начиная с С / индекс 2)
                для col_idx в диапазон(2, лен(ряд)):
 cell_val = строка[col_idx].полоска().ниже()
                    
                    # Если нашли фамилию в ячейке
                    если t_name_lower в cell_val и лен(cell_val) > 2:
 pair_num = строка[1].полоска() если лен(ряд) > 1 еще "?"
                        
                        # Предмет обычно строкой выше учителя
 тема = строки[я-1][col_idx].полоска() если я > 0 и лен(ряды[я-1]) > col_idx еще "Предмет?"
                        
                        # Группа в шапке (строка 2, индекс 1)
 имя_группы = строки[1][col_idx].полоска() если лен(ряды[1]) > col_idx еще "Группа?"
                        
                        # Ищем кабинет в строке предмета (i-1)
 комната = получить_комнату_безопасно(ряды, i-1, col_idx)
 room_str = ф" [каб. {комната}]" если комната еще ""
                        
 все_уроки.добавить(ф"📅 **{текущий_день}**\н{число_пар} пара: {предмет} — {имя_группы}{room_str}")

    возвращаться "\н\н".присоединиться(все_уроки) если все_уроки еще "🔍 Ничего не найдено."

# --- ОБРАБОТЧИКИ ---

@dp.сообщение(Команда("старт"), Фильтр состояний('*'))
@dp.сообщение(Ф.текст == "⬅️ Назад")
асинхронный деф start_cmd(сообщение: типы.Сообщение, состояние: FSMContext):
    ждать состояние.прозрачный()
 кб = ОтветитьKeyboardBuilder()
 кб.ряд(КлавиатураКнопка(текст="🎓 Я студент"), КлавиатураКнопка(текст="👨‍🏫 Я преподаватель"))
    ждать сообщение.отвечать("Добро пожаловать! Кто вы?", reply_markup=кб.как_разметка(изменить размер_клавиатуры=Истинный))

@dp.сообщение(Ф.текст == "👨‍🏫 Я преподаватель")
асинхронный деф режим_учителя(сообщение: типы.Сообщение, состояние: FSMContext):
    ждать состояние.установить_состояние(Состояние пользователя.ожидание_учителя_)
    ждать сообщение.отвечать("📝 Введите вашу фамилию:", 
 ответ_разметка=ОтветКлавиатураРазметка(клавиатура=[[КлавиатураКнопка(текст="⬅️ Назад")]], изменить размер_клавиатуры=Истинный))

@dp.сообщение(Состояние пользователя.ожидание_учителя_)
асинхронный деф учитель_поиск(сообщение: типы.Сообщение, состояние: FSMContext):
    если сообщение.текст == "⬅️ Назад": возвращаться ждать start_cmd(сообщение, состояние)
    
 wait_msg = ждать сообщение.отвечать("⏳ Секунду, проверяю все курсы...")
 результат = ждать расписание_учителя_принеси(сообщение.текст)
    ждать wait_msg.редактировать_текст(ф"👨‍🏫 **Расписание для {сообщение.текст}:**\н\н{результат}", режим_анализа="Маркдаун")

@dp.сообщение(Ф.текст == "🎓 Я студент")
асинхронный деф режим_студента(сообщение: типы.Сообщение, состояние: FSMContext):
 кб = ОтветитьKeyboardBuilder()
    для c в КУРСЫ: кб.добавлять(КлавиатураКнопка(текст=с))
 кб.ряд(КлавиатураКнопка(текст="⬅️ Назад"))
    ждать состояние.установить_состояние(Состояние пользователя.выбор_курса)
    ждать сообщение.отвечать("Выберите ваш курс:", reply_markup=кб.регулировать(2).как_разметка(изменить размер_клавиатуры=Истинный))

# (Здесь должна быть ваша старая логика выбора группы для студентов)

асинхронный деф основной():
    ждать бот.удалить_вебхук(drop_pending_updates=Истинный)
    ждать дп.старт_опроса(бот)

если __имя__ == "__основной__":
 асинсио.бегать(основной())
