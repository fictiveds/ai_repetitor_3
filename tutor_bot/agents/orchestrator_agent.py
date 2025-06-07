from typing import List, Dict, Any, Optional
from tutor_bot.agents.base_agent import BaseAgent, AgentContext, AgentResponse
from tutor_bot.integrations.llm_service import LLMMessage, LLMService
from tutor_bot.database.repositories.prompt_repository import PromptRepository
import json

class OrchestratorAgent(BaseAgent):
    AGENT_NAME = "OrchestratorAgent"
    # Определения намерений (можно вынести в конфиг или базу данных)
    INTENT_BOOK_LESSON = "book_lesson"
    INTENT_CANCEL_LESSON = "cancel_lesson"
    INTENT_GET_INFO = "get_info" # О репетиторе, ценах, формате
    INTENT_CHECK_AVAILABLE_SLOTS = "check_available_slots"
    INTENT_GENERAL_QUERY = "general_query" # Общий вопрос, неясное намерение
    INTENT_NON_TARGET_REQUEST = "non_target_request" # Нецелевой запрос (решить задачу, предложения и т.д.)

    # Соответствие намерений и агентов, которые их обрабатывают
    INTENT_TO_AGENT_MAP = {
        INTENT_BOOK_LESSON: "CalendarAgent", # CalendarAgent будет заниматься и созданием, и проверкой слотов для записи
        INTENT_CANCEL_LESSON: "CalendarAgent",
        INTENT_GET_INFO: "ConsultationAgent",
        INTENT_CHECK_AVAILABLE_SLOTS: "CalendarAgent",
        INTENT_GENERAL_QUERY: "CommunicationAgent", # CommunicationAgent может попробовать уточнить или ответить на общие вопросы
        INTENT_NON_TARGET_REQUEST: "CommunicationAgent" # CommunicationAgent даст стандартный ответ на нецелевые запросы
    }

    def __init__(self, llm_service: LLMService, prompt_repository: PromptRepository):
        super().__init__(agent_name=self.AGENT_NAME, llm_service=llm_service, prompt_repository=prompt_repository)
        # Системный промпт для оркестратора будет специфичным
        # Он должен содержать описание всех намерений и как их определять

    async def initialize(self):
        # Промпт для определения намерения
        # В реальном проекте этот промпт лучше хранить в базе данных (PromptRepository)
        # и загружать через self.initialize_prompt(prompt_name="orchestrator_intent_detection_prompt")
        default_orchestrator_prompt = f"""
Ты - AI-диспетчер для помощника репетитора. Твоя задача - проанализировать запрос пользователя и определить его основное намерение.
Доступные намерения:
1. {self.INTENT_BOOK_LESSON}: Пользователь хочет записаться на урок, выбрать время, или спрашивает о пробном уроке.
   Ключевые слова: записаться, пробный урок, выбрать время, есть ли место, хочу урок.
2. {self.INTENT_CANCEL_LESSON}: Пользователь хочет отменить существующую запись на урок.
   Ключевые слова: отменить занятие, не смогу прийти, перенести (если нет нового времени - это отмена).
3. {self.INTENT_GET_INFO}: Пользователь запрашивает информацию о репетиторе, стоимости занятий, формате (онлайн/оффлайн), предметах, к чему готовит (ЕГЭ, ОГЭ, ВПР, школьная программа).
   Ключевые слова: сколько стоит, цена, как проходят занятия, о репетиторе, подготовка к, физика.
4. {self.INTENT_CHECK_AVAILABLE_SLOTS}: Пользователь спрашивает о доступном времени, свободных слотах, расписании.
   Ключевые слова: свободное время, когда можно, расписание, есть ли окна.
5. {self.INTENT_NON_TARGET_REQUEST}: Пользователь просит решить задачу, помочь на экзамене, предлагает работу, рекламу или задает вопрос не по теме записи на уроки.
   Ключевые слова: решите задачу, помогите с контрольной, вакансия, сотрудничество.
6. {self.INTENT_GENERAL_QUERY}: Общий вопрос, приветствие, или если намерение неясно из вышеперечисленных.
   Ключевые слова: привет, как дела, не знаю что хочу, а вы кто.

Проанализируй последний запрос пользователя и историю диалога (если есть).
В ответе ОБЯЗАТЕЛЬНО используй JSON формат с ключом 'intent' и одним из перечисленных выше значений намерения.
Пример ответа: {{"intent": "{self.INTENT_BOOK_LESSON}"}}
Если пользователь просто поздоровался или задал общий вопрос, используй {self.INTENT_GENERAL_QUERY}.
Если пользователь просит что-то не по теме (решить задачу, предлагает работу) - используй {self.INTENT_NON_TARGET_REQUEST}.
Учитывай контекст предыдущих сообщений, если они есть.
Текущая дата для информации: {{ $now }}.
Не добавляй никаких других слов или объяснений в свой ответ, только JSON.
        """
        # Попытка загрузить из БД, если не получится - используем default
        await self.initialize_prompt(prompt_name="orchestrator_intent_prompt_v2", default_prompt_text=default_orchestrator_prompt)

    async def process(self, context: AgentContext) -> AgentResponse:
        if not self.system_prompt or not self.system_prompt.content:
            # Инициализация промпта, если он еще не был загружен
            await self.initialize()
            if not self.system_prompt: # Если и после этого нет, то проблема
                 return AgentResponse(error_message="Orchestrator agent system prompt not initialized.", is_final=True)

        # Формируем историю для LLM: системный промпт + история диалога + последний запрос пользователя
        llm_messages: List[LLMMessage] = []
        # Динамически подставляем текущую дату в системный промпт
        # В реальном LLM сервисе это может делаться через параметры шаблонизатора
        from datetime import datetime
        # Заменяем {{ $now }} на текущую дату. Убедимся, что self.system_prompt.content не None
        current_system_prompt_text = self.system_prompt.content if self.system_prompt else ""
        current_system_prompt_text = current_system_prompt_text.replace("{{ $now }}", datetime.now().strftime("%Y-%m-%d %H:%M:%S MSK"))

        llm_messages.append(LLMMessage(role="system", content=current_system_prompt_text))

        # Добавляем историю диалога, если она есть в контексте
        if context.dialog_history:
            # Ограничим историю, чтобы не превышать лимиты токенов LLM
            # Берем последние N сообщений (например, 10)
            for msg in context.dialog_history[-10:]:
                llm_messages.append(LLMMessage(role=msg.role, content=msg.content)) # Убедимся, что msg соответствует LLMMessage

        # Добавляем текущий запрос пользователя
        llm_messages.append(LLMMessage(role="user", content=context.user_input))

        # Вызов LLM для определения намерения
        # Оркестратор не использует инструменты, он только классифицирует
        llm_response = await self.llm_service.generate_response(messages=llm_messages, temperature=0.1, max_tokens=100, tool_choice="none")

        if llm_response.error or not llm_response.message or not llm_response.message.content:
            error_msg = llm_response.error or "LLM did not return content for intent detection."
            print(f"{self.agent_name} error: {error_msg}")
            # По умолчанию перенаправляем на CommunicationAgent для обработки ошибки или неясного запроса
            return AgentResponse(next_agent="CommunicationAgent", error_message=error_msg, is_final=False)

        try:
            # LLM должна вернуть JSON строку
            response_json = json.loads(llm_response.message.content.strip())
            intent = response_json.get("intent")
            print(f"{self.agent_name} detected intent: {intent}")

            if not intent or intent not in self.INTENT_TO_AGENT_MAP:
                print(f"Warning: Unknown or unhandled intent '{intent}'. Defaulting to CommunicationAgent.")
                # Если намерение не распознано или нет для него агента, передаем CommunicationAgent
                return AgentResponse(next_agent="CommunicationAgent", action_details={'original_intent': intent})

            # Определяем следующего агента на основе намерения
            next_agent_name = self.INTENT_TO_AGENT_MAP[intent]
            return AgentResponse(next_agent=next_agent_name, action_details={'detected_intent': intent})
        except json.JSONDecodeError as e:
            print(f"{self.agent_name} JSONDecodeError: {e}. LLM response: {llm_response.message.content}")
            # Если LLM вернула не JSON, это ошибка - передаем CommunicationAgent
            return AgentResponse(next_agent="CommunicationAgent", error_message=f"Invalid format from intent LLM: {e}", is_final=False)
        except Exception as e:
            print(f"{self.agent_name} unexpected error: {e}")
            return AgentResponse(next_agent="CommunicationAgent", error_message=f"Unexpected error in Orchestrator: {e}", is_final=False)
