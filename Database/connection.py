# Библиотеки
import logging
import os

from dotenv import load_dotenv
from pymongo.errors import ServerSelectionTimeoutError
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()
logger = logging.getLogger(__name__)

# Подключение к БД
MONGO_HOST = os.getenv("MONGO_HOST")
MONGO_PORT = int(os.getenv("MONGO_PORT"))
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")

# Глобальные переменные
mongo_client: AsyncIOMotorClient = None
db = None

# Функция для подключения к MongoDB
async def connect_to_mongo():
    global mongo_client, db

    try:
        logger.info(f"Попытка подключения к базе данных.")

        connection_string = f'mongodb://{MONGO_HOST}:{MONGO_PORT}/{MONGO_DB_NAME}'
        mongo_client = AsyncIOMotorClient(connection_string)

        await mongo_client.server_info()

        db = mongo_client[MONGO_DB_NAME]

        logger.info(f'Подключение к базе данных успешно.')

    except ServerSelectionTimeoutError as e:
        logger.critical(f'Ошибка подключения к MongoDB: {e}')
        raise
    except Exception as e:
        logger.critical(f'Неожиданная ошибка при подключение к MongoDB: {e}')
        raise

async def close_mongo_connection():
    global mongo_client

    if mongo_client:
        mongo_client.close()
        logger.info("Соединение с MongoDB закрыто.")

__all__ = ['db', 'connect_to_mongo', 'close_mongo_connection']