import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# Настройки MongoDB (заглушка)
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = int(os.getenv("MONGO_PORT", 27017))
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "tutor_bot_db")
MONGO_USER = os.getenv("MONGO_USER", None)
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD", None)

# Настройки Google Calendar API
GOOGLE_SCOPES = ['https://www.googleapis.com/auth/calendar']
# Путь к файлу сервисного аккаунта должен быть указан в .env
# Пример: SERVICE_ACCOUNT_FILE=./path/to/your/service-account-file.json
SERVICE_ACCOUNT_FILE = os.getenv('SERVICE_ACCOUNT_FILE', 'service_account.json') # Укажите путь по умолчанию или оставьте None, если он всегда должен быть в .env

# ID календаря должен быть указан в .env
# Пример: GOOGLE_CALENDAR_ID=your-calendar-id@group.calendar.google.com
GOOGLE_CALENDAR_ID = os.getenv('GOOGLE_CALENDAR_ID', 'primary')

# Настройки LLM (заглушка)
LLM_API_KEY = os.getenv("LLM_API_KEY", "your_llm_api_key_here")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "gpt-3.5-turbo") # Пример

# Настройки FastAPI приложения
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", 8000))
DEBUG_MODE = os.getenv("DEBUG_MODE", "False").lower() == "true"

# Другие настройки
DEFAULT_TIMEZONE = "Europe/Moscow"

# Проверка наличия критически важных переменных окружения
if not SERVICE_ACCOUNT_FILE and os.getenv('ENV_TYPE') != 'test': # Не выводить предупреждение при тестах
    print(f"WARNING: SERVICE_ACCOUNT_FILE не загружен из .env! Текущее значение: {SERVICE_ACCOUNT_FILE}")

if (not GOOGLE_CALENDAR_ID or GOOGLE_CALENDAR_ID == 'primary' or GOOGLE_CALENDAR_ID == 'your-calendar-id@group.calendar.google.com') and os.getenv('ENV_TYPE') != 'test':
    print(f"WARNING: GOOGLE_CALENDAR_ID не загружен из .env или используется значение по умолчанию! Текущее значение: {GOOGLE_CALENDAR_ID}")

# Пример .env файла, который должен лежать в корне проекта (рядом с main.py)
# MONGO_HOST=localhost
# MONGO_PORT=27017
# MONGO_DB_NAME=tutor_bot_db
# SERVICE_ACCOUNT_FILE=./path/to/your/service-account-file.json
# GOOGLE_CALENDAR_ID=your-calendar-id@group.calendar.google.com
# LLM_API_KEY=your_actual_llm_api_key
