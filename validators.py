"""
Модуль для валидации входных данных
Содержит функции для проверки параметров командной строки, дат, email адресов и других данных
"""
import re
import os
import datetime
from typing import Optional, List, Any
from pathlib import Path
import logging
from config import Config

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Исключение для ошибок валидации"""
    pass


class InputValidator:
    """Класс для валидации входных данных"""
    
    @staticmethod
    def validate_email(email: str) -> bool:
        """
        Валидация email адреса
        
        Args:
            email: Email адрес для проверки
            
        Returns:
            True если email корректный, False иначе
        """
        if not email or not isinstance(email, str):
            return False
        
        # Простая регулярка для email
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(email_pattern, email.strip()))
    
    @staticmethod
    def validate_date(date_str: str) -> bool:
        """
        Валидация даты в формате YYYY-MM-DD
        
        Args:
            date_str: Строка с датой
            
        Returns:
            True если дата корректная, False иначе
        """
        if not date_str or not isinstance(date_str, str):
            return False
        
        try:
            datetime.datetime.strptime(date_str.strip(), '%Y-%m-%d')
            return True
        except ValueError:
            return False
    
    @staticmethod
    def validate_count(count: Any) -> bool:
        """
        Валидация количества писем

        Args:
            count: Количество для проверки

        Returns:
            True если количество корректное, False иначе
        """
        try:
            count_int = int(count)
            # 0 = все письма, 1-1000 = конкретное количество
            return 0 <= count_int <= 1000
        except (ValueError, TypeError):
            return False
    
    @staticmethod
    def validate_output_dir(output_dir: str) -> bool:
        """
        Валидация директории для вывода
        
        Args:
            output_dir: Путь к директории
            
        Returns:
            True если директория существует или может быть создана, False иначе
        """
        if not output_dir or not isinstance(output_dir, str):
            return False
        
        try:
            path = Path(output_dir)
            
            # Если директория существует, проверяем права на запись
            if path.exists():
                return path.is_dir() and os.access(path, os.W_OK)
            
            # Если не существует, пробуем создать
            try:
                path.mkdir(parents=True, exist_ok=True)
                return True
            except (OSError, PermissionError):
                return False
                
        except Exception:
            return False
    
    @staticmethod
    def validate_format(format_type: str) -> bool:
        """
        Валидация формата отчета
        
        Args:
            format_type: Формат отчета
            
        Returns:
            True если формат поддерживается, False иначе
        """
        if not format_type or not isinstance(format_type, str):
            return False
        
        return format_type.lower() in Config.SUPPORTED_FORMATS
    
    @staticmethod
    def validate_keywords(keywords: str) -> bool:
        """
        Валидация ключевых слов для поиска
        
        Args:
            keywords: Строка с ключевыми словами
            
        Returns:
            True если ключевые слова корректные, False иначе
        """
        if not keywords or not isinstance(keywords, str):
            return True  # Пустые ключевые слова допустимы
        
        # Проверяем длину и отсутствие опасных символов
        keywords = keywords.strip()
        if len(keywords) > 500:  # Разумное ограничение
            return False
        
        # Запрещаем потенциально опасные символы
        dangerous_chars = ['<', '>', '"', "'", '&', ';', '|', '`']
        return not any(char in keywords for char in dangerous_chars)
    
    @staticmethod
    def validate_sender_filter(sender: str) -> bool:
        """
        Валидация фильтра по отправителю
        
        Args:
            sender: Фильтр отправителя
            
        Returns:
            True если фильтр корректный, False иначе
        """
        if not sender or not isinstance(sender, str):
            return True  # Пустой фильтр допустим
        
        sender = sender.strip()
        
        # Может быть email или часть email
        if '@' in sender:
            return InputValidator.validate_email(sender)
        else:
            # Проверяем, что это разумная строка для поиска
            return len(sender) >= 2 and len(sender) <= 100
    
    @staticmethod
    def validate_language(language: str) -> bool:
        """
        Валидация языка отчета
        
        Args:
            language: Код языка
            
        Returns:
            True если язык поддерживается, False иначе
        """
        if not language or not isinstance(language, str):
            return False
        
        return language.lower() in Config.SUPPORTED_LANGUAGES
    
    @staticmethod
    def validate_attachment_size(size: int) -> bool:
        """
        Валидация размера вложения
        
        Args:
            size: Размер в байтах
            
        Returns:
            True если размер допустимый, False иначе
        """
        try:
            size_int = int(size)
            return 0 <= size_int <= Config.MAX_ATTACHMENT_SIZE
        except (ValueError, TypeError):
            return False
    
    @classmethod
    def validate_command_line_args(cls, args) -> List[str]:
        """
        Комплексная валидация аргументов командной строки
        
        Args:
            args: Объект с аргументами командной строки
            
        Returns:
            Список ошибок валидации (пустой если все корректно)
        """
        errors = []
        
        # Валидация количества (разрешаем большие числа для внутреннего использования)
        if args.count < 0:
            errors.append(f"Некорректное количество писем: {args.count}. Должно быть от 0 до 1000 (0 = все письма).")
        
        # Валидация директории вывода
        if not cls.validate_output_dir(args.output):
            errors.append(f"Некорректная директория вывода: {args.output}")
        
        # Валидация отправителя
        if hasattr(args, 'sender') and args.sender:
            if not cls.validate_sender_filter(args.sender):
                errors.append(f"Некорректный фильтр отправителя: {args.sender}")
        
        # Валидация дат
        if hasattr(args, 'since') and args.since:
            if not cls.validate_date(args.since):
                errors.append(f"Некорректная дата 'since': {args.since}. Используйте формат YYYY-MM-DD.")
        
        if hasattr(args, 'until') and args.until:
            if not cls.validate_date(args.until):
                errors.append(f"Некорректная дата 'until': {args.until}. Используйте формат YYYY-MM-DD.")
        
        # Валидация формата отчета
        if hasattr(args, 'format') and args.format:
            if not cls.validate_format(args.format):
                errors.append(f"Неподдерживаемый формат: {args.format}. Доступные: {Config.SUPPORTED_FORMATS}")
        
        # Валидация ключевых слов
        if hasattr(args, 'keywords') and args.keywords:
            if not cls.validate_keywords(args.keywords):
                errors.append(f"Некорректные ключевые слова: {args.keywords}")
        
        # Валидация языка
        if hasattr(args, 'language') and args.language:
            if not cls.validate_language(args.language):
                errors.append(f"Неподдерживаемый язык: {args.language}. Доступные: {Config.SUPPORTED_LANGUAGES}")
        
        # Проверка логики дат
        if (hasattr(args, 'since') and args.since and 
            hasattr(args, 'until') and args.until and
            cls.validate_date(args.since) and cls.validate_date(args.until)):
            
            since_date = datetime.datetime.strptime(args.since, '%Y-%m-%d')
            until_date = datetime.datetime.strptime(args.until, '%Y-%m-%d')
            
            if since_date > until_date:
                errors.append("Дата 'since' должна быть раньше или равна дате 'until'")
        
        return errors
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """
        Очищает имя файла от опасных символов
        
        Args:
            filename: Исходное имя файла
            
        Returns:
            Безопасное имя файла
        """
        if not filename:
            return "default"
        
        # Убираем опасные символы
        dangerous_chars = ['<', '>', ':', '"', '|', '?', '*', '/', '\\']
        safe_filename = filename
        
        for char in dangerous_chars:
            safe_filename = safe_filename.replace(char, '_')
        
        # Ограничиваем длину
        if len(safe_filename) > 200:
            safe_filename = safe_filename[:200]
        
        return safe_filename.strip()
    
    @staticmethod
    def validate_api_key(api_key: str) -> bool:
        """
        Валидация API ключа
        
        Args:
            api_key: API ключ для проверки
            
        Returns:
            True если ключ выглядит корректно, False иначе
        """
        if not api_key or not isinstance(api_key, str):
            return False
        
        api_key = api_key.strip()
        
        # Базовые проверки
        if len(api_key) < 10:  # Слишком короткий
            return False
        
        if len(api_key) > 500:  # Слишком длинный
            return False
        
        # Не должен содержать пробелы
        if ' ' in api_key:
            return False
        
        return True
