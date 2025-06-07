from typing import Dict, Optional, List
from tutor_bot.database.models import Prompt as PromptModel
from tutor_bot.database.repositories.prompt_repository import PromptRepository
from datetime import datetime, timedelta

class PromptManager:
    def __init__(self, prompt_repository: PromptRepository, cache_ttl_seconds: int = 300):
        self.prompt_repository = prompt_repository
        self.cache: Dict[str, Dict[str, any]] = {} # Кэш для хранения промптов: {prompt_name: {'text': str, 'loaded_at': datetime}}
        self.cache_ttl = timedelta(seconds=cache_ttl_seconds)
        print(f"PromptManager initialized. Cache TTL: {self.cache_ttl.total_seconds()} seconds.")

    async def _load_prompt_from_db(self, name: str) -> Optional[PromptModel]:
        """Загружает активный промпт из БД по имени."""
        # Предполагаем, что get_active_by_name возвращает самую последнюю активную версию
        return await self.prompt_repository.get_active_by_name(name)

    async def get_prompt_text(self, name: str, version: Optional[int] = None, use_cache: bool = True) -> Optional[str]:
        """
        Получает текст промпта по имени (и опционально версии).
        Если версия не указана, ищет последнюю активную версию.
        Использует кэширование, если включено.
        """
        prompt_key = f"{name}:{version if version else 'active'}"

        if use_cache and prompt_key in self.cache:
            cached_item = self.cache[prompt_key]
            if datetime.utcnow() - cached_item['loaded_at'] < self.cache_ttl:
                # print(f"Prompt '{prompt_key}' found in cache and is valid.")
                return cached_item['text']
            else:
                # print(f"Prompt '{prompt_key}' found in cache but expired. Reloading.")
                del self.cache[prompt_key] # Удаляем устаревший элемент

        # Загрузка из БД
        prompt_model: Optional[PromptModel] = None
        if version is not None:
            prompt_model = await self.prompt_repository.get_by_name_and_version(name, version)
        else:
            prompt_model = await self._load_prompt_from_db(name) # Загрузка последней активной

        if prompt_model and prompt_model.text:
            if use_cache:
                self.cache[prompt_key] = {'text': prompt_model.text, 'loaded_at': datetime.utcnow()}
                # print(f"Prompt '{prompt_key}' loaded from DB and cached.")
            return prompt_model.text
        else:
            # print(f"Prompt '{prompt_key}' not found in DB.")
            return None

    async def get_prompt_model(self, name: str, version: Optional[int] = None) -> Optional[PromptModel]:
        """Получает полную модель промпта (включая метаданные), без кэширования текста."""
        if version is not None:
            return await self.prompt_repository.get_by_name_and_version(name, version)
        else:
            return await self._load_prompt_from_db(name)

    async def create_prompt(self, name: str, text: str, description: Optional[str] = None, tags: Optional[List[str]] = None, version: int = 1, is_active: bool = True) -> PromptModel:
        """Создает новый промпт или новую версию существующего (если имя то же, но версия другая)."""
        existing_prompt = await self.prompt_repository.get_by_name_and_version(name, version)
        if existing_prompt:
            raise ValueError(f"Prompt with name '{name}' and version {version} already exists.")

        new_prompt = PromptModel(
            name=name,
            version=version,
            text=text,
            description=description,
            tags=tags or [],
            is_active=is_active
        )

        # Если этот промпт делается активным, нужно деактивировать другие активные версии этого же промпта (если есть)
        if is_active:
            active_prompts_for_name = await self.prompt_repository.find({'name': name, 'is_active': True})
            for active_prompt in active_prompts_for_name:
                if active_prompt.version != version:
                    active_prompt.is_active = False
                    # Мы должны использовать ID модели, а не сам объект модели, для обновления
                    await self.prompt_repository.update(str(active_prompt.id), {'is_active': False})
                    if f"{name}:active" in self.cache: # Очищаем кэш для активной версии
                        del self.cache[f"{name}:active"]

        created_prompt = await self.prompt_repository.create(new_prompt)
        # В коде была переменная use_cache, но она не передавалась в эту функцию.
        # Для простоты будем считать, что если создали активный промпт, то кеш обновить надо.
        if created_prompt.is_active:
             self.cache[f"{name}:active"] = {'text': created_prompt.text, 'loaded_at': datetime.utcnow()}
        return created_prompt

    async def update_prompt_text(self, name: str, version: int, new_text: str) -> Optional[PromptModel]:
        """Обновляет текст конкретной версии промпта."""
        prompt_to_update = await self.prompt_repository.get_by_name_and_version(name, version)
        if not prompt_to_update:
            return None

        updated_data = {'text': new_text, 'updated_at': datetime.utcnow()}
        updated_model = await self.prompt_repository.update(str(prompt_to_update.id), updated_data)

        if updated_model:
            # Обновляем кэш, если промпт был там
            prompt_key_versioned = f"{name}:{version}"
            prompt_key_active = f"{name}:active"
            if prompt_key_versioned in self.cache:
                self.cache[prompt_key_versioned] = {'text': updated_model.text, 'loaded_at': datetime.utcnow()}
            if updated_model.is_active and prompt_key_active in self.cache:
                self.cache[prompt_key_active] = {'text': updated_model.text, 'loaded_at': datetime.utcnow()}
            elif updated_model.is_active and prompt_key_active not in self.cache: # Если стал активным, а в кеше нет
                self.cache[prompt_key_active] = {'text': updated_model.text, 'loaded_at': datetime.utcnow()}
        return updated_model

    async def set_active_version(self, name: str, version_to_activate: int) -> bool:
        """Устанавливает указанную версию промпта как активную, деактивируя другие."""
        target_prompt = await self.prompt_repository.get_by_name_and_version(name, version_to_activate)
        if not target_prompt: return False

        # Деактивируем все другие версии этого промпта
        all_versions = await self.prompt_repository.find({'name': name})
        for prompt_version in all_versions:
            if prompt_version.version != version_to_activate and prompt_version.is_active:
                await self.prompt_repository.update(str(prompt_version.id), {'is_active': False, 'updated_at': datetime.utcnow()})
            elif prompt_version.version == version_to_activate and not prompt_version.is_active:
                await self.prompt_repository.update(str(prompt_version.id), {'is_active': True, 'updated_at': datetime.utcnow()})

        # Обновляем кэш для активной версии
        active_prompt_key = f"{name}:active"
        if active_prompt_key in self.cache: del self.cache[active_prompt_key] # Удаляем старый активный из кэша
        # Загружаем новый активный в кэш
        newly_active_prompt = await self.prompt_repository.get_by_name_and_version(name, version_to_activate)
        if newly_active_prompt and newly_active_prompt.is_active:
             self.cache[active_prompt_key] = {'text': newly_active_prompt.text, 'loaded_at': datetime.utcnow()}
        return True

    async def list_prompts_by_name(self, name: str) -> List[PromptModel]:
        """Возвращает все версии промпта с указанным именем."""
        return await self.prompt_repository.find({'name': name}, limit=100) # Ограничение на всякий случай

    async def list_all_prompt_names(self) -> List[str]:
        """Возвращает список уникальных имен всех промптов."""
        # Это может быть неэффективно на больших коллекциях.
        # В MongoDB это делается через distinct.
        collection = await self.prompt_repository._get_collection() # Доступ к коллекции напрямую (осторожно)
        return await collection.distinct('name')
