from tutor_bot.database.models import User
from tutor_bot.database.repositories.base_repository import BaseRepository
from typing import Optional

class UserRepository(BaseRepository[User]):
    def __init__(self):
        super().__init__(collection_name="users")

    def _get_model_type(self) -> type[User]:
        return User

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        return await self.find_one({"telegram_id": telegram_id})

    async def get_by_username(self, username: str) -> Optional[User]:
        # Поиск без учета регистра для username
        return await self.find_one({"username": {"$regex": f"^{username}$", "$options": "i"}})
