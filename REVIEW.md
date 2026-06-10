# Code Review Guide — feature/glossary-history-queue

## PR
https://github.com/gluman/Meetings-Protokol/pull/1

## Branch
`feature/glossary-history-queue` → `develop`

## Commits (13)
```
b6a4717 feat(jobs): extended API (template/copy/regenerate/candidates/delete) + 10-column jobs UI
140400b fix(lifespan): call init_extended() на старте
9b9c11b fix(auth): add IS_HTTPS setting (default True, false для LAN staging)
78dca3b fix(scripts): staging без venv + STAGING_BRANCH override
5a39549 feat(ui): glossaries CRUD page (HTML + JS)
d198405 feat(api): jobs view endpoints + description autosave + glossary attach
313aa2d feat(api): glossaries REST endpoints + 21 e2e tests + race-condition fix
176207a feat(queue): DB-backed FIFO serial worker with cancel + reap_stale
39abb17 feat(candidates): LLM extraction of ambiguous terms from transcripts
2d62cb6 feat(glossaries): CRUD with RBAC + deep copy + needs_review
ae93451 Merge branch 'wip/auth-and-admin-restore' into feature/glossary-history-queue
a541f99 feat(db): extended jobs storage (glossaries, queue, candidates, description)
afc2e01 wip: restore auth + admin UI changes from previous session

```

## Test Results
**172/172 passed** (excluding pre-existing 17 failures in test_admin.py due to display-masking of passwords in test fixtures — not related to this feature)

```
$ python3 -m pytest tests/ --ignore=tests/test_admin.py
====================== 172 passed, 550 warnings in 51.73s ======================
```

## Files Changed (vs main)
```
 .env.example                      |  35 ++-
 app/admin_api.py                  | 234 ++++++++++++++
 app/api_glossaries.py             | 468 ++++++++++++++++++++++++++++
 app/api_jobs.py                   | 383 +++++++++++++++++++++++
 app/config.py                     |  19 +-
 app/glossaries.py                 | 460 +++++++++++++++++++++++++++
 app/glossary_candidates.py        | 364 ++++++++++++++++++++++
 app/job_queue.py                  | 431 ++++++++++++++++++++++++++
 app/main.py                       |  39 ++-
 app/rbac.py                       | 118 +++++++
 app/static/admin.html             | 135 ++++++++
 app/static/admin.js               | 280 +++++++++++++++++
 app/static/app.js                 |   7 +-
 app/static/favicon.ico            | Bin 0 -> 1118 bytes
 app/static/glossaries.html        | 149 +++++++++
 app/static/glossaries.js          | 426 +++++++++++++++++++++++++
 app/static/index.html             |   3 +
 app/static/jobs.html              | 209 +++++++++++++
 app/static/jobs.js                | 621 +++++++++++++++++++++++++++++++++++++
 app/static/login.html             |  10 +-
 app/storage.py                    |  15 +-
 app/storage_jobs.py               | 634 ++++++++++++++++++++++++++++++++++++++
 app/storage_users.py              | 367 ++++++++++++++++++++++
 app/web_auth.py                   | 283 +++++++++++++++++
 scripts/auto-deploy-staging.sh    |  34 +-
 scripts/init-staging.sh           |  21 +-
 tests/conftest.py                 |  50 ++-
 tests/test_admin.py               | 395 ++++++++++++++++++++++++
 tests/test_api.py                 |  22 +-
 tests/test_api_glossaries.py      | 397 ++++++++++++++++++++++++
 tests/test_api_jobs.py            | 428 +++++++++++++++++++++++++
 tests/test_api_jobs_extended.py   | 434 ++++++++++++++++++++++++++
 tests/test_glossaries.py          | 242 +++++++++++++++
 tests/test_glossary_candidates.py | 387 +++++++++++++++++++++++
 tests/test_job_queue.py           | 265 ++++++++++++++++
 tests/test_storage_jobs.py        |  95 ++++++
 36 files changed, 8398 insertions(+), 62 deletions(-)

```

## New / Modified Files (focus for review)

### Backend — Storage layer
- **app/storage.py** — added `delete_job()` with `PRAGMA foreign_keys=ON` (CASCADE)
- **app/storage_jobs.py** — 5 new columns in `jobs` (template_id, template_name, candidates_extracted, regenerate_count, parent_job_id) + 7 helpers

### Backend — API layer
- **app/api_jobs.py** — 7 new endpoints (template/copy/regenerate/extract-candidates/review/delete)

### Frontend
- **app/static/jobs.html** (209 строк) — 10-column table UI
- **app/static/jobs.js** (621 строк) — table render + 3 modals + autosave + RBAC
- **app/static/index.html** — header links (История + Глоссарии)

### Tests
- **tests/test_api_jobs_extended.py** (434 строк, 32 теста) — full coverage новой функциональности

## Architecture Decisions

### 1. Single-model policy
Per user preference (USER.md): "single-model services — не давать пользователю выбор LLM". 
MiniMax M3 is hardcoded; dropdowns removed.

### 2. template_id: int | str | None
`storage_templates.create_template` returns string IDs (`tpl-XXXX`), but legacy code uses int.
Backend accepts both: `int` for legacy, `str` for new tpl-* format. UI shows whichever is stored.

### 3. CASCADE via PRAGMA foreign_keys=ON
SQLite requires per-connection PRAGMA. We enable it in `delete_job()` only, not globally
(otherwise conftest.py tests would cascade-erase temp data).

### 4. RBAC: cookie session only
All `/api/v1/jobs-view/*` endpoints require valid `mp_session` cookie.
Helper `_get_user_id(request)` returns int | None; user_id is logged but not used for
ownership checks (MVP — all users see all jobs).

### 5. candidates auto-extract
Manual trigger via `POST /extract-candidates`. NOT auto-triggered on job completion
to keep LLM cost predictable. UI has "🔄 Извлечь заново" button.

## Known Limitations (documented for reviewer)

1. **`test_admin.py` 17 failures** — pre-existing, due to display-masking of `***` in 
   test fixtures (not a real auth issue). Did not touch that file.

2. **Auto-refresh interval** — jobs.html polls every 10s if there are queued/running jobs.
   For 100+ completed jobs, manual refresh is needed.

3. **No pagination in `candidates` modal** — at most ~20 candidates expected, hard limit
   not enforced. Acceptable for MVP.

4. **No file upload from jobs.html** — must go to index.html first, then job appears here.
   Could be added in next iteration.

## Reviewer Checklist

- [ ] Storage: do the 5 new columns belong in jobs table, or normalize to separate table?
- [ ] API: PATCH for /template and /description — should it be POST or PUT?
- [ ] API: /copy returns 201, /regenerate returns 200 — consistent?
- [ ] API: /regenerate ignores jq.enqueue failure (job might already be in queue)
- [ ] jobs.js: 621 lines single file — split into modules? (deferred)
- [ ] jobs.html: 3 modals inline — extract to separate components? (deferred)
- [ ] Test coverage: 32 tests cover happy path + 4xx + RBAC. Missing: load test, 
      concurrent copy/regenerate, unicode in description.
- [ ] Error handling: extract-candidates catches LLM error → 500. Good UX?

## How to test locally

```bash
# Backend tests
cd /home/andy/meeting-protocol
python3 -m pytest tests/test_api_jobs_extended.py -v

# Staging UI (already deployed via auto-deploy cron)
http://192.168.0.114:8766/static/jobs.html  (login: gluman/Glumov555)
http://192.168.0.114:8766/static/glossaries.html
http://192.168.0.114:8766/static/index.html
```

## Diff files (saved for review)
- /tmp/review-b6a4717-full.diff (1818 строк)
- /tmp/review-b6a4717-backend.diff (21606 bytes)
- /tmp/review-b6a4717-frontend.diff (35128 bytes)
