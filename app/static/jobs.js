/* =============================================================================
 * Jobs UI — таблица истории транскрибаций (10 колонок)
 * Колонки:
 *   1. Файл (имя + размер)
 *   2. Промпт (заметка)
 *   3. Шаблон (название + кнопка "Сменить")
 *   4. Описание (берётся из protocol_json или задаётся вручную)
 *   5. Время создания (когда документ готов)
 *   6. Длительность (от submitted до completed)
 *   7. Скачать (когда ready)
 *   8. Примечание (textarea + autosave 2с)
 *   9. Глоссарии (бэйджи)
 *  10. Действия (process/delete/copy/candidates)
 * =========================================================================== */

const API = {
  list: '/api/v1/jobs-view/?',
  get: (id) => `/api/v1/jobs-view/${id}`,
  patchDescription: (id) => `/api/v1/jobs-view/${id}/description`,
  patchTemplate: (id) => `/api/v1/jobs-view/${id}/template`,
  copy: (id) => `/api/v1/jobs-view/${id}/copy`,
  regenerate: (id) => `/api/v1/jobs-view/${id}/regenerate`,
  delete: (id) => `/api/v1/jobs-view/${id}`,
  candidates: (id) => `/api/v1/jobs-view/${id}/candidates`,
  reviewCandidate: (cid) => `/api/v1/jobs-view/candidates/${cid}/review`,
  extractCandidates: (id) => `/api/v1/jobs-view/${id}/extract-candidates`,
  glossaries: '/api/v1/glossaries/?',
  attachGlossary: (id) => `/api/v1/jobs-view/${id}/glossaries`,
  detachGlossary: (id, gid) => `/api/v1/jobs-view/${id}/glossaries/${gid}`,
  templates: '/api/v1/templates',
  me: '/web/me',
  logout: '/web/logout',
};

const state = {
  jobs: [],
  total: 0,
  limit: 25,
  offset: 0,
  statusFilter: '',
  search: '',
  templates: [],
  glossaries: [],
  user: null,
  modal: { templateJobId: null, glossariesJobId: null, candidatesJobId: null },
};

// ---------- helpers ----------
async function apiFetch(url, opts = {}) {
  const r = await fetch(url, { credentials: 'include', ...opts });
  if (r.status === 401 || r.status === 403) {
    window.location.href = '/static/login.html';
    return null;
  }
  if (!r.ok) {
    const err = await r.text();
    throw new Error(`${r.status}: ${err}`);
  }
  if (r.status === 204) return null;
  return r.json();
}

function fmtDate(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString('ru-RU', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    });
  } catch { return iso; }
}

function fmtDuration(created, finished) {
  if (!created) return '—';
  if (!finished) return '⏳ в процессе';
  const c = new Date(created);
  const f = new Date(finished);
  const sec = Math.round((f - c) / 1000);
  if (sec < 60) return `${sec}с`;
  if (sec < 3600) return `${Math.floor(sec / 60)}м ${sec % 60}с`;
  return `${Math.floor(sec / 3600)}ч ${Math.floor((sec % 3600) / 60)}м`;
}

function fmtSize(bytes) {
  if (!bytes) return '';
  if (bytes < 1024) return bytes + ' Б';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' КБ';
  if (bytes < 1024 * 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' МБ';
  return (bytes / 1024 / 1024 / 1024).toFixed(2) + ' ГБ';
}

function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ---------- top-level loaders ----------
async function loadMe() {
  try {
    const r = await fetch(API.me, { credentials: 'include' });
    if (r.ok) {
      const data = await r.json();
      state.user = data;
      document.getElementById('userInfo').textContent =
        `${data.user} · ${data.role}`;
      if (data.role === 'admin') {
        document.getElementById('adminLink').style.display = '';
      }
    }
  } catch (e) { console.warn('loadMe failed', e); }
}

async function loadTemplates() {
  try {
    const data = await apiFetch(API.templates);
    state.templates = (data && data.templates) || (Array.isArray(data) ? data : []);
  } catch (e) {
    console.warn('loadTemplates failed', e);
    state.templates = [];
  }
}

async function loadGlossaries() {
  try {
    const data = await apiFetch(API.glossaries);
    state.glossaries = (data && (data.glossaries || data)) || [];
  } catch (e) {
    console.warn('loadGlossaries failed', e);
    state.glossaries = [];
  }
}

async function loadJobs() {
  const params = new URLSearchParams({
    limit: state.limit,
    offset: state.offset,
  });
  if (state.statusFilter) params.set('status', state.statusFilter);

  const container = document.getElementById('jobsTableContainer');
  container.innerHTML = '<div class="loading">Загрузка...</div>';

  try {
    const data = await apiFetch(API.list + params.toString());
    if (!data) return;
    state.jobs = data.jobs || [];
    state.total = data.total || 0;
    renderTable();
    renderPagination();
  } catch (e) {
    container.innerHTML = `<div class="empty-state">❌ Ошибка загрузки: ${escapeHtml(e.message)}</div>`;
  }
}

function renderTable() {
  const container = document.getElementById('jobsTableContainer');
  const totalInfo = document.getElementById('totalInfo');
  totalInfo.textContent = `Всего: ${state.total}`;

  if (state.jobs.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <h3>📭 Нет заданий</h3>
        <p>Загрузите аудио или видео и нажмите "Обработать" на главной странице.</p>
        <a href="/static/index.html" class="action-btn primary">⬆ Загрузить файл</a>
      </div>`;
    return;
  }

  // Filter by search
  const filtered = state.search
    ? state.jobs.filter(j => {
        const s = state.search.toLowerCase();
        return (j.file_name || '').toLowerCase().includes(s) ||
               (j.description || '').toLowerCase().includes(s) ||
               (j.template_name || '').toLowerCase().includes(s);
      })
    : state.jobs;

  if (filtered.length === 0) {
    container.innerHTML = `<div class="empty-state">Нет совпадений по фильтру</div>`;
    return;
  }

  const rows = filtered.map(renderRow).join('');
  container.innerHTML = `
    <table class="jobs-table">
      <thead>
        <tr>
          <th>📁 Файл</th>
          <th>📝 Промпт</th>
          <th>📋 Шаблон</th>
          <th>📄 Описание</th>
          <th>⏱ Создан</th>
          <th>⏳ Длительность</th>
          <th>⬇ Скачать</th>
          <th>💬 Примечание</th>
          <th>📖 Глоссарии</th>
          <th>🎯 Действия</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;

  // Wire events
  container.querySelectorAll('.note-input').forEach(el => {
    el.addEventListener('input', (e) => onNoteChange(e.target));
  });
  container.querySelectorAll('[data-action]').forEach(el => {
    el.addEventListener('click', (e) => onActionClick(e.currentTarget));
  });
}

function renderRow(j) {
  const statusClass = `status-${j.status || 'unknown'}`;
  const queue = j.queue_position != null
    ? `<span class="queue-pill">#${j.queue_position} в очереди</span>`
    : '';
  const regen = j.regenerate_count > 0
    ? `<span class="regen-count" title="Сколько раз пересоздавался документ">↻${j.regenerate_count}</span>`
    : '';

  const fileName = escapeHtml(j.file_name || '(без имени)');
  const prompt = j.protocol_json
    ? extractPromptFromProtocol(j.protocol_json)
    : '';
  const tplName = j.template_name
    ? escapeHtml(j.template_name)
    : '<i style="color:#94a3b8;">дефолт</i>';

  // description из protocol_json (если есть) — обрезаем
  let docxDesc = '';
  if (j.protocol_json) {
    try {
      const p = JSON.parse(j.protocol_json);
      docxDesc = [p.date, p.time_start, p.participants, p.agenda]
        .filter(Boolean).join(' · ').slice(0, 200);
    } catch {}
  }

  const candidatesBadge = (j.candidates_count > 0)
    ? `<span class="badge-cand" title="Найдены спорные термины">${j.candidates_count}</span>`
    : '';

  // глоссарии (бэйджи)
  const glossHtml = (j.glossary_count > 0)
    ? `<span class="badge-glossary">📖 ${j.glossary_count}</span>`
    : '<i style="color:#cbd5e1;">нет</i>';

  return `
    <tr data-job-id="${escapeHtml(j.job_id)}">
      <td class="col-filename">
        <div><b>${fileName}</b></div>
        <small style="color:#64748b;">${j.is_video ? '🎥 видео' : '🎵 аудио'}</small>
        <small style="color:#94a3b8; font-family: monospace; font-size: 10px;">${escapeHtml(j.job_id)}</small>
      </td>
      <td class="col-prompt" title="${escapeHtml(prompt || '')}">
        ${prompt ? escapeHtml(prompt.slice(0, 80)) + (prompt.length > 80 ? '…' : '') : '<i style="color:#cbd5e1;">—</i>'}
      </td>
      <td class="col-template">
        <span>${tplName}</span><br>
        <button class="action-btn" data-action="set-template" data-id="${escapeHtml(j.job_id)}">Сменить</button>
      </td>
      <td class="col-description">
        ${docxDesc ? escapeHtml(docxDesc) : '<i style="color:#cbd5e1;">—</i>'}
      </td>
      <td>${fmtDate(j.finished_at || j.created_at)}</td>
      <td>${fmtDuration(j.created_at, j.finished_at)}${regen}</td>
      <td class="col-actions">
        ${j.status === 'completed' && j.file_name
          ? `<a class="action-btn primary" href="/api/v1/download/${j.job_id}.docx" download="${escapeHtml(j.file_name.replace(/\.[^.]+$/, ''))}.docx">⬇ DOCX</a>`
          : '<i style="color:#cbd5e1;">—</i>'}
      </td>
      <td class="col-description">
        <textarea class="note-input"
          data-action="description"
          data-id="${escapeHtml(j.job_id)}"
          placeholder="Примечание..."
          maxlength="2000">${escapeHtml(j.description || '')}</textarea>
      </td>
      <td>${glossHtml} ${candidatesBadge}</td>
      <td class="col-actions">
        ${j.status === 'completed'
          ? `<button class="action-btn" data-action="regenerate" data-id="${escapeHtml(j.job_id)}" title="Пересоздать документ">🔄</button>`
          : ''}
        <button class="action-btn" data-action="copy" data-id="${escapeHtml(j.job_id)}" title="Копировать">📋</button>
        <button class="action-btn" data-action="glossaries" data-id="${escapeHtml(j.job_id)}" title="Глоссарии">📖</button>
        ${(j.candidates_count > 0 || j.status === 'completed')
          ? `<button class="action-btn" data-action="candidates" data-id="${escapeHtml(j.job_id)}" title="Спорные термины">🔍</button>`
          : ''}
        <button class="action-btn danger" data-action="delete" data-id="${escapeHtml(j.job_id)}" title="Удалить">🗑</button>
      </td>
    </tr>`;
}

function extractPromptFromProtocol(json) {
  try {
    const p = JSON.parse(json);
    return p.prompt || p.notes || p.user_notes || '';
  } catch { return ''; }
}

function renderPagination() {
  const pag = document.getElementById('pagination');
  const pageInfo = document.getElementById('pageInfo');
  const prev = document.getElementById('prevPage');
  const next = document.getElementById('nextPage');
  const totalPages = Math.ceil(state.total / state.limit);
  const currentPage = Math.floor(state.offset / state.limit) + 1;

  if (state.total <= state.limit) {
    pag.style.display = 'none';
    return;
  }
  pag.style.display = '';
  pageInfo.textContent = `Страница ${currentPage} из ${totalPages}`;
  prev.disabled = state.offset === 0;
  next.disabled = state.offset + state.limit >= state.total;
}

// ---------- event handlers ----------
const noteTimers = {};

function onNoteChange(textarea) {
  const id = textarea.dataset.id;
  textarea.classList.remove('saved', 'saving');
  textarea.classList.add('saving');
  clearTimeout(noteTimers[id]);
  noteTimers[id] = setTimeout(async () => {
    try {
      const r = await apiFetch(API.patchDescription(id), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: textarea.value }),
      });
      textarea.classList.remove('saving');
      textarea.classList.add('saved');
      setTimeout(() => textarea.classList.remove('saved'), 1500);
    } catch (e) {
      textarea.classList.remove('saving');
      textarea.classList.add('err');
      console.error('description save failed', e);
    }
  }, 2000);
}

async function onActionClick(btn) {
  const id = btn.dataset.id;
  const action = btn.dataset.action;
  btn.disabled = true;
  try {
    switch (action) {
      case 'set-template':
        openTemplateModal(id);
        break;
      case 'copy':
        await copyJob(id);
        break;
      case 'regenerate':
        await regenerateJob(id);
        break;
      case 'glossaries':
        openGlossariesModal(id);
        break;
      case 'candidates':
        openCandidatesModal(id);
        break;
      case 'delete':
        await deleteJob(id);
        break;
    }
  } finally {
    btn.disabled = false;
  }
}

async function copyJob(id) {
  if (!confirm('Создать копию этой строки? (тот же файл + prompt + шаблон)')) return;
  const data = await apiFetch(API.copy(id), { method: 'POST' });
  if (data) {
    alert(`Скопировано: ${data.new_job_id}`);
    loadJobs();
  }
}

async function regenerateJob(id) {
  if (!confirm('Пересоздать документ (с уточнённым глоссарием)?')) return;
  const data = await apiFetch(API.regenerate(id), { method: 'POST' });
  if (data) {
    alert(`Пересоздание поставлено в очередь. regen #${data.regenerate_count}`);
    loadJobs();
  }
}

async function deleteJob(id) {
  if (!confirm('Удалить эту строку? Это действие нельзя отменить.')) return;
  await apiFetch(API.delete(id), { method: 'DELETE' });
  loadJobs();
}

// ---------- modals ----------
function openTemplateModal(id) {
  const job = state.jobs.find(j => j.job_id === id);
  if (!job) return;
  state.modal.templateJobId = id;
  document.getElementById('currentTplName').textContent =
    job.template_name || 'дефолт';
  const sel = document.getElementById('tplSelect');
  sel.innerHTML = state.templates
    .map(t => `<option value="${escapeHtml(t.id)}" ${t.id === job.template_id ? 'selected' : ''}>
      ${escapeHtml(t.name)}${t.is_default ? ' (дефолт)' : ''}
    </option>`).join('');
  document.getElementById('templateModal').hidden = false;
}

function closeTemplateModal() {
  document.getElementById('templateModal').hidden = true;
  state.modal.templateJobId = null;
}

async function saveTemplateChoice() {
  const id = state.modal.templateJobId;
  const tid = document.getElementById('tplSelect').value;
  await apiFetch(API.patchTemplate(id), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ template_id: tid }),
  });
  closeTemplateModal();
  loadJobs();
}

async function resetTemplateChoice() {
  const id = state.modal.templateJobId;
  await apiFetch(API.patchTemplate(id), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ template_id: null }),
  });
  closeTemplateModal();
  loadJobs();
}

async function openGlossariesModal(id) {
  state.modal.glossariesJobId = id;
  const job = state.jobs.find(j => j.job_id === id);
  const list = document.getElementById('glossariesList');
  list.innerHTML = '<div class="loading">Загрузка...</div>';
  document.getElementById('glossariesModal').hidden = false;

  try {
    // Берём текущие привязки job + список всех доступных глоссариев
    const jobData = await apiFetch(API.get(id));
    const attachedIds = new Set((jobData.glossaries || []).map(g => g.id));

    list.innerHTML = state.glossaries.length === 0
      ? '<div class="empty-state">Нет глоссариев. <a href="/static/glossaries.html">Создать →</a></div>'
      : state.glossaries.map(g => `
          <label style="display:flex; gap:.5rem; align-items:start; padding:.4rem; border:1px solid #e2e8f0; border-radius:6px; margin-bottom:.3rem;">
            <input type="checkbox" data-gid="${g.id}" ${attachedIds.has(g.id) ? 'checked' : ''}>
            <span><b>${escapeHtml(g.name)}</b>
              ${g.is_shared ? '<span class="badge-glossary">общий</span>' : ''}
              <br><small style="color:#64748b;">${(g.entries || []).length} терминов</small>
            </span>
          </label>
        `).join('');
  } catch (e) {
    list.innerHTML = `<div class="empty-state">Ошибка: ${escapeHtml(e.message)}</div>`;
  }
}

function closeGlossariesModal() {
  document.getElementById('glossariesModal').hidden = true;
  state.modal.glossariesJobId = null;
}

async function saveGlossariesChoice() {
  const id = state.modal.glossariesJobId;
  const list = document.getElementById('glossariesList');
  const checked = list.querySelectorAll('input[type=checkbox]');
  const jobData = await apiFetch(API.get(id));
  const attached = new Set((jobData.glossaries || []).map(g => g.id));

  for (const cb of checked) {
    const gid = parseInt(cb.dataset.gid, 10);
    if (cb.checked && !attached.has(gid)) {
      await apiFetch(API.attachGlossary(id), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ glossary_id: gid }),
      });
    } else if (!cb.checked && attached.has(gid)) {
      await apiFetch(API.detachGlossary(id, gid), { method: 'DELETE' });
    }
  }
  closeGlossariesModal();
  loadJobs();
}

async function openCandidatesModal(id) {
  state.modal.candidatesJobId = id;
  document.getElementById('candidatesModal').hidden = false;
  const list = document.getElementById('candidatesList');
  list.innerHTML = '<div class="loading">Загрузка...</div>';

  try {
    const data = await apiFetch(API.candidates(id));
    const cands = data.candidates || [];
    if (cands.length === 0) {
      list.innerHTML = `
        <div class="empty-state">
          <p>Нет спорных терминов.</p>
          <p><small>Нажмите "🔄 Извлечь заново" для LLM-анализа протокола.</small></p>
        </div>`;
      return;
    }
    list.innerHTML = cands.map(c => `
      <div class="cand-row">
        <div class="term">${escapeHtml(c.term)}
          <span class="badge-cand">${escapeHtml(c.status)}</span>
        </div>
        ${c.context ? `<div class="ctx">"${escapeHtml(c.context)}"</div>` : ''}
        ${c.suggested_definition ? `<div class="defn">💡 ${escapeHtml(c.suggested_definition)}</div>` : ''}
        <div class="actions">
          <button class="action-btn" data-cand-action="accept" data-cid="${c.id}">✓ Принять</button>
          <button class="action-btn" data-cand-action="reject" data-cid="${c.id}">✗ Отклонить</button>
        </div>
      </div>
    `).join('');
    list.querySelectorAll('[data-cand-action]').forEach(b => {
      b.addEventListener('click', () => reviewCandidate(b.dataset.cid, b.dataset.candAction));
    });
  } catch (e) {
    list.innerHTML = `<div class="empty-state">Ошибка: ${escapeHtml(e.message)}</div>`;
  }
}

async function reviewCandidate(cid, action) {
  const status = action === 'accept' ? 'accepted' : 'rejected';
  await apiFetch(API.reviewCandidate(cid), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  });
  openCandidatesModal(state.modal.candidatesJobId); // reload
  loadJobs();
}

async function extractCandidates() {
  const id = state.modal.candidatesJobId;
  if (!confirm('Запустить LLM-извлечение спорных терминов? Это может занять время.')) return;
  try {
    const data = await apiFetch(API.extractCandidates(id), { method: 'POST' });
    alert(`Извлечено: ${data.extracted} терминов`);
    openCandidatesModal(id);
    loadJobs();
  } catch (e) {
    alert('Ошибка: ' + e.message);
  }
}

// ---------- bootstrap ----------
document.addEventListener('DOMContentLoaded', async () => {
  await loadMe();
  await Promise.all([loadTemplates(), loadGlossaries(), loadJobs()]);

  // Toolbar events
  document.getElementById('searchInput').addEventListener('input', (e) => {
    state.search = e.target.value;
    renderTable();
  });
  document.getElementById('statusFilter').addEventListener('change', (e) => {
    state.statusFilter = e.target.value;
    state.offset = 0;
    loadJobs();
  });
  document.getElementById('refreshBtn').addEventListener('click', () => {
    loadTemplates();
    loadGlossaries();
    loadJobs();
  });
  document.getElementById('prevPage').addEventListener('click', () => {
    if (state.offset > 0) {
      state.offset = Math.max(0, state.offset - state.limit);
      loadJobs();
    }
  });
  document.getElementById('nextPage').addEventListener('click', () => {
    if (state.offset + state.limit < state.total) {
      state.offset += state.limit;
      loadJobs();
    }
  });

  // Modal events
  document.getElementById('tplCancel').addEventListener('click', closeTemplateModal);
  document.getElementById('tplSave').addEventListener('click', saveTemplateChoice);
  document.getElementById('tplReset').addEventListener('click', resetTemplateChoice);
  document.getElementById('glCancel').addEventListener('click', closeGlossariesModal);
  document.getElementById('glSave').addEventListener('click', saveGlossariesChoice);
  document.getElementById('candClose').addEventListener('click', () => {
    document.getElementById('candidatesModal').hidden = true;
  });
  document.getElementById('candExtract').addEventListener('click', extractCandidates);

  // Logout
  document.getElementById('logoutBtn').addEventListener('click', async () => {
    await fetch(API.logout, { method: 'POST', credentials: 'include' });
    window.location.href = '/static/login.html';
  });

  // Auto-refresh каждые 10с если есть queued/running
  setInterval(() => {
    if (state.jobs.some(j => j.status === 'queued' || j.status === 'running')) {
      loadJobs();
    }
  }, 10000);
});
