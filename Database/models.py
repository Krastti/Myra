# Библиотеки
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class Reminder(BaseModel):
    id: str = str(uuid.uuid4()) # UUID
    user_id: int # ID пользователя в Telegram
    chat_id: int # ID чата Telegram
    reminder_text: str # Текст для напоминания
    target_datetime: datetime # Время, когда нужно напомнить
    created_at: datetime = datetime.now() # Время создания
    is_sent: bool = False # Отправлено ли напоминание
    sent_at: Optional[datetime] = None # Время отправки

    class Collection:
        name = 'reminders'

__all__ = ['Reminder']