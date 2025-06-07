from typing import Dict, Type, Optional, List
from tutor_bot.agents.base_agent import BaseAgent, AgentContext, AgentResponse
from tutor_bot.agents.orchestrator_agent import OrchestratorAgent
from tutor_bot.agents.consultation_agent import ConsultationAgent
from tutor_bot.agents.calendar_agent import CalendarAgent
from tutor_bot.agents.validation_agent import ValidationAgent
from tutor_bot.agents.communication_agent import CommunicationAgent
from tutor_bot.integrations.llm_service import LLMService, LLMMessage
from tutor_bot.integrations.calendar_service import GoogleCalendarService
from tutor_bot.database.mongodb_client import MongoDBClient, get_db_client
from tutor_bot.database.repositories.prompt_repository import PromptRepository
from tutor_bot.database.repositories.dialog_repository import DialogRepository # Для сохранения истории
from tutor_bot.database.models import Dialog, Message as DialogMessageEntity # Модель для БД
import json

class AgentDispatcher:
    def __init__(self, llm_service: LLMService, calendar_service: GoogleCalendarService, db_client: MongoDBClient, prompt_repo: PromptRepository):
        self.llm_service = llm_service
        self.calendar_service = calendar_service
        self.db_client = db_client
        self.prompt_repository = prompt_repo
        self.dialog_repository = DialogRepository() # Инициализируем репозиторий диалогов

        self.agents: Dict[str, BaseAgent] = {
            OrchestratorAgent.AGENT_NAME: OrchestratorAgent(llm_service, prompt_repo),
            ConsultationAgent.AGENT_NAME: ConsultationAgent(llm_service, prompt_repo),
            CalendarAgent.AGENT_NAME: CalendarAgent(llm_service, prompt_repo, calendar_service),
            ValidationAgent.AGENT_NAME: ValidationAgent(llm_service, prompt_repo),
            CommunicationAgent.AGENT_NAME: CommunicationAgent(llm_service, prompt_repo)
        }
        self.orchestrator = self.agents[OrchestratorAgent.AGENT_NAME]

    async def initialize_agents(self):
        """Инициализирует все агенты (например, загружает их промпты)."""
        for agent_name, agent_instance in self.agents.items():
            if hasattr(agent_instance, 'initialize') and callable(agent_instance.initialize):
                print(f"Initializing agent: {agent_name}...")
                await agent_instance.initialize()
            else:
                print(f"Agent {agent_name} does not have an async initialize method.")

    async def dispatch(self, user_id: str, user_input: str, dialog_id: Optional[str] = None) -> AgentResponse:
        """
        Основной метод для обработки входящего запроса пользователя.
        Управляет диалогом, вызывает агентов и сохраняет историю.
        """
        if not self.db_client or not self.db_client._client: # Убедимся, что клиент БД подключен
             # Попытка подключиться, если еще не подключены (для случаев, когда диспатчер создается до полного старта FastAPI)
            if hasattr(self.db_client, 'connect') and not (self.db_client._client and self.db_client._db):
                 await self.db_client.connect()

        # 1. Загрузка или создание диалога
        current_dialog: Optional[Dialog] = None
        if dialog_id:
            current_dialog = await self.dialog_repository.get_by_id(dialog_id)

        if not current_dialog:
            # Пытаемся найти активный диалог для пользователя или создаем новый
            # Это упрощенная логика, user_id должен быть PyObjectId, если он так хранится
            # current_dialog = await self.dialog_repository.get_active_dialog_by_user_id(user_id) # user_id нужно преобразовать в PyObjectId
            # Пока будем создавать новый диалог для каждого нового dispatch без dialog_id для простоты
            from tutor_bot.database.models import PyObjectId # Импорт здесь, чтобы избежать циклов
            new_dialog_obj = Dialog(user_id=PyObjectId(user_id)) # Предполагаем, что user_id это строка UUID
            current_dialog = await self.dialog_repository.create(new_dialog_obj)
            dialog_id = str(current_dialog.id)

        dialog_history_llm: List[LLMMessage] = []
        if current_dialog and current_dialog.messages:
            for msg_entity in current_dialog.messages:
                dialog_history_llm.append(LLMMessage(role=msg_entity.role, content=msg_entity.content))

        # Сохраняем текущее сообщение пользователя в истории
        user_message_entity = DialogMessageEntity(role="user", content=user_input)
        if current_dialog: # current_dialog здесь не может быть None
             await self.dialog_repository.add_message_to_dialog(str(current_dialog.id), user_message_entity)

        # 2. Определение намерения через OrchestratorAgent
        orchestrator_context = AgentContext(
            user_input=user_input,
            user_id=user_id,
            dialog_history=dialog_history_llm,
            current_dialog_id=dialog_id,
            llm_service=self.llm_service,
            db_client=self.db_client,
            prompt_repo=self.prompt_repository
        )
        orchestrator_response = await self.orchestrator.process(orchestrator_context)

        next_agent_name = orchestrator_response.next_agent
        current_action_details = orchestrator_response.action_details or {}
        current_error_message = orchestrator_response.error_message

        # 3. Вызов целевого агента
        if not next_agent_name or next_agent_name not in self.agents:
            print(f"Warning: Orchestrator returned invalid agent name '{next_agent_name}'. Defaulting to CommunicationAgent.")
            next_agent_name = CommunicationAgent.AGENT_NAME
            current_error_message = current_error_message or "Не удалось определить подходящего обработчика для вашего запроса."

        target_agent = self.agents[next_agent_name]
        print(f"Dispatching to: {next_agent_name}")

        # Передаем историю и другие сервисы в контексте
        # Обновляем dialog_history_llm, чтобы включить последнее сообщение пользователя для контекста агента
        actual_dialog_history_for_agent = dialog_history_llm + [LLMMessage(role="user", content=user_input)]

        target_agent_context = AgentContext(
            user_input=user_input, # Некоторые агенты могут захотеть видеть оригинальный ввод, даже если есть история
            user_id=user_id,
            dialog_history=actual_dialog_history_for_agent, # Передаем полную историю с последним сообщением
            current_dialog_id=dialog_id,
            llm_service=self.llm_service,
            calendar_service=self.calendar_service, # CalendarAgent и другие могут его использовать
            db_client=self.db_client,
            prompt_repo=self.prompt_repository,
            additional_data={ # Передаем результаты от Оркестратора
                'detected_intent': current_action_details.get('detected_intent'),
                'original_intent': current_action_details.get('original_intent'),
                'action_details': current_action_details.get('action_details', current_action_details), # Для ValidationAgent
                'error_message': current_error_message
            }
        )

        agent_final_response = await target_agent.process(target_agent_context)

        # 4. Если целевой агент предлагает следующего агента (например, CalendarAgent -> ValidationAgent)
        #    Это цикл, который должен иметь ограничение по глубине или другую логику выхода.
        #    Пока сделаем один шаг перенаправления.
        if agent_final_response.next_agent and agent_final_response.next_agent in self.agents and agent_final_response.next_agent != next_agent_name:
            next_next_agent_name = agent_final_response.next_agent
            print(f"Redirecting from {next_agent_name} to: {next_next_agent_name}")
            next_target_agent = self.agents[next_next_agent_name]
            # Обновляем additional_data для следующего агента, если они были в ответе предыдущего
            target_agent_context.additional_data.update(agent_final_response.action_details or {})
            # Если ValidationAgent, он ожидает 'action_details' напрямую
            if next_next_agent_name == ValidationAgent.AGENT_NAME and 'action_details' not in target_agent_context.additional_data:
                 target_agent_context.additional_data['action_details'] = agent_final_response.action_details

            agent_final_response = await next_target_agent.process(target_agent_context)

        # 5. Сохранение ответа ассистента в истории
        if agent_final_response.text_response and current_dialog:
            assistant_message_entity = DialogMessageEntity(role="assistant", content=agent_final_response.text_response)
            await self.dialog_repository.add_message_to_dialog(str(current_dialog.id), assistant_message_entity)

        # Если есть финальный JSON для вывода (от ValidationAgent)
        if agent_final_response.is_final and agent_final_response.action_details and \
           ('action' in agent_final_response.action_details and 'lesson' in agent_final_response.action_details):
            # Это специальный случай для вывода JSON как указано в задаче
            # Мы должны вернуть этот JSON в чистом виде, без оборачивания в AgentResponse.text_response
            # Поэтому модифицируем agent_final_response или возвращаем специальный тип
            # Для простоты, пока просто поместим JSON в text_response, но с префиксом
            # В FastAPI хендлере это нужно будет обработать отдельно.
            final_json_str = json.dumps(agent_final_response.action_details)
            # Переопределяем text_response, чтобы он содержал ТОЛЬКО JSON, как в задаче
            # agent_final_response.text_response = f"json {final_json_str}" # Старый вариант
            # Новый вариант: action_details уже содержит JSON, is_final=True сигнализирует об этом.
            # Текстовый ответ может быть подтверждением типа "Ок, сделано!" а JSON в action_details.
            # Но по условию задачи, если JSON - то ТОЛЬКО JSON.
            # Поэтому, если is_final и action_details это наш JSON, то text_response должен быть им.
            agent_final_response.text_response = f"json {final_json_str}" # Убедимся, что это будет единственный вывод
            # agent_final_response.text_response = None # Чтобы не было лишнего текста от агента, если JSON выводится отдельно

        # Добавляем dialog_id в ответ, чтобы клиент мог его использовать для продолжения диалога
        if not agent_final_response.action_details: agent_final_response.action_details = {}
        agent_final_response.action_details['dialog_id'] = dialog_id

        return agent_final_response
