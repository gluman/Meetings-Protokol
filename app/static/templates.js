// Meeting Protocol — управление шаблонами

// === Web-сессия ===
async function checkSession() {
  try {
    const r = await fetch('/web/check', { credentials: 'include' });
    if (r.status === 401) {
      window.location.href = '/';
      return false;
    }
    const data = await r.json();
    if (!data.auth_disabled) {
      document.getElementById('userInfo').textContent = '👤 ' + (data.user || '');
    }
    return true;
  } catch (e) {
    return false;
  }
}
document.getElementById('logoutBtn').addEventListener('click', async () => {
  await fetch('/web/logout', { method: 'POST', credentials: 'include' });
  window.location.href = '/';
});
checkSession();

// === UI refs ===
const dropZone = document.getElementById('exampleDropZone');
const fileInput = document.getElementById('exampleFileInput');
const templateName = document.getElementById('templateName');
const createStatus = document.getElementById('createStatus');
const templateList = document.getElementById('templateList');

let selectedFile = null;

dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', e => {
  e.preventDefault();
  dropZone.classList.add('dragover');
});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('dragover');
  if (e.dataTransfer.files.length) {
    selectedFile = e.dataTransfer.files[0];
    setStatus(`Файл: ${selectedFile.name} (${formatSize(selectedFile.size)})`, '');
  }
});
fileInput.addEventListener('change', e => {
  if (e.target.files.length) {
    selectedFile = e.target.files[0];
    setStatus(`Файл: ${selectedFile.name} (${formatSize(selectedFile.size)})`, '');
  }
});

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1024 / 1024).toFixed(1) + ' MB';
}

function setStatus(text, kind) {
  createStatus.textContent = text;
  createStatus.className = 'model-info' + (kind ? ' ' + kind : '');
}

// === Создание шаблона из файла ===
dropZone.addEventListener('dblclick', createTemplateFromFile);
dropZone.addEventListener('click', () => {
  // не делаем ничего — клик уже открывает fileInput
});

async function createTemplateFromFile() {
  if (!selectedFile) {
    setStatus('Сначала выберите файл', 'err');
    return;
  }
  setStatus('Загружаю и парсю...', '');
  const fd = new FormData();
  fd.append('file', selectedFile);
  if (templateName.value.trim()) {
    fd.append('name', templateName.value.trim());
  }
  try {
    const r = await fetch('/api/v1/templates/from-example', {
      method: 'POST',
      body: fd,
      credentials: 'include',
    });
    if (!r.ok) {
      const data = await r.json().catch(() => ({}));
      throw new Error(data.detail || 'HTTP ' + r.status);
    }
    const t = await r.json();
    setStatus(`✓ Шаблон "${t.name}" создан${t.is_default ? ' (по умолчанию)' : ''}. Откройте список ниже, чтобы сделать дефолтным или отредактировать промпт.`, 'ok');
    selectedFile = null;
    fileInput.value = '';
    templateName.value = '';
    loadTemplates();
  } catch (e) {
    setStatus('Ошибка: ' + e.message, 'err');
  }
}

// Добавляю кнопку "Создать" рядом с drop-zone
const createBtn = document.createElement('button');
createBtn.className = 'btn-primary';
createBtn.textContent = '🚀 Создать шаблон';
createBtn.style.marginTop = '1rem';
createBtn.style.width = '100%';
createBtn.addEventListener('click', createTemplateFromFile);
dropZone.parentElement.appendChild(createBtn);

// === Список шаблонов ===
async function loadTemplates() {
  try {
    const r = await fetch('/api/v1/templates', { credentials: 'include' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    renderTemplates(data.templates || []);
  } catch (e) {
    templateList.innerHTML = '<p class="status err">Ошибка загрузки: ' + e.message + '</p>';
  }
}

function renderTemplates(list) {
  if (!list.length) {
    templateList.innerHTML = '<p class="status">Шаблонов пока нет. Создайте первый выше ↑</p>';
    return;
  }
  let html = '<div class="template-list">';
  for (const t of list) {
    html += `
      <div class="template-item" data-id="${t.id}">
        <div class="template-header">
          <h3>${escapeHtml(t.name)} ${t.is_default ? '<span class="badge">по умолчанию</span>' : ''}</h3>
          <div class="template-actions">
            ${!t.is_default ? `<button class="btn-link" data-action="default">Сделать дефолтным</button>` : ''}
            <button class="btn-link" data-action="prompt">📝 Промпт</button>
            <button class="btn-link" data-action="view">Структура</button>
            <button class="btn-link danger" data-action="delete">🗑</button>
          </div>
        </div>
        <p class="template-meta">
          📁 ${escapeHtml(t.source_filename || '—')} ·
          ${t.sections.length} разделов ·
          ${t.prompt.length} символов промпта ·
          ${escapeHtml(t.source_format)}
        </p>
        <div class="template-details" data-state="hidden" hidden>
          <details><summary>Промпт</summary><pre>${escapeHtml(t.prompt)}</pre></details>
          <details><summary>Структура (${t.sections.length} разделов)</summary><pre>${escapeHtml(JSON.stringify(t.sections, null, 2))}</pre></details>
        </div>
        <div class="template-prompt-edit" data-state="hidden" hidden>
          <textarea rows="12" style="width:100%">${escapeHtml(t.prompt)}</textarea>
          <div class="form-actions">
            <button class="btn-primary" data-action="save-prompt">💾 Сохранить</button>
            <button class="btn-secondary" data-action="cancel-edit">Отмена</button>
          </div>
        </div>
      </div>
    `;
  }
  html += '</div>';
  templateList.innerHTML = html;
  attachHandlers();
}

function attachHandlers() {
  document.querySelectorAll('.template-item').forEach(item => {
    const id = item.dataset.id;
    const actions = item.querySelectorAll('[data-action]');
    actions.forEach(btn => {
      btn.addEventListener('click', () => handleAction(item, id, btn.dataset.action));
    });
  });
}

async function handleAction(item, id, action) {
  if (action === 'view') {
    const det = item.querySelector('.template-details');
    if (det.hidden) { det.hidden = false; }
    else { det.hidden = true; }
    return;
  }
  if (action === 'prompt') {
    const ed = item.querySelector('.template-prompt-edit');
    ed.hidden = !ed.hidden;
    return;
  }
  if (action === 'save-prompt') {
    const text = item.querySelector('.template-prompt-edit textarea').value;
    try {
      const r = await fetch('/api/v1/templates/' + id + '/prompt', {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: text }),
      });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const updated = await r.json();
      // обновим textarea
      item.querySelector('.template-prompt-edit textarea').value = updated.prompt;
      item.querySelector('.template-meta').innerHTML = `
        📁 ${escapeHtml(updated.source_filename || '—')} ·
        ${updated.sections.length} разделов ·
        ${updated.prompt.length} символов промпта ·
        ${escapeHtml(updated.source_format)}
      `;
      alert('✓ Промпт сохранён');
    } catch (e) {
      alert('Ошибка: ' + e.message);
    }
    return;
  }
  if (action === 'cancel-edit') {
    item.querySelector('.template-prompt-edit').hidden = true;
    return;
  }
  if (action === 'default') {
    try {
      const r = await fetch('/api/v1/templates/' + id + '/default', {
        method: 'POST', credentials: 'include',
      });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      loadTemplates();
    } catch (e) {
      alert('Ошибка: ' + e.message);
    }
    return;
  }
  if (action === 'delete') {
    if (!confirm('Удалить шаблон? Это действие необратимо.')) return;
    try {
      const r = await fetch('/api/v1/templates/' + id, {
        method: 'DELETE', credentials: 'include',
      });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      loadTemplates();
    } catch (e) {
      alert('Ошибка: ' + e.message);
    }
    return;
  }
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c]);
}

loadTemplates();
