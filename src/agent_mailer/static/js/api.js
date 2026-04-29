// --- API helpers ---
async function api(path, opts) {
  const options = { credentials: 'same-origin', ...opts };
  const resp = await fetch(BASE + path, options);
  if (resp.status === 401) {
    clearSessionCookie();
    showLoginPage();
    throw new Error(t('login.errorSessionExpired'));
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

async function fetchInbox(address, page, pageSize, fromTeamId) {
  let url = `/admin/messages/inbox/${encodeURIComponent(address)}?all=true`;
  if (page != null) url += `&page=${page}&page_size=${pageSize || 20}`;
  if (fromTeamId) url += `&from_team_id=${encodeURIComponent(fromTeamId)}`;
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

// --- Team Memories ---
async function fetchTeamMemories(teamId) {
  return api(`/admin/teams/${encodeURIComponent(teamId)}/memories`);
}

async function createTeamMemory(teamId, data) {
  return api(`/admin/teams/${encodeURIComponent(teamId)}/memories`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

async function updateTeamMemory(teamId, memoryId, data) {
  return api(`/admin/teams/${encodeURIComponent(teamId)}/memories/${encodeURIComponent(memoryId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

async function upsertTeamMemory(teamId, data) {
  return api(`/admin/teams/${encodeURIComponent(teamId)}/memories/upsert`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

async function deleteTeamMemory(teamId, memoryId) {
  return api(`/admin/teams/${encodeURIComponent(teamId)}/memories/${encodeURIComponent(memoryId)}`, {
    method: 'DELETE',
  });
}
