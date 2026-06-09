// Glossaries UI — CRUD для глоссариев, entries, share, copy, candidates
// Backend: /api/v1/glossaries/* (см. app/api_glossaries.py)

const API_BASE = "/api/v1";

// State
let currentUser = null;
let glossariesCache = []; // [{id, name, is_shared, owner_id, entry_count, ...}]
let entriesCache = {};     // glossaryId -> [{id, term, abbreviation, description, needs_review}]

// ---------------------------------------------------------------------------
// Auth helpers
// ---------------------------------------------------------------------------
async function fetchMe() {
  try {
    const r = await fetch("/web/check");
    if (r.ok) {
      const data = await r.json();
      currentUser = data.user || null;
      return data;
    }
  } catch (e) {
    console.warn("fetchMe failed:", e);
  }
  return null;
}

function renderUserBar() {
  const info = document.getElementById("userInfo");
  if (currentUser) {
    info.textContent = `👤 ${currentUser.username || currentUser}`;
  } else {
    info.textContent = "👤 (не авторизован)";
  }
}

document.getElementById("logoutBtn").addEventListener("click", async () => {
  await fetch("/web/logout", { method: "POST" });
  window.location.href = "/";
});

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------
async function apiListGlossaries() {
  const r = await fetch(`${API_BASE}/glossaries`, { credentials: "include" });
  if (!r.ok) throw new Error(`list glossaries: ${r.status}`);
  const data = await r.json();
  // API returns: {glossaries: [...], total: N}
  return data.glossaries || data || [];
}

async function apiCreateGlossary(name, isShared) {
  const r = await fetch(`${API_BASE}/glossaries`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, is_shared: isShared }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.detail || `create: ${r.status}`);
  }
  return r.json();
}

async function apiUpdateGlossary(id, payload) {
  const r = await fetch(`${API_BASE}/glossaries/${id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`update: ${r.status}`);
  return r.json();
}

async function apiDeleteGlossary(id) {
  const r = await fetch(`${API_BASE}/glossaries/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!r.ok && r.status !== 204) throw new Error(`delete: ${r.status}`);
}

async function apiCopyGlossary(id) {
  const r = await fetch(`${API_BASE}/glossaries/${id}/copy`, {
    method: "POST",
    credentials: "include",
  });
  if (!r.ok) throw new Error(`copy: ${r.status}`);
  return r.json();
}

async function apiListEntries(glossaryId) {
  const r = await fetch(`${API_BASE}/glossaries/${glossaryId}/entries`, {
    credentials: "include",
  });
  if (!r.ok) throw new Error(`list entries: ${r.status}`);
  const data = await r.json();
  return data.entries || data || [];
}

async function apiCreateEntry(glossaryId, term, abbreviation, description, needsReview) {
  const r = await fetch(`${API_BASE}/glossaries/${glossaryId}/entries`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      term,
      abbreviation: abbreviation || null,
      description: description || null,
      needs_review: needsReview || false,
    }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.detail || `create entry: ${r.status}`);
  }
  return r.json();
}

async function apiUpdateEntry(entryId, payload) {
  const r = await fetch(`${API_BASE}/glossary-entries/${entryId}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`update entry: ${r.status}`);
  return r.json();
}

async function apiDeleteEntry(entryId) {
  const r = await fetch(`${API_BASE}/glossary-entries/${entryId}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!r.ok && r.status !== 204) throw new Error(`delete entry: ${r.status}`);
}

async function apiToggleNeedsReview(entryId) {
  const r = await fetch(
    `${API_BASE}/glossary-entries/${entryId}/toggle-needs-review`,
    { method: "POST", credentials: "include" }
  );
  if (!r.ok) throw new Error(`toggle: ${r.status}`);
  return r.json();
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------
function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderGlossaries() {
  const root = document.getElementById("glossaryList");
  if (!glossariesCache.length) {
    root.innerHTML = '<p class="empty-state">Нет глоссариев. Создайте первый выше ⬆️</p>';
    return;
  }
  let html = "";
  for (const g of glossariesCache) {
    const isOwner = currentUser && g.owner_id === currentUser.id;
    const entries = entriesCache[g.id] || [];
    html += `
      <div class="gloss-card ${g.is_shared ? "shared" : ""}">
        <div class="gloss-card-header">
          <div>
            <div class="gloss-card-name">
              ${escapeHtml(g.name)}
              <span class="badge ${g.is_shared ? "badge-shared" : "badge-private"}">
                ${g.is_shared ? "🌐 общий" : "🔒 личный"}
              </span>
              ${isOwner ? '<span class="badge badge-owner">мой</span>' : ""}
            </div>
            <div class="gloss-card-meta">
              ${entries.length} термин${entries.length === 1 ? "" : entries.length < 5 ? "а" : "ов"} ·
              владелец: ${escapeHtml(g.owner_username || g.owner_id)}
            </div>
          </div>
          <div class="gloss-card-actions">
            <button class="btn-secondary" data-action="add-entry" data-gid="${g.id}">+ Термин</button>
            <button class="btn-secondary" data-action="copy" data-gid="${g.id}">📋 Копия</button>
            ${isOwner ? `
              <button class="btn-secondary" data-action="edit" data-gid="${g.id}">✏️</button>
              <button class="btn-secondary" data-action="delete" data-gid="${g.id}">🗑️</button>
            ` : ""}
          </div>
        </div>
        ${entries.length ? renderEntriesTable(entries, isOwner) : '<p class="empty-state" style="padding:0.5rem">Пока нет терминов</p>'}
      </div>
    `;
  }
  root.innerHTML = html;
  attachGlossaryActionHandlers();
}

function renderEntriesTable(entries, isOwner) {
  let rows = "";
  for (const e of entries) {
    rows += `
      <tr>
        <td class="term">${escapeHtml(e.term)}</td>
        <td class="abbr">${escapeHtml(e.abbreviation || "")}</td>
        <td class="desc">${escapeHtml(e.description || "")}</td>
        <td class="needs-review">
          ${e.needs_review ? '<span class="needs-review-flag">⚠️ требует проверки</span>' : ""}
        </td>
        <td class="actions">
          <button data-action="toggle-review" data-eid="${e.id}" data-gid="${e.glossary_id}">${e.needs_review ? "✓ ok" : "⚠️ flag"}</button>
          ${isOwner ? `
            <button data-action="edit-entry" data-eid="${e.id}" data-gid="${e.glossary_id}">✏️</button>
            <button data-action="delete-entry" data-eid="${e.id}">🗑️</button>
          ` : ""}
        </td>
      </tr>
    `;
  }
  return `
    <table class="entries-table">
      <thead>
        <tr>
          <th>Термин</th>
          <th>Аббревиатура</th>
          <th>Описание</th>
          <th>⚠️</th>
          <th></th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

// ---------------------------------------------------------------------------
// Action handlers (event delegation on the list root)
// ---------------------------------------------------------------------------
function attachGlossaryActionHandlers() {
  const root = document.getElementById("glossaryList");
  root.querySelectorAll("button[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => handleAction(btn.dataset));
  });
}

async function handleAction(ds) {
  const gid = parseInt(ds.gid, 10);
  const eid = ds.eid ? parseInt(ds.eid, 10) : null;
  try {
    switch (ds.action) {
      case "add-entry":
        openEntryModal(gid, null);
        break;
      case "edit-entry":
        const entries = entriesCache[gid] || [];
        const entry = entries.find((x) => x.id === eid);
        if (entry) openEntryModal(gid, entry);
        break;
      case "delete-entry":
        if (!confirm("Удалить термин?")) return;
        await apiDeleteEntry(eid);
        await loadEntries(gid);
        renderGlossaries();
        break;
      case "toggle-review":
        await apiToggleNeedsReview(eid);
        await loadEntries(gid);
        renderGlossaries();
        break;
      case "copy":
        await apiCopyGlossary(gid);
        await reload();
        break;
      case "edit":
        const g = glossariesCache.find((x) => x.id === gid);
        if (g) openGlossaryModal(g);
        break;
      case "delete":
        if (!confirm(`Удалить глоссарий "${glossariesCache.find(x=>x.id===gid)?.name}"? Все термины будут потеряны.`)) return;
        await apiDeleteGlossary(gid);
        await reload();
        break;
    }
  } catch (e) {
    alert(`Ошибка: ${e.message}`);
  }
}

// ---------------------------------------------------------------------------
// Modals
// ---------------------------------------------------------------------------
function openEntryModal(glossaryId, entry) {
  document.getElementById("entryModalTitle").textContent = entry ? "Редактировать термин" : "Добавить термин";
  document.getElementById("entryId").value = entry ? entry.id : "";
  document.getElementById("entryGlossaryId").value = glossaryId;
  document.getElementById("entryTerm").value = entry ? entry.term : "";
  document.getElementById("entryAbbreviation").value = entry ? (entry.abbreviation || "") : "";
  document.getElementById("entryDescription").value = entry ? (entry.description || "") : "";
  document.getElementById("entryNeedsReview").checked = entry ? !!entry.needs_review : false;
  document.getElementById("entryFormStatus").textContent = "";
  document.getElementById("entryModal").style.display = "flex";
}

function closeEntryModal() {
  document.getElementById("entryModal").style.display = "none";
}

document.getElementById("entryCancelBtn").addEventListener("click", closeEntryModal);
document.getElementById("entryModal").addEventListener("click", (e) => {
  if (e.target.id === "entryModal") closeEntryModal();
});

document.getElementById("entryForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const status = document.getElementById("entryFormStatus");
  const entryId = document.getElementById("entryId").value;
  const gid = parseInt(document.getElementById("entryGlossaryId").value, 10);
  const term = document.getElementById("entryTerm").value.trim();
  const abbr = document.getElementById("entryAbbreviation").value.trim();
  const desc = document.getElementById("entryDescription").value.trim();
  const needs = document.getElementById("entryNeedsReview").checked;
  if (!term) { status.textContent = "❌ Термин обязателен"; return; }
  try {
    if (entryId) {
      await apiUpdateEntry(parseInt(entryId, 10), {
        term, abbreviation: abbr || null, description: desc || null, needs_review: needs,
      });
    } else {
      await apiCreateEntry(gid, term, abbr, desc, needs);
    }
    closeEntryModal();
    await loadEntries(gid);
    renderGlossaries();
  } catch (e) {
    status.textContent = `❌ ${e.message}`;
  }
});

function openGlossaryModal(g) {
  document.getElementById("editGlossaryId").value = g.id;
  document.getElementById("editGlossaryName").value = g.name;
  document.getElementById("editGlossaryShared").checked = !!g.is_shared;
  document.getElementById("glossaryFormStatus").textContent = "";
  document.getElementById("glossaryModal").style.display = "flex";
}

function closeGlossaryModal() {
  document.getElementById("glossaryModal").style.display = "none";
}

document.getElementById("glossaryCancelBtn").addEventListener("click", closeGlossaryModal);
document.getElementById("glossaryModal").addEventListener("click", (e) => {
  if (e.target.id === "glossaryModal") closeGlossaryModal();
});

document.getElementById("glossaryForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = parseInt(document.getElementById("editGlossaryId").value, 10);
  const name = document.getElementById("editGlossaryName").value.trim();
  const isShared = document.getElementById("editGlossaryShared").checked;
  const status = document.getElementById("glossaryFormStatus");
  if (!name) { status.textContent = "❌ Название обязательно"; return; }
  try {
    await apiUpdateGlossary(id, { name, is_shared: isShared });
    closeGlossaryModal();
    await reload();
  } catch (e) {
    status.textContent = `❌ ${e.message}`;
  }
});

// ---------------------------------------------------------------------------
// Create glossary button
// ---------------------------------------------------------------------------
document.getElementById("createGlossaryBtn").addEventListener("click", async () => {
  const name = document.getElementById("newGlossaryName").value.trim();
  const isShared = document.getElementById("newGlossaryShared").checked;
  const status = document.getElementById("createStatus");
  if (!name) { status.textContent = "❌ Введите название"; return; }
  try {
    await apiCreateGlossary(name, isShared);
    document.getElementById("newGlossaryName").value = "";
    document.getElementById("newGlossaryShared").checked = false;
    status.textContent = "✅ Создано";
    await reload();
  } catch (e) {
    status.textContent = `❌ ${e.message}`;
  }
});

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------
async function loadEntries(gid) {
  try {
    entriesCache[gid] = await apiListEntries(gid);
  } catch (e) {
    console.error(`loadEntries(${gid}) failed:`, e);
    entriesCache[gid] = [];
  }
}

async function reload() {
  glossariesCache = await apiListGlossaries();
  // load entries for each glossary in parallel
  await Promise.all(glossariesCache.map((g) => loadEntries(g.id)));
  renderGlossaries();
}

(async function init() {
  await fetchMe();
  renderUserBar();
  try {
    await reload();
  } catch (e) {
    document.getElementById("glossaryList").innerHTML =
      `<p class="empty-state">Ошибка загрузки: ${e.message}</p>`;
  }
})();
