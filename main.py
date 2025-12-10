# Библиотеки
import asyncio
import logging
import sys
import os
import dotenv

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
from aiohttp import ClientConnectorError

# Импорты
from Commands.start import router as start_router
from Commands.help import router as help_router
from Commands.tinvest import router as tinvest_router
from Commands.reminders import router as reminders_router, set_bot_instance, load_pending_reminders
from Database.connection import connect_to_mongo, close_mongo_connection
from clean_logs import run_daily_cleanup

# Создание логов
logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(name)s] - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)

# Получение токена Бота
dotenv.load_dotenv("config.env")
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    logger.error("Токен бота не обнаружен")
    sys.exit(1)

# Функция проверки стабильности подключения
async def check_internet_connection(bot: Bot) -> bool:
    try:
        await bot.get_me()
        logger.debug("Проверка подключения к Telegram API прошла успешно.")
        return True
    except (TelegramNetworkError, ClientConnectorError) as e:
        logger.warning(f"Проверка подключения к Telegram API не удалась: {e}")
        return False
    except Exception as e:
        logger.error(f'Произошла неожиданная ошибка при проверке подключения: {e}')
        return False

# Функция main для инициализации бота
async def main() -> None:
    bot: Bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    try:
        await connect_to_mongo()
    except Exception as e:
        logger.critical(f"Не удалось подключиться к MongoDB: {e}")
        sys.exit(1)

    set_bot_instance(bot)

    dp.include_router(start_router)
    dp.include_router(help_router)
    dp.include_router(tinvest_router)
    dp.include_router(reminders_router)

    # Загрузка напоминаний из БД
    await load_pending_reminders()

    # Фоновая задача по очистке логов
    log_cleanup_task = asyncio.create_task(run_daily_cleanup('bot.log', 7))

    max_retry = 5 # Максимальное количество попыток переподключения
    retry_delay = 3 # Задержка между попытками подключения в секундах
    attempt = 0

    while attempt < max_retry:
        try:
            logger.info("Попытка запустить бота...")

            # Проверяем подключение перед запуском бота
            if not await check_internet_connection(bot):
                attempt += 1
                if attempt == max_retry:
                    logger.critical(f'Не удалось подключиться после {max_retry} попыток.')
                    break
                logger.info(f'Повторная попытка через {retry_delay} секунд...')
                await asyncio.sleep(retry_delay)
                continue

            # Если подключение стабильно
            logger.info("Подключение стабильно. Запуск бота...")
            logger.info('Бот успешно запущен и работает.')
            await asyncio.gather(
                dp.start_polling(bot),
                log_cleanup_task,
            )
            break

        except (TelegramNetworkError, ClientConnectorError, asyncio.TimeoutError) as e:
            # Обрабатываем сетевые ошибки и таймауты
            logger.warning(f"Сетевая ошибка или таймаут при работе с Telegram API: {e}")
            attempt += 1
            if attempt >= max_retry:
                logger.critical(f"Сетевые ошибки повторяются. Достигнуто максимальное количество попыток ({max_retry}). Завершение.")
                break
            logger.info(f"Переподключение через {retry_delay} секунд...")
            await asyncio.sleep(retry_delay)

        except Exception as e:
            logger.critical(f"Случилась критическая ошибка при запуске бота: {e}")
            sys.exit(1)
        finally:
            # Завершаем задачу очистки логов
            log_cleanup_task.cancel()
            try:
                await log_cleanup_task
            except asyncio.CancelledError:
                logger.info('Фоновая задача очистки логов остановлена.')
            except Exception as e:
                logger.error(f'Ошибка при остановке задачи очистки логов: {e}')

            await close_mongo_connection()
            await bot.session.close()
            logger.info('Сессия бота закрыта.')

# Запуск бота
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info('Остановка бота...')