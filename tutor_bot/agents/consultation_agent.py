from typing import List, Dict, Any, Optional
from tutor_bot.agents.base_agent import BaseAgent, AgentContext, AgentResponse
from tutor_bot.integrations.llm_service import LLMMessage, LLMService
from tutor_bot.database.repositories.prompt_repository import PromptRepository
import json

class ConsultationAgent(BaseAgent):
    AGENT_NAME = "ConsultationAgent"

    def __init__(self, llm_service: LLMService, prompt_repository: PromptRepository):
        super().__init__(agent_name=self.AGENT_NAME, llm_service=llm_service, prompt_repository=prompt_repository)

    async def initialize(self):
        # Промпт для консультационного агента. Он должен содержать всю информацию для ответов.
        # Этот промпт взят из вашего общего описания задачи.
        default_consultation_prompt = """
Ты — дружелюбный AI-чатбот по имени Александр, помощник репетитора Юрия Фёдоровича по физике.
Твоя задача — предоставлять информацию об услугах репетитора, формате и стоимости занятий.
Веди диалог максимально по-человечески, четко и вежливо.

Сегодняшняя дата: {{ $now }}
Часовой пояс: Московское время (MSK).

Информация для предоставления клиентам:

1. Формат занятий:
   - Занятия проходят онлайн.
   - Занятия индивидуальные.
   - Репетитор: Юрий Фёдорович, специализируется на физике.

2. Время работы репетитора:
   - Обычно по будням с 17:00 до 22:00 по МСК.
   - Для уточнения свободного времени предложи записаться на пробный урок или спросить о конкретных днях (этим займется CalendarAgent, но ты можешь упомянуть о такой возможности).

3. Стоимость занятий (все уроки по 60 минут):
   - Школьная программа (помощь с домашними заданиями, повышение успеваемости, устранение пробелов): 1000-1200₽/час.
   - Подготовка к ОГЭ/ЕГЭ по физике: 1200-1500₽/час.
   - Подготовка к ВПР по физике: 1000-1200₽/час.
   - Пробный урок: оплачивается по той же стоимости, что и обычное занятие, в зависимости от цели (школьная программа, ОГЭ/ЕГЭ, ВПР).

4. Цели обращения, которые ты можешь обсудить:
   - Подготовка к ОГЭ по физике.
   - Подготовка к ЕГЭ по физике.
   - Подготовка к ВПР по физике.
   - Помощь со школьной программой по физике (повышение успеваемости, устранение пробелов).
   - Срочная помощь (например, «контрольная завтра») - уточни, что репетитор постарается помочь, если будет время, но лучше готовиться заранее.

5. Что НЕ входит в твои обязанности (и обязанности репетитора вне уроков):
   - Решение задач за ученика или помощь на экзаменах/контрольных в реальном времени.
     Ответ: «Извините, мы не решаем задачи и не помогаем на экзаменах. Занимаемся только обучением и подготовкой.»
   - Обсуждение вопросов не по теме записи или услуг репетитора (технические проблемы с платформой, организационные вопросы не связанные с расписанием, предложения работы/сотрудничества).
     Ответ: «Я помощник по записи на занятия и могу помочь только с информацией об услугах, стоимости и расписании. По другим вопросам, пожалуйста, напишите напрямую репетитору в WhatsApp: +7 919 389-56-57»

Твоя задача - отвечать на вопросы пользователя, основываясь на этой информации.
Если пользователь выражает желание записаться или узнать о свободном времени, сообщи, что можешь передать его запрос для записи или проверки слотов (это будет обработано другим агентом).
Не предлагай конкретные временные слоты сам.
Если не знаешь ответ, используй шаблон: «К сожалению, я не могу ответить на этот вопрос. Пожалуйста, уточните его у репетитора в WhatsApp: +7 919 389-56-57. Он ответит на все ваши вопросы.»
Если тебя приняли за репетитора: «Я помощник репетитора, Александр. Помогаю с организацией занятий и предоставлением информации. Все учебные вопросы лучше обсудить на уроке с Юрием Фёдоровичем.»
Если вопрос неясный или выходит за рамки: «Не совсем понял ваш вопрос. Хотите, я передам его репетитору, чтобы он сам связался с вами?»
Предложения работы/сотрудничества: «Спасибо за предложение! Не интересует.» и завершай диалог по этой теме.
Старайся быть кратким, но информативным. Не используй фразы типа «извините за путаницу».
В конце своего ответа, если ты предоставил информацию и диалог может быть продолжен для записи, укажи это, чтобы Оркестратор мог снова оценить намерение.
Не выводи JSON.
        """
        await self.initialize_prompt(prompt_name="consultation_agent_main_prompt_v2", default_prompt_text=default_consultation_prompt)

    async def process(self, context: AgentContext) -> AgentResponse:
        if not self.system_prompt or not self.system_prompt.content:
            await self.initialize()
            if not self.system_prompt:
                 return AgentResponse(error_message=f"{self.agent_name} system prompt not initialized.", is_final=True)

        llm_messages: List[LLMMessage] = []
        from datetime import datetime
        current_system_prompt_text = self.system_prompt.content if self.system_prompt else ""
        current_system_prompt_text = current_system_prompt_text.replace("{{ $now }}", datetime.now().strftime("%Y-%m-%d %H:%M:%S MSK"))
        llm_messages.append(LLMMessage(role="system", content=current_system_prompt_text))

        # Добавляем историю диалога, если она есть
        if context.dialog_history:
            for msg in context.dialog_history[-5:]:
                 # Убедимся, что msg это LLMMessage или преобразуем его
                 if isinstance(msg, LLMMessage):
                     llm_messages.append(msg)
                 elif isinstance(msg, dict): # Если история хранится как dict
                     llm_messages.append(LLMMessage(role=msg.get('role', 'user'), content=msg.get('content', '')))

        llm_messages.append(LLMMessage(role="user", content=context.user_input))

        # ConsultationAgent обычно не использует инструменты, он генерирует текст
        llm_response = await self._get_llm_response(messages=llm_messages, tool_choice="none")

        if llm_response.error or not llm_response.message or not llm_response.message.content:
            error_msg = llm_response.error or "LLM did not return content for consultation."
            print(f"{self.agent_name} error: {error_msg}")
            # Если LLM не смогла ответить, можно вернуть стандартное сообщение или передать CommunicationAgent
            standard_error_response = "К сожалению, я сейчас не могу обработать ваш запрос. Пожалуйста, попробуйте позже или свяжитесь с репетитором напрямую."
            return AgentResponse(text_response=standard_error_response, is_final=True) # или is_final=False, next_agent='CommunicationAgent'

        # Ответ LLM - это прямой ответ пользователю
        response_text = llm_response.message.content.strip()

        # Простой эвристический анализ ответа LLM, чтобы понять, нужно ли перенаправлять на другой агент
        # Например, если в ответе есть фразы вроде "для записи" или "узнать свободное время"
        # Это очень упрощенно, в идеале LLM сама могла бы подсказать следующий шаг или оркестратор переопределит намерение
        potential_next_step_keywords = ["записаться", "запись", "свободное время", "выбрать время", "когда можно", "пробный урок"]
        next_agent_suggestion = None
        if any(keyword in response_text.lower() for keyword in potential_next_step_keywords) or \
           any(keyword in context.user_input.lower() for keyword in potential_next_step_keywords):
            # Если LLM или пользователь упомянули запись, возможно, нужно передать CalendarAgent
            # Но ConsultationAgent сам не переводит, он просто отвечает. Оркестратор должен это решить.
            # Поэтому is_final=False, чтобы Оркестратор снова проанализировал.
            pass # Оставляем is_final=False по умолчанию для Оркестратора

        # По умолчанию, после консультации, мы ожидаем, что пользователь либо задаст уточняющий вопрос (снова Consultation),
        # либо захочет записаться (Calendar), либо диалог завершится.
        # Поэтому is_final=False, чтобы Оркестратор мог переоценить намерение после ответа консультанта.
        return AgentResponse(text_response=response_text, is_final=False)
