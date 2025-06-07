from typing import List, Dict, Any, Optional
from tutor_bot.agents.base_agent import BaseAgent, AgentContext, AgentResponse
from tutor_bot.integrations.llm_service import LLMMessage, LLMService
from tutor_bot.database.repositories.prompt_repository import PromptRepository
import json

class ValidationAgent(BaseAgent):
    AGENT_NAME = "ValidationAgent"

    def __init__(self, llm_service: LLMService, prompt_repository: PromptRepository):
        super().__init__(agent_name=self.AGENT_NAME, llm_service=llm_service, prompt_repository=prompt_repository)

    async def initialize(self):
        # Промпт для агента валидации.
        # Он должен подтвердить детали у пользователя и, если все верно, подготовить финальный JSON.
        default_validation_prompt = """
Ты — AI-ассистент Александр, проверяющий детали записи или отмены урока.
Твоя задача — получить от пользователя подтверждение собранных данных.
Сегодняшняя дата: {{ $now }} (MSK).

Тебе будут переданы детали предполагаемого действия (создание или отмена урока) в поле 'action_details' в системном сообщении.
Формат 'action_details':
Для создания: {{'action': 'create', 'lesson': {{'name': 'Имя', 'phone': 'Телефон', 'start_datetime': 'Время начала', 'end_datetime': 'Время конца'}}}}
Для отмены: {{'action': 'delete', 'lesson': {{'name': 'Имя', 'phone': 'Телефон', 'start_datetime': 'Время начала', 'end_datetime': 'Время конца'}}}}

Твои шаги:
1. Представь пользователю все детали из 'action_details.lesson' для подтверждения.
   Пример для записи: «Хорошо, давайте подтвердим детали. Вы хотите записаться на урок: Имя: [Имя], Телефон: [Телефон], Дата и время: [Дата и время начала]. Всё верно?»
   Пример для отмены: «Давайте подтвердим отмену урока: Имя: [Имя], Телефон: [Телефон], Дата и время: [Дата и время начала]. Отменяем этот урок?»
   Обязательно укажи стоимость, если она известна или может быть вычислена (цель занятия, например, ЕГЭ/ОГЭ или школьная программа, влияет на стоимость). Уточни у CalendarAgent или ConsultationAgent, если нужно.
   Стоимость занятий: Школьная программа/ВПР: 1000-1200₽/час, ЕГЭ/ОГЭ: 1200-1500₽/час. Все уроки по 60 минут.

2. Получи ответ пользователя.
3. Если пользователь подтверждает (говорит 'да', 'верно', 'подтверждаю' и т.п.):
   - Ответь подтверждающим сообщением, например: «Отлично, данные подтверждены!».
   - Затем, в поле 'action_details' ответа агента, верни ТОЛЬКО JSON, который был в 'action_details' ИСХОДНОГО запроса к тебе. Этот JSON будет финальным выводом системы.
   - Установи is_final = True.
4. Если пользователь НЕ подтверждает (говорит 'нет', 'неверно', 'изменить' и т.п.) или хочет внести изменения:
   - Сообщи, что понял, и детали не подтверждены.
   - Спроси, что именно нужно изменить или какие данные неверны.
   - Передай управление обратно Оркестратору (установи next_agent = 'OrchestratorAgent'), чтобы он мог направить на CalendarAgent или ConsultationAgent для исправления данных.
   - Установи is_final = False.
5. Если пользователь задает вопрос не по теме подтверждения:
   - Попробуй кратко ответить, если это простой вопрос о стоимости/формате, используя информацию выше.
   - Затем вернись к вопросу подтверждения.
   - Если вопрос сложный, передай Оркестратору.

Не используй инструменты. Твоя задача - диалог и подтверждение.
В свой первый ответ пользователю (шаг 1) не включай JSON.
        """
        await self.initialize_prompt(prompt_name="validation_agent_main_prompt_v1", default_prompt_text=default_validation_prompt)

    async def process(self, context: AgentContext) -> AgentResponse:
        if not self.system_prompt or not self.system_prompt.content:
            await self.initialize()
            if not self.system_prompt: return AgentResponse(error_message=f"{self.agent_name} system prompt not initialized.", is_final=True)

        action_details = context.additional_data.get("action_details") # Эти детали передает CalendarAgent
        if not action_details or 'action' not in action_details or 'lesson' not in action_details:
            # Если нет деталей для валидации, возможно, агент вызван ошибочно. Перенаправляем.
            return AgentResponse(text_response="Не найдено деталей для подтверждения. Уточните ваш запрос.", next_agent="OrchestratorAgent", is_final=False)

        lesson_info = action_details.get('lesson', {})
        action_type = action_details.get('action')

        # Первый вход в ValidationAgent: запрашиваем подтверждение
        # Мы можем использовать флаг в context.additional_data или в истории диалога, чтобы понять, это первый вызов или ответ на подтверждение
        # Для простоты, будем считать, что если user_input не является явным подтверждением/отрицанием, то это первый вызов.

        is_confirmation_attempt = context.additional_data.get('validation_underway', False)

        llm_messages: List[LLMMessage] = []
        from datetime import datetime
        # Заменяем {{ $now }} и другие плейсхолдеры в системном промпте
        system_prompt_text = self.system_prompt.content.replace("{{ $now }}", datetime.now().strftime("%Y-%m-%d %H:%M:%S MSK"))
        # Передаем детали урока в системный промпт LLM, чтобы она могла их использовать для формулировки запроса подтверждения
        # Это можно сделать, добавив специальное сообщение или модифицировав системный промпт
        system_prompt_text += f"\n\nДЕТАЛИ ДЛЯ ПРОВЕРКИ: {json.dumps(action_details)}"
        llm_messages.append(LLMMessage(role="system", content=system_prompt_text))

        if context.dialog_history:
            for msg in context.dialog_history[-3:]:
                if isinstance(msg, LLMMessage): llm_messages.append(msg)
                elif isinstance(msg, dict): llm_messages.append(LLMMessage(role=msg.get('role','user'), content=msg.get('content','')))
        llm_messages.append(LLMMessage(role="user", content=context.user_input)) # Последний ответ пользователя

        # Вызов LLM для обработки ответа пользователя или генерации запроса на подтверждение
        # ValidationAgent использует LLM для ведения диалога подтверждения
        llm_response_obj = await self._get_llm_response(messages=llm_messages, tool_choice="none")

        if llm_response_obj.error or not llm_response_obj.message or not llm_response_obj.message.content:
            return AgentResponse(text_response="Произошла ошибка при обработке вашего подтверждения.", is_final=True)

        llm_text_response = llm_response_obj.message.content.strip()

        # Анализируем ответ LLM (который должен был проанализировать ответ пользователя)
        # Это упрощенная логика. В идеале, LLM сама должна сказать, подтвердил пользователь или нет.
        # Мы можем добавить в промпт LLM инструкцию вернуть специальный JSON с флагом подтверждения.
        user_input_lower = context.user_input.lower()
        confirmed_keywords = ['да', 'верно', 'подтверждаю', 'хорошо', 'отлично', 'ок', 'yes']
        denied_keywords = ['нет', 'неверно', 'отмена', 'изменить', 'не так', 'no']

        user_confirmed = any(keyword in user_input_lower for keyword in confirmed_keywords)
        user_denied = any(keyword in user_input_lower for keyword in denied_keywords)

        if not is_confirmation_attempt: # Первый заход - LLM должна была сформировать вопрос
            context.additional_data['validation_underway'] = True # Ставим флаг, что мы в процессе валидации
            context.additional_data['original_action_details'] = action_details # Сохраняем исходные детали
            return AgentResponse(text_response=llm_text_response, is_final=False, additional_data=context.additional_data)

        # Если это ответ на запрос подтверждения
        original_action_details_for_final_json = context.additional_data.get('original_action_details', action_details)

        if user_confirmed and not user_denied: # Пользователь подтвердил
            final_text = "Отлично! Данные подтверждены. "
            if action_type == 'create': final_text += "Запись создана."
            elif action_type == 'delete': final_text += "Запись отменена."
            # Возвращаем исходный JSON, который был предназначен для вывода
            return AgentResponse(text_response=final_text, action_details=original_action_details_for_final_json, is_final=True)
        elif user_denied: # Пользователь не подтвердил или хочет изменить
            # LLM должна была уже сформулировать вопрос 'что изменить?' или передать управление
            # Если LLM не справилась, возвращаем общий ответ и передаем Оркестратору
            response_text_on_denial = llm_text_response # Используем ответ LLM, если он есть и адекватен
            if "что именно" not in response_text_on_denial.lower() and "какие данные" not in response_text_on_denial.lower():
                 response_text_on_denial = "Понял вас. Какие данные неверны или что вы хотели бы изменить?"
            return AgentResponse(text_response=response_text_on_denial, next_agent="OrchestratorAgent", is_final=False)
        else: # Непонятный ответ от пользователя
            # LLM должна была попросить уточнить. llm_text_response - это ее попытка.
            return AgentResponse(text_response=llm_text_response + " Пожалуйста, подтвердите детали (да/нет) или укажите, что нужно изменить.", is_final=False, additional_data=context.additional_data)
