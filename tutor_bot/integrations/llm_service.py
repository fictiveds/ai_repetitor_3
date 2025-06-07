from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import asyncio # Для имитации асинхронной операции
import json # Для работы с аргументами функций

try:
    from tutor_bot.config import LLM_API_KEY, LLM_MODEL_NAME
except ModuleNotFoundError:
    print('Warning: Could not import from tutor_bot.config for LLM service. Using defaults.')
    LLM_API_KEY = 'your_llm_api_key_here'
    LLM_MODEL_NAME = 'mock_llm_model'


class LLMMessage(BaseModel):
    role: str # 'system', 'user', 'assistant', 'tool'
    content: Optional[str] = None
    name: Optional[str] = None # Имя функции/инструмента для tool role
    tool_call_id: Optional[str] = None # Для tool role
    tool_calls: Optional[List[Dict[str, Any]]] = None # Для assistant role

class LLMResponse(BaseModel):
    message: LLMMessage
    error: Optional[str] = None
    usage: Optional[Dict[str, int]] = None

class LLMService:
    def __init__(self, api_key: str = LLM_API_KEY, model_name: str = LLM_MODEL_NAME):
        self.api_key = api_key
        self.model_name = model_name
        if not self.api_key or self.api_key == 'your_llm_api_key_here':
            print(f'WARNING: LLM_API_KEY is not set or is using the default placeholder in LLMService. Model: {self.model_name}')
        print(f'LLMService initialized with model: {self.model_name}')

    async def generate_response(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int = 1500,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = 'auto'
    ) -> LLMResponse:
        print(f'LLMService.generate_response called with {len(messages)} messages. Model: {self.model_name}')
        if tools:
            print(f'Tools available: {[tool.get("function", {}).get("name") for tool in tools if tool.get("type") == "function"]}')
        print(f'Tool choice: {tool_choice}')
        await asyncio.sleep(0.1)
        last_message = messages[-1] if messages else LLMMessage(role='user', content='')

        if tools and last_message.role == 'user' and last_message.content:
            user_content_lower = last_message.content.lower()
            if isinstance(tool_choice, dict) and tool_choice.get('type') == 'function':
                func_name = tool_choice.get('function', {}).get('name')
                print(f'LLMService (mock): Forced to call tool \'{func_name}\' by tool_choice.')
                return LLMResponse(
                    message=LLMMessage(
                        role='assistant',
                        tool_calls=[{
                            'id': f'call_mock_{func_name}_123',
                            'type': 'function',
                            'function': {'name': func_name, 'arguments': '{}'}
                        }]
                    ),
                    usage={'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20}
                )

            if 'покажи свободные слоты' in user_content_lower or 'свободное время' in user_content_lower:
                tool_name_to_call = 'get_available_slots'
                if any(t.get('function', {}).get('name') == tool_name_to_call for t in tools if t.get('type') == 'function'):
                    print(f'LLMService (mock): Decided to call tool \'{tool_name_to_call}\' for slots.')
                    args = {'date': 'today', 'duration_minutes': 60}
                    if 'завтра' in user_content_lower: args['date'] = 'tomorrow'
                    return LLMResponse(
                        message=LLMMessage(
                            role='assistant',
                            tool_calls=[{
                                'id': f'call_mock_{tool_name_to_call}_123',
                                'type': 'function',
                                'function': {'name': tool_name_to_call, 'arguments': json.dumps(args)}
                            }]
                        ),
                        usage={'prompt_tokens': 15, 'completion_tokens': 20, 'total_tokens': 35}
                    )

            if 'запиши на урок' in user_content_lower or 'записаться на' in user_content_lower:
                tool_name_to_call = 'create_lesson_booking'
                if any(t.get('function', {}).get('name') == tool_name_to_call for t in tools if t.get('type') == 'function'):
                    print(f'LLMService (mock): Decided to call tool \'{tool_name_to_call}\' for booking.')
                    args = {
                        'name': 'Иван Петров (извлечено)',
                        'phone': '+79001234560 (извлечено)',
                        'start_datetime': '2024-09-10T10:00:00',
                        'end_datetime': '2024-09-10T11:00:00',
                        'description': f'Запрос: {last_message.content}'
                    }
                    return LLMResponse(
                        message=LLMMessage(
                            role='assistant',
                            tool_calls=[{"id": f'call_mock_{tool_name_to_call}_456',
                                'type': 'function',
                                'function': {'name': tool_name_to_call, 'arguments': json.dumps(args)}
                            }]
                        ),
                        usage={'prompt_tokens': 20, 'completion_tokens': 30, 'total_tokens': 50}
                    )

        if last_message.role == 'tool':
            mock_tool_response_follow_up = f'LLM ({self.model_name}): Получен результат от инструмента \'{last_message.name}\'. '
            mock_tool_response_follow_up += f'Содержимое: \'{last_message.content[:100]}...\'. Теперь я могу продолжить.'
            return LLMResponse(
                message=LLMMessage(role='assistant', content=mock_tool_response_follow_up),
                usage={'prompt_tokens': 25, 'completion_tokens': 25, 'total_tokens': 50}
            )

        mock_reply_content = f'Это заглушка ответа от LLM ({self.model_name}) на ваше сообщение: \'{last_message.content}\'. '
        if not tools:
            mock_reply_content += 'Инструменты не были предоставлены для использования. '
        return LLMResponse(
            message=LLMMessage(role='assistant', content=mock_reply_content),
            usage={'prompt_tokens': 10, 'completion_tokens': 15, 'total_tokens': 25}
        )

    async def get_embedding(self, text: str, model_name: Optional[str] = None) -> List[float]:
        effective_model = model_name or self.model_name
        print(f'LLMService.get_embedding called for text: \'{text[:50]}...\' using model (conceptually): {effective_model}')
        await asyncio.sleep(0.05)
        return [i * 0.001 for i in range(1536)]
