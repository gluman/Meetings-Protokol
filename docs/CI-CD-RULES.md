# 🛡 Branch Protection & Deploy Rules

> **Owner:** @Andrey
> **Last updated:** 2026-06-09

## `main` (production)

**Назначение:** то, что работает у пользователей. https://meeting-protocol.gluman.tech/

**Защита (Settings → Branches → Branch protection rules → main):**

- ☑ Require a pull request before merging
  - ☑ Require approvals: **1**
  - ☑ Dismiss stale pull request approvals when new commits are pushed
  - ☑ Require review from Code Owners
- ☑ Require status checks to pass before merging
  - ☑ Require branches to be up to date before merging
  - Required status checks: `Lint (ruff)`, `Test (Python 3.12)`, `Build check (import smoke test)`, `Secrets scan (gitleaks)`
- ☑ Require conversation resolution before merging
- ☑ Require linear history
- ☑ Include administrators

**Deploy:**
- Триггер: push в `main` (после merge PR)
- Механизм: `scripts/auto-deploy.sh` запускается cron'ом каждые 5 мин на srv-technik1
- Задержка: 0-5 мин после merge
- Откат: `git revert` + push → через 5 мин вернётся

---

## `develop` (staging)

**Назначение:** pre-production среда для тестирования фич. https://staging-meeting-protocol.gluman.tech/

**Защита:**

- ☑ Require a pull request before merging
  - ☑ Require approvals: **0** (только CI)
- ☑ Require status checks to pass before merging
  - Required status checks: `Lint (ruff)`, `Test (Python 3.12)`, `Build check`, `Secrets scan`
- ☐ Linear history: **нет** (здесь merge commits допустимы для истории PR)
- ☑ Include administrators

**Deploy:**
- Триггер: push в `develop`
- Механизм: `scripts/auto-deploy-staging.sh` запускается cron'ом каждые 5 мин
- Вручную: `bash /home/andy/meeting-protocol/scripts/deploy-staging.sh`

---

## `feature/*` (разработка)

**Назначение:** изолированная разработка фич.

**Защита:** нет (это рабочие ветки, можно force-push).

**Создаются от:** `develop`

**Мерджатся в:** `develop` через PR

**Naming:**
- `feature/glossary-history` — фича
- `feature/queue-worker` — фича
- `feature/cicd-setup` — настройка инфры

---

## `hotfix/*` (критические фиксы)

**Назначение:** срочные исправления в production.

**Создаются от:** `main`

**Мерджатся в:** `main` И `develop` (два PR, чтобы не потерять фикс в develop)

**Naming:**
- `hotfix/fix-job-queue-stuck` — фикс воркера
- `hotfix/fix-migration-2026-06-09` — фикс миграции БД

---

## Conventional Commits

Используем для auto-changelog в GitHub Releases:

```
feat: новая функциональность
fix: исправление бага
refactor: рефакторинг без изменения поведения
docs: только документация
test: добавление/правка тестов
ci: изменения в CI/CD
chore: рутинные задачи (deps, версии)
perf: улучшение производительности
```

Примеры:
```
feat(glossary): add CRUD + share + needs_review flag
fix(queue): reap stale running jobs on startup
docs(readme): add quickstart section
ci(github): add gitleaks secrets scan
```
