"""
Конфигурационный модуль для email analyzer
Содержит все константы и настройки приложения
"""
import os
from typing import List, Dict, Any
from decouple import config


class Config:
    """Класс для управления конфигурационными параметрами"""
    
    # API конфигурация
    GEMINI_API_KEY: str = config("GEMINI_API_KEY", default="")
    GOOGLE_MODEL: str = config("GOOGLE_MODEL", default="gemini-2.5-flash")
    
    # Gmail API конфигурация
    CLIENT_SECRETS_FILE: str = config("CLIENT_SECRETS_FILE", default="credentials.json")
    SCOPES: List[str] = ["https://www.googleapis.com/auth/gmail.readonly"]
    
    # Mail.ru конфигурация
    MAILRU_USERNAME: str = config("MAILRU_USERNAME", default="")
    MAILRU_PASSWORD: str = config("MAILRU_PASSWORD", default="")
    
    # IMAP серверы конфигурация
    IMAP_SERVERS: Dict[str, Dict[str, Any]] = {
        'mailru': {
            'server': 'imap.mail.ru',
            'port': 993,
            'ssl': True
        },
        'yandex': {
            'server': 'imap.yandex.ru',
            'port': 993,
            'ssl': True
        },
        'outlook': {
            'server': 'outlook.office365.com',
            'port': 993,
            'ssl': True
        }
    }
    
    # Ограничения и лимиты
    MAX_EMAIL_LENGTH: int = config("MAX_EMAIL_LENGTH", default=10000, cast=int)
    MAX_EMAIL_SIZE: int = config("MAX_EMAIL_SIZE", default=50 * 1024 * 1024, cast=int)  # 50MB
    MAX_ATTACHMENT_SIZE: int = config("MAX_ATTACHMENT_SIZE", default=10 * 1024 * 1024, cast=int)  # 10MB
    
    # Повторные попытки
    MAX_RETRIES: int = config("MAX_RETRIES", default=3, cast=int)
    RETRY_DELAY: float = config("RETRY_DELAY", default=1.0, cast=float)
    
    # Логирование
    LOG_LEVEL: str = config("LOG_LEVEL", default="INFO")
    LOG_FILE: str = config("LOG_FILE", default="email_analyzer.log")
    LOG_FORMAT: str = config("LOG_FORMAT", default="%(asctime)s - %(levelname)s - %(message)s")
    
    # Форматы отчетов
    SUPPORTED_FORMATS: List[str] = ["markdown", "json", "csv"]
    DEFAULT_FORMAT: str = config("DEFAULT_FORMAT", default="markdown")
    
    # Категории для анализа
    EMAIL_CATEGORIES: List[str] = [
        "Важное", "Работа", "Финансы", "Покупки", 
        "Социальные сети", "Рассылки", "Спам", "Личное", "Прочее"
    ]
    
    # Приоритеты
    PRIORITY_LEVELS: List[str] = ["Высокий", "Средний", "Низкий"]
    
    # Шаблоны промптов для Gemini AI
    GEMINI_PROMPT_TEMPLATE: str = """Проанализируй электронное письмо и классифицируй его.

КАТЕГОРИИ: {categories}
ПРИОРИТЕТЫ: {priorities}

ЗАДАЧИ:
1. Определи категорию письма
2. Оцени приоритет (Высокий - срочные дела, безопасность; Средний - работа, покупки; Низкий - рассылки, реклама)
3. Составь краткое резюме (2-3 предложения, суть письма)
4. Извлеки ключевые данные: даты, имена, компании, номера, контакты, ссылки

ВЛОЖЕНИЯ: {attachment_info}
ТЕКСТ: {text}

Ответь только JSON без дополнительного текста:
{{"category": "категория", "priority": "приоритет", "summary": "резюме", "entities": ["данные"]}}"""
    
    # Языки для отчетов
    SUPPORTED_LANGUAGES: List[str] = ["ru", "en"]
    DEFAULT_LANGUAGE: str = config("DEFAULT_LANGUAGE", default="ru")
    
    # Тайм-ауты
    SOCKET_TIMEOUT: int = config("SOCKET_TIMEOUT", default=30, cast=int)
    API_TIMEOUT: int = config("API_TIMEOUT", default=60, cast=int)
    
    @classmethod
    def validate(cls) -> bool:
        """Валидация конфигурации"""
        errors = []
        
        if not cls.GEMINI_API_KEY:
            errors.append("GEMINI_API_KEY не установлен")
        
        if cls.MAX_RETRIES < 1:
            errors.append("MAX_RETRIES должно быть больше 0")
        
        if cls.RETRY_DELAY < 0:
            errors.append("RETRY_DELAY не может быть отрицательным")
        
        if cls.DEFAULT_FORMAT not in cls.SUPPORTED_FORMATS:
            errors.append(f"DEFAULT_FORMAT должен быть одним из: {cls.SUPPORTED_FORMATS}")
        
        if errors:
            for error in errors:
                print(f"Ошибка конфигурации: {error}")
            return False
        
        return True
    
    @classmethod
    def get_prompt_template(cls, categories: List[str] = None, priorities: List[str] = None) -> str:
        """Получить шаблон промпта с подставленными категориями и приоритетами"""
        categories = categories or cls.EMAIL_CATEGORIES
        priorities = priorities or cls.PRIORITY_LEVELS
        
        return cls.GEMINI_PROMPT_TEMPLATE.format(
            categories=str(categories),
            priorities=str(priorities),
            attachment_info="{attachment_info}",
            text="{text}"
        )
