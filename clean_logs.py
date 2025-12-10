import os
import re
import logging
import asyncio
from datetime import datetime, timedelta

LOG_FILE = 'bot.log'
DAYS_TO_KEEP = 7
DATE_PATTERN = re.compile(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d{3)?')
DATE_FORMAT = "%Y-%m-%d %H:%M:%S,%f"

logger = logging.getLogger('__name__')

def parse_log_date(date_str: str) -> datetime | None:
    try:
        if ',' in date_str:
            return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S,%f")
        else:
            return datetime.strptime(date_str, DATE_FORMAT)
    except ValueError:
        return None

def old_line(line: str, cutoff_date: datetime) -> bool:
    match = DATE_PATTERN.search(line)
    if match:
        date_str = match.group(1)
        log_date = parse_log_date(date_str)
        if log_date:
            return log_date < cutoff_date
    return False

async def clean_logs(file_path: str, days_to_keep: int):
    if not os.path.exists(file_path):
        logger.warning(f"Файл логов не найден для очистки: {file_path}")
        return
    cutoff_date = datetime.now() - timedelta(days=days_to_keep)
    logger.info(f'Удаление строк логов, дата которых раньше: {cutoff_date.strftime("%Y-%m-%d %H:%M:%S")}')

    try:
        async with asyncio.Lock():
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
    except Exception as e:
        logger.error(f'Ошибка при чтении файла {file_path}: {e}')
        return

    # Фильтруем строки
    lines_to_keep = [line for line in lines if not old_line(line, cutoff_date)]

    try:
        async with asyncio.Lock():
            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(lines_to_keep)
        logger.info(f"Очистка завершена. Удалено {len(lines) - len(lines_to_keep)} строк")
    except Exception as e:
        logger.error(f'Ошибка при записи в файл {file_path}: {e}')

async def run_daily_cleanup(log_file_path: str, days_to_keep: int):
    while True:
        now = datetime.now()
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        seconds_until_midnight = (next_midnight - now).total_seconds()

        logger.info(f"Следующая очистка логов запланирована на {next_midnight.strftime('%Y-%m-%d %H:%M:%S')}. Ждём {seconds_until_midnight:.2f} секунд...")

        await asyncio.sleep(seconds_until_midnight)

        await clean_logs(log_file_path, days_to_keep)

__all__ =['clean_logs', 'run_daily_cleanup']