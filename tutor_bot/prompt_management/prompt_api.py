from fastapi import APIRouter, Depends, HTTPException, status, Body
from typing import List, Optional
from tutor_bot.database.models import Prompt as PromptModelPydantic # Pydantic модель для ответа/ввода
from tutor_bot.prompt_management.prompt_manager import PromptManager
from tutor_bot.database.mongodb_client import MongoDBClient, get_db_client # Для DI
from tutor_bot.database.repositories.prompt_repository import PromptRepository
from pydantic import BaseModel # Убедимся, что BaseModel импортирован

router = APIRouter(
    prefix="/prompts",
    tags=["Prompt Management"]
)

# --- Зависимость для получения PromptManager ---
async def get_prompt_manager(db_client: MongoDBClient = Depends(get_db_client)) -> PromptManager:
    # Убедимся, что соединение с БД установлено, если это не было сделано ранее
    # В FastAPI это обычно делается при старте приложения, но для надежности можно проверить
    if not db_client._client or not db_client._db: # Проверяем внутренние атрибуты клиента
        await db_client.connect()
    prompt_repo = PromptRepository() # Репозиторий будет использовать тот же db_client
    return PromptManager(prompt_repository=prompt_repo)

# --- Модели для запросов API, если они отличаются от основной модели Prompt ---
class PromptCreateUpdate(BaseModel): # Используем BaseModel из Pydantic
    name: str
    text: str
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    version: Optional[int] = None # При создании можно опустить для авто-версионирования или указать
    is_active: Optional[bool] = True

class PromptTextUpdate(BaseModel):
    text: str

# --- Эндпоинты API ---
@router.post("/", response_model=PromptModelPydantic, status_code=status.HTTP_201_CREATED)
async def create_prompt_api(prompt_data: PromptCreateUpdate = Body(...), manager: PromptManager = Depends(get_prompt_manager)):
    """Создает новый промпт. Если версия не указана, пытается создать версию 1."""
    version_to_create = prompt_data.version if prompt_data.version is not None else 1
    try:
        # Проверяем, существует ли уже такой промпт с такой версией
        existing = await manager.get_prompt_model(prompt_data.name, version_to_create)
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Prompt '{prompt_data.name}' version {version_to_create} already exists.")

        created_prompt = await manager.create_prompt(
            name=prompt_data.name,
            text=prompt_data.text,
            description=prompt_data.description,
            tags=prompt_data.tags,
            version=version_to_create,
            is_active=prompt_data.is_active if prompt_data.is_active is not None else True
        )
        return created_prompt
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        # Логирование ошибки здесь было бы полезно
        print(f"Error creating prompt: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error while creating prompt.")

@router.get("/names", response_model=List[str])
async def get_all_prompt_names(manager: PromptManager = Depends(get_prompt_manager)):
    """Получает список уникальных имен всех промптов."""
    return await manager.list_all_prompt_names()

@router.get("/{prompt_name}", response_model=List[PromptModelPydantic])
async def get_prompt_versions_by_name(prompt_name: str, manager: PromptManager = Depends(get_prompt_manager)):
    """Получает все версии промпта по его имени."""
    prompts = await manager.list_prompts_by_name(prompt_name)
    if not prompts:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No prompts found with name '{prompt_name}'.")
    return prompts

@router.get("/{prompt_name}/active", response_model=PromptModelPydantic)
async def get_active_prompt_by_name(prompt_name: str, manager: PromptManager = Depends(get_prompt_manager)):
    """Получает активную версию промпта по имени."""
    prompt = await manager.get_prompt_model(prompt_name) # get_prompt_model без версии вернет активный
    if not prompt or not prompt.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Active prompt not found for '{prompt_name}'.")
    return prompt

@router.get("/{prompt_name}/{version}", response_model=PromptModelPydantic)
async def get_specific_prompt_version(prompt_name: str, version: int, manager: PromptManager = Depends(get_prompt_manager)):
    """Получает конкретную версию промпта по имени и версии."""
    prompt = await manager.get_prompt_model(prompt_name, version)
    if not prompt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Prompt '{prompt_name}' version {version} not found.")
    return prompt

@router.put("/{prompt_name}/{version}/text", response_model=PromptModelPydantic)
async def update_prompt_version_text_api(prompt_name: str, version: int, text_data: PromptTextUpdate = Body(...), manager: PromptManager = Depends(get_prompt_manager)):
    """Обновляет текст конкретной версии промпта."""
    updated_prompt = await manager.update_prompt_text(prompt_name, version, text_data.text)
    if not updated_prompt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Prompt '{prompt_name}' version {version} not found for update.")
    return updated_prompt

@router.put("/{prompt_name}/{version}/activate", response_model=PromptModelPydantic)
async def set_prompt_version_active_api(prompt_name: str, version: int, manager: PromptManager = Depends(get_prompt_manager)):
    """Устанавливает указанную версию промпта как активную."""
    success = await manager.set_active_version(prompt_name, version)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Prompt '{prompt_name}' version {version} not found or could not be activated.")
    activated_prompt = await manager.get_prompt_model(prompt_name, version) # Получаем обновленную модель
    if not activated_prompt or not activated_prompt.is_active:
        # Этого не должно произойти, если set_active_version отработал корректно
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to confirm activation for prompt '{prompt_name}' version {version}.")
    return activated_prompt

# Добавить эндпоинт для обновления всего промпта (PUT /{prompt_name}/{version}) может быть полезно
# @router.put("/{prompt_name}/{version}", response_model=PromptModelPydantic)
# async def update_specific_prompt_version(...)
# ...
