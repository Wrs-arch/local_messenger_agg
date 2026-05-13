#!/usr/bin/env python3
"""
Скрипт для компиляции AI Email Analyzer в исполняемый файл .exe
Использует PyInstaller для создания standalone приложения
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class EmailAnalyzerBuilder:
    """Класс для сборки AI Email Analyzer в .exe"""
    
    def __init__(self):
        self.project_dir = Path(__file__).parent
        self.dist_dir = self.project_dir / "dist"
        self.build_dir = self.project_dir / "build"
        self.main_script = "deepseek_email_analyzer3.py"
        self.app_name = "EmailAnalyzer"
        
    def check_dependencies(self):
        """Проверка наличия необходимых зависимостей"""
        logger.info("🔍 Проверка зависимостей...")
        
        try:
            import PyInstaller
            logger.info(f"✅ PyInstaller найден: {PyInstaller.__version__}")
        except ImportError:
            logger.error("❌ PyInstaller не найден!")
            logger.info("Установите PyInstaller: pip install pyinstaller")
            return False
        
        # Проверяем основной скрипт
        if not (self.project_dir / self.main_script).exists():
            logger.error(f"❌ Основной скрипт {self.main_script} не найден!")
            return False
        
        logger.info(f"✅ Основной скрипт найден: {self.main_script}")
        
        # Проверяем модули
        required_modules = [
            "config.py", "email_parser.py", "report_generator.py", 
            "validators.py", "decorators.py"
        ]
        
        for module in required_modules:
            if (self.project_dir / module).exists():
                logger.info(f"✅ Модуль найден: {module}")
            else:
                logger.warning(f"⚠️ Модуль не найден: {module}")
        
        return True
    
    def clean_build_dirs(self):
        """Очистка директорий сборки"""
        logger.info("🧹 Очистка директорий сборки...")
        
        for dir_path in [self.dist_dir, self.build_dir]:
            if dir_path.exists():
                shutil.rmtree(dir_path)
                logger.info(f"🗑️ Удалена директория: {dir_path}")
        
        # Удаляем .spec файл если есть
        spec_file = self.project_dir / f"{self.app_name}.spec"
        if spec_file.exists():
            spec_file.unlink()
            logger.info(f"🗑️ Удален файл: {spec_file}")
    
    def create_pyinstaller_spec(self):
        """Создание .spec файла для PyInstaller"""
        logger.info("📝 Создание .spec файла...")
        
        spec_content = f'''# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# Дополнительные данные для включения
added_files = [
    ('requirements.txt', '.'),
    ('README.md', '.'),
]

# Скрытые импорты
hidden_imports = [
    'google.generativeai',
    'google.auth',
    'google.oauth2',
    'googleapiclient',
    'decouple',
    'charset_normalizer',
    'email.mime',
    'email.header',
    'email.utils',
    'imaplib',
    'json',
    'csv',
    'pathlib',
]

a = Analysis(
    ['{self.main_script}'],
    pathex=[],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='{self.app_name}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
'''
        
        spec_file = self.project_dir / f"{self.app_name}.spec"
        with open(spec_file, 'w', encoding='utf-8') as f:
            f.write(spec_content)
        
        logger.info(f"✅ Создан .spec файл: {spec_file}")
        return spec_file
    
    def build_executable(self, spec_file):
        """Сборка исполняемого файла"""
        logger.info("🔨 Начинаем сборку исполняемого файла...")
        
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--clean",
            "--noconfirm",
            str(spec_file)
        ]
        
        logger.info(f"Команда сборки: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=300  # 5 минут таймаут
            )
            
            if result.returncode == 0:
                logger.info("✅ Сборка завершена успешно!")
                return True
            else:
                logger.error("❌ Ошибка при сборке:")
                logger.error(result.stderr)
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("❌ Таймаут сборки (5 минут)")
            return False
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка: {e}")
            return False
    
    def create_batch_file(self):
        """Создание .bat файла для запуска"""
        logger.info("📝 Создание batch файла...")
        
        exe_path = self.dist_dir / f"{self.app_name}.exe"
        if not exe_path.exists():
            logger.warning("⚠️ .exe файл не найден, batch файл не создан")
            return
        
        batch_content = f'''@echo off
chcp 65001 > nul
title AI Email Analyzer
echo 📧 AI Email Analyzer v3.0
echo.
echo Запуск анализатора писем...
echo.

"{self.app_name}.exe" %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ Произошла ошибка при выполнении программы
    echo Код ошибки: %ERRORLEVEL%
    echo.
    pause
)
'''
        
        batch_file = self.dist_dir / "run_analyzer.bat"
        with open(batch_file, 'w', encoding='utf-8') as f:
            f.write(batch_content)
        
        logger.info(f"✅ Создан batch файл: {batch_file}")
    
    def create_readme_for_exe(self):
        """Создание README для исполняемого файла"""
        logger.info("📝 Создание README для .exe...")
        
        readme_content = '''# 📧 AI Email Analyzer - Исполняемая версия

## 🚀 Быстрый старт

1. **Настройте переменные окружения:**
   - Создайте файл `.env` в той же папке, где находится `EmailAnalyzer.exe`
   - Добавьте в него ваши настройки:
   ```
   GEMINI_API_KEY=your_gemini_api_key_here
   MAILRU_USERNAME=your_email@mail.ru
   MAILRU_PASSWORD=your_app_password
   ```

2. **Для Gmail:**
   - Поместите файл `credentials.json` в ту же папку

3. **Запуск:**
   - Двойной клик на `run_analyzer.bat` для запуска с интерфейсом
   - Или запустите `EmailAnalyzer.exe` из командной строки

## 📖 Примеры использования

```cmd
# Анализ Gmail (по умолчанию)
EmailAnalyzer.exe

# Анализ Mail.ru
EmailAnalyzer.exe --source mailru

# Анализ с параметрами
EmailAnalyzer.exe -c 20 -f json --source mailru

# Справка
EmailAnalyzer.exe --help
```

## 📁 Структура файлов

```
📁 EmailAnalyzer/
├── EmailAnalyzer.exe      # Основное приложение
├── run_analyzer.bat       # Скрипт запуска
├── .env                   # Ваши настройки (создать самостоятельно)
├── credentials.json       # Gmail API ключи (скачать из Google Cloud)
├── README_EXE.md         # Эта инструкция
└── requirements.txt       # Список зависимостей (справочно)
```

## 🆘 Устранение неполадок

- **Ошибка "GEMINI_API_KEY не найден":** Проверьте файл `.env`
- **Ошибка подключения к Mail.ru:** Используйте пароль приложения
- **Ошибка Gmail API:** Проверьте файл `credentials.json`

Подробная документация в основном README.md проекта.
'''
        
        readme_file = self.dist_dir / "README_EXE.md"
        with open(readme_file, 'w', encoding='utf-8') as f:
            f.write(readme_content)
        
        logger.info(f"✅ Создан README: {readme_file}")
    
    def copy_additional_files(self):
        """Копирование дополнительных файлов"""
        logger.info("📋 Копирование дополнительных файлов...")
        
        files_to_copy = [
            "requirements.txt",
            ".env.example" if (self.project_dir / ".env.example").exists() else None
        ]
        
        for file_name in files_to_copy:
            if file_name and (self.project_dir / file_name).exists():
                src = self.project_dir / file_name
                dst = self.dist_dir / file_name
                shutil.copy2(src, dst)
                logger.info(f"📄 Скопирован файл: {file_name}")
    
    def show_build_info(self):
        """Показать информацию о сборке"""
        exe_path = self.dist_dir / f"{self.app_name}.exe"
        
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            logger.info("🎉 Сборка завершена успешно!")
            logger.info(f"📁 Исполняемый файл: {exe_path}")
            logger.info(f"📏 Размер файла: {size_mb:.1f} МБ")
            logger.info(f"📂 Директория: {self.dist_dir}")
            logger.info("")
            logger.info("🚀 Для запуска:")
            logger.info(f"   cd {self.dist_dir}")
            logger.info(f"   .\\{self.app_name}.exe --help")
            logger.info("")
            logger.info("💡 Или используйте run_analyzer.bat для удобного запуска")
        else:
            logger.error("❌ Исполняемый файл не найден!")
    
    def build(self):
        """Основной метод сборки"""
        logger.info("🏗️ Начинаем сборку AI Email Analyzer...")
        
        # Проверяем зависимости
        if not self.check_dependencies():
            return False
        
        # Очищаем директории
        self.clean_build_dirs()
        
        # Создаем .spec файл
        spec_file = self.create_pyinstaller_spec()
        
        # Собираем исполняемый файл
        if not self.build_executable(spec_file):
            return False
        
        # Создаем дополнительные файлы
        self.create_batch_file()
        self.create_readme_for_exe()
        self.copy_additional_files()
        
        # Показываем информацию о сборке
        self.show_build_info()
        
        return True


def main():
    """Главная функция"""
    print("🏗️ AI Email Analyzer Builder v1.0")
    print("=" * 50)
    
    builder = EmailAnalyzerBuilder()
    
    try:
        success = builder.build()
        if success:
            print("\n✅ Сборка завершена успешно!")
            return 0
        else:
            print("\n❌ Сборка завершилась с ошибками!")
            return 1
            
    except KeyboardInterrupt:
        print("\n⏹️ Сборка прервана пользователем")
        return 1
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
