from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from tutor_bot.integrations.llm_service import LLMService, LLMMessage, LLMResponse
from tutor_bot.integrations.calendar_service import GoogleCalendarService
from tutor_bot.database.mongodb_client import MongoDBClient
from tutor_bot.database.repositories.prompt_repository import PromptRepository

class AgentContext:
    """Контекст, передаваемый агенту для обработки запроса."""
    def __init__(self,
                 user_input: str,
                 user_id: str, # Или другой идентификатор пользователя
                 dialog_history: List[LLMMessage] = [],
                 current_dialog_id: Optional[str] = None,
                 llm_service: Optional[LLMService] = None,
                 calendar_service: Optional[GoogleCalendarService] = None,
                 db_client: Optional[MongoDBClient] = None,
                 prompt_repo: Optional[PromptRepository] = None,
                 additional_data: Optional[Dict[str, Any]] = None):
        self.user_input = user_input
        self.user_id = user_id
        self.dialog_history = dialog_history
        self.current_dialog_id = current_dialog_id
        self.llm_service = llm_service
        self.calendar_service = calendar_service
        self.db_client = db_client
        self.prompt_repo = prompt_repo
        self.additional_data = additional_data if additional_data is not None else {}

class AgentResponse:
    """Ответ от агента."""
    def __init__(self,
                 text_response: Optional[str] = None,
                 tool_calls: Optional[List[Dict[str, Any]]] = None,
                 action_details: Optional[Dict[str, Any]] = None,
                 next_agent: Optional[str] = None, # Имя следующего агента, если требуется передача управления
                 is_final: bool = False, # Является ли этот ответ окончательным для пользователя
                 error_message: Optional[str] = None):
        self.text_response = text_response
        self.tool_calls = tool_calls
        self.action_details = action_details # Например, JSON для календаря
        self.next_agent = next_agent
        self.is_final = is_final
        self.error_message = error_message

class BaseAgent(ABC):
    """Абстрактный базовый класс для всех агентов."""

    def __init__(self, agent_name: str, llm_service: LLMService, prompt_repository: PromptRepository):
        self.agent_name = agent_name
        self.llm_service = llm_service
        self.prompt_repository = prompt_repository
        self.system_prompt: Optional[LLMMessage] = None

    async def initialize_prompt(self, prompt_name: Optional[str] = None, default_prompt_text: Optional[str] = None):
        """Инициализирует системный промпт для агента."""
        prompt_to_use = None
        if prompt_name:
            db_prompt = await self.prompt_repository.get_active_by_name(prompt_name)
            if db_prompt:
                prompt_to_use = db_prompt.text
                print(f'Agent {self.agent_name} initialized system prompt \'{prompt_name}\' from DB.')
            else:
                print(f'Warning: Prompt \'{prompt_name}\' not found in DB for agent {self.agent_name}.')

        if not prompt_to_use and default_prompt_text:
            prompt_to_use = default_prompt_text
            print(f'Agent {self.agent_name} initialized with default system prompt.')

        if prompt_to_use:
            self.system_prompt = LLMMessage(role="system", content=prompt_to_use)
        else:
            # Если системный промпт не нужен или будет динамическим, это нормально
            print(f'Warning: Agent {self.agent_name} has no system prompt configured.')

    @abstractmethod
    async def process(self, context: AgentContext) -> AgentResponse:
        """
        Обрабатывает запрос пользователя и возвращает ответ.
        Этот метод должен быть реализован каждым конкретным агентом.
        """
        pass

    async def _get_llm_response(self, messages: List[LLMMessage], tools: Optional[List[Dict[str, Any]]] = None, tool_choice: Optional[Any] = "auto") -> LLMResponse:
        """Вспомогательный метод для вызова LLM с текущим системным промптом."""
        full_messages = []
        if self.system_prompt:
            full_messages.append(self.system_prompt)
        full_messages.extend(messages)
        return await self.llm_service.generate_response(full_messages, tools=tools, tool_choice=tool_choice)
