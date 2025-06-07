from tutor_bot.database.models import Dialog, PyObjectId, Message
from tutor_bot.database.repositories.base_repository import BaseRepository
from typing import List, Optional
from datetime import datetime
from bson import ObjectId # Для работы с ObjectId если user_id хранится так

class DialogRepository(BaseRepository[Dialog]):
    def __init__(self):
        super().__init__(collection_name="dialogs")

    def _get_model_type(self) -> type[Dialog]:
        return Dialog

    async def get_active_dialog_by_user_id(self, user_id: PyObjectId) -> Optional[Dialog]:
        # user_id в модели Dialog это PyObjectId (UUID). В MongoDB он будет храниться как строка.
        return await self.find_one({"user_id": str(user_id), "status": "active"})

    async def get_dialogs_by_user_id(self, user_id: PyObjectId, limit: int = 10, sort_desc: bool = True) -> List[Dialog]:
        criteria = {"user_id": str(user_id)}
        collection = await self._get_collection()

        # Сортировка по времени начала диалога, если требуется
        sort_options = [("start_time", -1 if sort_desc else 1)]

        cursor = collection.find(criteria).sort(sort_options).limit(limit)
        documents = await cursor.to_list(length=limit)
        return [self._get_model_type()(**doc) for doc in documents]

    async def add_message_to_dialog(self, dialog_id: str, message: Message) -> Optional[Dialog]:
        collection = await self._get_collection()
        message_data = message.dict(exclude_none=True)

        obj_dialog_id = None
        try:
            obj_dialog_id = ObjectId(dialog_id)
        except Exception:
            obj_dialog_id = str(dialog_id) # Если ID диалога это UUID строка

        result = await collection.update_one(
            {"_id": obj_dialog_id},
            {"$push": {"messages": message_data}, "$set": {"end_time": datetime.utcnow(), "last_activity_date": datetime.utcnow()}}
        )
        if result.modified_count > 0:
            return await self.get_by_id(dialog_id)
        return None
