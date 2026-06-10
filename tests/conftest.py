"""Глобальные фикстуры для тестов meeting-protocol.

Каждый тест получает изолированный storage_dir в /tmp, чтобы не ломать
прод-БД. settings.storage_dir пересоздаётся перед каждым тестом.
"""
import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _init_db():
    """Инициализировать все таблицы в изолированном storage перед каждым тестом."""
    # Создаём уникальный tmp storage для теста
    tmp = Path(tempfile.mkdtemp(prefix="meeting_protocol_test_"))

    # Подменяем settings.storage_dir
    os.environ["STORAGE_DIR"] = str(tmp)
    from app.config import settings
    settings.storage_dir = tmp
    (tmp / "protocols").mkdir(exist_ok=True)
    (tmp / "audio").mkdir(exist_ok=True)

    # Сбрасываем кешированные пути в storage / storage_templates / storage_jobs /
    # storage_users (все вычисляют DB_PATH = settings.storage_dir / "X.db" на уровне модуля)
    from app import storage as storage_mod
    from app import storage_templates as st_mod
    from app import storage_jobs as sj_mod
    from app import storage_users as su_mod
    storage_mod.DB_PATH = tmp / "jobs.db"
    st_mod.DB_PATH = tmp / "jobs.db"
    sj_mod._DB_PATH = None  # sj вычисляет через _db_path() — сбрасываем кеш
    su_mod.DB_PATH = tmp / "users.db"  # users — отдельный файл

    # НЕ допускаем, чтобы migrate_from_env() при импорте app.main создавала
    # admin user из .env (web_username=web_password) в test-БД — иначе id=1
    # всегда admin, и permission-тесты в test_glossaries падают при общем прогоне.
    settings.web_username = ""
    settings.web_password = ""

    # Инициализируем все таблицы (порядок важен: init_db ДО init_extended,
    # т.к. init_extended делает ALTER TABLE jobs ADD COLUMN description)
    from app import storage, storage_templates, storage_jobs, storage_users
    storage.init_db()
    storage_templates.init_templates_table()
    storage_jobs.init_extended()
    storage_users.init_users_table()  # users table for test isolation

    yield

    # Чистим после теста
    shutil.rmtree(tmp, ignore_errors=True)
