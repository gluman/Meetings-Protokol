// Admin panel logic
// - tabs
// - users CRUD (create, change role, activate/deactivate, delete, reset password)
// - settings override (read all, edit/save, revert to .env)
// - info panel (me, storage path, db size)

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function toast(msg, type = 'ok', ms = 3500) {
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), ms);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || err.error || `HTTP ${res.status}`);
  }
  return res.json();
}

// --- Auth check -----------------------------------------------------------
async function checkAuth() {
  try {
    const me = await api('/web/api/v1/admin/me');
    $('#userInfo').textContent = `${me.user || '(guest)'} · ${me.role || 'no-role'}`;
    if (!me.is_admin) {
      $('#notAdminWarning').style.display = 'block';
      $('#adminContent').style.display = 'none';
      return false;
    }
    $('#adminContent').style.display = 'block';
    return true;
  } catch (e) {
    if (e.message.includes('401') || e.message.includes('no session')) {
      window.location.href = '/static/login.html';
    } else {
      toast('Ошибка авторизации: ' + e.message, 'err');
    }
    return false;
  }
}

// --- Tabs -----------------------------------------------------------------
function initTabs() {
  $$('.admin-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      const panel = btn.dataset.panel;
      $$('.admin-tab').forEach(b => b.classList.toggle('active', b === btn));
      $$('.admin-panel').forEach(p => p.classList.toggle('active', p.id === `panel-${panel}`));
      if (panel === 'settings') loadSettings();
      if (panel === 'info') loadInfo();
    });
  });
}

// --- Logout ---------------------------------------------------------------
function initLogout() {
  $('#logoutBtn').addEventListener('click', async () => {
    try {
      await api('/web/logout', { method: 'POST' });
    } catch {}
    window.location.href = '/static/login.html';
  });
}

// --- USERS ----------------------------------------------------------------
async function loadUsers() {
  try {
    const users = await api('/web/api/v1/admin/users');
    const tbody = $('#usersTable tbody');
    tbody.innerHTML = '';
    for (const u of users) {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${u.id}</td>
        <td><b>${escapeHtml(u.username)}</b></td>
        <td><span class="role-${u.role}">${u.role}</span></td>
        <td>${u.is_active ? '<span class="status-active">● active</span>' : '<span class="status-inactive">○ inactive</span>'}</td>
        <td><small>${(u.created_at || '').slice(0, 19).replace('T', ' ')}</small></td>
        <td><small>${u.last_login_at ? u.last_login_at.slice(0, 19).replace('T', ' ') : '—'}</small></td>
        <td>
          <button data-act="role" data-id="${u.id}" data-role="${u.role}">Сменить роль</button>
          <button data-act="toggle" data-id="${u.id}" data-active="${u.is_active}">${u.is_active ? 'Деактивировать' : 'Активировать'}</button>
          <button data-act="reset" data-id="${u.id}">Сброс пароля</button>
          <button data-act="del" data-id="${u.id}" data-name="${escapeHtml(u.username)}" style="color:#dc2626;">Удалить</button>
        </td>
      `;
      tbody.appendChild(tr);
    }
  } catch (e) {
    toast('Ошибка загрузки пользователей: ' + e.message, 'err');
  }
}

function initUsers() {
  $('#createUserForm').addEventListener('submit', async e => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      await api('/web/api/v1/admin/users', {
        method: 'POST',
        body: JSON.stringify({
          username: fd.get('username'),
          password: fd.get('password'),
          role: fd.get('role'),
        }),
      });
      toast('Пользователь создан', 'ok');
      e.target.reset();
      loadUsers();
    } catch (err) {
      toast('Ошибка: ' + err.message, 'err');
    }
  });

  $('#usersTable').addEventListener('click', async e => {
    const btn = e.target.closest('button');
    if (!btn) return;
    const id = parseInt(btn.dataset.id);
    const act = btn.dataset.act;
    try {
      if (act === 'role') {
        const cur = btn.dataset.role;
        const next = cur === 'admin' ? 'editor' : cur === 'editor' ? 'viewer' : 'admin';
        await api(`/web/api/v1/admin/users/${id}`, {
          method: 'PUT',
          body: JSON.stringify({ role: next }),
        });
        toast(`Роль изменена: ${cur} → ${next}`, 'ok');
        loadUsers();
      } else if (act === 'toggle') {
        const isActive = btn.dataset.active === '1' || btn.dataset.active === 'true';
        await api(`/web/api/v1/admin/users/${id}`, {
          method: 'PUT',
          body: JSON.stringify({ is_active: !isActive }),
        });
        toast(isActive ? 'Деактивирован' : 'Активирован', 'ok');
        loadUsers();
      } else if (act === 'reset') {
        const r = await api(`/web/api/v1/admin/users/${id}/reset-password`, { method: 'POST' });
        prompt(`Новый пароль для ${r.username}:\n\n${r.new_password}\n\nСкопируйте сейчас — больше не покажем.`);
      } else if (act === 'del') {
        if (!confirm(`Удалить пользователя "${btn.dataset.name}"? Это необратимо.`)) return;
        await api(`/web/api/v1/admin/users/${id}`, { method: 'DELETE' });
        toast('Удалён', 'ok');
        loadUsers();
      }
    } catch (err) {
      toast('Ошибка: ' + err.message, 'err');
    }
  });
}

// --- SETTINGS -------------------------------------------------------------
async function loadSettings() {
  const list = $('#settingsList');
  list.innerHTML = '<p>Загрузка…</p>';
  try {
    const items = await api('/web/api/v1/admin/settings');
    list.innerHTML = '';
    for (const it of items) {
      const div = document.createElement('div');
      div.className = 'admin-setting';
      const isSecret = it.secret;
      const dispVal = isSecret && it.effective_value ? '••••••••' : (it.effective_value || '(пусто)');
      const badge = it.is_overridden
        ? '<span class="override-badge">override</span>'
        : '<span class="env-badge">env</span>';
      div.innerHTML = `
        <div class="label-block">
          <b>${escapeHtml(it.label)}</b>
          <small><code>${it.key}</code> · ${it.type} ${badge}</small>
        </div>
        <div class="value-input">
          <input type="${isSecret ? 'password' : 'text'}"
                 data-key="${it.key}" data-secret="${isSecret}"
                 value="${escapeHtml(dispVal)}"
                 placeholder="${isSecret ? '(скрыто)' : ''}"
                 ${isSecret ? 'autocomplete="new-password"' : ''}>
        </div>
        <div class="actions">
          <button data-act="save" data-key="${it.key}">💾</button>
          ${it.is_overridden ? `<button data-act="revert" data-key="${it.key}">↩</button>` : ''}
        </div>
      `;
      list.appendChild(div);
    }
  } catch (e) {
    list.innerHTML = `<p style="color:#dc2626;">Ошибка: ${e.message}</p>`;
  }
}

function initSettings() {
  $('#settingsList').addEventListener('click', async e => {
    const btn = e.target.closest('button');
    if (!btn) return;
    const key = btn.dataset.key;
    const act = btn.dataset.act;
    try {
      if (act === 'save') {
        const input = $(`input[data-key="${key}"]`);
        const isSecret = input.dataset.secret === 'true';
        const val = input.value;
        // Для секретов: пустая строка = не менять
        if (isSecret && (val === '' || val === '••••••••')) {
          toast('Секрет не изменён (пустое значение)', 'info');
          return;
        }
        await api(`/web/api/v1/admin/settings/${key}`, {
          method: 'PUT',
          body: JSON.stringify({ value: val }),
        });
        toast(`"${key}" сохранено`, 'ok');
        loadSettings();
      } else if (act === 'revert') {
        if (!confirm(`Вернуть "${key}" к значению из .env?`)) return;
        await api(`/web/api/v1/admin/settings/${key}`, { method: 'DELETE' });
        toast(`"${key}" возвращён к .env`, 'ok');
        loadSettings();
      }
    } catch (err) {
      toast('Ошибка: ' + err.message, 'err');
    }
  });
}

// --- INFO -----------------------------------------------------------------
async function loadInfo() {
  const c = $('#infoContent');
  c.innerHTML = '<p>Загрузка…</p>';
  try {
    const me = await api('/web/api/v1/admin/me');
    c.innerHTML = `
      <table class="admin-table">
        <tr><th>Текущий пользователь</th><td>${escapeHtml(me.user || '(none)')}</td></tr>
        <tr><th>Роль</th><td><span class="role-${me.role}">${me.role || '—'}</span></td></tr>
        <tr><th>Web-auth</th><td>${me.auth_enabled ? '✅ включён' : '❌ выключен (dev)'}</td></tr>
        <tr><th>Сервис</th><td>Meeting Protocol</td></tr>
        <tr><th>Версия</th><td>2.0</td></tr>
      </table>
      <h3 style="margin-top: 1.5rem;">Безопасность</h3>
      <ul style="line-height: 1.8;">
        <li>Пароли хэшируются через <code>pbkdf2_hmac(sha256, 200k iterations)</code></li>
        <li>JWT подписан HMAC-SHA256, TTL = ${me.ttl_hours || 24}ч</li>
        <li>Cookies: <code>httponly=true, samesite=lax</code></li>
        <li>RBAC: 3 роли (admin/editor/viewer)</li>
        <li>Защита от удаления последнего админа</li>
        <li>Сброс пароля возвращает plaintext ОДИН РАЗ</li>
      </ul>
    `;
  } catch (e) {
    c.innerHTML = `<p style="color:#dc2626;">Ошибка: ${e.message}</p>`;
  }
}

// --- helpers --------------------------------------------------------------
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// --- init -----------------------------------------------------------------
(async function () {
  initLogout();
  initTabs();
  initUsers();
  initSettings();
  if (await checkAuth()) {
    loadUsers();
  }
})();
