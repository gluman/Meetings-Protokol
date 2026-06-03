// Meeting Protocol — клиентский JS

// === Web-сессия (cookie-based, JWT) ===
async function checkSession() {
  try {
    const r = await fetch('/web/check', { credentials: 'include' });
    if (r.status === 401) {
      // Не авторизован — редирект на login
      window.location.href = '/';
      return false;
    }
    const data = await r.json();
    if (data.auth_disabled) {
      document.getElementById('userInfo').textContent = '🔓 Auth выключен (dev-режим)';
    } else {
      document.getElementById('userInfo').textContent = `👤 ${data.user || ''}`;
    }
    return true;
  } catch (e) {
    console.error('checkSession failed', e);
    return false;
  }
}

document.getElementById('logoutBtn').addEventListener('click', async () => {
  await fetch('/web/logout', { method: 'POST', credentials: 'include' });
  window.location.href = '/';
});

// При загрузке страницы — проверяем сессию
checkSession();

// === UI refs ===
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const fileInfo = document.getElementById('fileInfo');
const fileName = document.getElementById('fileName');
const fileSize = document.getElementById('fileSize');
const fileType = document.getElementById('fileType');
const resetFile = document.getElementById('resetFile');
const promptInput = document.getElementById('promptInput');
const submitBtn = document.getElementById('submitBtn');
const progressSection = document.getElementById('progressSection');
const progressFill = document.getElementById('progressFill');
const statusText = document.getElementById('statusText');
const resultSection = document.getElementById('resultSection');
const downloadLink = document.getElementById('downloadLink');
const viewJsonBtn = document.getElementById('viewJsonBtn');
const newSessionBtn = document.getElementById('newSessionBtn');
const jsonOutput = document.getElementById('jsonOutput');
const errorSection = document.getElementById('errorSection');
const errorText = document.getElementById('errorText');
const retryBtn = document.getElementById('retryBtn');

let selectedFile = null;
let currentJobId = null;

// Drop zone
dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', e => {
  e.preventDefault();
  dropZone.classList.add('dragover');
});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('dragover');
  if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', e => {
  if (e.target.files.length) handleFile(e.target.files[0]);
});

function handleFile(file) {
  selectedFile = file;
  fileName.textContent = file.name;
  fileSize.textContent = formatSize(file.size);
  fileType.textContent = file.type || '—';
  fileInfo.style.display = 'flex';
  submitBtn.disabled = false;
  fileInput.value = '';
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  if (bytes < 1024 * 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB';
  return (bytes / 1024 / 1024 / 1024).toFixed(2) + ' GB';
}

resetFile.addEventListener('click', () => {
  selectedFile = null;
  fileInfo.style.display = 'none';
  submitBtn.disabled = true;
});

submitBtn.addEventListener('click', async () => {
  if (!selectedFile) return;

  submitBtn.disabled = true;
  resultSection.style.display = 'none';
  errorSection.style.display = 'none';
  progressSection.style.display = 'block';
  progressFill.style.width = '5%';
  statusText.textContent = 'Загрузка файла...';

  const fd = new FormData();
  fd.append('file', selectedFile);
  fd.append('prompt', promptInput.value);

  // XHR с прогрессом (fetch не умеет upload-progress).
  // XHR стабильнее fetch для больших файлов через мобильный интернет.
  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/v1/transcribe');
  xhr.withCredentials = true;
  xhr.timeout = 0;  // нет клиентского таймаута — сервер решает

  xhr.upload.addEventListener('progress', (e) => {
    if (!e.lengthComputable) return;
    const pct = Math.min(90, Math.round(e.loaded / e.total * 90));
    progressFill.style.width = pct + '%';
    const mb = (e.loaded / 1024 / 1024).toFixed(1);
    const totalMb = (e.total / 1024 / 1024).toFixed(1);
    statusText.textContent = `Загрузка: ${mb} / ${totalMb} МБ (${pct}%)`;
  });

  xhr.upload.addEventListener('error', () => {
    showError('Ошибка сети при загрузке. Проверьте подключение и попробуйте снова.');
  });
  xhr.upload.addEventListener('abort', () => {
    showError('Загрузка прервана.');
  });

  xhr.addEventListener('load', () => {
    let data = null;
    try { data = JSON.parse(xhr.responseText); } catch (_) { /* ignore */ }
    if (xhr.status >= 200 && xhr.status < 300 && data && data.job_id) {
      currentJobId = data.job_id;
      progressFill.style.width = '95%';
      statusText.textContent = 'Принято. Обработка (M3 + DOCX)...';
      pollJob();
      return;
    }
    const detail = (data && (data.detail || data.error)) ||
                    `HTTP ${xhr.status}: ${(xhr.responseText || '').slice(0, 200)}`;
    showError('Сервер: ' + detail);
  });

  xhr.addEventListener('error', () => {
    showError('Не удалось подключиться к серверу. Проверьте интернет/URL.');
  });

  try {
    xhr.send(fd);
  } catch (e) {
    showError('Ошибка: ' + e.message);
  }
});

async function pollJob() {
  if (!currentJobId) return;
  try {
    const resp = await fetch('/api/v1/jobs/' + currentJobId, { credentials: 'include' });
    if (!resp.ok) {
      setTimeout(pollJob, 2000);
      return;
    }
    const job = await resp.json();

    if (job.status === 'completed') {
      progressFill.style.width = '100%';
      statusText.textContent = 'Готово!';
      setTimeout(() => {
        progressSection.style.display = 'none';
        showResult(job);
      }, 300);
    } else if (job.status === 'failed') {
      showError(job.error || 'Неизвестная ошибка');
    } else {
      const progressMap = { pending: 35, transcribing: 50, analyzing: 70, rendering: 90 };
      progressFill.style.width = (progressMap[job.status] || 40) + '%';
      const statusMap = {
        pending: 'В очереди...',
        transcribing: 'Транскрибация аудио...',
        analyzing: 'Анализ M3...',
        rendering: 'Генерация DOCX...',
      };
      statusText.textContent = statusMap[job.status] || job.status;
      setTimeout(pollJob, 2000);
    }
  } catch (e) {
    setTimeout(pollJob, 3000);
  }
}

function showResult(job) {
  resultSection.style.display = 'block';
  downloadLink.href = job.docx_url || ('/api/v1/download/' + job.job_id + '.docx');
  // Имя файла для скачивания — на основе оригинального имени аудио
  const dlName = job.download_name || (job.job_id + '.docx');
  downloadLink.setAttribute('download', dlName);
  downloadLink.textContent = '📥 Скачать DOCX (' + dlName + ')';
  jsonOutput.textContent = JSON.stringify({
    job_id: job.job_id,
    status: job.status,
    model_used: job.model_used,
    is_video: job.is_video,
    original_name: job.file_name,
    download_name: dlName,
    protocol: job.protocol,
  }, null, 2);
  document.getElementById('jsonDetails').open = false;
  submitBtn.disabled = false;
}

function showError(msg) {
  progressSection.style.display = 'none';
  errorSection.style.display = 'block';
  errorText.textContent = msg;
  submitBtn.disabled = false;
}

viewJsonBtn.addEventListener('click', () => {
  document.getElementById('jsonDetails').open = true;
});

newSessionBtn.addEventListener('click', () => {
  resultSection.style.display = 'none';
  selectedFile = null;
  fileInfo.style.display = 'none';
  promptInput.value = '';
  submitBtn.disabled = true;
  currentJobId = null;
  document.getElementById('jsonDetails').open = false;
});

retryBtn.addEventListener('click', () => {
  errorSection.style.display = 'none';
  if (selectedFile) submitBtn.click();
});

// === Prompt editor modal ===
const promptModal = document.getElementById('promptModal');
const promptEditor = document.getElementById('promptEditor');
const promptStatus = document.getElementById('promptStatus');
const promptMeta = document.getElementById('promptMeta');
const promptTabs = document.querySelectorAll('.prompt-tab');
let currentPromptName = 'audio';

function setPromptStatus(text, kind) {
  promptStatus.textContent = text;
  promptStatus.className = 'prompt-status' + (kind ? ' ' + kind : '');
  if (kind === 'ok') {
    setTimeout(() => { promptStatus.textContent = ''; promptStatus.className = 'prompt-status'; }, 3000);
  }
}

function updatePromptMeta() {
  const text = promptEditor.value || '';
  const lines = text ? text.split('\n').length : 0;
  promptMeta.textContent = `${text.length} символов, ${lines} строк`;
}

async function loadPrompt(name) {
  setPromptStatus('Загружаю...');
  try {
    const r = await fetch('/api/v1/prompts/' + name, { credentials: 'include' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    promptEditor.value = data.text;
    updatePromptMeta();
    setPromptStatus('Загружено', 'ok');
  } catch (e) {
    setPromptStatus('Ошибка: ' + e.message, 'err');
  }
}

promptTabs.forEach(tab => {
  tab.addEventListener('click', () => {
    promptTabs.forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    currentPromptName = tab.dataset.name;
    loadPrompt(currentPromptName);
  });
});

promptEditor.addEventListener('input', updatePromptMeta);

document.getElementById('editPromptBtn').addEventListener('click', () => {
  promptModal.hidden = false;
  loadPrompt(currentPromptName);
});

document.getElementById('promptModalClose').addEventListener('click', () => {
  promptModal.hidden = true;
});

promptModal.addEventListener('click', (e) => {
  if (e.target === promptModal) promptModal.hidden = true;
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !promptModal.hidden) promptModal.hidden = true;
});

document.getElementById('promptSaveBtn').addEventListener('click', async () => {
  const text = promptEditor.value.trim();
  if (!text) { setPromptStatus('Промпт не может быть пустым', 'err'); return; }
  setPromptStatus('Сохраняю...');
  try {
    const r = await fetch('/api/v1/prompts/' + currentPromptName, {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text })
    });
    if (!r.ok) throw new Error('HTTP ' + r.status + ': ' + (await r.text()).slice(0, 200));
    const data = await r.json();
    updatePromptMeta();
    setPromptStatus(`✓ Сохранено (${data.length} символов). Вступит в силу со следующей задачи.`, 'ok');
  } catch (e) {
    setPromptStatus('Ошибка: ' + e.message, 'err');
  }
});

document.getElementById('promptResetBtn').addEventListener('click', async () => {
  if (!confirm('Сбросить "' + currentPromptName + '"-промпт на дефолтный?')) return;
  setPromptStatus('Сбрасываю...');
  try {
    const r = await fetch('/api/v1/prompts/' + currentPromptName + '/reset', {
      method: 'POST',
      credentials: 'include'
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    await loadPrompt(currentPromptName);
  } catch (e) {
    setPromptStatus('Ошибка: ' + e.message, 'err');
  }
});
