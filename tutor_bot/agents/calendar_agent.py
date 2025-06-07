from typing import List, Dict, Any, Optional
from tutor_bot.agents.base_agent import BaseAgent, AgentContext, AgentResponse
from tutor_bot.integrations.llm_service import LLMMessage, LLMService
from tutor_bot.integrations.calendar_service import GoogleCalendarService, CalendarEventInput
from tutor_bot.database.repositories.prompt_repository import PromptRepository
from datetime import datetime, timedelta
import json
try:
    from dateutil import parser as date_parser
except ImportError:
    date_parser = None

class CalendarAgent(BaseAgent):
    AGENT_NAME = "CalendarAgent"

    # Определяем структуру инструментов (функций), которые этот агент предоставляет LLM
    TOOLS_DEFINITION = [
        {
            "type": "function",
            "function": {
                "name": "create_lesson_booking",
                "description": "Создает запись на урок в календаре. Обязательно уточни имя и телефон клиента, если они не предоставлены.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string", "description": "Имя клиента и, возможно, цель урока. Например, 'Иван - Подготовка к ЕГЭ'"},
                        "phone": {"type": "string", "description": "Номер телефона клиента для связи"},
                        "start_datetime": {"type": "string", "description": "Дата и время начала урока в формате ISO YYYY-MM-DDTHH:MM:SS, например, 2024-03-28T10:00:00"},
                        "duration_minutes": {"type": "integer", "description": "Длительность урока в минутах (по умолчанию 60)", "default": 60},
                        "description": {"type": "string", "description": "Дополнительное описание или детали урока, включая телефон. Например, 'Клиент: Иван, Телефон: +79991234567. Цель: ЕГЭ.'"}"
                    },
                    "required": ["summary", "phone", "start_datetime", "description"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_available_slots",
                "description": "Получает список свободных временных слотов для записи на урок.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_date_iso": {"type": "string", "description": "Начальная дата для поиска слотов в формате ISO YYYY-MM-DD, например, 2024-03-28. По умолчанию - сегодня." },
                        "days_to_search": {"type": "integer", "description": "Количество дней для поиска, начиная со start_date_iso. По умолчанию 7 дней.", "default": 7},
                        "duration_minutes": {"type": "integer", "description": "Желаемая длительность урока в минутах. По умолчанию 60.", "default": 60}
                    },
                    "required": [] # Все параметры опциональны, будут значения по умолчанию
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "cancel_lesson_booking",
                "description": "Отменяет существующую запись на урок. Требуется точная дата и время начала урока, а также имя или телефон для подтверждения.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_datetime": {"type": "string", "description": "Точная дата и время начала урока для отмены в формате ISO YYYY-MM-DDTHH:MM:SS"},
                        "summary_contains": {"type": "string", "description": "Часть имени или телефона из описания урока для подтверждения отмены (например, имя клиента)"}
                    },
                    "required": ["start_datetime", "summary_contains"]
                }
            }
        }
    ]

    def __init__(self, llm_service: LLMService, prompt_repository: PromptRepository, calendar_service: GoogleCalendarService):
        super().__init__(agent_name=self.AGENT_NAME, llm_service=llm_service, prompt_repository=prompt_repository)
        self.calendar_service = calendar_service

    async def initialize(self):
        default_calendar_prompt = """
Ты — AI-ассистент Александр, отвечающий за управление расписанием репетитора Юрия Фёдоровича.
Твоя основная задача — записывать учеников на уроки, показывать свободные слоты и отменять записи, используя предоставленные инструменты.
Взаимодействуй с пользователем вежливо и четко.
Сегодняшняя дата: {{ $now }} (MSK).

Правила работы с инструментами:
1. create_lesson_booking: Используй для создания новой записи. Всегда запрашивай имя и телефон клиента, если они не предоставлены явно. Убедись, что время начала урока указано точно. Длительность урока по умолчанию 60 минут. В summary указывай имя клиента и цель (если известна), в description - полное имя, телефон и цель.
2. get_available_slots: Используй, когда пользователь спрашивает о свободном времени или хочет посмотреть расписание. По умолчанию ищи на 7 дней вперед от указанной даты (или от сегодня). Длительность урока по умолчанию 60 минут.
3. cancel_lesson_booking: Используй для отмены урока. Убедись, что пользователь предоставил точное время начала урока и какую-то идентифицирующую информацию (имя/телефон), чтобы отменить правильный урок.

Общие правила:
- Перед вызовом create_lesson_booking или cancel_lesson_booking, если не хватает данных (например, имя/телефон для новой записи, или точное время/имя для отмены), СНАЧАЛА ЗАПРОСИ эти данные у пользователя. Не вызывай инструмент без всех обязательных параметров.
- После успешного выполнения действия (запись, отмена, показ слотов), сообщи результат пользователю.
- Если пользователь просит отменить урок, но не указывает детали, уточни их.
- Не показывай клиенту список ВСЕХ занятых слотов или детали чужих уроков.
- Если выбранное время для записи занято (после проверки через get_available_slots или если create_lesson_booking вернул ошибку конфликта), предложи альтернативные варианты из доступных.
- Всегда подтверждай детали записи (имя, телефон, дата, время, стоимость - если известна) перед финальным JSON для создания урока (это будет делать ValidationAgent, но ты должен собрать эти данные).
- Для новой записи, после согласования времени, вежливо попроси имя и номер телефона, если они еще не известны.
- Не отправляй JSON в чат напрямую. Твоя задача - вызвать правильный инструмент с правильными аргументами или запросить доп. информацию.
Рабочее время репетитора: обычно будни с 17:00 до 22:00 МСК. Учитывай это при предложении слотов.
Стоимость занятий: Школьная программа/ВПР: 1000-1200₽/час, ЕГЭ/ОГЭ: 1200-1500₽/час. Пробный урок по той же цене.
Если пользователь спрашивает о стоимости или формате, а ты должен работать с календарем, вежливо сообщи, что эту информацию лучше уточнить у консультационного агента, или кратко ответь, если уверен, и вернись к задаче календаря.
Если пользователь пишет «в следующий вторник» и т.п., используй инструмент check_days (если бы он был) или попробуй вычислить дату относительно {{ $now }} для передачи в инструменты.
        """
        await self.initialize_prompt(prompt_name="calendar_agent_main_prompt_v2", default_prompt_text=default_calendar_prompt)

    async def process(self, context: AgentContext) -> AgentResponse:
        if not self.system_prompt or not self.system_prompt.content:
            await self.initialize()
            if not self.system_prompt: return AgentResponse(error_message=f"{self.agent_name} system prompt not initialized.", is_final=True)

        llm_messages: List[LLMMessage] = []
        current_system_prompt_text = self.system_prompt.content.replace("{{ $now }}", datetime.now().strftime("%Y-%m-%d %H:%M:%S MSK"))
        llm_messages.append(LLMMessage(role="system", content=current_system_prompt_text))

        if context.dialog_history:
            for msg in context.dialog_history[-5:]:
                if isinstance(msg, LLMMessage): llm_messages.append(msg)
                elif isinstance(msg, dict): llm_messages.append(LLMMessage(role=msg.get('role','user'), content=msg.get('content','')))
        llm_messages.append(LLMMessage(role="user", content=context.user_input))

        # Вызов LLM с инструментами
        llm_response_outer = await self._get_llm_response(messages=llm_messages, tools=self.TOOLS_DEFINITION, tool_choice="auto")
        llm_response_message = llm_response_outer.message

        if llm_response_outer.error or not llm_response_message:
            return AgentResponse(text_response="Извините, произошла ошибка при обработке вашего запроса с календарем.", is_final=True)

        # Проверяем, есть ли вызовы инструментов
        if llm_response_message.tool_calls:
            tool_call = llm_response_message.tool_calls[0] # Предполагаем один вызов за раз для простоты
            function_name = tool_call.get("function", {}).get("name")
            try:
                arguments = json.loads(tool_call.get("function", {}).get("arguments", "{}"))
                print(f"{self.agent_name} attempting to call tool: {function_name} with args: {arguments}")

                # Вызов соответствующего метода календаря
                if function_name == "create_lesson_booking":
                    return await self._handle_create_lesson_booking(arguments, context)
                elif function_name == "get_available_slots":
                    return await self._handle_get_available_slots(arguments, context)
                elif function_name == "cancel_lesson_booking":
                    return await self._handle_cancel_lesson_booking(arguments, context)
                else:
                    return AgentResponse(text_response=f"Неизвестный инструмент {function_name} запрошен.", is_final=True)
            except json.JSONDecodeError:
                return AgentResponse(text_response="Ошибка в формате аргументов для инструмента.", is_final=True)
            except Exception as e:
                print(f"Error executing tool {function_name}: {e}")
                return AgentResponse(text_response=f"Произошла ошибка при выполнении операции с календарем: {e}", is_final=True)
        else:
            # Если LLM не вызвала инструмент, а просто ответила текстом (например, запросила доп. информацию)
            response_text = llm_response_message.content if llm_response_message.content else "Пожалуйста, уточните ваш запрос."
            return AgentResponse(text_response=response_text, is_final=False) # is_final=False чтобы оркестратор мог переоценить

    async def _handle_create_lesson_booking(self, args: Dict, context: AgentContext) -> AgentResponse:
        summary = args.get("summary")
        phone = args.get("phone")
        start_datetime_str = args.get("start_datetime")
        duration_minutes = args.get("duration_minutes", 60)
        description = args.get("description") # Должен содержать имя и телефон

        if not all([summary, phone, start_datetime_str, description]):
            missing_fields = [f for f, v in [('summary', summary), ('phone', phone), ('start_datetime', start_datetime_str), ('description', description)] if not v]
            return AgentResponse(text_response=f"Для записи на урок не хватает данных: {', '.join(missing_fields)}. Пожалуйста, уточните.", is_final=False)

        try:
            if not date_parser:
                raise RuntimeError("dateutil.parser is not available. Cannot parse start_datetime.")
            start_dt = date_parser.isoparse(start_datetime_str)
            end_dt = start_dt + timedelta(minutes=duration_minutes)
        except ValueError:
            return AgentResponse(text_response=f"Неверный формат даты или времени: {start_datetime_str}. Используйте YYYY-MM-DDTHH:MM:SS.", is_final=False)

        event_input = CalendarEventInput(
            summary=summary,
            start_datetime=start_dt.isoformat(),
            end_datetime=end_dt.isoformat(),
            description=description,
            # location, attendees, timezone можно добавить при необходимости
        )
        try:
            # Проверка на существующие события (опционально, но хорошо бы)
            # existing_events = await self.calendar_service.list_events(time_min=start_dt, time_max=end_dt)
            # if existing_events: return AgentResponse(text_response=f"Выбранное время {start_datetime_str} уже занято. Пожалуйста, выберите другое.", is_final=False)

            created_event = await self.calendar_service.create_event(event_input)
            if created_event:
                # Важный момент: здесь мы формируем JSON для финального вывода, как указано в задаче
                # Этот JSON должен быть передан ValidationAgent или напрямую в финальный ответ, если валидация не нужна
                final_json_output = {
                    "action": "create",
                    "lesson": {
                        "name": summary, # Предполагаем, что summary содержит имя
                        "phone": phone,
                        "start_datetime": created_event.start.get('dateTime'),
                        "end_datetime": created_event.end.get('dateTime')
                    }
                }
                # Сообщение пользователю и JSON для системы
                user_message = f"Отлично! Вы записаны на урок {created_event.start.get('dateTime')}. Детали: {summary}. Я передал данные для подтверждения."
                # Вместо is_final=True, передаем на ValidationAgent
                return AgentResponse(text_response=user_message, action_details=final_json_output, next_agent="ValidationAgent", is_final=False)
            else:
                return AgentResponse(text_response="Не удалось создать запись на урок. Попробуйте позже.", is_final=True)
        except RuntimeError as e: # Ловим ошибки от calendar_service
             # Проверяем на конфликт (хотя Google API обычно не возвращает специфичный код для этого при insert)
            if "conflict" in str(e).lower() or "busy" in str(e).lower():
                 return AgentResponse(text_response=f"Выбранное время {start_datetime_str} уже занято. Пожалуйста, выберите другое или попросите показать свободные слоты.", is_final=False)
            return AgentResponse(text_response=f"Ошибка при создании записи: {e}", is_final=True)

    async def _handle_get_available_slots(self, args: Dict, context: AgentContext) -> AgentResponse:
        start_date_str = args.get("start_date_iso", datetime.now().strftime("%Y-%m-%d"))
        days_to_search = args.get("days_to_search", 7)
        duration_minutes = args.get("duration_minutes", 60)

        try:
            if not date_parser:
                raise RuntimeError("dateutil.parser is not available. Cannot parse start_date.")
            start_date = date_parser.isoparse(start_date_str)
            # Устанавливаем начало дня для корректного поиска
            start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = start_date + timedelta(days=days_to_search)
        except ValueError:
            return AgentResponse(text_response=f"Неверный формат даты: {start_date_str}. Используйте YYYY-MM-DD.", is_final=False)

        # Определение рабочих часов репетитора (из вашего промпта)
        # Это должно быть более гибко настраиваемым в будущем
        tutor_working_hours = { # 0=пн, 6=вс
            "weekdays": [(17, 22)], # с 17:00 до 22:00
            "weekends": [] # Предположим, по выходным не работает, или можно добавить
            # 0: [(17,22)], 1: [(17,22)], 2: [(17,22)], 3: [(17,22)], 4: [(17,22)] # Альтернативный формат
        }

        try:
            free_slots = await self.calendar_service.find_free_slots(start_dt=start_date, end_dt=end_date, duration_minutes=duration_minutes, tutor_working_hours=tutor_working_hours)
            if not free_slots:
                return AgentResponse(text_response=f"Свободных слотов на ближайшие {days_to_search} дней не найдено. Попробуйте другие даты.", is_final=False)

            response_lines = ["Доступные слоты для записи:"]
            for slot in free_slots[:10]: # Ограничим вывод, чтобы не был слишком длинным
                slot_start_dt = date_parser.isoparse(slot['start'])
                # Форматируем для пользователя
                response_lines.append(f"- {slot_start_dt.strftime('%Y-%m-%d %H:%M')} (МСК)")
            if len(free_slots) > 10: response_lines.append("...и другие.")
            response_lines.append("Пожалуйста, выберите удобное время или уточните дату для поиска.")
            return AgentResponse(text_response="\n".join(response_lines), is_final=False)
        except RuntimeError as e:
            return AgentResponse(text_response=f"Ошибка при поиске свободных слотов: {e}", is_final=True)

    async def _handle_cancel_lesson_booking(self, args: Dict, context: AgentContext) -> AgentResponse:
        start_datetime_str = args.get("start_datetime")
        summary_contains = args.get("summary_contains") # Имя или телефон для идентификации

        if not start_datetime_str or not summary_contains:
            return AgentResponse(text_response="Для отмены урока укажите точное время начала и ваше имя/телефон, указанные при записи.", is_final=False)

        try:
            if not date_parser: raise RuntimeError("dateutil.parser is not available.")
            start_dt = date_parser.isoparse(start_datetime_str)
        except ValueError:
            return AgentResponse(text_response=f"Неверный формат даты/времени для отмены: {start_datetime_str}.", is_final=False)

        # Ищем событие для отмены
        # Google Calendar API не позволяет искать по summary напрямую при удалении.
        # Нужно сначала найти ID события.
        # Ищем события точно в это время начала.
        # Добавляем небольшой интервал (например, +/- 1 минута) на случай неточного совпадения или если LLM округлила время
        time_buffer = timedelta(minutes=1)
        events_to_check = await self.calendar_service.list_events(time_min=start_dt - time_buffer, time_max=start_dt + time_buffer, max_results=5)

        event_to_cancel_id = None
        event_details_for_user = None
        original_summary = None
        original_phone = None # Попытаемся извлечь из description

        for event in events_to_check:
            event_start_dt_obj = date_parser.isoparse(event.start.get('dateTime'))
            # Сверяем время с учетом возможной разницы в таймзонах (isoparse делает aware)
            if event_start_dt_obj == start_dt:
                # Проверяем, содержит ли summary или description нужные данные
                # summary_contains может быть частью имени или телефона
                full_description = event.description or ""
                if summary_contains.lower() in (event.summary or "").lower() or \
                   summary_contains.lower() in full_description.lower():
                    event_to_cancel_id = event.id
                    event_details_for_user = f"Урок: {event.summary} на {event.start.get('dateTime')}"
                    original_summary = event.summary
                    # Пытаемся извлечь телефон из description для JSON
                    import re
                    phone_match = re.search(r'Телефон:?\s*([+\d\s()-]+)', full_description, re.IGNORECASE)
                    if phone_match: original_phone = phone_match.group(1).strip()
                    break

        if not event_to_cancel_id:
            return AgentResponse(text_response=f"Урок на {start_datetime_str} с указанными данными ({summary_contains}) не найден. Пожалуйста, проверьте детали.", is_final=False)

        # Здесь в реальном боте нужно подтверждение от пользователя перед отмной
        # Например, "Найден урок: {event_details_for_user}. Вы уверены, что хотите его отменить?"
        # Для простоты, пока отменяем сразу, но передаем на ValidationAgent для подтверждения

        try:
            deleted = await self.calendar_service.delete_event(event_to_cancel_id)
            if deleted:
                final_json_output = {
                    "action": "delete",
                    "lesson": {
                        "name": original_summary or summary_contains, # Имя из урока или то, что ввел пользователь
                        "phone": original_phone or "не указан при отмене", # Телефон
                        "start_datetime": start_datetime_str,
                        "end_datetime": (start_dt + timedelta(minutes=60)).isoformat() # Предполагаем длительность 60 мин
                    }
                }
                user_message = f"Урок {event_details_for_user} успешно отменен. Данные переданы для подтверждения."
                return AgentResponse(text_response=user_message, action_details=final_json_output, next_agent="ValidationAgent", is_final=False)
            else:
                return AgentResponse(text_response=f"Не удалось отменить урок {event_details_for_user}. Возможно, он уже был отменен.", is_final=True)
        except RuntimeError as e:
            return AgentResponse(text_response=f"Ошибка при отмене урока: {e}", is_final=True)
