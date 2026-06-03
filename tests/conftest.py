"""Глобальные фикстуры для тестов meeting-protocol."""
import pytest


@pytest.fixture(autouse=True)
def _init_db():
    """Инициализировать все таблицы (jobs + templates) перед каждым тестом."""
    from app import storage, storage_templates
    storage.init_db()
    storage_templates.init_templates_table()
    yield
