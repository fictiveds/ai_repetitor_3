from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from pymongo.errors import ConnectionFailure
from tutor_bot.config import MONGO_HOST, MONGO_PORT, MONGO_DB_NAME, MONGO_USER, MONGO_PASSWORD
from tutor_bot.database.models import User, Dialog, Prompt # To ensure models are defined for potential type hinting or direct use

class MongoDBClient:
    _client: AsyncIOMotorClient = None
    _db: AsyncIOMotorDatabase = None

    async def connect(self):
        if self._client:
            return

        mongo_uri = f"mongodb://{MONGO_HOST}:{MONGO_PORT}"
        if MONGO_USER and MONGO_PASSWORD:
            mongo_uri = f"mongodb://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}"

        print(f"Connecting to MongoDB at {mongo_uri}...")
        try:
            self._client = AsyncIOMotorClient(mongo_uri)
            # Проверка соединения (опционально, но полезно для быстрой диагностики)
            await self._client.admin.command('ping')
            self._db = self._client[MONGO_DB_NAME]
            print(f"Successfully connected to MongoDB. Database: {MONGO_DB_NAME}")
        except ConnectionFailure as e:
            print(f"Failed to connect to MongoDB: {e}")
            raise
        except Exception as e: # более общая ошибка, если пинг не удался по другой причине
            print(f"An error occurred during MongoDB connection or ping: {e}")
            # В зависимости от политики, можно либо пробросить ошибку дальше, либо попытаться подключиться без пинга
            # Если мы здесь, но ConnectionFailure не было, значит клиент создан, но пинг не прошел.
            # Для некоторых окружений пинг может быть заблокирован, но БД доступна.
            if self._client and not self._db: # Если клиент создан, но БД не присвоена
                 self._db = self._client[MONGO_DB_NAME]
                 print(f"MongoDB client created, but ping failed. Proceeding with database: {MONGO_DB_NAME}")
            else:
                 raise # Перевыбрасываем, если ситуация не ясна

    async def close(self):
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
            print("MongoDB connection closed.")

    def get_database(self) -> AsyncIOMotorDatabase:
        if not self._db:
            # Это не должно происходить, если connect был вызван и успешен
            raise Exception("Database not initialized. Call connect() first.")
        return self._db

    def get_collection(self, collection_name: str) -> AsyncIOMotorCollection:
        if not self._db:
            raise Exception("Database not initialized. Call connect() first.")
        return self._db[collection_name]

    # Можно добавить свойства для прямого доступа к коллекциям, если они фиксированы
    @property
    def users_collection(self) -> AsyncIOMotorCollection:
        return self.get_collection("users")

    @property
    def dialogs_collection(self) -> AsyncIOMotorCollection:
        return self.get_collection("dialogs")

    @property
    def prompts_collection(self) -> AsyncIOMotorCollection:
        return self.get_collection("prompts")

# Глобальный экземпляр клиента для удобства использования в приложении
mongodb_client = MongoDBClient()

async def get_db_client() -> MongoDBClient:
    # Эту функцию можно использовать для DI в FastAPI
    if not mongodb_client._client: # Проверяем, есть ли активный клиент
        await mongodb_client.connect()
    return mongodb_client

async def get_db() -> AsyncIOMotorDatabase:
    client = await get_db_client()
    return client.get_database()

# Пример использования (можно убрать или закомментировать)
# async def main():
#     await mongodb_client.connect()
#     db = mongodb_client.get_database()
#     print(f"Collections: {await db.list_collection_names()}")
#     # users = mongodb_client.users_collection
#     # print(f"Users collection: {users.name}")
#     await mongodb_client.close()

# if __name__ == "__main__":
#     import asyncio
#     asyncio.run(main())
