import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from fastapi import HTTPException # Используется для выброса ошибок, если сервис вызывается из FastAPI контекста

# Импорт конфигурации
try:
    from tutor_bot.config import GOOGLE_SCOPES, SERVICE_ACCOUNT_FILE, GOOGLE_CALENDAR_ID, DEFAULT_TIMEZONE
except ModuleNotFoundError:
    # Это может произойти, если файл запускается отдельно, а не как часть пакета tutor_bot
    # Для локального тестирования или если структура проекта отличается:
    print("Warning: Could not import from tutor_bot.config. Attempting relative import for config values (may fail).")
    # Зададим значения по умолчанию, если импорт не удался, для возможности базовой работы модуля
    # Это не идеальное решение для продакшена.
    SERVICE_ACCOUNT_FILE = os.getenv('SERVICE_ACCOUNT_FILE', 'service_account.json')
    GOOGLE_CALENDAR_ID = os.getenv('GOOGLE_CALENDAR_ID', 'primary')
    GOOGLE_SCOPES = ['https://www.googleapis.com/auth/calendar']
    DEFAULT_TIMEZONE = "Europe/Moscow"

# Попытка импортировать dateutil.parser
try:
    from dateutil import parser as date_parser
except ImportError:
    print("WARNING: python-dateutil is not installed. Date parsing in find_free_slots might be less robust. Run: pip install python-dateutil")
    date_parser = None

# --- Pydantic модели для данных календаря ---
class CalendarEventInput(BaseModel):
    summary: str = Field(..., description="Название события")
    start_datetime: str = Field(..., description="Дата и время начала (ISO format, e.g., '2024-03-28T10:00:00')")
    end_datetime: str = Field(..., description="Дата и время окончания (ISO format, e.g., '2024-03-28T11:00:00')")
    description: Optional[str] = Field(None, description="Описание события")
    location: Optional[str] = Field(None, description="Место проведения")
    timezone: str = Field(default=DEFAULT_TIMEZONE, description="Часовой пояс")
    attendees: Optional[List[str]] = Field(None, description="Список email участников")

class CalendarEventResponse(BaseModel):
    id: str
    summary: str
    description: Optional[str] = None
    location: Optional[str] = None
    start: Dict[str, str]
    end: Dict[str, str]
    htmlLink: Optional[str] = None
    status: Optional[str] = None
    organizer: Optional[Dict[str, str]] = None
    attendees: Optional[List[Dict[str, Any]]] = None

# --- Сервис для работы с Google Calendar ---
class GoogleCalendarService:
    def __init__(self, service_account_file: str = SERVICE_ACCOUNT_FILE, scopes: List[str] = GOOGLE_SCOPES, calendar_id: str = GOOGLE_CALENDAR_ID):
        self.service_account_file = service_account_file
        self.scopes = scopes
        self.calendar_id = calendar_id
        self._service = None

        if not os.path.exists(self.service_account_file):
            # Это предупреждение будет полезно при инициализации
            print(f"WARNING: Service account file '{self.service_account_file}' not found at initialization time.")


    def _get_service(self):
        if self._service is None:
            try:
                if not os.path.exists(self.service_account_file):
                    # Эта ошибка критична для работы сервиса
                    raise FileNotFoundError(f"Service account file not found: {self.service_account_file}")

                credentials = service_account.Credentials.from_service_account_file(
                    self.service_account_file,
                    scopes=self.scopes
                )
                self._service = build('calendar', 'v3', credentials=credentials, cache_discovery=False) # cache_discovery=False для избежания проблем с кешем в некоторых окружениях
            except FileNotFoundError as fnf_error:
                print(f"Critical Error: Google Calendar API service account file missing: {str(fnf_error)}")
                # В FastAPI контексте это бы вызвало HTTPException. Вне его, это приведет к ошибке при вызове методов.
                # Можно установить self._service в специальное состояние или просто дать ошибке распространиться.
                raise # Перевыбрасываем ошибку, так как без сервисного файла работать нельзя
            except Exception as e:
                print(f"Critical Error: Could not initialize Google Calendar service: {str(e)}")
                raise # Перевыбрасываем
        return self._service

    async def list_events(self, max_results: int = 50, time_min: Optional[datetime] = None, time_max: Optional[datetime] = None) -> List[CalendarEventResponse]:
        service = self._get_service()

        time_min_iso = (time_min or datetime.utcnow()).isoformat() + 'Z'
        time_max_iso = (time_max or ((time_min or datetime.utcnow()) + timedelta(days=30))).isoformat() + 'Z'

        try:
            events_result = service.events().list(
                calendarId=self.calendar_id,
                timeMin=time_min_iso,
                timeMax=time_max_iso,
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])
            # Пропускаем поля, которых может не быть в ответе API, если они Optional в Pydantic модели
            return [CalendarEventResponse(**{k: v for k, v in event.items() if k in CalendarEventResponse.__fields__}) for event in events]
        except HttpError as error:
            print(f"Google API HttpError listing events: {error.resp.status} - {error.content.decode('utf-8', 'ignore')}")
            raise RuntimeError(f"Google API error listing events: {error.content.decode('utf-8', 'ignore')}")
        except Exception as e:
            print(f"Unexpected error listing events: {e}")
            raise RuntimeError(f"Unexpected error listing events: {e}")

    async def create_event(self, event_data: CalendarEventInput) -> Optional[CalendarEventResponse]:
        service = self._get_service()
        event_body = event_data.dict(exclude_none=True) # Pydantic model to dict

        # Google API ожидает start/end как словари
        event_body['start'] = {'dateTime': event_data.start_datetime, 'timeZone': event_data.timezone}
        event_body['end'] = {'dateTime': event_data.end_datetime, 'timeZone': event_data.timezone}
        if event_data.attendees:
            event_body['attendees'] = [{'email': email} for email in event_data.attendees]
        else:
            if 'attendees' in event_body: del event_body['attendees']


        try:
            created_event = service.events().insert(
                calendarId=self.calendar_id,
                body=event_body,
                sendNotifications=True
            ).execute()
            return CalendarEventResponse(**{k: v for k, v in created_event.items() if k in CalendarEventResponse.__fields__})
        except HttpError as error:
            print(f"Google API HttpError creating event: {error.resp.status} - {error.content.decode('utf-8', 'ignore')}")
            raise RuntimeError(f"Google API error creating event: {error.content.decode('utf-8', 'ignore')}")
        except Exception as e:
            print(f"Unexpected error creating event: {e}")
            raise RuntimeError(f"Unexpected error creating event: {e}")

    async def get_event(self, event_id: str) -> Optional[CalendarEventResponse]:
        service = self._get_service()
        try:
            event = service.events().get(calendarId=self.calendar_id, eventId=event_id).execute()
            return CalendarEventResponse(**{k: v for k, v in event.items() if k in CalendarEventResponse.__fields__})
        except HttpError as error:
            if error.resp.status == 404: return None
            print(f"Google API HttpError getting event: {error.resp.status} - {error.content.decode('utf-8', 'ignore')}")
            raise RuntimeError(f"Google API error getting event: {error.content.decode('utf-8', 'ignore')}")
        except Exception as e:
            print(f"Unexpected error getting event {event_id}: {e}")
            raise RuntimeError(f"Unexpected error getting event: {e}")

    async def delete_event(self, event_id: str) -> bool:
        service = self._get_service()
        try:
            service.events().delete(
                calendarId=self.calendar_id,
                eventId=event_id,
                sendNotifications=True
            ).execute()
            return True
        except HttpError as error:
            if error.resp.status == 404:
                print(f"Event {event_id} not found for deletion.")
                return False
            print(f"Google API HttpError deleting event: {error.resp.status} - {error.content.decode('utf-8', 'ignore')}")
            raise RuntimeError(f"Google API error deleting event: {error.content.decode('utf-8', 'ignore')}")
        except Exception as e:
            print(f"Unexpected error deleting event {event_id}: {e}")
            raise RuntimeError(f"Unexpected error deleting event: {e}")

    async def update_event(self, event_id: str, event_data: CalendarEventInput) -> Optional[CalendarEventResponse]:
        service = self._get_service()
        event_body = event_data.dict(exclude_none=True)
        event_body['start'] = {'dateTime': event_data.start_datetime, 'timeZone': event_data.timezone}
        event_body['end'] = {'dateTime': event_data.end_datetime, 'timeZone': event_data.timezone}
        if event_data.attendees:
            event_body['attendees'] = [{'email': email} for email in event_data.attendees]
        else:
            if 'attendees' in event_body: del event_body['attendees']

        try:
            updated_event = service.events().update(
                calendarId=self.calendar_id,
                eventId=event_id,
                body=event_body,
                sendNotifications=True
            ).execute()
            return CalendarEventResponse(**{k: v for k, v in updated_event.items() if k in CalendarEventResponse.__fields__})
        except HttpError as error:
            if error.resp.status == 404: return None
            print(f"Google API HttpError updating event: {error.resp.status} - {error.content.decode('utf-8', 'ignore')}")
            raise RuntimeError(f"Google API error updating event: {error.content.decode('utf-8', 'ignore')}")
        except Exception as e:
            print(f"Unexpected error updating event {event_id}: {e}")
            raise RuntimeError(f"Unexpected error updating event: {e}")

    async def find_free_slots(self, start_dt: datetime, end_dt: datetime, duration_minutes: int = 60,
                              tutor_working_hours: Optional[Dict[str, List[tuple[int, int]]]] = None) -> List[Dict[str, str]]:
        service = self._get_service()

        # Убедимся, что datetime aware, если они изначально naive, применим таймзону по умолчанию
        # Google API требует aware datetime objects.
        # Для простоты, здесь не обрабатываем конвертацию таймзон явно, полагаясь на корректные входные данные.

        try:
            events_result = service.events().list(
                calendarId=self.calendar_id,
                timeMin=start_dt.isoformat(), # Google API ожидает ISO формат с Z или смещением
                timeMax=end_dt.isoformat(),
                singleEvents=True,
                orderBy='startTime'
            ).execute()
        except HttpError as error:
            print(f"Google API HttpError in find_free_slots (list_events): {error.resp.status} - {error.content.decode('utf-8', 'ignore')}")
            raise RuntimeError(f"Google API error listing events for free slots: {error.content.decode('utf-8', 'ignore')}")

        busy_periods = []
        for event in events_result.get('items', []):
            if event.get('status') == 'cancelled': continue

            event_start_str = event['start'].get('dateTime')
            event_end_str = event['end'].get('dateTime')
            if not event_start_str or not event_end_str: continue

            try:
                if date_parser:
                    busy_start = date_parser.isoparse(event_start_str)
                    busy_end = date_parser.isoparse(event_end_str)
                else: # Fallback, если dateutil не установлен
                    busy_start = datetime.fromisoformat(event_start_str.replace('Z', '+00:00'))
                    busy_end = datetime.fromisoformat(event_end_str.replace('Z', '+00:00'))
                busy_periods.append((busy_start, busy_end))
            except Exception as e:
                print(f"Error parsing event time for free/busy: {e}. Event data: {event_start_str}, {event_end_str}")
                continue

        free_slots_list = []
        current_check_time = start_dt
        slot_delta = timedelta(minutes=duration_minutes)

        while current_check_time + slot_delta <= end_dt:
            slot_start = current_check_time
            slot_end = current_check_time + slot_delta

            # Проверка рабочих часов репетитора
            if tutor_working_hours:
                # Эта логика должна быть уточнена и протестирована.
                # Особенно важна корректная работа с таймзонами.
                # Здесь предполагается, что slot_start в той же таймзоне, что и tutor_working_hours.
                weekday = slot_start.weekday() # Пн=0, Вс=6
                slot_hour_start = slot_start.hour

                work_intervals = []
                if "weekdays" in tutor_working_hours and 0 <= weekday <= 4:
                    work_intervals = tutor_working_hours["weekdays"]
                elif "weekends" in tutor_working_hours and 5 <= weekday <= 6:
                    work_intervals = tutor_working_hours["weekends"]
                elif str(weekday) in tutor_working_hours: # Если ключи словаря - строки дней недели
                    work_intervals = tutor_working_hours[str(weekday)]
                elif weekday in tutor_working_hours: # Если ключи - int
                    work_intervals = tutor_working_hours[weekday]

                is_in_working_time = False
                for start_h, end_h in work_intervals:
                    # Убедимся, что слот полностью попадает в рабочий интервал
                    if start_h <= slot_hour_start and                        (slot_start + slot_delta).hour < end_h or                        ((slot_start + slot_delta).hour == end_h and (slot_start + slot_delta).minute == 0) :
                        is_in_working_time = True
                        break
                if not is_in_working_time:
                    current_check_time += timedelta(minutes=15) # Инкремент для поиска следующего слота
                    continue

            # Проверка на пересечение с занятыми периодами
            is_slot_free = True
            for busy_start, busy_end in busy_periods:
                if max(slot_start, busy_start) < min(slot_end, busy_end): # Пересечение
                    is_slot_free = False
                    break

            if is_slot_free:
                free_slots_list.append({"start": slot_start.isoformat(), "end": slot_end.isoformat()})

            current_check_time += timedelta(minutes=15) # Инкремент для поиска следующего слота (можно сделать =duration_minutes, если не нужны пересекающиеся варианты)

        return free_slots_list
