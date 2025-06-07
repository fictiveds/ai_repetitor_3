from tutor_bot.database.models import Prompt
from tutor_bot.database.repositories.base_repository import BaseRepository
from typing import Optional, List

class PromptRepository(BaseRepository[Prompt]):
    def __init__(self):
        super().__init__(collection_name="prompts")

    def _get_model_type(self) -> type[Prompt]:
        return Prompt

    async def get_active_by_name(self, name: str) -> Optional[Prompt]:
        # Ищем активный промпт по имени, предпочитая самую новую версию.
        # MongoDB не гарантирует порядок без явной сортировки.
        collection = await self._get_collection()
        cursor = collection.find({"name": name, "is_active": True}).sort("version", -1).limit(1)
        documents = await cursor.to_list(length=1)
        if documents:
             return self._get_model_type()(**documents[0])
        return None

    async def get_by_name_and_version(self, name: str, version: int) -> Optional[Prompt]:
        return await self.find_one({"name": name, "version": version})

    async def get_all_active_by_tag(self, tag: str, limit: int = 100) -> List[Prompt]:
        return await self.find({"tags": tag, "is_active": True}, limit=limit)
