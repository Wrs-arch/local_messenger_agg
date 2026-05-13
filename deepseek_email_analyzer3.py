import os
import base64
import sys
import codecs
import datetime
import argparse
import json
import time
import logging
import imaplib
import email
import email.header
import email.utils
import re
import socket
from typing import List, Dict, Optional
import google.generativeai as genai
from dotenv import load_dotenv
from decouple import config as decouple_config
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Загрузка переменных окружения
load_dotenv()

# Импорт конфигурации и модулей
from config import Config
from decorators import retry, api_retry, imap_retry, safe_execute, log_execution_time
from email_parser import EmailParser
from report_generator import ReportGenerator
from validators import InputValidator, ValidationError

# Устанавливаем глобальный тайм-аут для сокетов
socket.setdefaulttimeout(Config.SOCKET_TIMEOUT)

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL.upper()),
    format=Config.LOG_FORMAT,
    handlers=[
        logging.FileHandler(Config.LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Принудительная UTF-8 кодировка для вывода
if sys.stdout.encoding != 'utf-8':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())



class MailRuClient:
    """Клиент для работы с Mail.ru через IMAP с поддержкой контекстного менеджера"""
    def __init__(self, username: str, password: str):
        # Валидация входных данных
        if not username or not password:
            raise ValueError("Username и password обязательны")

        # Простая валидация email
        if not InputValidator.validate_email(username):
            raise ValueError(f"Некорректный email: {username}")

        self.username = username
        self.password = password
        mailru_config = Config.IMAP_SERVERS['mailru']
        self.imap_server = mailru_config['server']
        self.imap_port = mailru_config['port']
        self.connection = None
        self.email_parser = EmailParser()

    def __enter__(self):
        """Вход в контекстный менеджер - устанавливаем соединение"""
        if self.connect():
            return self
        else:
            raise ConnectionError("Не удалось подключиться к IMAP серверу")

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Выход из контекстного менеджера - закрываем соединение"""
        self.disconnect()
        return False  # Не подавляем исключения

    @imap_retry
    def connect(self) -> bool:
        """Подключается к IMAP серверу Mail.ru"""
        try:
            self.connection = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            self.connection.login(self.username, self.password)
            logger.info("Успешное подключение к Mail.ru IMAP")
            return True
        except (imaplib.IMAP4.error, socket.error) as e:
            logger.error(f"Ошибка подключения к Mail.ru IMAP: {type(e).__name__}")
            return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка подключения: {type(e).__name__}")
            return False

    def disconnect(self):
        """Отключается от IMAP сервера"""
        if self.connection:
            try:
                self.connection.close()
                self.connection.logout()
            except:
                pass
            self.connection = None

    def get_emails(self, count: int = 10, folder: str = 'INBOX',
                   sender: Optional[str] = None, since: Optional[str] = None,
                   until: Optional[str] = None, unread: bool = False) -> List[Dict]:
        """Получает список писем через IMAP с поддержкой фильтров"""
        # Валидация параметров
        if count <= 0:
            raise ValueError("Количество писем должно быть больше 0")

        connection_created = False
        if not self.connection:
            if not self.connect():
                return []
            connection_created = True

        try:
            self.connection.select(folder)

            # Строим поисковый запрос IMAP
            search_criteria = []

            if sender:
                # Фильтрация по отправителю (поддерживает частичное совпадение)
                search_criteria.append(f'FROM "{sender}"')

            if unread:
                search_criteria.append('UNSEEN')

            if since:
                # Конвертируем дату в формат IMAP (DD-Mon-YYYY)
                try:
                    since_date = datetime.datetime.strptime(since, '%Y-%m-%d')
                    since_imap = since_date.strftime('%d-%b-%Y')
                    search_criteria.append(f'SINCE {since_imap}')
                except ValueError:
                    logger.warning(f"Неверный формат даты 'since': {since}")

            if until:
                # Конвертируем дату в формат IMAP (DD-Mon-YYYY)
                try:
                    until_date = datetime.datetime.strptime(until, '%Y-%m-%d')
                    until_imap = until_date.strftime('%d-%b-%Y')
                    search_criteria.append(f'BEFORE {until_imap}')
                except ValueError:
                    logger.warning(f"Неверный формат даты 'until': {until}")

            # Если нет критериев поиска, ищем все письма
            if not search_criteria:
                search_criteria.append('ALL')

            search_query = ' '.join(search_criteria)
            logger.info(f"IMAP поисковый запрос: {search_query}")

            status, messages = self.connection.search(None, search_query)
            if status != 'OK':
                logger.error(f"Ошибка поиска писем: {status}")
                return []

            message_ids = messages[0].split()
            logger.info(f"Найдено {len(message_ids)} писем по критериям поиска")

            # Берем последние count писем
            message_ids = message_ids[-count:] if len(message_ids) > count else message_ids
            message_ids.reverse()  # Сначала новые

            emails = []
            for msg_id in message_ids:
                email_data = self._get_email_data(msg_id.decode())
                if email_data:
                    emails.append(email_data)

            return emails

        except (imaplib.IMAP4.error, socket.error) as e:
            logger.error(f"Ошибка IMAP при получении писем: {type(e).__name__}")
            if connection_created:
                self.disconnect()
            return []
        except Exception as e:
            logger.error(f"Неожиданная ошибка получения писем: {type(e).__name__}")
            if connection_created:
                self.disconnect()
            return []

    def _get_email_data(self, msg_id: str) -> Optional[Dict]:
        """Получает данные письма по ID"""
        try:
            # Получаем флаги письма для определения статуса прочтения
            status, flag_data = self.connection.fetch(msg_id, '(FLAGS)')
            flags = flag_data[0] if flag_data else b''
            is_read = b'\\Seen' in flags

            # Получаем содержимое письма
            status, msg_data = self.connection.fetch(msg_id, '(RFC822)')
            if status != 'OK':
                return None

            raw_email = msg_data[0][1]

            # Проверяем размер письма
            if len(raw_email) > Config.MAX_EMAIL_SIZE:
                logger.warning(f"Письмо {msg_id} слишком большое ({len(raw_email)} байт), пропускаем")
                return None

            email_message = email.message_from_bytes(raw_email)

            # Используем EmailParser для извлечения метаданных
            metadata = self.email_parser.get_email_metadata(email_message)

            # Извлечение тела письма
            body = self.email_parser.extract_body(email_message)

            # Извлечение вложений
            attachments_info = self.email_parser.extract_attachments(email_message)
            attachments = [att['filename'] for att in attachments_info]

            return {
                'id': msg_id,
                'subject': metadata['subject'],
                'sender': metadata['sender'],
                'date': metadata['date'],
                'body': body,
                'attachments': attachments,
                'is_read': is_read
            }

        except (imaplib.IMAP4.error, UnicodeDecodeError) as e:
            logger.error(f"Ошибка обработки письма {msg_id}: {type(e).__name__}")
            return None
        except Exception as e:
            logger.error(f"Неожиданная ошибка при обработке письма {msg_id}: {type(e).__name__}")
            return None



    def get_email_details(self, msg_id: str) -> Optional[Dict]:
        """Получает детали письма (для совместимости с API)"""
        return self._get_email_data(msg_id)

class EmailAnalyzer:
    """Анализатор писем с использованием Gemini AI"""
    def __init__(self, api_key: str, model_name: str = "gemini-pro"):
        # Валидация API ключа
        if not InputValidator.validate_api_key(api_key):
            raise ValidationError("Некорректный API ключ Gemini")

        self.api_key = api_key
        self.model_name = model_name
        self.gmail_service = None
        self.mailru_client = None
        self.report_generator = ReportGenerator()
        self.stats = {
            'processed': 0,
            'errors': 0,
            'categories': {},
            'start_time': time.time(),
            'sources': {'gmail': 0, 'mailru': 0}
        }

    def setup_mailru(self, username: str, password: str):
        """Настройка клиента Mail.ru"""
        try:
            self.mailru_client = MailRuClient(username, password)
            return self.mailru_client.connect()
        except (ValueError, ValidationError) as e:
            logger.error(f"Ошибка настройки Mail.ru клиента: {e}")
            return False

    def get_gmail_service(self):
        """Аутентификация в Gmail API"""
        creds = None
        if os.path.exists("token.json"):
            creds = Credentials.from_authorized_user_file("token.json", Config.SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    logger.error(f"Ошибка обновления токена: {e}")
                    creds = None

            if not creds:
                if not os.path.exists(Config.CLIENT_SECRETS_FILE):
                    logger.error(f"Файл {Config.CLIENT_SECRETS_FILE} не найден!")
                    return None

                flow = InstalledAppFlow.from_client_secrets_file(Config.CLIENT_SECRETS_FILE, Config.SCOPES)
                creds = flow.run_local_server(port=0)

            with open("token.json", "w") as token:
                token.write(creds.to_json())

        try:
            self.gmail_service = build("gmail", "v1", credentials=creds)
            logger.info("Успешное подключение к Gmail API")
            return self.gmail_service
        except HttpError as error:
            logger.error(f"Ошибка создания сервиса Gmail: {error}")
            return None

    def get_latest_emails(self, count: int, sender: Optional[str] = None, 
                         since: Optional[str] = None, until: Optional[str] = None,
                         unread: bool = False) -> List[Dict]:
        """Получение писем из Gmail"""
        query_parts = []
        if sender:
            query_parts.append(f"from:({sender})")
        if since:
            query_parts.append(f"after:{since}")
        if until:
            query_parts.append(f"before:{until}")
        if unread:
            query_parts.append("is:unread")
        
        query = ' '.join(query_parts)
        
        try:
            results = self.gmail_service.users().messages().list(
                userId="me", 
                maxResults=count, 
                q=query
            ).execute()
            messages = results.get("messages", [])
            logger.info(f"Найдено {len(messages)} писем в Gmail")
            return messages
        except HttpError as error:
            logger.error(f"Ошибка получения писем из Gmail: {error}")
            return []

    def get_mailru_emails(self, count: int, sender: Optional[str] = None,
                         since: Optional[str] = None, until: Optional[str] = None,
                         unread: bool = False) -> List[Dict]:
        """Получение писем из Mail.ru с поддержкой фильтров"""
        if not self.mailru_client:
            logger.error("Клиент Mail.ru не настроен")
            return []

        emails = self.mailru_client.get_emails(count, sender=sender, since=since, until=until, unread=unread)
        self.stats['sources']['mailru'] = len(emails)
        return emails

    def get_email_details(self, msg_id: str, source: str = 'gmail') -> Optional[Dict]:
        """Получение деталей письма"""
        if source == 'gmail':
            for attempt in range(Config.MAX_RETRIES):
                try:
                    message = self.gmail_service.users().messages().get(
                        userId="me",
                        id=msg_id,
                        format='full'
                    ).execute()

                    payload = message.get('payload', {})
                    headers = payload.get('headers', [])

                    details = {
                        "id": msg_id,
                        "subject": next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'Без темы'),
                        "sender": next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Неизвестный отправитель'),
                        "date": datetime.datetime.fromtimestamp(int(message.get('internalDate', 0)) / 1000).strftime('%Y-%m-%d %H:%M:%S'),
                        "body": "",
                        "attachments": [],
                        "is_read": 'UNREAD' not in message.get('labelIds', [])
                    }

                    self._extract_content(payload, details)

                    # Используем EmailParser для выбора лучшего контента
                    email_parser = EmailParser()
                    plain_text = "\n".join(details.get('plain_parts', [])).strip()
                    html_text = ""

                    if 'html_parts' in details:
                        combined_html = "\n".join(details['html_parts'])
                        html_text = email_parser._clean_html(combined_html).strip()

                    # Выбираем лучший контент
                    best_content = email_parser._choose_best_content(plain_text, html_text)

                    # Если ничего не получилось, создаем специальное сообщение
                    if not best_content:
                        if 'html_parts' in details:
                            best_content = "Письмо содержит только HTML без извлекаемого текста. Возможно, содержит только изображения или стили."
                        else:
                            best_content = ""

                    details['body'] = best_content

                    if len(details['body']) > Config.MAX_EMAIL_LENGTH:
                        details['body'] = details['body'][:Config.MAX_EMAIL_LENGTH] + "... [текст обрезан]"

                    details['body'] = details['body'].strip()

                    # Очищаем временные данные
                    details.pop('plain_parts', None)
                    details.pop('html_parts', None)

                    return details

                except HttpError as error:
                    if attempt < Config.MAX_RETRIES - 1:
                        logger.warning(f"Ошибка получения деталей письма (попытка {attempt + 1}): {error}")
                        time.sleep(Config.RETRY_DELAY)
                    else:
                        logger.error(f"Не удалось получить детали письма после {Config.MAX_RETRIES} попыток: {error}")
                        return None
        
        elif source == 'mailru':
            details = self.mailru_client.get_email_details(msg_id)
            if details:
                return details
        
        return None

    def _extract_content(self, part: Dict, details: Dict):
        """Извлечение содержимого письма (для Gmail) с улучшенной обработкой HTML"""
        if 'parts' in part:
            for subpart in part['parts']:
                self._extract_content(subpart, details)

        filename = part.get('filename')
        if filename:
            details['attachments'].append(filename)

        mime_type = part.get('mimeType', '')
        if mime_type in ['text/plain', 'text/html'] and 'data' in part.get('body', {}):
            try:
                data = part['body']['data']
                decoded_text = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

                # Сохраняем отдельно plain и html контент для последующего выбора
                if mime_type == 'text/plain':
                    if 'plain_parts' not in details:
                        details['plain_parts'] = []
                    details['plain_parts'].append(decoded_text)
                elif mime_type == 'text/html':
                    if 'html_parts' not in details:
                        details['html_parts'] = []
                    details['html_parts'].append(decoded_text)

            except Exception as e:
                logger.warning(f"Ошибка декодирования текста: {e}")

    @api_retry
    @log_execution_time
    def analyze_email_with_gemini(self, text: str, attachments: List[str]) -> Dict:
        """Анализ письма с помощью Gemini AI"""
        if not text.strip() and not attachments:
            return {
                "summary": "Пустое письмо без содержимого.",
                "category": "Прочее",
                "entities": [],
                "priority": "Низкий"
            }

        # Проверяем специальные случаи
        if "только HTML без извлекаемого текста" in text:
            return {
                "summary": "Письмо содержит только HTML-контент без текста. Возможно, состоит из изображений, стилей или интерактивных элементов.",
                "category": "Прочее",
                "entities": [],
                "priority": "Низкий"
            }

        # Проверяем, не является ли письмо только техническим мусором
        if len(text.strip()) < 50:
            # Проверяем на наличие только технических элементов
            tech_keywords = ['html', 'css', 'style', 'script', 'div', 'span', 'class=', 'id=']
            text_lower = text.lower()
            tech_count = sum(1 for keyword in tech_keywords if keyword in text_lower)

            if tech_count > 2:  # Если много технических элементов
                return {
                    "summary": "Письмо содержит только техническую HTML-разметку без содержательного текста",
                    "category": "Прочее",
                    "entities": [],
                    "priority": "Низкий"
                }

        for attempt in range(Config.MAX_RETRIES):
            try:
                genai.configure(api_key=self.api_key)
                model = genai.GenerativeModel(self.model_name)

                attachment_info = f"Вложения: {', '.join(attachments)}.\n" if attachments else ""

                # Получаем базовый шаблон и подставляем данные
                base_template = Config.GEMINI_PROMPT_TEMPLATE
                prompt = base_template.format(
                    categories=str(Config.EMAIL_CATEGORIES),
                    priorities=str(Config.PRIORITY_LEVELS),
                    attachment_info=attachment_info,
                    text=text[:5000]
                )

                response = model.generate_content(prompt)

                # Проверяем, есть ли валидный ответ
                if not response.candidates or not response.candidates[0].content.parts:
                    # Проверяем причину блокировки
                    if response.candidates and response.candidates[0].finish_reason:
                        finish_reason = response.candidates[0].finish_reason
                        if finish_reason == 8:  # SAFETY
                            logger.warning("Gemini заблокировал ответ из-за политики безопасности")
                            return {
                                "summary": "Письмо заблокировано системой безопасности ИИ",
                                "category": "Прочее",
                                "entities": [],
                                "priority": "Низкий"
                            }
                        else:
                            logger.warning(f"Gemini завершил работу с кодом: {finish_reason}")

                    # Если нет валидного ответа, пропускаем попытку
                    if attempt < Config.MAX_RETRIES - 1:
                        logger.warning(f"Пустой ответ от Gemini (попытка {attempt + 1})")
                        time.sleep(Config.RETRY_DELAY)
                        continue
                    else:
                        return {
                            "summary": "Не удалось получить ответ от ИИ",
                            "category": "Ошибка",
                            "entities": [],
                            "priority": "Низкий"
                        }

                raw_response = response.text
                logger.debug(f"Сырой ответ Gemini: '{raw_response}'")
                logger.debug(f"Сырой ответ Gemini: '{raw_response}'")

                cleaned_response = raw_response.strip()

                # Более агрессивная очистка ответа
                cleaned_response = cleaned_response.replace('```json', '').replace('```', '').strip()

                # Удаляем лишние символы в начале и конце
                cleaned_response = cleaned_response.strip('\n\r\t ')

                # Если ответ не начинается с {, пытаемся найти JSON
                if not cleaned_response.startswith('{'):
                    # Ищем первую открывающую скобку
                    start_idx = cleaned_response.find('{')
                    if start_idx != -1:
                        cleaned_response = cleaned_response[start_idx:]
                        logger.debug(f"Найден JSON начиная с позиции {start_idx}")

                # Если ответ не заканчивается на }, пытаемся найти конец JSON
                if not cleaned_response.endswith('}'):
                    # Ищем последнюю закрывающую скобку
                    end_idx = cleaned_response.rfind('}')
                    if end_idx != -1:
                        cleaned_response = cleaned_response[:end_idx + 1]
                        logger.debug(f"Обрезан JSON до позиции {end_idx}")

                logger.debug(f"Финальный очищенный ответ: '{cleaned_response}'")

                result = json.loads(cleaned_response)

                required_keys = ['category', 'priority', 'summary', 'entities']
                for key in required_keys:
                    if key not in result:
                        result[key] = "Не определено" if key != 'entities' else []

                logger.debug(f"Успешно распарсили JSON: {result}")
                return result

            except json.JSONDecodeError as e:
                if attempt < Config.MAX_RETRIES - 1:
                    logger.warning(f"Ошибка парсинга JSON (попытка {attempt + 1}): {e}")
                    logger.warning(f"Проблемный ответ: {cleaned_response[:500]}...")
                    time.sleep(Config.RETRY_DELAY)
                else:
                    logger.error(f"Не удалось распарсить JSON после {Config.MAX_RETRIES} попыток: {e}")
                    logger.error(f"Финальный ответ: {cleaned_response}")
                    return {
                        "summary": f"Ошибка парсинга JSON: {str(e)}",
                        "category": "Ошибка",
                        "entities": [],
                        "priority": "Низкий"
                    }
            except Exception as e:
                if attempt < Config.MAX_RETRIES - 1:
                    logger.warning(f"Ошибка анализа письма (попытка {attempt + 1}): {e}")
                    time.sleep(Config.RETRY_DELAY)
                else:
                    logger.error(f"Не удалось проанализировать письмо: {e}")
                    return {
                        "summary": f"Ошибка анализа: {str(e)}",
                        "category": "Ошибка",
                        "entities": [],
                        "priority": "Низкий"
                    }

        return {}

    def generate_report(self, results: List[Dict], output_filename: str, filters: Dict, format_type: str = "markdown"):
        """Генерация отчета в указанном формате"""
        # Подготавливаем статистику
        stats = self.stats.copy()
        stats['total_time'] = time.time() - self.stats['start_time']

        # Генерируем отчет
        success = self.report_generator.generate_report(
            results=results,
            output_filename=output_filename,
            format_type=format_type,
            filters=filters,
            stats=stats
        )

        if not success:
            logger.error(f"Не удалось создать отчет: {output_filename}")

        return success

    def run(self, count: int, source: str = 'gmail', sender: Optional[str] = None,
            since: Optional[str] = None, until: Optional[str] = None,
            unread: bool = False, output_dir: str = ".", format_type: str = "markdown",
            keywords: Optional[str] = None):
        """Основной метод запуска анализа"""
        if not self.api_key:
            logger.error("GEMINI_API_KEY не найден в переменных окружения!")
            return False

        # Валидация входных параметров (разрешаем большие числа для "все письма")
        if count < 0:
            logger.error(f"Некорректное количество писем: {count}")
            return False

        if not InputValidator.validate_output_dir(output_dir):
            logger.error(f"Некорректная директория вывода: {output_dir}")
            return False

        if not InputValidator.validate_format(format_type):
            logger.error(f"Неподдерживаемый формат: {format_type}")
            return False
            
        emails = []
        
        if source == 'gmail':
            if not self.get_gmail_service():
                logger.error("Не удалось подключиться к Gmail API")
                return False
                
            emails = self.get_latest_emails(count, sender, since, until, unread)
            self.stats['sources']['gmail'] = len(emails)
            
        elif source == 'mailru':
            if not self.mailru_client:
                logger.error("Клиент Mail.ru не настроен")
                return False

            emails = self.get_mailru_emails(count, sender, since, until, unread)
            self.stats['sources']['mailru'] = len(emails)
            
        else:
            logger.error(f"Неизвестный источник писем: {source}")
            return False
            
        if not emails:
            logger.info("Писем не найдено")
            return True
        
        results = []
        logger.info(f"Начинаем анализ {len(emails)} писем...")
        
        for i, email_meta in enumerate(emails, 1):
            logger.info(f"Обработка {i}/{len(emails)}: {email_meta.get('id', 'N/A')}")
            
            details = self.get_email_details(email_meta['id'], source)
            if not details:
                self.stats['errors'] += 1
                continue
            
            analysis = self.analyze_email_with_gemini(details['body'], details['attachments'])
            
            category = analysis.get('category', 'Неизвестно')
            self.stats['categories'][category] = self.stats['categories'].get(category, 0) + 1
            self.stats['processed'] += 1
            
            results.append({
                'details': details,
                'analysis': analysis
            })
            
            time.sleep(0.1)
        
        # Генерируем имя файла отчета
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = self.report_generator.get_output_filename(output_dir, format_type, timestamp)

        filters = {
            'source': source,
            'count': count,
            'sender': sender,
            'since': since,
            'until': until,
            'unread': unread,
            'keywords': keywords
        }

        # Генерируем отчет
        if not self.generate_report(results, output_filename, filters, format_type):
            logger.error("Не удалось создать отчет")
            return False

        logger.info(f"✅ Анализ завершен! Результаты сохранены в: {output_filename}")
        logger.info(f"Обработано: {self.stats['processed']}, Ошибок: {self.stats['errors']}")

        # Закрываем соединение с Mail.ru если оно было открыто
        if self.mailru_client:
            self.mailru_client.disconnect()

        return True

def main():
    """Точка входа в программу"""
    parser = argparse.ArgumentParser(description="🤖 AI-анализ писем из Gmail и Mail.ru")
    parser.add_argument("-c", "--count", type=int, default=10, help="Количество писем (по умолчанию: 10, 0 = все письма текущей даты)")
    parser.add_argument("--source", choices=['gmail', 'mailru'], default='gmail', help="Источник писем")
    parser.add_argument("-s", "--sender", type=str, help="Фильтр по отправителю")
    parser.add_argument("--since", type=str, help="Фильтр по начальной дате (YYYY-MM-DD)")
    parser.add_argument("--until", type=str, help="Фильтр по конечной дате (YYYY-MM-DD)")
    parser.add_argument("-u", "--unread", action='store_true', help="Только непрочитанные письма")
    parser.add_argument("-o", "--output", type=str, default=".", help="Директория для сохранения отчета")
    parser.add_argument("-f", "--format", type=str, default="markdown",
                       choices=Config.SUPPORTED_FORMATS, help="Формат отчета")
    parser.add_argument("-k", "--keywords", type=str, help="Ключевые слова для фильтрации")
    parser.add_argument("-v", "--verbose", action='store_true', help="Подробный вывод")

    args = parser.parse_args()

    # Обработка специального случая count=0
    if args.count == 0:
        # Если не указаны даты, устанавливаем текущую дату
        if not args.since and not args.until:
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            args.since = today
            args.until = today
            logger.info(f"📅 count=0: анализируем все письма за {today}")
        else:
            logger.info("📅 count=0: анализируем все письма в указанном диапазоне дат")

        # Устанавливаем большое число для получения всех писем
        args.count = 999999

    # Валидация аргументов командной строки
    validation_errors = InputValidator.validate_command_line_args(args)
    if validation_errors:
        logger.error("Ошибки валидации:")
        for error in validation_errors:
            logger.error(f"  - {error}")
        sys.exit(1)
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        # Также устанавливаем DEBUG для всех обработчиков
        for handler in logging.getLogger().handlers:
            handler.setLevel(logging.DEBUG)

    # Валидация конфигурации
    if not Config.validate():
        sys.exit(1)

    analyzer = EmailAnalyzer(Config.GEMINI_API_KEY, Config.GOOGLE_MODEL)

    if args.source == 'mailru':
        if not Config.MAILRU_USERNAME or not Config.MAILRU_PASSWORD:
            logger.error("Требуются MAILRU_USERNAME и MAILRU_PASSWORD в .env файле")
            logger.info("Добавьте в .env файл:")
            logger.info("MAILRU_USERNAME=your_email@mail.ru")
            logger.info("MAILRU_PASSWORD=your_password")
            sys.exit(1)

        if not analyzer.setup_mailru(Config.MAILRU_USERNAME, Config.MAILRU_PASSWORD):
            logger.error("Не удалось подключиться к Mail.ru")
            sys.exit(1)
    
    success = analyzer.run(
        count=args.count,
        source=args.source,
        sender=args.sender,
        since=args.since,
        until=args.until,
        unread=args.unread,
        output_dir=args.output,
        format_type=args.format,
        keywords=args.keywords
    )
    
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()