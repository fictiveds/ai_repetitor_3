import logging
import sys
from typing import Optional # Moved to top
from tutor_bot.config import DEBUG_MODE # Чтобы уровень логирования зависел от режима

def setup_logger(name: str = "tutor_bot", level: Optional[int] = None) -> logging.Logger:
    """
    Настраивает и возвращает логгер с указанным именем и уровнем.
    """
    if level is None:
        level = logging.DEBUG if DEBUG_MODE else logging.INFO

    # Предотвращаем многократное добавление обработчиков, если логгер уже существует
    logger = logging.getLogger(name)
    if logger.hasHandlers():
        # Если логгер уже настроен, просто возвращаем его
        # Но убедимся, что уровень соответствует требуемому (может измениться при перезагрузке конфига)
        logger.setLevel(level)
        # print(f"Logger '{name}' already configured. Set level to {logging.getLevelName(level)}.")
        return logger

    logger.setLevel(level)

    # Обработчик для вывода в stdout
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(level)

    # Форматтер
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    stream_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)

    # Можно добавить другие обработчики, например, для записи в файл:
    # file_handler = logging.FileHandler('tutor_bot.log')
    # file_handler.setLevel(logging.WARNING) # Например, в файл только ошибки и предупреждения
    # file_handler.setFormatter(formatter)
    # logger.addHandler(file_handler)

    # logger.propagate = False # Опционально, чтобы избежать дублирования с корневым логгером, если он настроен

    # print(f"Logger '{name}' configured. Level: {logging.getLevelName(level)}.")
    return logger

# Глобальный экземпляр логгера для использования в приложении
# logger = setup_logger() # Инициализация при импорте модуля
# Лучше инициализировать логгер в основном приложении или там, где он нужен впервые,
# чтобы избежать проблем с порядком импорта и конфигурацией.

# Пример использования:
# from tutor_bot.utils.logging import setup_logger
# logger = setup_logger(__name__)
# logger.info("Это информационное сообщение.")
# logger.debug("Это отладочное сообщение.")
