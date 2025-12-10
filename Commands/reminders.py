from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
import asyncio
import logging
import re
from datetime import datetime, timedelta

from Database.connection import connect_to_mongo # Импортируем функцию, если нужно где-то ещё, но не обязательно здесь
from Database.models import Reminder
from pydantic import ValidationError # Импортируем ValidationError

# Создаём роутер для команд, связанных с напоминаниями
router = Router()

logger = logging.getLogger(__name__)

bot_instance = None

def set_bot_instance(bot):
    """Функция для установки глобального экземпляра бота."""
    global bot_instance
    bot_instance = bot
    logger.info("Экземпляр бота установлен для модуля напоминаний.")

def parse_time(time_str: str) -> timedelta | datetime | None:
    now = datetime.now()

    # Паттерн для "через N минут/часов"
    match_relative = re.match(r'через\s+(\d+)\s+(минут|час|часа|часов)', time_str, re.IGNORECASE)
    if match_relative:
        value = int(match_relative.group(1))
        unit = match_relative.group(2).lower()
        if 'минут' in unit:
            return timedelta(minutes=value)
        elif 'час' in unit: # покрывает "час", "часа", "часов"
            return timedelta(hours=value)

    # Паттерн для "в HH:MM"
    match_absolute = re.match(r'в\s+(\d{1,2}):(\d{2})', time_str)
    if match_absolute:
        hour = int(match_absolute.group(1))
        minute = int(match_absolute.group(2))
        target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target_time <= now: # Если указанное время уже прошло сегодня, предполагаем завтра
            target_time += timedelta(days=1)
        return target_time - now # Возвращаем timedelta до цели

    return None # Не удалось распознать

async def send_reminder(chat_id: int, text: str, reminder_id: str):
    global bot_instance
    if not bot_instance:
        logger.error("send_reminder: bot_instance не установлен!")
        return

    from Database.connection import db # Импортируем внутри функции, когда она выполняется

    try:
        await bot_instance.send_message(chat_id=chat_id, text=f"⏰ Напоминание: {text}")
        logger.info(f"Напоминание отправлено пользователю {chat_id}: {text}")

        # Обновляем статус в БД
        await db["reminders"].update_one(
            {"id": reminder_id, "is_sent": False}, # Убедимся, что не отправлено дважды
            {"$set": {"is_sent": True, "sent_at": datetime.now()}}
        )
        logger.debug(f"Статус напоминания {reminder_id} обновлён на 'отправлено' в БД.")
    except Exception as e:
        logger.error(f"Ошибка при отправке напоминания пользователю {chat_id} или обновлении БД: {e}")
        try:
            await db["reminders"].update_one(
                {"id": reminder_id},
                {"$set": {"is_sent": True, "sent_at": datetime.now(), "error_on_send": str(e)}}
            )
        except Exception as db_e:
            logger.error(f"Ошибка при обновлении статуса ошибки в БД: {db_e}")

async def schedule_reminder_from_db(reminder: Reminder):
    global bot_instance
    if not bot_instance:
        logger.error("schedule_reminder_from_db: bot_instance не установлен!")
        return

    # Вычисляем задержку в секундах
    now = datetime.now()
    if reminder.target_datetime <= now:
        # Если время уже прошло, отправляем немедленно (или с минимальной задержкой)
        delay_seconds = 0
        logger.warning(f"Напоминание {reminder.id} для {reminder.user_id} уже просрочено. Отправляем немедленно.")
    else:
        delay_seconds = (reminder.target_datetime - now).total_seconds()

    if delay_seconds < 0:
        delay_seconds = 0 # На всякий случай

    logger.info(f"Планирование напоминания {reminder.id} через {delay_seconds} секунд.")

    # Создаём асинхронную задачу
    task = asyncio.create_task(asyncio.sleep(delay_seconds))
    task.add_done_callback(
        lambda t: asyncio.create_task(send_reminder(reminder.chat_id, reminder.reminder_text, reminder.id))
    )

async def load_pending_reminders():
    """Загружает из БД и планирует все неотправленные напоминания."""
    logger.info("Загрузка неотправленных напоминаний из БД...")
    try:
        # --- ОБРАЩАЕМСЯ К db ЧЕРЕЗ МОДУЛЬ connection ---
        from Database.connection import db # Импортируем внутри функции, когда она выполняется
        # ---
        if db is None:
            logger.critical("Переменная db не инициализирована! Подключение к MongoDB не выполнено?")
            return

        # Ищем все напоминания, которые ещё не были отправлены
        pending_reminders_docs = await db["reminders"].find({"is_sent": False}).to_list(length=1000)
        logger.info(f"Найдено {len(pending_reminders_docs)} неотправленных документов в БД.")

        for reminder_doc in pending_reminders_docs:
            # Удаляем '_id' из словаря, если он есть
            reminder_doc.pop('_id', None)

            try:
                # Создаём объект Reminder из данных БД
                reminder = Reminder(**reminder_doc)
                logger.debug(f"Успешно создан объект Reminder из БД для id: {reminder.id}")
                # Планируем его
                asyncio.create_task(schedule_reminder_from_db(reminder))
            except ValidationError as ve:
                logger.error(f"Ошибка валидации при создании Reminder из документа БД: {reminder_doc}. Ошибка: {ve}")
                # Продолжаем обработку следующих документов
                continue
            except Exception as e:
                logger.error(f"Неожиданная ошибка при создании Reminder из документа БД: {reminder_doc}. Ошибка: {e}")
                # Продолжаем обработку следующих документов
                continue

    except Exception as e:
        logger.error(f"Ошибка при загрузке напоминаний из БД: {e}")


@router.message(Command('set_reminder'))
async def command_set_reminder_handler(message: Message, state: FSMContext) -> None:
    global bot_instance
    if not bot_instance:
        await message.answer("❌ Ошибка: бот не инициализирован для работы с напоминаниями.")
        logger.error("command_set_reminder_handler: bot_instance не установлен!")
        return

    # Получаем текст команды после /set_reminder
    command_text = message.text[len('/set_reminder'):].strip()

    if not command_text:
        await message.answer("❌ Пожалуйста, укажите время и сообщение для напоминания.\nПример: <code>/set_reminder через 5 минут Закрыть задачу</code> или <code>/set_reminder в 18:30 Встреча с командой</code>", parse_mode='HTML')
        return

    # Простая логика: ищем "через N минут/часов" или "в HH:MM" и текст после
    time_match = re.search(r'(через\s+\d+\s+(минут|час|часа|часов)|в\s+\d{1,2}:\d{2})', command_text, re.IGNORECASE)
    if not time_match:
        await message.answer("❌ Не удалось распознать формат времени. Попробуйте:\n<code>/set_reminder через 5 минут Текст напоминания</code>\n<code>/set_reminder в 18:30 Текст напоминания</code>", parse_mode='HTML')
        return

    time_str = time_match.group(0)
    reminder_text = command_text[len(time_str):].strip()

    if not reminder_text:
        await message.answer("❌ Пожалуйста, укажите текст напоминания после времени.")
        return

    # Парсим время
    time_delta_or_datetime = parse_time(time_str)
    if time_delta_or_datetime is None:
        await message.answer("❌ Не удалось распознать указанное время. Попробуйте ещё раз.")
        return

    # Вычисляем target_datetime
    if isinstance(time_delta_or_datetime, timedelta):
        target_datetime = datetime.now() + time_delta_or_datetime
    else: # Это timedelta, возвращённый из parse_time для "в HH:MM"
         # Пересчитаем корректное время
        target_datetime = datetime.now() + time_delta_or_datetime

    if target_datetime <= datetime.now():
        await message.answer("❌ Указанное время уже прошло.")
        return

    # --- Сохраняем напоминание в MongoDB ---
    from Database.connection import db # Импортируем внутри функции, когда она выполняется
    if db is None:
            logger.critical("Переменная db не инициализирована! Подключение к MongoDB не выполнено?")
            await message.answer("❌ Ошибка: бот не инициализирован для работы с базой данных.")
            return

    reminder_obj = Reminder(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        reminder_text=reminder_text,
        target_datetime=target_datetime
    )

    try:
        result = await db["reminders"].insert_one(reminder_obj.dict())
        logger.info(f"Напоминание сохранено в БД с id: {reminder_obj.id}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении напоминания в БД: {e}")
        await message.answer("❌ Произошла ошибка при сохранении напоминания в базу данных.")
        return

    # --- Планируем задачу ---
    asyncio.create_task(schedule_reminder_from_db(reminder_obj))

    # Форматируем время для пользователя
    formatted_time = target_datetime.strftime("%H:%M %d.%m.%Y")
    await message.answer(f"✅ Напоминание установлено на <b>{formatted_time}</b>:\n<i>{reminder_text}</i>", parse_mode='HTML')
    logger.info(f"Пользователь {message.from_user.full_name} (ID: {message.from_user.id}) установил напоминание '{reminder_text}' на {formatted_time}.")


# --- Команда для отмены напоминаний (опционально) ---
@router.message(Command('cancel_reminders'))
async def command_cancel_reminders_handler(message: Message) -> None:
    user_id = message.from_user.id
    from Database.connection import db # Импортируем внутри функции, когда она выполняется
    if db is None:
        logger.critical("Переменная db не инициализирована! Подключение к MongoDB не выполнено?")
        await message.answer("❌ Ошибка: бот не инициализирован для работы с базой данных.")
        return
    try:
        result = await db["reminders"].delete_many(
            {"user_id": user_id, "is_sent": False}
        )
        deleted_count = result.deleted_count
        await message.answer(f"✅ Отменено {deleted_count} запланированных напоминаний.")
        logger.info(f"Пользователь {message.from_user.full_name} (ID: {message.from_user.id}) отменил {deleted_count} напоминаний.")
    except Exception as e:
        logger.error(f"Ошибка при отмене напоминаний для {user_id}: {e}")
        await message.answer("❌ Произошла ошибка при отмене напоминаний.")


__all__ = ["router", "set_bot_instance", "load_pending_reminders"]