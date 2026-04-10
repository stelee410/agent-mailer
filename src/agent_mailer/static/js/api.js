// --- API helpers ---
async function api(path, opts) {
  const options = { credentials: 'same-origin', ...opts };
  const resp = await fetch(BASE + path, options);
  if (resp.status === 401) {
    clearSessionCookie();
    showLoginPage();
    throw new Error('Session expired. Please log in again.');
  }
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || resp.statusText);
  }
  return resp.json();
}

// --- Data fetching ---
async function fetchStats() {
  statsData = await api('/admin/agents/stats');
  return statsData;
}

async function fetchAgents() {
  agents = await api('/admin/agents');
  return agents;
}

async function fetchInbox(address, page, pageSize) {
  let url = `/admin/messages/inbox/${encodeURIComponent(address)}?all=true`;
  if (page != null) url += `&page=${page}&page_size=${pageSize || 20}`;
  return api(url);
}

async function fetchThread(threadId) {
  return api(`/admin/messages/thread/${encodeURIComponent(threadId)}`);
}

async function fetchThreadsSummary(opts = {}) {
  const { archived = false, trashed = false } = opts;
  let q = '';
  if (trashed) q = '?trashed=true';
  else if (archived) q = '?archived=true';
  threadsData = await api('/admin/threads/summary' + q);
  return threadsData;
}

async function fetchTrashedMessages() {
  trashedMessagesData = await api('/admin/trash/messages');
  return trashedMessagesData;
}
