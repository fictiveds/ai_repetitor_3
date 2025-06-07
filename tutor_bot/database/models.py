from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid

class PyObjectId(uuid.UUID):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not isinstance(v, uuid.UUID):
            try:
                return uuid.UUID(str(v))
            except ValueError:
                raise ValueError("Not a valid UUID")
        return v

    @classmethod
    def __modify_schema__(cls, field_schema):
        field_schema.update(type="string")

class User(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    telegram_id: Optional[int] = Field(None, unique=True, index=True)
    username: Optional[str] = Field(None)
    first_name: Optional[str] = Field(None)
    last_name: Optional[str] = Field(None)
    phone_number: Optional[str] = Field(None)
    email: Optional[EmailStr] = Field(None)
    registration_date: datetime = Field(default_factory=datetime.utcnow)
    last_activity_date: datetime = Field(default_factory=datetime.utcnow)
    preferences: Dict[str, Any] = Field(default_factory=dict) # e.g., preferred_timezone

    class Config:
        json_encoders = {PyObjectId: str, datetime: lambda dt: dt.isoformat()}
        allow_population_by_field_name = True
        schema_extra = {
            "example": {
                "_id": "00000000-0000-0000-0000-000000000000",
                "telegram_id": 123456789,
                "username": "testuser",
                "first_name": "Test",
                "last_name": "User",
                "phone_number": "+79001234567",
                "email": "test@example.com",
                "registration_date": "2023-01-01T10:00:00Z",
                "last_activity_date": "2023-01-01T12:00:00Z",
                "preferences": {"timezone": "Europe/Moscow"}
            }
        }

class Message(BaseModel):
    role: str = Field(..., description="Role of the message sender (e.g., 'user', 'assistant', 'system')")
    content: str = Field(..., description="Content of the message")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict) # e.g., agent_used, intent_detected

class Dialog(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    user_id: PyObjectId = Field(..., index=True)
    start_time: datetime = Field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = Field(None)
    messages: List[Message] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict) # Store current conversation context, e.g., slot_filling_info
    status: str = Field(default="active") # e.g., active, completed, cancelled

    class Config:
        json_encoders = {PyObjectId: str, datetime: lambda dt: dt.isoformat()}
        allow_population_by_field_name = True
        schema_extra = {
            "example": {
                "_id": "11111111-1111-1111-1111-111111111111",
                "user_id": "00000000-0000-0000-0000-000000000000",
                "start_time": "2023-01-01T10:00:00Z",
                "messages": [
                    {"role": "user", "content": "Hello", "timestamp": "2023-01-01T10:00:05Z"},
                    {"role": "assistant", "content": "Hi there!", "timestamp": "2023-01-01T10:00:10Z"}
                ],
                "status": "active"
            }
        }

class Prompt(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    name: str = Field(..., unique=True, index=True, description="Unique name for the prompt (e.g., 'orchestrator_system_prompt')")
    version: int = Field(default=1, description="Version of the prompt")
    text: str = Field(..., description="The actual prompt text, can contain placeholders like {{variable}}")
    description: Optional[str] = Field(None, description="Description of what the prompt is for")
    tags: List[str] = Field(default_factory=list, description="Tags for categorizing prompts (e.g., 'system', 'agent_X')")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = Field(default=True, description="Whether this prompt version is currently active")

    class Config:
        json_encoders = {PyObjectId: str, datetime: lambda dt: dt.isoformat()}
        allow_population_by_field_name = True
        schema_extra = {
            "example": {
                "_id": "22222222-2222-2222-2222-222222222222",
                "name": "consultation_agent_greeting",
                "version": 1,
                "text": "Здравствуйте! Я Александр, помощник репетитора Юрия Фёдоровича. Чем могу помочь?",
                "description": "Initial greeting message for the consultation agent.",
                "tags": ["greeting", "consultation_agent"],
                "is_active": True
            }
        }

# Example of how to use PyObjectId with Pydantic models for MongoDB
# from bson import ObjectId
# class YourMongoDBModel(BaseModel):
#     id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
#     ...
#     class Config:
#         json_encoders = {
#             ObjectId: str, # If you were using raw ObjectId
#             PyObjectId: str # For our custom type
#         }
