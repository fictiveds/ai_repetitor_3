from abc import ABC, abstractmethod
from typing import Generic, TypeVar, List, Optional, Any, Dict
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorCollection
from tutor_bot.database.mongodb_client import get_db
from tutor_bot.database.models import PyObjectId
from bson import ObjectId # Для преобразования строк ID в ObjectId для запросов MongoDB

T = TypeVar('T', bound=BaseModel) # Тип для модели Pydantic

class BaseRepository(Generic[T], ABC):
    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        self._collection: Optional[AsyncIOMotorCollection] = None

    async def _get_collection(self) -> AsyncIOMotorCollection:
        if self._collection is None:
            db = await get_db()
            self._collection = db[self.collection_name]
        return self._collection

    @abstractmethod
    def _get_model_type(self) -> type[T]:
        # Этот метод должен быть реализован в подклассах, чтобы возвращать тип Pydantic модели
        pass

    async def get_by_id(self, id: str) -> Optional[T]:
        collection = await self._get_collection()
        obj_id_to_query = None
        try:
            # Попытка преобразовать id в ObjectId, если это строка в формате ObjectId
            obj_id_to_query = ObjectId(id)
        except Exception:
            # Если не удалось, возможно, id это UUID или другая строка.
            # В нашей модели PyObjectId это UUID. MongoDB может хранить UUID как строку или как бинарный тип.
            # Если мы храним PyObjectId (UUID) как строку в MongoDB, то ищем по строке.
            # Если мы используем кастомный кодек для UUID в MongoDB, то драйвер может это обработать.
            # Для простоты, если ObjectId не получается, ищем по строке id.
            obj_id_to_query = str(id) # Убедимся что это строка для запроса

        document = await collection.find_one({"_id": obj_id_to_query})
        if document:
            return self._get_model_type()(**document)
        return None

    async def get_all(self, skip: int = 0, limit: int = 100) -> List[T]:
        collection = await self._get_collection()
        cursor = collection.find().skip(skip).limit(limit)
        documents = await cursor.to_list(length=limit)
        return [self._get_model_type()(**doc) for doc in documents]

    async def create(self, item: T) -> T:
        collection = await self._get_collection()
        data = item.dict(by_alias=True, exclude_none=True)

        # Наша модель PyObjectId генерирует UUID. Убедимся, что он используется как _id.
        # Если '_id' уже есть в data (например, из item.dict(by_alias=True)), используем его.
        # Если нет, но есть 'id', используем его как '_id'.
        if "_id" not in data and "id" in data:
             data["_id"] = data.pop("id")
        elif "_id" not in data and "id" not in data:
            # Если ID не был сгенерирован моделью (что маловероятно с default_factory),
            # MongoDB сгенерирует свой ObjectId. Это может быть проблемой для PyObjectId (UUID).
            # Мы ожидаем, что PyObjectId уже установил 'id' в модели.
            pass


        await collection.insert_one(data)
        # Возвращаем исходный item, т.к. его ID (PyObjectId/UUID) уже был установлен.
        return item

    async def update(self, id: str, item_update_data: Dict[str, Any]) -> Optional[T]:
        collection = await self._get_collection()
        obj_id_to_query = None
        try:
            obj_id_to_query = ObjectId(id)
        except Exception:
            obj_id_to_query = str(id)

        result = await collection.update_one({"_id": obj_id_to_query}, {"$set": item_update_data})
        if result.modified_count > 0:
            return await self.get_by_id(id) # Получаем обновленный документ по оригинальному ID
        # Если документ не был изменен, но существует, можно вернуть его текущее состояние
        elif result.matched_count > 0:
            return await self.get_by_id(id)
        return None

    async def update_by_model(self, id: str, item: T) -> Optional[T]:
        update_data = item.dict(by_alias=True, exclude_none=True, exclude={"id", "_id"})
        return await self.update(id, update_data)

    async def delete(self, id: str) -> bool:
        collection = await self._get_collection()
        obj_id_to_query = None
        try:
            obj_id_to_query = ObjectId(id)
        except Exception:
            obj_id_to_query = str(id)

        result = await collection.delete_one({"_id": obj_id_to_query})
        return result.deleted_count > 0

    async def find_one(self, criteria: Dict[str, Any]) -> Optional[T]:
        collection = await self._get_collection()
        # Нужно быть осторожным с типами в criteria, особенно для '_id'
        if "_id" in criteria and isinstance(criteria["_id"], str):
            try:
                criteria["_id"] = ObjectId(criteria["_id"])
            except Exception:
                 # Если не ObjectId-строка, оставляем как есть (предполагая UUID-строку)
                 pass

        document = await collection.find_one(criteria)
        if document:
            return self._get_model_type()(**document)
        return None

    async def find(self, criteria: Dict[str, Any], skip: int = 0, limit: int = 100) -> List[T]:
        collection = await self._get_collection()
        if "_id" in criteria and isinstance(criteria["_id"], str):
            try:
                criteria["_id"] = ObjectId(criteria["_id"])
            except Exception:
                 pass
        cursor = collection.find(criteria).skip(skip).limit(limit)
        documents = await cursor.to_list(length=limit)
        return [self._get_model_type()(**doc) for doc in documents]
