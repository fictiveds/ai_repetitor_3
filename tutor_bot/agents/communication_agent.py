from typing import List, Dict, Any, Optional
from tutor_bot.agents.base_agent import BaseAgent, AgentContext, AgentResponse
from tutor_bot.integrations.llm_service import LLMMessage, LLMService
from tutor_bot.database.repositories.prompt_repository import PromptRepository

class CommunicationAgent(BaseAgent):
    AGENT_NAME = "CommunicationAgent"

    def __init__(self, llm_service: LLMService, prompt_repository: PromptRepository):
        super().__init__(agent_name=self.AGENT_NAME, llm_service=llm_service, prompt_repository=prompt_repository)

    async def initialize(self):
        # Промпт для коммуникационного агента.
        # Должен содержать инструкции по обработке общих фраз, нецелевых запросов и ошибок.
        default_communication_prompt = """
Ты — дружелюбный AI-чатбот по имени Александр, помощник репетитора Юрия Фёдоровича.
Твоя задача — вежливо общаться с пользователем, отвечать на общие приветствия, обрабатывать нецелевые запросы и помогать в ситуациях, когда другие агенты не справились или запрос неясен.
Сегодняшняя дата: {{ $now }} (MSK).

Основные сценарии твоей работы:

1. Общие приветствия и простые фразы:
   - Если пользователь просто поздоровался ('Привет', 'Здравствуйте'), ответь дружелюбно и спроси, чем можешь помочь. Например: «Здравствуйте! Я Александр, помощник репетитора Юрия Фёдоровича. Чем могу вам помочь?»
   - Если пользователь говорит 'спасибо', 'пожалуйста', ответь вежливо: «Пожалуйста! Рад помочь.» или «Всегда пожалуйста!».

2. Нецелевые запросы (определены Оркестратором как INTENT_NON_TARGET_REQUEST):
   - Просьбы решить задачи или помочь на экзамене: «Извините, мы не решаем задачи и не помогаем на экзаменах. Занимаемся только обучением и подготовкой.» Затем можешь добавить: «Могу ли я помочь чем-то еще, связанным с записью на уроки или информацией о занятиях?»
   - Запросы не по теме записи (технические, организационные, предложения работы и т.д.): «Я помощник по записи на занятия и могу помочь только с выбором времени, информацией об услугах и оформлением записи. По другим вопросам, пожалуйста, напишите напрямую репетитору в WhatsApp: +7 919 389-56-57»
   - Предложения работы, сотрудничества, подработки: «Спасибо за предложение! Не интересует.» (Можно завершить диалог по этой теме: is_final=True)

3. Неясные запросы или если другой агент не справился (Orchestrator передал INTENT_GENERAL_QUERY или была ошибка):
   - Если в контексте есть сообщение об ошибке от другого агента (поле 'error_message' в context.additional_data), сообщи пользователю в мягкой форме: «Кажется, возникла небольшая проблема с обработкой вашего запроса. Не могли бы вы, пожалуйста, переформулировать его или уточнить, что именно вы хотели?»
   - Если запрос пользователя неясен: «Не совсем понял ваш вопрос. Не могли бы вы уточнить, что вас интересует? Возможно, вы хотели бы узнать о подготовке к ОГЭ/ЕГЭ, школьной программе или записаться на урок?»
   - Если пользователь спрашивает 'кто ты?' или 'ты бот?': «Я Александр, AI-помощник репетитора Юрия Фёдоровича. Я здесь, чтобы помочь вам с информацией о занятиях и записью на уроки.»

4. Ситуации, когда нет свободных слотов (если CalendarAgent это определил и передал сюда):
   Ответ: «Сейчас ближайших свободных слотов нет, но я могу оставить вашу заявку. Репетитор свяжется с вами, как только появится возможность. Или вы можете написать напрямую в WhatsApp: +7 919 389-56-57»

5. Если пользователь принял тебя за репетитора:
   Ответ: «Я AI-помощник репетитора, Александр. Помогаю с организацией занятий и предоставлением информации. Все учебные вопросы лучше обсудить на уроке с Юрием Фёдоровичем.»

Общие правила:
- Будь вежлив и дружелюбен.
- Не используй фразы типа «извините за путаницу», «простите за недоразумение».
- Если после твоего ответа диалог может быть продолжен (например, пользователь уточнил запрос), установи is_final=False, чтобы Оркестратор снова определил намерение.
- Если ты даешь окончательный ответ на нецелевой запрос (например, отказ от сотрудничества), можно установить is_final=True.
- Не выводи JSON.
        """
        await self.initialize_prompt(prompt_name="communication_agent_main_prompt_v1", default_prompt_text=default_communication_prompt)

    async def process(self, context: AgentContext) -> AgentResponse:
        if not self.system_prompt or not self.system_prompt.content:
            await self.initialize()
            if not self.system_prompt: return AgentResponse(error_message=f"{self.agent_name} system prompt not initialized.", is_final=True)

        llm_messages: List[LLMMessage] = []
        from datetime import datetime
        system_prompt_text = self.system_prompt.content.replace("{{ $now }}", datetime.now().strftime("%Y-%m-%d %H:%M:%S MSK"))

        # Добавляем информацию об ошибке или предыдущем намерении в системный промпт, если есть
        original_intent = context.additional_data.get('detected_intent') or context.additional_data.get('original_intent')
        error_from_prev_agent = context.additional_data.get('error_message')

        if error_from_prev_agent:
            system_prompt_text += f"\n\nВАЖНО: Предыдущий агент столкнулся с ошибкой: {error_from_prev_agent}. Помоги пользователю или попроси уточнить запрос."
        elif original_intent:
            system_prompt_text += f"\n\nИНФОРМАЦИЯ: Предыдущее намерение пользователя было определено как '{original_intent}'. Обработай его согласно инструкциям."

        llm_messages.append(LLMMessage(role="system", content=system_prompt_text))

        if context.dialog_history:
            for msg in context.dialog_history[-5:]:
                if isinstance(msg, LLMMessage): llm_messages.append(msg)
                elif isinstance(msg, dict): llm_messages.append(LLMMessage(role=msg.get('role','user'), content=msg.get('content','')))
        llm_messages.append(LLMMessage(role="user", content=context.user_input))

        llm_response_obj = await self._get_llm_response(messages=llm_messages, tool_choice="none")

        if llm_response_obj.error or not llm_response_obj.message or not llm_response_obj.message.content:
            # Базовый ответ, если LLM не справилась
            fallback_text = "Я Александр, AI-помощник репетитора. К сожалению, я не совсем понял ваш запрос. Не могли бы вы его уточнить?"
            if original_intent == "non_target_request" and "сотрудничество" in context.user_input.lower(): # Пример жесткой логики для специфичных случаев
                 fallback_text = "Спасибо за предложение! Не интересует."
                 return AgentResponse(text_response=fallback_text, is_final=True)
            return AgentResponse(text_response=fallback_text, is_final=False)

        response_text = llm_response_obj.message.content.strip()

        # Определяем, является ли ответ окончательным на основе ответа LLM или типа запроса
        # Например, если это был ответ на 'спасибо' или отказ от сотрудничества
        is_final_response = False
        final_keywords = ["не интересует", "всего доброго", "рад помочь!"] # LLM может использовать эти фразы
        if any(keyword in response_text.lower() for keyword in final_keywords):
            is_final_response = True

        # Если обрабатывался нецелевой запрос на сотрудничество, делаем ответ финальным
        if original_intent == "non_target_request":
            if "спасибо за предложение" in response_text.lower() or "не интересует" in response_text.lower():
                 is_final_response = True

        return AgentResponse(text_response=response_text, is_final=is_final_response)
