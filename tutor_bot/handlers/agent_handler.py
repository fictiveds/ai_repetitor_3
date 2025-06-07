from fastapi import APIRouter, Depends, HTTPException, Body, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import json

from tutor_bot.agents.agent_dispatcher import AgentDispatcher
from tutor_bot.integrations.llm_service import LLMService
from tutor_bot.integrations.calendar_service import GoogleCalendarService
from tutor_bot.database.mongodb_client import MongoDBClient, get_db_client
from tutor_bot.database.repositories.prompt_repository import PromptRepository
from tutor_bot.config import SERVICE_ACCOUNT_FILE, GOOGLE_CALENDAR_ID, LLM_API_KEY, LLM_MODEL_NAME # Для инициализации сервисов

router = APIRouter(
    prefix="/agent",
    tags=["Agent Interaction"]
)

# --- Модель для входящего запроса ---
class AgentQueryInput(BaseModel):
    user_id: str = Field(..., description="Уникальный идентификатор пользователя (например, telegram_id или внутренний ID)")
    text: str = Field(..., description="Текст запроса от пользователя")
    dialog_id: Optional[str] = Field(None, description="ID текущего диалога для продолжения (если есть)")
    # Можно добавить другие поля, например, user_timezone, client_type и т.д.

# --- Модель для ответа ---
class AgentQueryResponse(BaseModel):
    text_response: Optional[str] = Field(None, description="Текстовый ответ ассистента")
    dialog_id: str = Field(..., description="ID диалога (может быть новым или существующим)")
    is_final: bool = Field(default=False, description="Является ли этот ответ окончательным в текущей ветке диалога")
    action_details: Optional[Dict[str, Any]] = Field(None, description="Детали выполненного действия, например, JSON для календаря, если это финальный шаг")
    error_message: Optional[str] = Field(None, description="Сообщение об ошибке, если что-то пошло не так")

# --- Глобальный экземпляр AgentDispatcher (ленивая инициализация) ---
agent_dispatcher_instance: Optional[AgentDispatcher] = None
is_dispatcher_initializing = False # Флаг для предотвращения многократной инициализации

async def get_agent_dispatcher(db_client: MongoDBClient = Depends(get_db_client), background_tasks: Optional[BackgroundTasks] = None) -> AgentDispatcher:
    global agent_dispatcher_instance, is_dispatcher_initializing

    if agent_dispatcher_instance is None and not is_dispatcher_initializing:
        is_dispatcher_initializing = True
        print("Initializing AgentDispatcher for the first time...")
        try:
            if not db_client._client or not db_client._db:
                print("Connecting to DB for dispatcher initialization...")
                await db_client.connect()

            prompt_repo = PromptRepository() # Использует тот же db_client
            llm_service = LLMService(api_key=LLM_API_KEY, model_name=LLM_MODEL_NAME)
            calendar_service = GoogleCalendarService(service_account_file=SERVICE_ACCOUNT_FILE, calendar_id=GOOGLE_CALENDAR_ID)

            # Проверка наличия файла сервисного аккаунта для календаря
            import os
            if not os.path.exists(SERVICE_ACCOUNT_FILE):
                print(f"CRITICAL WARNING: Google Calendar service account file NOT FOUND at {SERVICE_ACCOUNT_FILE}. Calendar functionality will be impaired.")
                # Можно либо выбросить ошибку и не стартовать, либо продолжить с неработающим календарем.
                # Для примера, продолжим, но календарь не будет работать.
                # calendar_service = None # Раскомментировать, если хотим полностью отключить календарь при отсутствии файла

            dispatcher = AgentDispatcher(llm_service, calendar_service, db_client, prompt_repo)
            # Запуск инициализации агентов в фоне, если это долгий процесс
            # Или дождаться здесь, если это быстро
            if background_tasks: # Если background_tasks доступен (из FastAPI)
                 background_tasks.add_task(dispatcher.initialize_agents)
                 print("Agent initialization scheduled in background.")
            else: # Если вызывается не из FastAPI запроса или для тестов
                 print("Initializing agents synchronously...")
                 await dispatcher.initialize_agents()
                 print("Agents initialized synchronously.")

            agent_dispatcher_instance = dispatcher
            print("AgentDispatcher initialized successfully.")
        except Exception as e:
            is_dispatcher_initializing = False # Сбрасываем флаг при ошибке
            print(f"Failed to initialize AgentDispatcher: {e}")
            # Выбросить ошибку или вернуть None/специальный объект, чтобы обработать выше
            raise HTTPException(status_code=503, detail=f"Agent system is not ready: {e}")
        finally:
            is_dispatcher_initializing = False # Сбрасываем флаг после завершения
    elif agent_dispatcher_instance is None and is_dispatcher_initializing:
        # Если другой запрос уже инициализирует, подождем немного
        import asyncio
        print("AgentDispatcher is initializing by another request, waiting...")
        for _ in range(10): # Ждем до 5 секунд (10 * 0.5с)
            if agent_dispatcher_instance is not None: break
            await asyncio.sleep(0.5)
        if agent_dispatcher_instance is None:
            raise HTTPException(status_code=503, detail="Agent system is still initializing, please try again shortly.")

    return agent_dispatcher_instance

@router.post("/query", response_model=AgentQueryResponse)
async def handle_agent_query(query: AgentQueryInput = Body(...), dispatcher: AgentDispatcher = Depends(get_agent_dispatcher)):
    """
    Принимает запрос пользователя и передает его системе агентов для обработки.
    """
    try:
        agent_system_response = await dispatcher.dispatch(user_id=query.user_id, user_input=query.text, dialog_id=query.dialog_id)

        # Проверяем, нужно ли вернуть чистый JSON
        # По условию, если action_details содержит 'action' и 'lesson', и is_final=True, то text_response должен быть этим JSON
        final_json_output = None
        if agent_system_response.is_final and isinstance(agent_system_response.action_details, dict):
            action = agent_system_response.action_details.get('action')
            lesson = agent_system_response.action_details.get('lesson')
            # Проверяем, что это именно тот JSON, который должен быть возвращен как основной ответ
            # (т.е. не просто dialog_id)
            if action in ['create', 'delete'] and isinstance(lesson, dict) and \
               all(k in lesson for k in ['name', 'phone', 'start_datetime', 'end_datetime']):
                final_json_output = f"json {json.dumps({'action': action, 'lesson': lesson})}"

        # Получаем dialog_id из action_details, если он там есть (Dispatcher должен его добавить)
        response_dialog_id = agent_system_response.action_details.get('dialog_id', query.dialog_id or 'unknown_dialog')
        if isinstance(response_dialog_id, list): response_dialog_id = response_dialog_id[0] # На случай если придет список

        return AgentQueryResponse(
            text_response=final_json_output if final_json_output else agent_system_response.text_response,
            dialog_id=str(response_dialog_id),
            is_final=agent_system_response.is_final,
            # Если final_json_output сформирован, action_details в ответе API можно очистить или оставить как есть
            action_details=None if final_json_output else agent_system_response.action_details,
            error_message=agent_system_response.error_message
        )
    except HTTPException as http_exc:
        # Перебрасываем HTTP исключения (например, от get_agent_dispatcher)
        raise http_exc
    except Exception as e:
        print(f"Error in /agent/query handler: {e}")
        import traceback
        traceback.print_exc() # Для детального лога ошибки в консоль сервера
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal server error: {str(e)}")
