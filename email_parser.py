"""
Модуль для парсинга и обработки электронных писем
Включает улучшенную обработку кодировок и извлечение содержимого
"""
import email
import email.header
import email.utils
import email.message
import logging
from typing import List, Dict, Optional, Union, Any
import charset_normalizer
from config import Config
from decorators import safe_execute, validate_input

try:
    from bs4 import BeautifulSoup
    HAS_BEAUTIFULSOUP = True
except ImportError:
    HAS_BEAUTIFULSOUP = False
    logging.warning("BeautifulSoup4 не установлен. HTML будет обрабатываться базовым способом.")

logger = logging.getLogger(__name__)


class EmailParser:
    """Класс для парсинга электронных писем с улучшенной обработкой кодировок"""
    
    def __init__(self):
        self.supported_encodings = ['utf-8', 'cp1251', 'koi8-r', 'iso-8859-1', 'windows-1252']
    
    @safe_execute(default_return="", log_errors=True)
    def decode_header(self, header_value: Union[str, bytes, None]) -> str:
        """
        Декодирует заголовок письма с улучшенной обработкой кодировок

        Args:
            header_value: Значение заголовка для декодирования

        Returns:
            Декодированная строка
        """
        if not header_value:
            return ""

        # Если это уже строка, проверяем на закодированные заголовки
        if isinstance(header_value, str):
            # Проверяем, есть ли закодированные части в строке
            if '=?' in header_value and '?=' in header_value:
                try:
                    # Декодируем закодированные заголовки
                    decoded_parts = email.header.decode_header(header_value)
                    decoded_string = ""

                    for part, encoding in decoded_parts:
                        if isinstance(part, bytes):
                            if encoding:
                                try:
                                    decoded_string += part.decode(encoding)
                                except (UnicodeDecodeError, LookupError):
                                    decoded_string += self._decode_with_charset_normalizer(part)
                            else:
                                decoded_string += self._decode_with_fallback(part)
                        else:
                            decoded_string += str(part)

                    return decoded_string.strip()
                except Exception as e:
                    logger.debug(f"Ошибка декодирования строкового заголовка: {e}")
                    return header_value
            else:
                return header_value

        try:
            # Стандартное декодирование заголовка для bytes
            decoded_parts = email.header.decode_header(header_value)
            decoded_string = ""

            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    if encoding:
                        try:
                            decoded_string += part.decode(encoding)
                        except (UnicodeDecodeError, LookupError):
                            # Если указанная кодировка не работает, пробуем автоопределение
                            decoded_string += self._decode_with_charset_normalizer(part)
                    else:
                        # Пробуем стандартные кодировки
                        decoded_string += self._decode_with_fallback(part)
                else:
                    decoded_string += str(part)

            return decoded_string.strip()

        except Exception as e:
            logger.warning(f"Ошибка декодирования заголовка: {e}")
            # Последняя попытка с charset_normalizer
            if isinstance(header_value, bytes):
                return self._decode_with_charset_normalizer(header_value)
            return str(header_value)
    
    def _decode_with_charset_normalizer(self, data: bytes) -> str:
        """
        Декодирование с использованием charset_normalizer для автоопределения кодировки
        """
        try:
            result = charset_normalizer.from_bytes(data)
            if result:
                return str(result.best())
        except Exception as e:
            logger.debug(f"Ошибка charset_normalizer: {e}")
        
        # Fallback к UTF-8 с игнорированием ошибок
        return data.decode('utf-8', errors='ignore')
    
    def _decode_with_fallback(self, data: bytes) -> str:
        """
        Декодирование с перебором популярных кодировок
        """
        for encoding in self.supported_encodings:
            try:
                return data.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        
        # Если ничего не сработало, используем charset_normalizer
        return self._decode_with_charset_normalizer(data)
    
    def extract_body(self, email_message: Any) -> str:
        """
        Извлекает тело письма с улучшенной обработкой HTML и выбором лучшего контента

        Args:
            email_message: Объект письма

        Returns:
            Текст тела письма
        """
        try:
            if email_message.is_multipart():
                return self._extract_multipart_body(email_message)
            else:
                # Простое письмо без multipart
                content_type = email_message.get_content_type()
                body = self._extract_part_content(email_message)

                if content_type == "text/html":
                    body = self._clean_html(body)

                return body.strip()

        except Exception as e:
            logger.error(f"Ошибка извлечения тела письма: {e}")
            return "Ошибка извлечения содержимого письма"

    def _extract_multipart_body(self, email_message: Any) -> str:
        """
        Извлекает тело из multipart письма с интеллектуальным выбором контента
        """
        plain_parts = []
        html_parts = []

        # Собираем все текстовые части
        for part in email_message.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            # Пропускаем вложения
            if "attachment" in content_disposition:
                continue

            if content_type == "text/plain":
                part_body = self._extract_part_content(part)
                if part_body.strip():
                    plain_parts.append(part_body)
            elif content_type == "text/html":
                part_body = self._extract_part_content(part)
                if part_body.strip():
                    html_parts.append(part_body)

        # Объединяем части
        plain_text = "\n".join(plain_parts).strip()
        html_text = ""

        # Обрабатываем HTML части
        if html_parts:
            combined_html = "\n".join(html_parts)
            html_text = self._clean_html(combined_html).strip()

        # Выбираем лучший контент
        best_content = self._choose_best_content(plain_text, html_text)

        # Если ничего не получилось, возвращаем специальное сообщение
        if not best_content:
            if html_parts:
                return "Письмо содержит только HTML без извлекаемого текста. Возможно, содержит только изображения или стили."
            else:
                return ""

        return best_content
    
    def _extract_part_content(self, part: Any) -> str:
        """
        Извлекает содержимое части письма с обработкой кодировок
        """
        try:
            # Получаем raw данные
            payload = part.get_payload(decode=True)
            if not payload:
                return ""
            
            # Определяем кодировку из заголовков
            charset = part.get_content_charset()
            
            if charset:
                try:
                    return payload.decode(charset)
                except (UnicodeDecodeError, LookupError):
                    logger.debug(f"Не удалось декодировать с кодировкой {charset}")
            
            # Если кодировка не указана или не работает, используем автоопределение
            return self._decode_with_charset_normalizer(payload)
            
        except Exception as e:
            logger.warning(f"Ошибка извлечения содержимого части: {e}")
            # Fallback к строковому представлению
            return str(part.get_payload())
    
    def _clean_html(self, html_content: str) -> str:
        """
        Очищает HTML контент от тегов и извлекает текст с использованием BeautifulSoup
        """
        if not html_content:
            return ""

        if HAS_BEAUTIFULSOUP:
            return self._clean_html_with_beautifulsoup(html_content)
        else:
            return self._clean_html_with_regex(html_content)

    def _clean_html_with_beautifulsoup(self, html_content: str) -> str:
        """
        Очищает HTML с помощью BeautifulSoup - более качественный парсинг
        """
        try:
            if not html_content or not html_content.strip():
                return ""

            soup = BeautifulSoup(html_content, "html.parser")

            # Проверяем, что soup создался корректно
            if soup is None:
                logger.warning("BeautifulSoup не смог распарсить HTML")
                return self._clean_html_with_regex(html_content)

            # Удаляем скрипты, стили и другие нежелательные элементы
            for element in soup(["script", "style", "meta", "link", "head"]):
                if element is not None:
                    element.decompose()

            # Извлекаем alt текст из изображений
            for img in soup.find_all("img"):
                if img is not None:
                    alt_text = img.get("alt", "").strip() if img.get("alt") else ""
                    if alt_text:
                        # Заменяем изображение на его alt текст
                        img.replace_with(f"[Изображение: {alt_text}]")
                    else:
                        img.decompose()

            # Извлекаем текст с разделителями
            try:
                text = soup.get_text(separator=' ', strip=True)
            except Exception as e:
                logger.warning(f"Ошибка извлечения текста из soup: {e}")
                text = str(soup) if soup else ""

            # Дополнительная очистка
            import re
            if text:
                # Убираем множественные пробелы
                text = re.sub(r'\s+', ' ', text)
                # Убираем лишние символы
                text = re.sub(r'[\r\n\t]+', ' ', text)

            result = text.strip() if text else ""

            # Проверяем, что получили осмысленный текст
            if len(result) < 10 or not re.search(r'[а-яёa-z0-9]', result, re.IGNORECASE):
                return ""

            return result

        except Exception as e:
            logger.warning(f"Ошибка парсинга HTML с BeautifulSoup: {e}")
            return self._clean_html_with_regex(html_content)

    def _clean_html_with_regex(self, html_content: str) -> str:
        """
        Fallback метод очистки HTML с помощью регулярных выражений
        """
        import re

        # Удаляем скрипты и стили
        clean_text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        clean_text = re.sub(r'<style[^>]*>.*?</style>', '', clean_text, flags=re.DOTALL | re.IGNORECASE)

        # Заменяем некоторые HTML элементы на переносы строк
        clean_text = re.sub(r'<br[^>]*>', '\n', clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r'</p>', '\n', clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r'</div>', '\n', clean_text, flags=re.IGNORECASE)

        # Удаляем все остальные HTML теги
        clean_text = re.sub(r'<[^>]+>', '', clean_text)

        # Декодируем HTML сущности
        import html
        clean_text = html.unescape(clean_text)

        # Убираем лишние пробелы и переносы
        clean_text = re.sub(r'\n\s*\n', '\n', clean_text)  # Множественные переносы
        clean_text = re.sub(r'[ \t]+', ' ', clean_text)    # Множественные пробелы
        clean_text = re.sub(r'^\s+|\s+$', '', clean_text, flags=re.MULTILINE)  # Пробелы в начале/конце строк

        result = clean_text.strip()

        # Если после очистки остался только мусор или очень мало текста, возвращаем пустую строку
        if len(result) < 10 or not re.search(r'[а-яёa-z]', result, re.IGNORECASE):
            return ""

        return result

    def _choose_best_content(self, plain_text: str, html_text: str) -> str:
        """
        Выбирает лучший контент между text/plain и text/html

        Args:
            plain_text: Текст из text/plain части
            html_text: Текст из text/html части (уже очищенный от HTML)

        Returns:
            Лучший текст для анализа
        """
        # Очищаем и нормализуем тексты
        plain_clean = plain_text.strip() if plain_text else ""
        html_clean = html_text.strip() if html_text else ""

        # Если есть только один вариант, возвращаем его
        if not plain_clean and not html_clean:
            return ""
        if not plain_clean:
            return html_clean
        if not html_clean:
            return plain_clean

        # Сравниваем по длине
        plain_len = len(plain_clean)
        html_len = len(html_clean)

        # Если HTML значительно длиннее (более чем в 1.5 раза), выбираем его
        if html_len > plain_len * 1.5:
            logger.debug(f"Выбран HTML контент (длина: {html_len} vs {plain_len})")
            return html_clean

        # Если plain text значительно длиннее, выбираем его
        if plain_len > html_len * 1.5:
            logger.debug(f"Выбран plain контент (длина: {plain_len} vs {html_len})")
            return plain_clean

        # Если длины примерно равны, проверяем на наличие ключевых слов
        import re

        # Подсчитываем количество слов
        plain_words = len(re.findall(r'\b\w+\b', plain_clean))
        html_words = len(re.findall(r'\b\w+\b', html_clean))

        # Выбираем тот, где больше слов
        if html_words > plain_words:
            logger.debug(f"Выбран HTML контент (слов: {html_words} vs {plain_words})")
            return html_clean
        else:
            logger.debug(f"Выбран plain контент (слов: {plain_words} vs {html_words})")
            return plain_clean
    
    @validate_input(
        lambda self, email_message: hasattr(email_message, 'walk') or hasattr(email_message, 'is_multipart'),
        "Неверный объект email сообщения"
    )
    def extract_attachments(self, email_message: Any) -> List[Dict[str, Union[str, int]]]:
        """
        Извлекает информацию о вложениях с проверкой размеров
        
        Args:
            email_message: Объект письма
            
        Returns:
            Список словарей с информацией о вложениях
        """
        attachments = []
        
        try:
            if email_message.is_multipart():
                for part in email_message.walk():
                    content_disposition = str(part.get("Content-Disposition", ""))
                    
                    if "attachment" in content_disposition:
                        filename = part.get_filename()
                        if filename:
                            # Декодируем имя файла
                            decoded_filename = self.decode_header(filename)
                            
                            # Получаем размер вложения
                            payload = part.get_payload(decode=True)
                            size = len(payload) if payload else 0
                            
                            # Проверяем размер вложения
                            if size > Config.MAX_ATTACHMENT_SIZE:
                                logger.warning(
                                    f"Вложение {decoded_filename} слишком большое "
                                    f"({size} байт), максимум {Config.MAX_ATTACHMENT_SIZE}"
                                )
                                continue
                            
                            attachments.append({
                                'filename': decoded_filename,
                                'size': size,
                                'content_type': part.get_content_type()
                            })
        
        except Exception as e:
            logger.error(f"Ошибка извлечения вложений: {e}")
        
        return attachments
    
    def get_email_metadata(self, email_message: Any) -> Dict[str, str]:
        """
        Извлекает метаданные письма
        
        Args:
            email_message: Объект письма
            
        Returns:
            Словарь с метаданными
        """
        try:
            # Извлекаем основные заголовки
            subject = self.decode_header(email_message.get('Subject', 'Без темы'))
            sender = self.decode_header(email_message.get('From', 'Неизвестный отправитель'))
            recipient = self.decode_header(email_message.get('To', ''))
            date_str = email_message.get('Date', '')
            message_id = email_message.get('Message-ID', '')
            
            # Парсим дату
            try:
                date_parsed = email.utils.parsedate_to_datetime(date_str)
                date_formatted = date_parsed.strftime('%Y-%m-%d %H:%M:%S')
            except:
                import datetime
                date_formatted = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            return {
                'subject': subject,
                'sender': sender,
                'recipient': recipient,
                'date': date_formatted,
                'message_id': message_id
            }
            
        except Exception as e:
            logger.error(f"Ошибка извлечения метаданных: {e}")
            return {
                'subject': 'Ошибка извлечения темы',
                'sender': 'Ошибка извлечения отправителя',
                'recipient': '',
                'date': '',
                'message_id': ''
            }
