"""
Декораторы для обработки ошибок и повторных попыток
"""
import time
import logging
import functools
from typing import Callable, Any, Type, Tuple, Optional
import imaplib
import socket
from googleapiclient.errors import HttpError
from config import Config

logger = logging.getLogger(__name__)


def retry(
    max_attempts: Optional[int] = None,
    delay: Optional[float] = None,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    backoff_factor: float = 1.0,
    max_delay: float = 60.0
):
    """
    Декоратор для автоматического выполнения повторных попыток при ошибках
    
    Args:
        max_attempts: Максимальное количество попыток (по умолчанию из Config)
        delay: Задержка между попытками в секундах (по умолчанию из Config)
        exceptions: Кортеж исключений, при которых выполняются повторные попытки
        backoff_factor: Коэффициент увеличения задержки с каждой попыткой
        max_delay: Максимальная задержка между попытками
    """
    if max_attempts is None:
        max_attempts = Config.MAX_RETRIES
    if delay is None:
        delay = Config.RETRY_DELAY
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt < max_attempts - 1:
                        logger.warning(
                            f"Ошибка в {func.__name__} (попытка {attempt + 1}/{max_attempts}): "
                            f"{type(e).__name__}: {str(e)}"
                        )
                        
                        # Логируем детали для определенных типов ошибок
                        if isinstance(e, HttpError):
                            logger.warning(f"HTTP статус: {e.resp.status}")
                        elif isinstance(e, (imaplib.IMAP4.error, socket.error)):
                            logger.warning(f"Сетевая ошибка: {type(e).__name__}")
                        
                        time.sleep(current_delay)
                        current_delay = min(current_delay * backoff_factor, max_delay)
                    else:
                        logger.error(
                            f"Не удалось выполнить {func.__name__} после {max_attempts} попыток. "
                            f"Последняя ошибка: {type(e).__name__}: {str(e)}"
                        )
            
            # Если все попытки исчерпаны, поднимаем последнее исключение
            if last_exception:
                raise last_exception
            
            return None
        
        return wrapper
    return decorator


def api_retry(func: Callable) -> Callable:
    """
    Специализированный декоратор для API вызовов (Gmail, Gemini)
    """
    return retry(
        exceptions=(HttpError, ConnectionError, TimeoutError),
        backoff_factor=2.0
    )(func)


def imap_retry(func: Callable) -> Callable:
    """
    Специализированный декоратор для IMAP операций
    """
    return retry(
        exceptions=(imaplib.IMAP4.error, socket.error, ConnectionError),
        backoff_factor=1.5
    )(func)


def safe_execute(default_return=None, log_errors=True):
    """
    Декоратор для безопасного выполнения функций с возвратом значения по умолчанию при ошибке
    
    Args:
        default_return: Значение, возвращаемое при ошибке
        log_errors: Логировать ли ошибки
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if log_errors:
                    logger.error(
                        f"Ошибка в {func.__name__}: {type(e).__name__}: {str(e)}"
                    )
                return default_return
        
        return wrapper
    return decorator


def validate_input(validation_func: Callable[[Any], bool], error_message: str = "Неверные входные данные"):
    """
    Декоратор для валидации входных параметров
    
    Args:
        validation_func: Функция валидации, принимающая аргументы и возвращающая bool
        error_message: Сообщение об ошибке при неудачной валидации
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            if not validation_func(*args, **kwargs):
                logger.error(f"Валидация не пройдена для {func.__name__}: {error_message}")
                raise ValueError(error_message)
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def log_execution_time(func: Callable) -> Callable:
    """
    Декоратор для логирования времени выполнения функции
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            logger.debug(f"{func.__name__} выполнена за {execution_time:.2f} сек")
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            logger.debug(f"{func.__name__} завершена с ошибкой за {execution_time:.2f} сек")
            raise
    
    return wrapper


def rate_limit(calls_per_second: float = 1.0):
    """
    Декоратор для ограничения скорости вызовов функции
    
    Args:
        calls_per_second: Максимальное количество вызовов в секунду
    """
    min_interval = 1.0 / calls_per_second
    last_called = [0.0]
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            elapsed = time.time() - last_called[0]
            left_to_wait = min_interval - elapsed
            
            if left_to_wait > 0:
                time.sleep(left_to_wait)
            
            last_called[0] = time.time()
            return func(*args, **kwargs)
        
        return wrapper
    return decorator
