# 🤝 Contributing to Meeting Protocol

> Документ для ревьюверов (Андрей — UI/функционал, LLM — код).

## Workflow

```
feature/<name>  ──PR──▶  develop  ──PR──▶  main
   │                ▲           ▲
   │                │           │
   └──CI green──────┘           │
                                │
                        prod deploy (cron, 5 мин)
```

**Подробно в [CI-CD-RULES.md](CI-CD-RULES.md).**

## Шпаргалка для LLM-ревью кода

При ревью PR проверь:

### 1. Архитектура
- [ ] Модуль имеет одну зону ответственности (SRP)
- [ ] Публичный API (импортируемые функции) — минимален и стабилен
- [ ] Нет circular imports
- [ ] DB-таблицы — в отдельном `storage_*.py`, API — в `*_api.py`, логика — в самом модуле

### 2. Типизация
- [ ] Все публичные функции имеют type hints (аргументы + return)
- [ ] Pydantic-модели для всех API request/response
- [ ] `Optional[T]` для nullable, `T | None` допустимо в Python 3.10+
- [ ] Enum'ы для ограниченных значений (не magic strings)

### 3. Docstring
- [ ] Каждый публичный класс — docstring в первых строках с описанием назначения
- [ ] Каждая публичная функция — docstring с Args/Returns/Raises
- [ ] Сложная логика — inline-комментарии с `# Потому что...`
- [ ] Все TODO/FIXME имеют owner (например `# TODO(@andrey): ...`)

### 4. БД-миграции
- [ ] `CREATE TABLE IF NOT EXISTS` (идемпотентно)
- [ ] `ALTER TABLE ADD COLUMN` в try/except (для совместимости с существующими БД)
- [ ] `FOREIGN KEY ... ON DELETE CASCADE` где нужна каскадная очистка
- [ ] Индексы для колонок, по которым идёт WHERE/JOIN

### 5. Безопасность
- [ ] Нет хардкода секретов/URL/internal-IP в коммите
- [ ] Все SQL — через `?` placeholder (не f-string)
- [ ] Path traversal: проверка `..`, `/`, `\` в user-supplied filenames
- [ ] Upload: проверка MIME + extension + size

### 6. Тесты
- [ ] Happy path покрыт
- [ ] Edge cases: пустой ввод, невалидный формат, отсутствие записи
- [ ] Permissions: viewer не может admin-действие
- [ ] Fixtures в `conftest.py` для переиспользуемых setup/teardown
- [ ] Тесты не зависят от реальных API (используют mock или `test-key-for-ci`)

### 7. Стиль
- [ ] Нет `print()` (только `logger`)
- [ ] Нет `import *`
- [ ] Нет мёртвого кода / закомментированных блоков
- [ ] Нет `pass` где должно быть исключение
- [ ] Имена файлов: `snake_case.py`, имена классов: `PascalCase`

## Формат ответа при ревью

```markdown
## Общее
- ✅ / ⚠️ / ❌ краткое summary

## Замечания

### 🔴 Блокер (не мерджится)
- `app/xxx.py:123` — почему плохо, как исправить (с примером кода)

### 🟡 Рекомендация (можно мерджить, но поправить в follow-up)
- `app/yyy.py:45` — стилистика / type hint

### 🟢 Похвала
- удачное разделение ответственности в `app/zzz.py`
```

## Локальная проверка перед push

```bash
# 1. Тесты
pytest -v

# 2. Линтер
ruff check app/ tests/
ruff format --check app/ tests/

# 3. Build check (быстрая sanity-проверка импортов)
python -c "from app.main import app; print(f'{app.title} v{app.version}, {len(app.routes)} routes')"

# 4. Проверить что нет секретов
git diff main..HEAD | grep -E "(api_key|password|secret|token).*=.*['\"]" || echo "OK no secrets"
```
