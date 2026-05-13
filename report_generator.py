"""
Модуль для генерации отчетов в различных форматах
Поддерживает Markdown, JSON, CSV форматы
"""
import json
import csv
import codecs
import datetime
import os
from typing import List, Dict, Any, Optional
from pathlib import Path
import logging
from config import Config
from decorators import safe_execute, validate_input

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Класс для генерации отчетов анализа писем в различных форматах"""
    
    def __init__(self):
        self.supported_formats = Config.SUPPORTED_FORMATS
    
    @validate_input(
        lambda self, results, output_filename, format_type, **kwargs: 
            format_type in self.supported_formats,
        "Неподдерживаемый формат отчета"
    )
    def generate_report(
        self, 
        results: List[Dict], 
        output_filename: str, 
        format_type: str = "markdown",
        filters: Optional[Dict] = None,
        stats: Optional[Dict] = None
    ) -> bool:
        """
        Генерирует отчет в указанном формате
        
        Args:
            results: Список результатов анализа писем
            output_filename: Имя выходного файла
            format_type: Формат отчета (markdown, json, csv)
            filters: Примененные фильтры
            stats: Статистика выполнения
            
        Returns:
            True если отчет успешно создан, False иначе
        """
        try:
            # Создаем директорию если не существует
            output_path = Path(output_filename)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            if format_type == "markdown":
                return self._generate_markdown_report(results, output_filename, filters, stats)
            elif format_type == "json":
                return self._generate_json_report(results, output_filename, filters, stats)
            elif format_type == "csv":
                return self._generate_csv_report(results, output_filename, filters, stats)
            else:
                logger.error(f"Неподдерживаемый формат: {format_type}")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка генерации отчета: {e}")
            return False
    
    @safe_execute(default_return=False, log_errors=True)
    def _generate_markdown_report(
        self, 
        results: List[Dict], 
        output_filename: str,
        filters: Optional[Dict] = None,
        stats: Optional[Dict] = None
    ) -> bool:
        """Генерирует отчет в формате Markdown"""
        
        with codecs.open(output_filename, 'w', 'utf-8') as f:
            # Заголовок
            f.write(f"# 📧 Анализ писем - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
            
            # Статистика
            if stats:
                f.write("## 📊 Статистика\n\n")
                total_time = stats.get('total_time', 0)
                f.write(f"- **Обработано писем:** {stats.get('processed', 0)}\n")
                f.write(f"- **Ошибки:** {stats.get('errors', 0)}\n")
                f.write(f"- **Время выполнения:** {total_time:.1f} сек\n")
                
                sources = stats.get('sources', {})
                if sources.get('gmail', 0) > 0:
                    f.write(f"- **Писем из Gmail:** {sources['gmail']}\n")
                if sources.get('mailru', 0) > 0:
                    f.write(f"- **Писем из Mail.ru:** {sources['mailru']}\n")
                f.write("\n")
            
            # Фильтры
            if filters:
                f.write("## 🔍 Примененные фильтры\n\n")
                f.write(f"- **Количество:** {filters.get('count', 'Не указано')}\n")
                f.write(f"- **Источник:** {filters.get('source', 'Gmail')}\n")
                f.write(f"- **Отправитель:** {filters.get('sender', 'Любой')}\n")
                f.write(f"- **Диапазон дат:** {filters.get('since', 'Любая')} - {filters.get('until', 'Любая')}\n")
                f.write(f"- **Только непрочитанные:** {'Да' if filters.get('unread') else 'Нет'}\n")
                if filters.get('keywords'):
                    f.write(f"- **Ключевые слова:** {filters['keywords']}\n")
                f.write("\n")
            
            # Распределение по категориям
            if stats and stats.get('categories'):
                f.write("## 📈 Распределение по категориям\n\n")
                for category, count in sorted(stats['categories'].items()):
                    f.write(f"- **{category}:** {count}\n")
                f.write("\n")
            
            f.write("---\n\n")
            
            # Детали писем
            for i, result in enumerate(results):
                if not result:
                    continue
                    
                details = result['details']
                analysis = result['analysis']
                
                priority_emoji = {
                    "Высокий": "🔴", 
                    "Средний": "🟡", 
                    "Низкий": "🟢"
                }.get(analysis.get('priority', 'Низкий'), '⚪')
                
                f.write(f"## {i+1}. {details['subject']}\n\n")
                f.write(f"**👤 От:** {details['sender']}\n")
                f.write(f"**📅 Дата:** {details['date']}\n")
                f.write(f"**📂 Категория:** {analysis.get('category', 'Не определено')}\n")
                f.write(f"**{priority_emoji} Приоритет:** {analysis.get('priority', 'Не определено')}\n")
                f.write(f"**📎 Вложения:** {', '.join(details['attachments']) if details['attachments'] else 'Нет'}\n")
                f.write(f"**📖 Статус:** {'Прочитано' if details['is_read'] else 'Не прочитано'}\n\n")
                
                f.write(f"### 📝 Краткое содержание\n")
                f.write(f"{analysis.get('summary', 'Резюме недоступно')}\n\n")
                
                entities = analysis.get('entities', [])
                if entities:
                    f.write(f"### 🔑 Ключевая информация\n")
                    for entity in entities:
                        f.write(f"- {entity}\n")
                    f.write("\n")
                
                f.write("---\n\n")
        
        logger.info(f"Markdown отчет сохранен: {output_filename}")
        return True
    
    @safe_execute(default_return=False, log_errors=True)
    def _generate_json_report(
        self, 
        results: List[Dict], 
        output_filename: str,
        filters: Optional[Dict] = None,
        stats: Optional[Dict] = None
    ) -> bool:
        """Генерирует отчет в формате JSON"""
        
        report_data = {
            "metadata": {
                "generated_at": datetime.datetime.now().isoformat(),
                "total_emails": len(results),
                "filters": filters or {},
                "statistics": stats or {}
            },
            "emails": []
        }
        
        for result in results:
            if not result:
                continue
                
            email_data = {
                "details": result['details'],
                "analysis": result['analysis']
            }
            report_data["emails"].append(email_data)
        
        with open(output_filename, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"JSON отчет сохранен: {output_filename}")
        return True
    
    @safe_execute(default_return=False, log_errors=True)
    def _generate_csv_report(
        self, 
        results: List[Dict], 
        output_filename: str,
        filters: Optional[Dict] = None,
        stats: Optional[Dict] = None
    ) -> bool:
        """Генерирует отчет в формате CSV"""
        
        fieldnames = [
            'id', 'subject', 'sender', 'date', 'category', 'priority', 
            'summary', 'entities', 'attachments', 'is_read'
        ]
        
        with open(output_filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for result in results:
                if not result:
                    continue
                    
                details = result['details']
                analysis = result['analysis']
                
                row = {
                    'id': details.get('id', ''),
                    'subject': details.get('subject', ''),
                    'sender': details.get('sender', ''),
                    'date': details.get('date', ''),
                    'category': analysis.get('category', ''),
                    'priority': analysis.get('priority', ''),
                    'summary': analysis.get('summary', ''),
                    'entities': '; '.join(analysis.get('entities', [])),
                    'attachments': '; '.join(details.get('attachments', [])),
                    'is_read': 'Да' if details.get('is_read', False) else 'Нет'
                }
                
                writer.writerow(row)
        
        logger.info(f"CSV отчет сохранен: {output_filename}")
        return True
    
    def generate_visualization_config(self, stats: Dict) -> Dict:
        """
        Генерирует JSON конфигурацию для визуализации статистики
        
        Args:
            stats: Статистика анализа
            
        Returns:
            Словарь с конфигурацией диаграммы
        """
        categories = stats.get('categories', {})
        
        if not categories:
            return {}
        
        labels = list(categories.keys())
        data = list(categories.values())
        colors = [
            "#FF6B6B", "#4ECDC4", "#FFD166", "#06D6A0", 
            "#F38BA8", "#A6E3A1", "#FAB387", "#CBA6F7"
        ]
        
        # Обрезаем цвета до количества категорий
        background_colors = colors[:len(labels)]
        
        config = {
            "type": "bar",
            "data": {
                "labels": labels,
                "datasets": [{
                    "label": "Количество писем",
                    "data": data,
                    "backgroundColor": background_colors
                }]
            },
            "options": {
                "scales": {
                    "y": {
                        "beginAtZero": True
                    }
                },
                "plugins": {
                    "title": {
                        "display": True,
                        "text": "Распределение писем по категориям"
                    }
                }
            }
        }
        
        return config
    
    def get_output_filename(self, base_dir: str, format_type: str, timestamp: Optional[str] = None) -> str:
        """
        Генерирует имя файла для отчета
        
        Args:
            base_dir: Базовая директория
            format_type: Формат файла
            timestamp: Временная метка (если не указана, генерируется автоматически)
            
        Returns:
            Полный путь к файлу отчета
        """
        if not timestamp:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        extensions = {
            "markdown": "md",
            "json": "json",
            "csv": "csv"
        }
        
        extension = extensions.get(format_type, "txt")
        filename = f"email_analysis_{timestamp}.{extension}"
        
        return os.path.join(base_dir, filename)
