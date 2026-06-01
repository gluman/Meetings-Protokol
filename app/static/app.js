// Meeting Protocol — клиентский JS

// === Auth ===
const API_KEY_STORAGE = 'meeting_protocol_api_key';
let apiKey = localStorage.getItem(API_KEY_STORAGE) || '';

const authSection = document.getElementById('authSection');
const apiKeyInput = document.getElementById('apiKeyInput');
const saveKeyBtn = document.getElementById('saveKeyBtn');
const authStatus = document.getElementById('authStatus');

function updateAuthStatus() {
  if (apiKey) {
    authStatus.textContent = '✓ Ключ сохранён. Можно загружать файлы.';
    authStatus.className = 'auth-status auth-ok';
    apiKeyInput.value = '••••••••';
  } else {
    authStatus.textContent = '⚠ Ключ не задан. Запросы будут отклонены сервером.';
    authStatus.className = 'auth-status auth-warn';
    apiKeyInput.value = '';
  }
}
updateAuthStatus();

saveKeyBtn.addEventListener('click', () => {
  const v = apiKeyInput.value.trim();
  if (v && v !== '••••••••') {
    apiKey = v;
    localStorage.setItem(API_KEY_STORAGE, apiKey);
  } else if (apiKeyInput.value === '') {
    apiKey = '';
    localStorage.removeItem(API_KEY_STORAGE);
  }
  updateAuthStatus();
});

apiKeyInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') saveKeyBtn.click();
});

function authHeaders() {
  const h = {};
  if (apiKey) h['Authorization'] = 'Bearer ' + apiKey;
  return h;
}

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
  if (!apiKey) {
    showError('Сначала введите API-ключ в разделе Авторизация');
    return;
  }

  submitBtn.disabled = true;
  resultSection.style.display = 'none';
  errorSection.style.display = 'none';
  progressSection.style.display = 'block';
  progressFill.style.width = '10%';
  statusText.textContent = 'Загрузка файла...';

  const fd = new FormData();
  fd.append('file', selectedFile);
  fd.append('prompt', promptInput.value);

  try {
    const resp = await fetch('/api/v1/transcribe', {
      method: 'POST',
      body: fd,
      headers: authHeaders(),
    });
    const data = await resp.json();
    if (!resp.ok) {
      if (resp.status === 401 || resp.status === 403) {
        throw new Error('Неверный API-ключ. Проверьте раздел "Авторизация".');
      }
      throw new Error(data.detail || 'Upload failed');
    }

    currentJobId = data.job_id;
    statusText.textContent = 'Обработка (M3 + DOCX)...';
    progressFill.style.width = '30%';
    pollJob();
  } catch (e) {
    showError('Ошибка: ' + e.message);
  }
});

async function pollJob() {
  if (!currentJobId) return;
  try {
    const resp = await fetch('/api/v1/jobs/' + currentJobId, { headers: authHeaders() });
    if (!resp.ok) {
      if (resp.status === 401 || resp.status === 403) {
        showError('Неверный API-ключ');
        return;
      }
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
  downloadLink.textContent = '📥 Скачать DOCX (' + job.job_id + ')';
  jsonOutput.textContent = JSON.stringify({
    job_id: job.job_id,
    status: job.status,
    model_used: job.model_used,
    is_video: job.is_video,
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
