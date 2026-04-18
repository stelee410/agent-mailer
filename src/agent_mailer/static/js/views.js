function _paginateList(items, page, pageSize) {
  pageSize = pageSize || 20;
  const total = items.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const start = (page - 1) * pageSize;
  return { items: items.slice(start, start + pageSize), total, page, totalPages };
}

function _paginationHtml(page, totalPages, total, onClickFn) {
  if (totalPages <= 1) return '';
  return `<div class="pagination">
    <button class="btn btn-secondary pagination-btn" ${page <= 1 ? 'disabled' : ''} onclick="${onClickFn}(${page - 1})">&laquo; Prev</button>
    <span class="pagination-info">Page ${page} / ${totalPages} (${total} total)</span>
    <button class="btn btn-secondary pagination-btn" ${page >= totalPages ? 'disabled' : ''} onclick="${onClickFn}(${page + 1})">Next &raquo;</button>
  </div>`;
}

// --- Search ---

async function showSearch(query, page) {
  clearNav();
  document.getElementById('navSearch').classList.add('active');
  setSidebarSpecialMode('none');
  currentView = { type: 'search', query: query || '', page: page || 1 };
  if (query) {
    location.hash = `search?q=${encodeURIComponent(query)}`;
  }
  renderSearchPage();
  if (query) await doSearch();
}

function renderSearchPage() {
  const main = document.getElementById('main');
  const q = currentView.query || '';
  main.innerHTML = `
    <div class="card">
      <h2>Search</h2>
      <div class="compose-form">
        <div>
          <label>Keyword</label>
          <input type="text" id="searchInput" placeholder="Search messages by subject or body..." value="${esc(q)}">
        </div>
        <div>
          <button class="btn btn-primary" onclick="doSearch()">Search</button>
        </div>
      </div>
      <div id="searchResults"></div>
    </div>`;
  document.getElementById('searchInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') doSearch();
  });
}

async function doSearch(page) {
  const input = document.getElementById('searchInput');
  const q = input ? input.value.trim() : '';
  if (!q) return;
  page = page || 1;
  currentView.query = q;
  currentView.page = page;
  location.hash = `search?q=${encodeURIComponent(q)}`;
  const results = document.getElementById('searchResults');
  results.innerHTML = '<p>Searching...</p>';
  try {
    const data = await api(`/admin/search?q=${encodeURIComponent(q)}&page=${page}&page_size=20`);
    if (data.messages.length === 0) {
      results.innerHTML = '<p class="empty" style="padding:16px 0">No results found.</p>';
      return;
    }
    const highlightSnippet = (text, query) => {
      const re = new RegExp('(' + query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
      return esc(text).replace(re, '<mark>$1</mark>');
    };
    results.innerHTML = `
      <div class="stats-table-wrap" style="margin-top:16px">
      <table class="stats-table">
        <thead><tr><th>Subject</th><th>Snippet</th><th>From</th><th>Date</th></tr></thead>
        <tbody>${data.messages.map(m => `
          <tr style="cursor:pointer" onclick="showThreadsThread('${esc(m.thread_id)}')">
            <td><strong>${esc(m.subject) || '(no subject)'}</strong></td>
            <td style="font-size:12px;max-width:300px;overflow:hidden;text-overflow:ellipsis">${highlightSnippet(m.body_snippet, q)}</td>
            <td style="color:var(--muted)">${esc(m.from_agent)}</td>
            <td style="color:var(--muted)">${esc(fmtTime(m.created_at))}</td>
          </tr>
        `).join('')}</tbody>
      </table>
      </div>
      ${data.total_pages > 1 ? `<div class="pagination">
        <button class="btn btn-secondary pagination-btn" ${page <= 1 ? 'disabled' : ''} onclick="doSearch(${page - 1})">&laquo; Prev</button>
        <span class="pagination-info">Page ${data.page} / ${data.total_pages} (${data.total} results)</span>
        <button class="btn btn-secondary pagination-btn" ${page >= data.total_pages ? 'disabled' : ''} onclick="doSearch(${page + 1})">Next &raquo;</button>
      </div>` : ''}`;
  } catch (e) {
    results.innerHTML = '<p class="empty">Error: ' + esc(e.message) + '</p>';
  }
}

// Handle URL hash for search persistence
window.addEventListener('hashchange', () => {
  const hash = location.hash;
  if (hash.startsWith('#search?q=')) {
    const q = decodeURIComponent(hash.substring('#search?q='.length));
    if (currentView?.type !== 'search' || currentView.query !== q) {
      showSearch(q);
    }
  }
});

// --- Image preview ---

function previewImage(url, filename) {
  const overlay = document.createElement('div');
  overlay.className = 'image-preview-overlay';
  overlay.innerHTML = `
    <div class="image-preview-box">
      <div class="image-preview-header">
        <span>${esc(filename)}</span>
        <button class="compose-modal-close" onclick="this.closest('.image-preview-overlay').remove()">&times;</button>
      </div>
      <img src="${esc(url)}" class="image-preview-img" alt="${esc(filename)}">
    </div>`;
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
  document.body.appendChild(overlay);
}

// --- Threads view ---

async function showThreads(page) {
  clearNav();
  document.getElementById('navThreads').classList.add('active');
  setSidebarSpecialMode('none');
  currentView = { type: 'threads', page: page || 1 };
  document.getElementById('main').innerHTML = '<div class="card"><h2>Threads</h2><p>Loading...</p></div>';
  try {
    await renderThreadsMain();
  } catch (e) {
    document.getElementById('main').innerHTML = '<div class="card"><h2>Threads</h2><p class="empty">Error: ' + (e.message || e) + '</p></div>';
  }
}

async function renderThreadsMain() {
  if (currentView?.type !== 'threads') return;
  const main = document.getElementById('main');
  try {
    await fetchThreadsSummary({});
  } catch (e) {
    main.innerHTML = '<div class="card"><h2>Threads</h2><p class="empty">Failed to load: ' + esc(e.message) + '</p></div>';
    return;
  }
  if (threadsData.length === 0) {
    main.innerHTML = '<div class="card"><h2>Threads</h2><p class="empty" style="padding:24px 0;text-align:center">No threads yet.</p></div>';
    return;
  }
  const pg = _paginateList(threadsData, currentView.page || 1);
  main.innerHTML = `
    <div class="card">
      <h2>Threads</h2>
      <div class="stats-table-wrap">
      <table class="stats-table">
        <thead><tr><th>Subject</th><th>Messages</th><th>Unread</th><th>Last Activity</th></tr></thead>
        <tbody>${pg.items.map(t => `
          <tr style="cursor:pointer" onclick="showThreadsThread('${esc(t.thread_id)}')">
            <td><strong>${esc(t.preview_subject) || '(no subject)'}</strong></td>
            <td class="stat-num">${t.message_count}</td>
            <td class="stat-num" style="color:${t.unread_count > 0 ? 'var(--danger)' : 'inherit'};font-weight:${t.unread_count > 0 ? '600' : 'normal'}">${t.unread_count}</td>
            <td style="color:var(--muted)">${esc(fmtTime(t.last_activity))}</td>
          </tr>
        `).join('')}</tbody>
      </table>
      </div>
      ${_paginationHtml(pg.page, pg.totalPages, pg.total, 'showThreads')}
    </div>`;
}

async function showThreadsThread(threadId) {
  currentView = { type: 'threadsThread', threadId };
  const main = document.getElementById('main');
  main.innerHTML = '<div class="card"><p>Loading...</p></div>';
  try {
    const msgs = await fetchThread(threadId);
    main.innerHTML = _renderThreadDetail(msgs, threadId, 'showThreads()', 'threads');
    hydrateMarkdownBodies(main);
  } catch (e) {
    main.innerHTML = `<div class="card"><button type="button" class="back-btn" onclick="showThreads()">&larr; Back</button><p class="empty">Error: ${esc(e.message)}</p></div>`;
  }
}

let _lastThreadMsg = null;

function _replyToThread() {
  if (!_lastThreadMsg) return;
  const m = _lastThreadMsg;
  showCompose(m.from_agent, 'Re: ' + m.subject, m.id, m.body, m.body_html, {mode:'reply'});
}

function _forwardFromThread() {
  if (!_lastThreadMsg) return;
  const m = _lastThreadMsg;
  showCompose('', 'Fwd: ' + m.subject, m.id, null, null, {mode:'forward'});
}

function _renderThreadDetail(msgs, threadId, backFn, context) {
  context = context || 'threads';
  const lastMsg = msgs[msgs.length - 1];
  _lastThreadMsg = lastMsg;
  let actionsHtml = '';
  if (context === 'threads') {
    actionsHtml = `
      <button class="btn btn-secondary" onclick="_replyToThread()">Reply</button>
      <button class="btn btn-secondary" onclick="_forwardFromThread()">Forward</button>
      <button class="btn btn-secondary" onclick="archiveThreadAction('${esc(threadId)}', '${esc(backFn)}')">Archive</button>
      <button class="btn btn-danger" onclick="trashThreadAction('${esc(threadId)}', '${esc(backFn)}')">Delete</button>`;
  } else if (context === 'archive') {
    actionsHtml = `
      <button class="btn btn-secondary" onclick="unarchiveThreadAction('${esc(threadId)}', '${esc(backFn)}')">UnArchive</button>
      <button class="btn btn-danger" onclick="trashThreadAction('${esc(threadId)}', '${esc(backFn)}')">Delete</button>`;
  } else if (context === 'trash') {
    actionsHtml = `
      <button class="btn btn-secondary" onclick="restoreThreadAction('${esc(threadId)}', '${esc(backFn)}')">Restore</button>
      <button class="btn btn-danger" onclick="purgeThreadAction('${esc(threadId)}', '${esc(backFn)}')">Permanent Delete</button>`;
  }
  return `
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:12px">
        <button type="button" class="back-btn" onclick="${backFn}">&larr; Back</button>
        <div class="thread-actions" style="display:flex;gap:8px;flex-wrap:wrap">${actionsHtml}</div>
      </div>
      <h2>Thread</h2>
      ${msgs.map(m => `
        <div class="thread-msg">
          <div class="thread-meta">
            <strong>${esc(m.from_agent)}</strong> &rarr; ${esc(m.to_agent)}
            <span class="msg-action-tag ${m.action}">${m.action}</span>
            <span style="margin-left:8px;color:var(--muted)">${esc(fmtTime(m.created_at))}</span>
          </div>
          ${m.subject ? `<div class="thread-subject-line${humanSubjectClass(m.from_agent)}">${esc(m.subject)}</div>` : ''}
          <div class="thread-body markdown-body" data-md-html="${mdDataAttr(m.body_html)}"></div>
        </div>
      `).join('')}
    </div>`;
}

async function archiveThreadAction(threadId, backFn) {
  if (!await showConfirm('Archive Thread', 'Archive this thread?', 'Archive')) return;
  try {
    await api(`/admin/threads/${encodeURIComponent(threadId)}/archive`, { method: 'POST' });
    eval(backFn);
  } catch (e) { alert(e.message); }
}

async function unarchiveThreadAction(threadId, backFn) {
  if (!await showConfirm('UnArchive Thread', 'Restore this thread from archive?', 'UnArchive')) return;
  try {
    await api(`/admin/threads/${encodeURIComponent(threadId)}/unarchive`, { method: 'POST' });
    eval(backFn);
  } catch (e) { alert(e.message); }
}

async function restoreThreadAction(threadId, backFn) {
  if (!await showConfirm('Restore Thread', 'Restore this thread from trash?', 'Restore')) return;
  try {
    await api(`/admin/threads/${encodeURIComponent(threadId)}/restore`, { method: 'POST' });
    eval(backFn);
  } catch (e) { alert(e.message); }
}

async function purgeThreadAction(threadId, backFn) {
  if (!await showConfirm('Permanent Delete', 'Permanently delete this thread? This cannot be undone.', 'Delete Forever')) return;
  try {
    await api(`/admin/threads/${encodeURIComponent(threadId)}/purge`, { method: 'POST' });
    eval(backFn);
  } catch (e) { alert(e.message); }
}

async function trashThreadAction(threadId, backFn) {
  if (!await showConfirm('Delete Thread', 'Move this thread to trash?', 'Delete')) return;
  try {
    await api(`/admin/threads/${encodeURIComponent(threadId)}/trash`, { method: 'POST' });
    eval(backFn);
  } catch (e) { alert(e.message); }
}

// --- Archive & Trash views ---

async function showArchive(page) {
  clearNav();
  document.getElementById('navArchive').classList.add('active');
  setSidebarSpecialMode('none');
  currentView = { type: 'archive', page: page || 1 };
  document.getElementById('main').innerHTML = '<div class="card"><h2>Archive</h2><p>Loading...</p></div>';
  try {
    await renderArchiveMain();
  } catch (e) {
    document.getElementById('main').innerHTML = '<div class="card"><h2>Archive</h2><p class="empty">Error: ' + (e.message || e) + '</p></div>';
    console.error('showArchive error:', e);
  }
}

async function renderArchiveMain() {
  if (currentView?.type !== 'archive') return;
  const main = document.getElementById('main');
  try {
    await fetchThreadsSummary({ archived: true });
  } catch (e) {
    main.innerHTML = '<div class="card"><h2>Archive</h2><p class="empty">Failed to load: ' + esc(e.message) + '</p></div>';
    return;
  }
  if (threadsData.length === 0) {
    main.innerHTML = '<div class="card"><h2>Archive</h2><p class="empty" style="padding:24px 0;text-align:center">No archived threads. Archived threads will appear here.</p></div>';
    return;
  }
  const pg = _paginateList(threadsData, currentView.page || 1);
  main.innerHTML = `
    <div class="card">
      <h2>Archive</h2>
      <div class="stats-table-wrap">
      <table class="stats-table">
        <thead><tr><th>Subject</th><th>Messages</th><th>Unread</th><th>Last Activity</th></tr></thead>
        <tbody>${pg.items.map(t => `
          <tr style="cursor:pointer" onclick="showArchiveThread('${esc(t.thread_id)}')">
            <td><strong>${esc(t.preview_subject) || '(no subject)'}</strong></td>
            <td class="stat-num">${t.message_count}</td>
            <td class="stat-num">${t.unread_count}</td>
            <td style="color:var(--muted)">${esc(fmtTime(t.last_activity))}</td>
          </tr>
        `).join('')}</tbody>
      </table>
      </div>
      ${_paginationHtml(pg.page, pg.totalPages, pg.total, 'showArchive')}
    </div>`;
}

async function showTrash() {
  clearNav();
  document.getElementById('navTrash').classList.add('active');
  setSidebarSpecialMode('none');
  currentView = { type: 'trash' };
  document.getElementById('main').innerHTML = '<div class="card"><h2>Trash</h2><p>Loading...</p></div>';
  try {
    await renderTrashMain();
  } catch (e) {
    document.getElementById('main').innerHTML = '<div class="card"><h2>Trash</h2><p class="empty">Error: ' + (e.message || e) + '</p></div>';
    console.error('showTrash error:', e);
  }
}

async function renderTrashMain() {
  if (currentView?.type !== 'trash') return;
  const main = document.getElementById('main');
  try {
    await fetchThreadsSummary({ trashed: true });
    await fetchTrashedMessages();
  } catch (e) {
    main.innerHTML = '<div class="card"><h2>Trash</h2><p class="empty">Failed to load trash data: ' + esc(e.message) + '</p></div>';
    return;
  }
  if (threadsData.length === 0 && trashedMessagesData.length === 0) {
    main.innerHTML = '<div class="card"><h2>Trash</h2><p class="empty" style="padding:24px 0;text-align:center">Trash is empty. Deleted threads and messages will appear here.</p></div>';
    return;
  }
  const threadsHtml = threadsData.length === 0
    ? '<div class="empty" style="padding:12px 0">No threads in trash.</div>'
    : `<div class="stats-table-wrap">
      <table class="stats-table">
        <thead><tr><th>Subject</th><th>Messages</th><th>Unread</th><th>Trashed At</th></tr></thead>
        <tbody>${threadsData.map(t => `
          <tr style="cursor:pointer" onclick="showTrashThread('${esc(t.thread_id)}')">
            <td><strong>${esc(t.preview_subject) || '(no subject)'}</strong></td>
            <td class="stat-num">${t.message_count}</td>
            <td class="stat-num">${t.unread_count}</td>
            <td style="color:var(--muted)">${esc(fmtTime(t.trashed_at || t.last_activity))}</td>
          </tr>
        `).join('')}</tbody>
      </table>
      </div>`;
  const msgsHtml = trashedMessagesData.length === 0
    ? '<div class="empty" style="padding:12px 0">No individual messages in trash.</div>'
    : `<div class="stats-table-wrap">
      <table class="stats-table">
        <thead><tr><th>Subject</th><th>From</th><th>Trashed At</th></tr></thead>
        <tbody>${trashedMessagesData.map(tm => `
          <tr style="cursor:pointer" onclick="showTrashMessage('${esc(tm.message_id)}')">
            <td><strong>${esc(tm.subject) || '(no subject)'}</strong></td>
            <td style="color:var(--muted)">${esc(tm.from_agent)}</td>
            <td style="color:var(--muted)">${esc(fmtTime(tm.trashed_at))}</td>
          </tr>
        `).join('')}</tbody>
      </table>
      </div>`;
  main.innerHTML = `
    <div class="card">
      <div class="card-header-row">
        <h2>Trash</h2>
        <button class="btn btn-danger" onclick="emptyTrash()">Empty Trash</button>
      </div>
      <h3 class="team-section-header">Trashed Threads</h3>
      ${threadsHtml}
      <h3 class="team-section-header">Trashed Messages</h3>
      ${msgsHtml}
    </div>`;
}

async function emptyTrash() {
  if (!await showConfirm('Empty Trash', 'Permanently delete ALL items in trash? This cannot be undone.', 'Empty Trash')) return;
  try {
    // Purge all trashed threads
    for (const t of threadsData) {
      await api(`/admin/threads/${encodeURIComponent(t.thread_id)}/purge`, { method: 'POST' });
    }
    // Purge all trashed messages
    for (const tm of trashedMessagesData) {
      await api(`/admin/messages/${encodeURIComponent(tm.message_id)}/purge`, { method: 'POST' });
    }
    await showTrash();
  } catch (e) { alert(e.message); }
}

async function showTrashThread(threadId) {
  currentView = { type: 'trashThread', threadId };
  const main = document.getElementById('main');
  main.innerHTML = '<div class="card"><p>Loading...</p></div>';
  try {
    const msgs = await fetchThread(threadId);
    main.innerHTML = _renderThreadDetail(msgs, threadId, 'showTrash()', 'trash');
    hydrateMarkdownBodies(main);
  } catch (e) {
    main.innerHTML = `<div class="card"><button type="button" class="back-btn" onclick="showTrash()">&larr; Back</button><p class="empty">Error: ${esc(e.message)}</p></div>`;
  }
}

async function showTrashMessage(messageId) {
  currentView = { type: 'trashMessage', messageId };
  await renderTrashedMessageView();
}

async function showArchiveThread(threadId) {
  currentView = { type: 'archiveThread', threadId };
  const main = document.getElementById('main');
  main.innerHTML = '<div class="card"><p>Loading...</p></div>';
  try {
    const msgs = await fetchThread(threadId);
    main.innerHTML = _renderThreadDetail(msgs, threadId, 'showArchive()', 'archive');
    hydrateMarkdownBodies(main);
  } catch (e) {
    main.innerHTML = `<div class="card"><button type="button" class="back-btn" onclick="showArchive()">&larr; Back</button><p class="empty">Error: ${esc(e.message)}</p></div>`;
  }
}

async function showTrashedMessageFromTrash(messageId) {
  currentView = { type: 'trashedMessage', messageId };
  await renderTrashedMessageView();
}

async function renderTrashedMessageView() {
  if (currentView?.type !== 'trashedMessage') return;
  const mid = currentView.messageId;
  const main = document.getElementById('main');
  let data;
  try {
    data = await api(`/admin/trash/messages/${encodeURIComponent(mid)}`);
  } catch (e) {
    main.innerHTML = `
      <div class="card">
        <p class="empty">This message is no longer in trash.</p>
        <button type="button" class="back-btn" id="tmGoneBack">\u2190 Back to Trash</button>
      </div>`;
    document.getElementById('tmGoneBack').onclick = () => {
      void showTrash();
    };
    return;
  }
  const m = data.message;
  main.innerHTML = `
    <button type="button" class="back-btn" id="tmBackBtn">\u2190 Back to Trash</button>
    <div class="card">
      <h2>Message in trash</h2>
      <p class="meta">Trashed at: ${esc(fmtTime(data.trashed_at))}</p>
      <div class="thread-msg">
        <div class="thread-meta">
          <strong>${esc(m.from_agent)}</strong> &rarr; ${esc(m.to_agent)}
          <span class="msg-action-tag ${m.action}" style="margin-left:6px">${m.action}</span>
          <span style="margin-left:8px;color:var(--muted)">${esc(fmtTime(m.created_at))}</span>
        </div>
        ${m.subject ? `<div class="thread-subject-line${humanSubjectClass(m.from_agent)}">${esc(m.subject)}</div>` : ''}
        <div class="thread-body markdown-body" data-md-html="${mdDataAttr(m.body_html)}"></div>
      </div>
      <div class="thread-actions" style="margin-top:12px">
        <button type="button" class="btn btn-secondary" id="tmRestoreBtn">Restore</button>
        <button type="button" class="btn btn-secondary" id="tmPurgeBtn" style="background:var(--danger)">Delete permanently</button>
      </div>
    </div>`;
  hydrateMarkdownBodies(main);
  document.getElementById('tmBackBtn').onclick = () => {
    void showTrash();
  };
  document.getElementById('tmRestoreBtn').onclick = async () => {
    try {
      await api(`/admin/messages/${encodeURIComponent(mid)}/restore`, { method: 'POST' });
      await showTrash();
    } catch (e) {
      alert(e.message);
    }
  };
  document.getElementById('tmPurgeBtn').onclick = async () => {
    if (!await showConfirm('永久删除消息', '确定要永久删除这条消息吗？此操作不可撤销。', '删除')) return;
    try {
      await api(`/admin/messages/${encodeURIComponent(mid)}/purge`, { method: 'POST' });
      await showTrash();
    } catch (e) {
      alert(e.message);
    }
  };
}

async function trashSingleMessage(messageId, opts = {}) {
  if (!await showConfirm('Move to Trash', 'Move this message to trash?', 'Move to Trash')) return;
  try {
    await api(`/admin/messages/${encodeURIComponent(messageId)}/trash`, { method: 'POST' });
    if (opts.fromInbox && expandedMsg === messageId) expandedMsg = null;
    if (currentView?.type === 'trashedMessage') {
      currentView = { type: 'trash' };
      document.getElementById('main').innerHTML =
        '<div class="empty">Select a deleted thread or message from the sidebar.</div>';
    }
    await refreshSidebar();
    if (opts.fromThread) await renderThreadView();
    else if (currentView?.type === 'inbox') await renderInbox();
  } catch (e) {
    alert(e.message);
  }
}

// --- Inbox view ---

async function showHumanInbox() {
  clearNav();
  document.getElementById('navInbox').classList.add('active');
  setSidebarSpecialMode('none');
  // Reset sidebar to By Agents mode
  sidebarMode = 'agents';
  const modeSelect = document.getElementById('sidebarModeSelect');
  if (modeSelect) modeSelect.value = 'agents';

  if (HUMAN_OPERATOR_ADDRESS) {
    currentView = { type: 'inbox', address: HUMAN_OPERATOR_ADDRESS, agentId: HUMAN_OPERATOR_AGENT_ID };
    document.getElementById('main').innerHTML = '';
    await refreshSidebar();
    await renderInbox();
  } else {
    currentView = null;
    document.getElementById('main').innerHTML =
      '<div class="empty">Select an agent to view inbox, or click Compose.</div>';
    await refreshSidebar();
  }
}

async function showInbox(address, agentId, page) {
  clearNav();
  setSidebarSpecialMode('none');
  currentView = { type: 'inbox', address, agentId: agentId || null, page: page || 1 };
  document.getElementById('main').innerHTML = '';
  await refreshSidebar();
  await renderInbox();
}

function renderTagEditor(agentId, tags) {
  if (!agentId) return '';
  const pills = tags.map((t, i) =>
    `<span class="tag-pill">${esc(t)}<button class="tag-remove" data-tag-idx="${i}" onclick="event.stopPropagation(); removeTag(${i})">&times;</button></span>`
  ).join('');
  return `<div class="tag-editor" id="tagEditor">${pills}<div class="tag-input-wrap"><input class="tag-input" id="tagInput" type="text" placeholder="+ 添加标签" data-agent-id="${esc(agentId)}" autocomplete="off"><div class="tag-autocomplete" id="tagAutocomplete"></div></div></div>`;
}

async function renderInbox() {
  if (currentView?.type !== 'inbox') return;
  const address = currentView.address;
  const agentId = currentView.agentId;
  const page = currentView.page || 1;
  const data = await fetchInbox(address, page, 20);
  const main = document.getElementById('main');

  const msgs = data.messages;
  const { total, total_pages } = data;

  msgs.forEach(m => { msgCache[m.id] = m; });

  const paginationHtml = total_pages > 1 ? `
    <div class="pagination">
      <button class="btn btn-secondary pagination-btn" ${page <= 1 ? 'disabled' : ''} onclick="showInbox('${esc(address)}', '${esc(agentId || '')}', ${page - 1})">&laquo; Prev</button>
      <span class="pagination-info">Page ${page} / ${total_pages} (${total} messages)</span>
      <button class="btn btn-secondary pagination-btn" ${page >= total_pages ? 'disabled' : ''} onclick="showInbox('${esc(address)}', '${esc(agentId || '')}', ${page + 1})">Next &raquo;</button>
    </div>` : '';

  const existingList = main.querySelector('.msg-list');
  if (existingList) {
    existingList.innerHTML = msgs.length === 0
      ? ''
      : msgs.map(m => renderMsgItem(m)).join('');
    const emptyEl = main.querySelector('.inbox-empty');
    if (msgs.length === 0 && !emptyEl) {
      existingList.insertAdjacentHTML('afterend', '<div class="empty inbox-empty">No messages.</div>');
    } else if (msgs.length > 0 && emptyEl) {
      emptyEl.remove();
    }
    const oldPag = main.querySelector('.pagination');
    if (oldPag) oldPag.outerHTML = paginationHtml;
    hydrateMarkdownBodies(main);
    return;
  }

  const agentData = agentId ? statsData.find(a => a.agent_id === agentId) : null;
  const currentTags = agentData ? (agentData.tags || []) : [];
  const tagEditorHtml = renderTagEditor(agentId, currentTags);

  main.innerHTML = `
    <div class="card">
      <h2>Inbox: ${esc(address)}</h2>
      ${tagEditorHtml}
      <ul class="msg-list">
        ${msgs.map(m => renderMsgItem(m)).join('')}
      </ul>
      ${msgs.length === 0 ? '<div class="empty inbox-empty">No messages.</div>' : ''}
      ${paginationHtml}
    </div>`;
  hydrateMarkdownBodies(main);
  hydrateTagInput();
}

function renderMsgItem(m) {
  const isExpanded = expandedMsg === m.id;
  const readClass = m.is_read ? 'read' : 'unread';
  const subjText = esc(m.subject) || '(no subject)';
  return `
    <li class="msg-item ${readClass}">
      <div class="msg-item-head" onclick="toggleMsg('${m.id}', event)">
        <div class="msg-header">
          <span class="msg-from">${esc(m.from_agent)}</span>
          <span>
            <span class="msg-action-tag ${m.action}">${m.action}</span>
            <span class="msg-time">${fmtTime(m.created_at)}</span>
            ${!isExpanded ? `<span class="thread-link msg-item-copy" title="以 Markdown 格式复制本条邮件" onclick="copyMessageAsMarkdown('${m.id}', event)">Copy as Markdown</span>
            <span class="thread-link msg-item-copy" title="保存邮件到所属 Team 的共享知识库" onclick="saveMessageToTeam('${m.id}', event)">Save to Team</span>` : ''}
          </span>
        </div>
        ${!isExpanded ? `
          <div class="msg-subject${humanSubjectClass(m.from_agent)}">${subjText}</div>
          <div class="msg-preview">${esc(m.body.substring(0, 100))}</div>
        ` : `
          <div class="msg-detail-subject${humanSubjectClass(m.from_agent)}">${subjText}</div>
        `}
      </div>
      ${isExpanded ? renderMsgDetail(m) : ''}
    </li>`;
}

function renderMsgDetail(m) {
  return `
    <div class="msg-detail">
      <div class="meta">From: ${esc(m.from_agent)} &rarr; To: ${esc(m.to_agent)}</div>
      <div class="meta">Action: ${m.action} | Thread: ${m.thread_id.substring(0, 8)}...</div>
      ${m.parent_id ? `<div class="meta">Reply to: ${m.parent_id.substring(0, 8)}...</div>` : ''}
      <div class="msg-body markdown-body" data-md-html="${mdDataAttr(m.body_html)}"></div>
      <div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:8px;align-items:center">
        <span class="thread-link" data-thread-id="${m.thread_id}" onclick="event.stopPropagation(); showThreadFromInboxLink(this.dataset.threadId)">View full thread</span>
        <span class="thread-link" onclick="replyToMsg('${m.id}', event)">Reply</span>
        <span class="thread-link" onclick="forwardToMsg('${m.id}', event)">Forward</span>
        <span class="thread-link" title="以 Markdown 格式复制本条邮件" onclick="copyMessageAsMarkdown('${m.id}', event)">Copy as Markdown</span>
        <span class="thread-link" title="保存邮件到所属 Team 的共享知识库" onclick="saveMessageToTeam('${m.id}', event)">Save to Team</span>
        ${m.is_read ? `<span class="thread-link" onclick="markMsgUnread('${m.id}', event)">Mark as unread</span>` : ''}
        <button type="button" class="btn btn-secondary msg-trash-action" style="font-size:12px;padding:4px 10px"
          onclick="event.stopPropagation(); trashSingleMessage('${m.id}', { fromInbox: true })">Move message to trash</button>
      </div>
    </div>`;
}

async function toggleMsg(msgId, ev) {
  if (ev.target.closest && (ev.target.closest('.thread-link') || ev.target.closest('.msg-trash-action'))) return;
  const expanding = expandedMsg !== msgId;
  expandedMsg = expanding ? msgId : null;
  if (expanding) {
    try {
      await api(`/admin/messages/${encodeURIComponent(msgId)}/read`, { method: 'PATCH' });
      refreshSidebar();
    } catch (e) { /* ignore */ }
  }
  renderInbox();
}

// --- Thread view ---

async function showThreadFromInboxLink(threadId) {
  const addr = currentView?.type === 'inbox' ? currentView.address : '';
  await showThread(threadId, addr, null, false);
}

async function showThreadFromSidebar(threadId, context = null) {
  clearNav();
  if (context === 'archive') {
    document.getElementById('navArchive').classList.add('active');
    setSidebarSpecialMode('archive');
  } else if (context === 'trash') {
    document.getElementById('navTrash').classList.add('active');
    setSidebarSpecialMode('trash');
  } else {
    setSidebarSpecialMode('none');
  }
  currentView = {
    type: 'thread',
    threadId,
    fromAddress: '',
    fromThreadSidebar: true,
    fromArchive: context === 'archive',
    fromTrash: context === 'trash',
  };
  await refreshSidebar();
  await renderThreadView();
}

async function showThread(threadId, fromAddress, ev, fromThreadSidebar = false) {
  if (ev) ev.stopPropagation();
  setSidebarSpecialMode('none');
  currentView = {
    type: 'thread',
    threadId,
    fromAddress: fromAddress || '',
    fromThreadSidebar,
    fromArchive: false,
    fromTrash: false,
  };
  await renderThreadView();
}

function buildThreadActionButtons(st) {
  const parts = [];
  if (st.trashed) {
    parts.push('<button type="button" class="btn btn-secondary" id="restoreThreadBtn">Restore</button>');
    parts.push(
      '<button type="button" class="btn btn-secondary" id="purgeThreadBtn" style="background:var(--danger)">Delete permanently</button>',
    );
    return parts.join('');
  }
  if (st.archived) {
    parts.push('<button type="button" class="btn btn-secondary" id="unarchiveThreadBtn">Unarchive</button>');
  } else {
    parts.push('<button type="button" class="btn btn-secondary" id="archiveThreadBtn">Archive thread</button>');
  }
  parts.push(
    '<button type="button" class="btn btn-secondary" id="trashThreadBtn" style="background:#64748b">Move to trash</button>',
  );
  return parts.join('');
}

async function renderThreadView() {
  if (currentView?.type !== 'thread') return;
  const { threadId, fromAddress, fromThreadSidebar, fromArchive, fromTrash } = currentView;
  const msgs = await fetchThread(threadId);
  msgs.forEach(m => { msgCache[m.id] = m; });
  let st = { archived: false, trashed: false };
  try {
    st = await api(`/admin/threads/${encodeURIComponent(threadId)}/status`);
  } catch (e) { /* ignore */ }
  const main = document.getElementById('main');
  let backLabel = '\u2190 Back to inbox';
  if (fromThreadSidebar) {
    if (fromTrash) backLabel = '\u2190 Back to Trash';
    else if (fromArchive) backLabel = '\u2190 Back to Archive';
    else backLabel = '\u2190 Back to thread list';
  }
  const firstSubject = msgs.length > 0 && String(msgs[0].subject || '').trim()
    ? String(msgs[0].subject).trim()
    : '';
  const threadTitle = firstSubject || '(no subject)';
  const actionHtml = buildThreadActionButtons(st);
  main.innerHTML = `
    <button type="button" class="back-btn" id="threadBackBtn">${backLabel}</button>
    <div class="card">
      <h2>${esc(threadTitle)}</h2>
      <div class="thread-actions">${actionHtml}</div>
      ${msgs.map(m => `
        <div class="thread-msg">
          <div class="thread-meta">
            <strong>${esc(m.from_agent)}</strong> &rarr; ${esc(m.to_agent)}
            <span class="msg-action-tag ${m.action}" style="margin-left:6px">${m.action}</span>
            <span style="margin-left:8px;color:var(--muted)">${fmtTime(m.created_at)}</span>
          </div>
          ${m.subject ? `<div class="thread-subject-line${humanSubjectClass(m.from_agent)}">${esc(m.subject)}</div>` : ''}
          <div class="thread-body markdown-body" data-md-html="${mdDataAttr(m.body_html)}"></div>
          ${!st.trashed ? `<div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:8px;align-items:center">
            <span class="thread-link" onclick="replyToMsg('${m.id}', event)">Reply</span>
            <span class="thread-link" onclick="forwardToMsg('${m.id}', event)">Forward</span>
            <span class="thread-link" title="以 Markdown 格式复制本条邮件" onclick="copyMessageAsMarkdown('${m.id}', event)">Copy as Markdown</span>
            <span class="thread-link" title="保存邮件到所属 Team 的共享知识库" onclick="saveMessageToTeam('${m.id}', event)">Save to Team</span>
            ${m.is_read ? `<span class="thread-link" onclick="markMsgUnread('${m.id}', event)">Mark as unread</span>` : ''}
            <button type="button" class="btn btn-secondary" style="font-size:12px;padding:4px 10px" onclick="trashSingleMessage('${m.id}', { fromThread: true })">Move message to trash</button>
          </div>` : ''}
        </div>
      `).join('')}
    </div>`;
  hydrateMarkdownBodies(main);
  document.getElementById('threadBackBtn').onclick = () => {
    if (fromThreadSidebar) threadBackToSidebarList();
    else showInbox(fromAddress);
  };

  const archiveBtn = document.getElementById('archiveThreadBtn');
  if (archiveBtn) {
    archiveBtn.onclick = async () => {
      try {
        await api(`/admin/threads/${encodeURIComponent(threadId)}/archive`, { method: 'POST' });
        if (currentView.fromArchive) await renderThreadView();
        else if (currentView.fromThreadSidebar) threadBackToSidebarList();
        else await showInbox(currentView.fromAddress);
        await refreshSidebar();
      } catch (e) {
        archiveBtn.insertAdjacentText('afterend', ' ' + e.message);
      }
    };
  }
  const unarchiveBtn = document.getElementById('unarchiveThreadBtn');
  if (unarchiveBtn) {
    unarchiveBtn.onclick = async () => {
      try {
        await api(`/admin/threads/${encodeURIComponent(threadId)}/unarchive`, { method: 'POST' });
        if (currentView.fromArchive) {
          currentView = { type: 'archive' };
          document.getElementById('main').innerHTML =
            '<div class="empty">Select an archived thread from the sidebar.</div>';
        }
        await refreshSidebar();
        if (!currentView.fromArchive && currentView.type === 'thread') await renderThreadView();
      } catch (e) {
        unarchiveBtn.insertAdjacentText('afterend', ' ' + e.message);
      }
    };
  }
  const trashBtn = document.getElementById('trashThreadBtn');
  if (trashBtn) {
    trashBtn.onclick = async () => {
      try {
        await api(`/admin/threads/${encodeURIComponent(threadId)}/trash`, { method: 'POST' });
        if (currentView.fromThreadSidebar) threadBackToSidebarList();
        else await showInbox(currentView.fromAddress);
        await refreshSidebar();
      } catch (e) {
        trashBtn.insertAdjacentText('afterend', ' ' + e.message);
      }
    };
  }
  const restoreBtn = document.getElementById('restoreThreadBtn');
  if (restoreBtn) {
    restoreBtn.onclick = async () => {
      try {
        await api(`/admin/threads/${encodeURIComponent(threadId)}/restore`, { method: 'POST' });
        currentView = { type: 'trash' };
        document.getElementById('main').innerHTML =
          '<div class="empty">Select a deleted thread or message from the sidebar.</div>';
        await refreshSidebar();
      } catch (e) {
        restoreBtn.insertAdjacentText('afterend', ' ' + e.message);
      }
    };
  }
  const purgeBtn = document.getElementById('purgeThreadBtn');
  if (purgeBtn) {
    purgeBtn.onclick = async () => {
      if (!await showConfirm('永久删除线程', '确定要永久删除这个线程及其所有消息吗？此操作不可撤销。', '删除')) return;
      try {
        await api(`/admin/threads/${encodeURIComponent(threadId)}/purge`, { method: 'POST' });
        currentView = { type: 'trash' };
        document.getElementById('main').innerHTML =
          '<div class="empty">Select a deleted thread or message from the sidebar.</div>';
        await refreshSidebar();
      } catch (e) {
        purgeBtn.insertAdjacentText('afterend', ' ' + e.message);
      }
    };
  }
}

function threadBackToSidebarList() {
  if (currentView?.fromTrash) {
    currentView = { type: 'trash' };
    document.getElementById('main').innerHTML =
      '<div class="empty">Select a deleted thread or message from the sidebar.</div>';
    void refreshSidebar();
    return;
  }
  if (currentView?.fromArchive) {
    currentView = { type: 'archive' };
    document.getElementById('main').innerHTML =
      '<div class="empty">Select an archived thread from the sidebar.</div>';
    void refreshSidebar();
    return;
  }
  currentView = { type: 'threadList' };
  document.getElementById('main').innerHTML =
    '<div class="empty">Select a thread from the sidebar, or switch to By Agents.</div>';
  void refreshSidebar();
}

// --- Compose view ---

async function showCompose(prefillTo, prefillSubject, prefillParentId, originalBody, originalBodyHtml, options) {
  options = options || {};
  const mode = options.mode != null ? options.mode : (prefillParentId ? 'reply' : 'send');

  if (agents.length === 0) await fetchAgents();

  let title = 'Compose Message';
  if (mode === 'reply') title = 'Reply';
  else if (mode === 'forward') title = 'Forward';

  const forwardScopeBlock = mode === 'forward' ? `
        <div class="compose-forward-scope">
          <label>Forwarded content</label>
          <p class="compose-forward-hint">Shown after your note. Pick scope for the new recipient.</p>
          <label class="compose-radio-row">
            <input type="radio" name="forwardScope" value="message" checked>
            <span>This message only</span>
          </label>
          <label class="compose-radio-row">
            <input type="radio" name="forwardScope" value="thread">
            <span>Full thread (chronological)</span>
          </label>
        </div>` : '';

  const bodyPlaceholder = mode === 'forward'
    ? 'Optional note (appears above forwarded content)...'
    : 'Write your message...';

  currentView = { type: 'compose' };
  const container = document.getElementById('main');
  container.innerHTML = `
    <div class="card">
      <h2>${title}</h2>
      <div class="compose-form">
        <div class="compose-to-wrap">
          <label>To</label>
          <input id="composeTo" type="text" placeholder="Type agent name or address..." value="${esc(prefillTo || '')}" autocomplete="off">
          <div class="compose-to-dropdown" id="composeToDropdown"></div>
        </div>
        <div>
          <label>Subject</label>
          <input id="composeSubject" type="text" placeholder="Subject..." value="${esc(prefillSubject || '')}">
        </div>
        ${forwardScopeBlock}
        <div>
          <label>Body <span style="font-weight:normal;color:var(--muted);font-size:11px">— type @ to insert image or memory reference</span></label>
          <textarea id="composeBody" placeholder="${esc(bodyPlaceholder)}"></textarea>
          <div class="compose-at-dropdown" id="composeAtDropdown"></div>
        </div>
        <div>
          <label>Attachments</label>
          <div class="compose-upload-zone" id="composeUploadZone">
            <div class="upload-hint">Drop images here, paste (Ctrl+V), or <label class="upload-browse" for="composeFileInput">browse</label></div>
            <input type="file" id="composeFileInput" accept="image/png,image/jpeg,image/gif,image/webp" multiple style="display:none">
          </div>
          <div class="compose-attachments" id="composeAttachments"></div>
        </div>
        ${originalBody ? (originalBodyHtml ? `
        <div>
          <label style="color:var(--muted)">Reference (source message)</label>
          <div class="markdown-body compose-original-md" data-md-html="${mdDataAttr(originalBodyHtml)}"></div>
        </div>` : `
        <div>
          <label style="color:var(--muted)">Reference (source message)</label>
          <div class="compose-original-md" style="white-space:pre-wrap;color:var(--muted)">${esc(originalBody)}</div>
        </div>`) : ''}
        <input type="hidden" id="composeParentId" value="${prefillParentId || ''}">
        <input type="hidden" id="composeMode" value="${esc(mode)}">
        <div style="display:flex;gap:12px;align-items:center">
          <button class="btn btn-primary" id="sendBtn" onclick="doSend()">Send</button>
          <div id="composeStatus"></div>
        </div>
      </div>
    </div>`;
  hydrateMarkdownBodies(container);
  hydrateComposeToInput();
  hydrateComposeUpload();
  hydrateComposeAtReference();
}

function closeComposeModal() {
  document.getElementById('composeModal').classList.remove('visible');
  document.getElementById('composeModalContent').innerHTML = '';
}

// --- Compose upload state ---
let composeUploadedFiles = [];
let pasteImageCounter = 0;

function renderComposeAttachments() {
  const container = document.getElementById('composeAttachments');
  if (!container) return;
  if (composeUploadedFiles.length === 0) { container.innerHTML = ''; return; }
  container.innerHTML = composeUploadedFiles.map((f, i) => `
    <div class="compose-attachment-item">
      <img src="${esc(f.url)}" class="compose-attachment-thumb" alt="${esc(f.filename)}" onclick="previewImage('${esc(f.url)}', '${esc(f.filename)}')" style="cursor:pointer" title="Click to preview">
      <div class="compose-attachment-info">
        <span class="compose-attachment-name">${esc(f.filename)}</span>
        <span class="compose-attachment-size">${(f.size / 1024).toFixed(1)} KB</span>
      </div>
      <button class="compose-attachment-remove" onclick="removeComposeAttachment(${i})">&times;</button>
    </div>
  `).join('');
}

function removeComposeAttachment(idx) {
  composeUploadedFiles.splice(idx, 1);
  renderComposeAttachments();
}

async function uploadFile(file) {
  const zone = document.getElementById('composeUploadZone');
  const hint = zone?.querySelector('.upload-hint');
  if (hint) hint.textContent = 'Uploading...';
  try {
    const formData = new FormData();
    formData.append('file', file);
    const resp = await fetch(BASE + '/files/upload', {
      method: 'POST',
      credentials: 'same-origin',
      body: formData,
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || 'Upload failed');
    }
    const data = await resp.json();
    composeUploadedFiles.push(data);
    renderComposeAttachments();
  } catch (e) {
    const status = document.getElementById('composeStatus');
    if (status) {
      status.className = 'compose-status error';
      status.textContent = 'Upload error: ' + e.message;
    }
  } finally {
    if (hint) hint.innerHTML = 'Drop images here, paste (Ctrl+V), or <label class="upload-browse" for="composeFileInput">browse</label>';
  }
}

function hydrateComposeUpload() {
  composeUploadedFiles = [];
  pasteImageCounter = 0;
  const zone = document.getElementById('composeUploadZone');
  const fileInput = document.getElementById('composeFileInput');
  if (!zone || !fileInput) return;

  // File input change
  fileInput.addEventListener('change', () => {
    for (const f of fileInput.files) uploadFile(f);
    fileInput.value = '';
  });

  // Drag & drop
  zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', (e) => {
    e.preventDefault();
    zone.classList.remove('dragover');
    for (const f of e.dataTransfer.files) {
      if (f.type.startsWith('image/')) uploadFile(f);
    }
  });

  // Ctrl+V paste — remove previous listener to avoid duplicates
  if (window._composePasteHandler) {
    document.removeEventListener('paste', window._composePasteHandler);
  }
  window._composePasteHandler = (e) => {
    if (currentView?.type !== 'compose') return;
    const items = e.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        e.preventDefault();
        const file = item.getAsFile();
        if (file) {
          pasteImageCounter++;
          const ext = file.type.split('/')[1] || 'png';
          const renamed = new File([file], `image${pasteImageCounter}.${ext}`, { type: file.type });
          uploadFile(renamed);
        }
      }
    }
  };
  document.addEventListener('paste', window._composePasteHandler);
}

function hydrateComposeAtReference() {
  const textarea = document.getElementById('composeBody');
  const dropdown = document.getElementById('composeAtDropdown');
  if (!textarea || !dropdown) return;
  let atActive = false;
  let atStartPos = -1;
  let cachedMemories = null;

  async function loadMemories() {
    if (cachedMemories !== null) return cachedMemories;
    try {
      if (teamsData.length === 0) await fetchTeams();
      const all = [];
      for (const t of teamsData) {
        const mems = await fetchTeamMemories(t.id);
        for (const m of mems) all.push(m);
      }
      cachedMemories = all;
    } catch (e) {
      cachedMemories = [];
    }
    return cachedMemories;
  }

  async function showDropdown(filter) {
    const memories = await loadMemories();
    const q = (filter || '').toLowerCase();

    const imgItems = composeUploadedFiles
      .filter(f => !q || f.filename.toLowerCase().includes(q))
      .map(f =>
        `<div class="compose-at-item" data-type="image" data-url="${esc(f.url)}" data-name="${esc(f.filename)}">
          <span class="compose-at-label compose-at-label-img">IMG</span>
          <img src="${esc(f.url)}" class="compose-at-thumb">
          <span>${esc(f.filename)}</span>
        </div>`
      );

    const memItems = memories
      .filter(m => !q || m.title.toLowerCase().includes(q))
      .map(m =>
        `<div class="compose-at-item" data-type="memory" data-url="${esc(location.origin + '/memories/' + m.id)}" data-name="${esc(m.title)}">
          <span class="compose-at-label compose-at-label-mem">MEM</span>
          <span>${esc(m.title)}</span>
        </div>`
      );

    const allItems = imgItems.concat(memItems);
    if (allItems.length === 0) {
      dropdown.classList.remove('visible');
      return;
    }
    dropdown.innerHTML = allItems.join('');
    dropdown.classList.add('visible');
  }

  textarea.addEventListener('input', () => {
    const val = textarea.value;
    const pos = textarea.selectionStart;
    if (pos > 0 && val[pos - 1] === '@' && (pos === 1 || /\s/.test(val[pos - 2]))) {
      atActive = true;
      atStartPos = pos;
      showDropdown('');
    } else if (atActive) {
      // Extract filter text after @
      const filter = val.substring(atStartPos, pos);
      if (/\s/.test(filter) || pos < atStartPos) {
        dropdown.classList.remove('visible');
        atActive = false;
        atStartPos = -1;
      } else {
        showDropdown(filter);
      }
    }
  });

  dropdown.addEventListener('mousedown', (e) => {
    e.preventDefault();
    const item = e.target.closest('.compose-at-item');
    if (!item) return;
    const type = item.dataset.type;
    const url = item.dataset.url;
    const name = item.dataset.name;
    const pos = textarea.selectionStart;
    // Replace from @ position to current cursor
    const before = textarea.value.substring(0, atStartPos - 1);
    const after = textarea.value.substring(pos);
    const insert = type === 'image' ? `![${name}](${url})` : `[@${name}](${url})`;
    textarea.value = before + insert + after;
    textarea.selectionStart = textarea.selectionEnd = before.length + insert.length;
    dropdown.classList.remove('visible');
    atActive = false;
    atStartPos = -1;
    textarea.focus();
  });

  textarea.addEventListener('blur', () => {
    setTimeout(() => { dropdown.classList.remove('visible'); atActive = false; atStartPos = -1; }, 150);
  });
}

function hydrateComposeToInput() {
  const input = document.getElementById('composeTo');
  const dropdown = document.getElementById('composeToDropdown');
  if (!input || !dropdown) return;
  let acIdx = -1;

  function render(query) {
    const q = (query || '').trim().toLowerCase();
    const matches = q
      ? agents.filter(a => a.name.toLowerCase().includes(q) || a.address.toLowerCase().includes(q))
      : agents;
    if (matches.length === 0) {
      dropdown.innerHTML = '<div class="compose-to-empty">No matching agents</div>';
      dropdown.classList.add('visible');
      return;
    }
    acIdx = -1;
    dropdown.innerHTML = matches.map(a =>
      `<div class="compose-to-item" data-address="${esc(a.address)}">${esc(a.name)} <span style="color:var(--muted)">(${esc(a.address)})</span></div>`
    ).join('');
    dropdown.classList.add('visible');
  }

  function pick(address) {
    input.value = address;
    dropdown.classList.remove('visible');
    dropdown.innerHTML = '';
    acIdx = -1;
  }

  function highlightItems() {
    const items = dropdown.querySelectorAll('.compose-to-item');
    items.forEach((it, i) => it.classList.toggle('active', i === acIdx));
    if (acIdx >= 0 && items[acIdx]) items[acIdx].scrollIntoView({ block: 'nearest' });
  }

  input.addEventListener('focus', () => render(input.value));
  input.addEventListener('input', () => render(input.value));
  input.addEventListener('blur', () => {
    setTimeout(() => { dropdown.classList.remove('visible'); }, 150);
  });

  dropdown.addEventListener('mousedown', (e) => {
    e.preventDefault();
    const item = e.target.closest('.compose-to-item');
    if (item) pick(item.dataset.address);
  });

  input.addEventListener('keydown', (e) => {
    const items = dropdown.querySelectorAll('.compose-to-item');
    const vis = dropdown.classList.contains('visible');
    if (e.key === 'ArrowDown' && vis) {
      e.preventDefault();
      acIdx = Math.min(acIdx + 1, items.length - 1);
      highlightItems();
      return;
    }
    if (e.key === 'ArrowUp' && vis) {
      e.preventDefault();
      acIdx = Math.max(acIdx - 1, -1);
      highlightItems();
      return;
    }
    if (e.key === 'Escape') {
      dropdown.classList.remove('visible');
      acIdx = -1;
      return;
    }
    if (e.key === 'Enter' && vis) {
      e.preventDefault();
      if (acIdx >= 0 && items[acIdx]) {
        pick(items[acIdx].dataset.address);
      } else if (items.length === 1) {
        pick(items[0].dataset.address);
      }
    }
  });
}

function replyToMsg(msgId, ev) {
  if (ev) ev.stopPropagation();
  const m = msgCache[msgId];
  if (!m) return;
  const reSubject = m.subject && m.subject.startsWith('Re:') ? m.subject : `Re: ${m.subject || ''}`;
  showCompose(m.from_agent, reSubject, m.id, m.body, m.body_html);
}

async function markMsgUnread(msgId, ev) {
  if (ev) ev.stopPropagation();
  try {
    const updated = await api(`/admin/messages/${encodeURIComponent(msgId)}/unread`, { method: 'PATCH' });
    msgCache[msgId] = { ...msgCache[msgId], ...updated };
    await refreshSidebar();
    if (currentView?.type === 'inbox') await renderInbox();
    if (currentView?.type === 'thread') await renderThreadView();
  } catch (e) {
    alert(e.message);
  }
}

function forwardToMsg(msgId, ev) {
  if (ev) ev.stopPropagation();
  const m = msgCache[msgId];
  if (!m) return;
  const subj = (m.subject || '').trim();
  const fwdSubject = subj && /^fwd:/i.test(subj) ? subj : `Fwd: ${subj || '(no subject)'}`;
  showCompose('', fwdSubject, m.id, m.body, m.body_html, { mode: 'forward' });
}

async function doSend() {
  const btn = document.getElementById('sendBtn');
  const status = document.getElementById('composeStatus');
  btn.disabled = true;
  status.textContent = '';

  const mode = (document.getElementById('composeMode') || {}).value || 'send';
  const parentId = document.getElementById('composeParentId').value;
  const toValue = document.getElementById('composeTo').value.trim();

  // Validate address exists
  if (!agents.some(a => a.address === toValue)) {
    status.className = 'compose-status error';
    status.textContent = 'Error: Address "' + toValue + '" does not exist. Please select a valid agent.';
    btn.disabled = false;
    return;
  }

  const body = {
    to_agent: toValue,
    subject: document.getElementById('composeSubject').value,
    body: document.getElementById('composeBody').value,
    attachments: composeUploadedFiles.map(f => ({ id: f.id, filename: f.filename, mime_type: f.mime_type, size: f.size, url: f.url })),
  };
  if (mode === 'forward') {
    body.action = 'forward';
    body.parent_id = parentId;
    const sel = document.querySelector('input[name="forwardScope"]:checked');
    body.forward_scope = sel ? sel.value : 'message';
  } else if (mode === 'reply') {
    body.action = 'reply';
    body.parent_id = parentId;
  } else {
    body.action = 'send';
  }

  try {
    await api('/admin/messages/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    status.className = 'compose-status success';
    status.textContent = 'Message sent!';
    document.getElementById('composeBody').value = '';
    document.getElementById('composeSubject').value = '';
    document.getElementById('composeParentId').value = '';
    await refreshSidebar();
  } catch (e) {
    status.className = 'compose-status error';
    status.textContent = 'Error: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

// --- Stats view ---

async function showStats() {
  clearNav();
  setSidebarSpecialMode('none');
  document.getElementById('navStats').classList.add('active');
  currentView = { type: 'stats' };
  await renderStats();
}

async function renderStats() {
  if (currentView?.type !== 'stats') return;
  await fetchStats();
  const main = document.getElementById('main');
  if (statsData.length === 0) {
    main.innerHTML = '<div class="card"><h2>Agent Statistics</h2><div class="empty">No agents registered.</div></div>';
    return;
  }
  main.innerHTML = `
    <div class="card">
      <h2>Agent Statistics</h2>
      <div class="stats-table-wrap">
      <table class="stats-table">
        <thead>
          <tr>
            <th>Name</th><th>Status</th><th>Address</th><th>Role</th>
            <th class="stat-num">Received</th><th class="stat-num">Read</th><th class="stat-num">Unread</th>
            <th class="stat-num">Sent</th><th class="stat-num">Replied</th><th class="stat-num">Forwarded</th>
          </tr>
        </thead>
        <tbody>
          ${statsData.map(a => `
            <tr>
              <td><strong>${esc(a.name)}</strong></td>
              <td style="text-align:center"><span class="status-dot status-${a.status || 'offline'}" title="${a.status === 'online' ? '在线' : a.status === 'idle' ? '空闲' : '离线'}"></span></td>
              <td style="color:var(--muted)">${esc(a.address)}</td>
              <td>${esc(a.role)}</td>
              <td class="stat-num">${a.messages_received}</td>
              <td class="stat-num">${a.messages_read}</td>
              <td class="stat-num" style="color:${a.messages_unread > 0 ? 'var(--danger)' : 'inherit'};font-weight:${a.messages_unread > 0 ? '600' : 'normal'}">${a.messages_unread}</td>
              <td class="stat-num">${a.messages_sent}</td>
              <td class="stat-num">${a.messages_replied}</td>
              <td class="stat-num">${a.messages_forwarded}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      </div>
    </div>`;
}

// --- API Keys view ---

async function showApiKeys() {
  clearNav();
  setSidebarSpecialMode('none');
  document.getElementById('navApiKeys').classList.add('active');
  currentView = { type: 'apikeys' };
  await renderApiKeys();
}

async function renderApiKeys(newKeyData) {
  if (currentView?.type !== 'apikeys') return;
  const main = document.getElementById('main');
  let keys = [];
  try {
    keys = await api('/users/api-keys');
  } catch (e) {
    main.innerHTML = `<div class="card"><p class="empty">Failed to load API keys: ${esc(e.message)}</p></div>`;
    return;
  }

  const newKeyHtml = newKeyData ? `
    <div class="apikey-new-box">
      <div class="apikey-warning">&#9888; This key will only be shown once. Copy it now!</div>
      <div class="apikey-value" id="newKeyValue">${esc(newKeyData.raw_key)}</div>
      <button class="btn-sm" onclick="copyNewKey()">Copy</button>
      <span id="newKeyCopyStatus" style="font-size:12px;color:var(--success);margin-left:8px"></span>
    </div>` : '';

  const keysTableHtml = keys.length === 0
    ? '<div class="empty" style="padding:20px 0">No API keys yet.</div>'
    : `<div style="overflow-x:auto">
      <table class="apikey-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Key</th>
            <th>Created</th>
            <th>Last Used</th>
            <th>Status</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          ${keys.map(k => `
            <tr>
              <td><strong>${esc(k.name)}</strong></td>
              <td class="apikey-masked">${esc(k.masked_key || maskKey(k.key_prefix))}</td>
              <td style="color:var(--muted);font-size:12px">${esc(fmtTime(k.created_at))}</td>
              <td style="color:var(--muted);font-size:12px">${k.last_used_at ? esc(fmtTime(k.last_used_at)) : '—'}</td>
              <td><span class="${k.is_active !== false ? 'apikey-status-active' : 'apikey-status-inactive'}">${k.is_active !== false ? 'Active' : 'Inactive'}</span></td>
              <td style="display:flex;gap:6px;flex-wrap:wrap">
                ${k.is_active !== false
                  ? `<button class="btn-danger-sm" onclick="deactivateApiKey('${esc(k.id)}', '${esc(k.name)}')">Deactivate</button>`
                  : `<button class="btn-sm" onclick="reactivateApiKey('${esc(k.id)}', '${esc(k.name)}')">Reactivate</button>`}
                <button class="btn-danger-sm" onclick="deleteApiKey('${esc(k.id)}', '${esc(k.name)}')">Delete</button>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>`;

  main.innerHTML = `
    <div class="card">
      <h2>API Keys</h2>
      ${newKeyHtml}
      <div style="margin-bottom:20px">
        <h3 style="font-size:14px;font-weight:600;margin-bottom:10px">Create New Key</h3>
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
          <input type="text" id="newKeyName" placeholder="Key name (e.g. my-agent)" style="padding:8px 12px;border:1px solid var(--border);border-radius:6px;font-size:14px;font-family:inherit;min-width:200px">
          <button class="btn btn-primary" onclick="createApiKey()">Create</button>
          <span id="createKeyStatus" style="font-size:13px"></span>
        </div>
      </div>
      <h3 style="font-size:14px;font-weight:600;margin-bottom:10px">Your Keys</h3>
      ${keysTableHtml}
    </div>
    <div class="card">
      <h2>Change Password</h2>
      <div class="compose-form" style="max-width:400px">
        <div>
          <label>Current Password</label>
          <input type="password" id="currentPassword" placeholder="Enter current password">
        </div>
        <div>
          <label>New Password</label>
          <input type="password" id="newPassword" placeholder="Enter new password (min 8 chars)">
        </div>
        <div>
          <label>Confirm New Password</label>
          <input type="password" id="confirmPassword" placeholder="Confirm new password">
        </div>
        <div style="display:flex;gap:12px;align-items:center">
          <button class="btn btn-primary" onclick="changePassword()">Update Password</button>
          <div id="passwordStatus"></div>
        </div>
      </div>
    </div>`;
}

function maskKey(prefix) {
  if (!prefix) return 'amk_****...****';
  return prefix + '****...****';
}

function copyNewKey() {
  const keyEl = document.getElementById('newKeyValue');
  if (!keyEl) return;
  navigator.clipboard.writeText(keyEl.textContent).then(() => {
    const status = document.getElementById('newKeyCopyStatus');
    if (status) { status.textContent = 'Copied!'; setTimeout(() => { status.textContent = ''; }, 2000); }
  }).catch(() => {
    const range = document.createRange();
    range.selectNodeContents(keyEl);
    window.getSelection().removeAllRanges();
    window.getSelection().addRange(range);
  });
}

async function createApiKey() {
  const nameInput = document.getElementById('newKeyName');
  const statusEl = document.getElementById('createKeyStatus');
  const name = nameInput ? nameInput.value.trim() : '';
  if (!name) {
    if (statusEl) { statusEl.textContent = 'Please enter a key name.'; statusEl.style.color = 'var(--danger)'; }
    return;
  }
  try {
    const result = await api('/users/api-keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    await renderApiKeys(result);
  } catch (e) {
    if (statusEl) { statusEl.textContent = 'Error: ' + e.message; statusEl.style.color = 'var(--danger)'; }
  }
}

async function deactivateApiKey(keyId, keyName) {
  const ok = await showConfirm('Deactivate API Key', `Deactivate key "${keyName}"? It will stop working immediately.`, 'Deactivate');
  if (!ok) return;
  try {
    await api(`/users/api-keys/${encodeURIComponent(keyId)}/deactivate`, { method: 'POST' });
    await renderApiKeys();
  } catch (e) {
    alert('Failed: ' + e.message);
  }
}

async function reactivateApiKey(keyId, keyName) {
  try {
    await api(`/users/api-keys/${encodeURIComponent(keyId)}/reactivate`, { method: 'POST' });
    await renderApiKeys();
  } catch (e) {
    alert('Failed: ' + e.message);
  }
}

async function deleteApiKey(keyId, keyName) {
  const ok = await showConfirm('Delete API Key', `Permanently delete key "${keyName}"? This cannot be undone.`, 'Delete');
  if (!ok) return;
  try {
    await api(`/users/api-keys/${encodeURIComponent(keyId)}`, { method: 'DELETE' });
    await renderApiKeys();
  } catch (e) {
    alert('Failed: ' + e.message);
  }
}

async function changePassword() {
  const status = document.getElementById('passwordStatus');
  const current = document.getElementById('currentPassword').value;
  const newPw = document.getElementById('newPassword').value;
  const confirm = document.getElementById('confirmPassword').value;
  status.textContent = '';
  status.className = '';

  if (!current || !newPw || !confirm) {
    status.className = 'compose-status error';
    status.textContent = 'Please fill in all fields.';
    return;
  }
  if (newPw !== confirm) {
    status.className = 'compose-status error';
    status.textContent = 'New passwords do not match.';
    return;
  }
  if (newPw.length < 8) {
    status.className = 'compose-status error';
    status.textContent = 'New password must be at least 8 characters.';
    return;
  }
  try {
    await api('/users/me/password', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password: current, new_password: newPw }),
    });
    status.className = 'compose-status success';
    status.textContent = 'Password changed successfully.';
    document.getElementById('currentPassword').value = '';
    document.getElementById('newPassword').value = '';
    document.getElementById('confirmPassword').value = '';
  } catch (e) {
    status.className = 'compose-status error';
    status.textContent = 'Error: ' + e.message;
  }
}

// --- Admin (superadmin) view ---

async function showAdmin() {
  if (!currentUser?.is_superadmin) return;
  clearNav();
  setSidebarSpecialMode('none');
  document.getElementById('navAdmin').classList.add('active');
  currentView = { type: 'admin' };
  await renderAdmin();
}

async function renderAdmin() {
  if (currentView?.type !== 'admin') return;
  const main = document.getElementById('main');
  main.innerHTML = '<div class="empty">Loading...</div>';

  let users = [], inviteCodes = [];
  try {
    [users, inviteCodes] = await Promise.all([
      api('/superadmin/users'),
      api('/superadmin/invite-codes'),
    ]);
  } catch (e) {
    main.innerHTML = `<div class="card"><p class="empty">Failed to load admin data: ${esc(e.message)}</p></div>`;
    return;
  }

  const usersHtml = users.length === 0
    ? '<div class="empty" style="padding:16px 0">No users.</div>'
    : `<table class="admin-table">
        <thead><tr><th>Username</th><th>Role</th><th>Created</th><th>Action</th></tr></thead>
        <tbody>
          ${users.map(u => `
            <tr>
              <td><strong>${esc(u.username)}</strong></td>
              <td>${u.is_superadmin ? '<span class="superadmin-badge">Superadmin</span>' : '<span style="color:var(--muted);font-size:12px">User</span>'}</td>
              <td style="color:var(--muted);font-size:12px">${esc(fmtTime(u.created_at))}</td>
              <td><button class="btn-sm" onclick="loginAs('${esc(u.id)}', '${esc(u.username)}')">Login As</button></td>
            </tr>
          `).join('')}
        </tbody>
      </table>`;

  const codesHtml = inviteCodes.length === 0
    ? '<div class="empty" style="padding:16px 0">No invite codes generated.</div>'
    : `<table class="admin-table">
        <thead><tr><th>Code</th><th>Used By</th><th>Created</th></tr></thead>
        <tbody>
          ${inviteCodes.map(c => `
            <tr>
              <td class="invite-code-mono">${esc(c.code)}</td>
              <td style="color:var(--muted)">${c.used_by ? esc(c.used_by) : '—'}</td>
              <td style="color:var(--muted);font-size:12px">${esc(fmtTime(c.created_at))}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>`;

  main.innerHTML = `
    <div class="card">
      <h2>Admin Panel</h2>

      <div class="admin-section">
        <h3>Users</h3>
        ${usersHtml}
      </div>

      <div class="admin-section">
        <h3>Invite Codes</h3>
        <div style="margin-bottom:14px;display:flex;align-items:center;gap:12px">
          <button class="btn btn-primary" onclick="generateInviteCode()">Generate Invite Code</button>
          <span id="inviteCodeStatus" style="font-size:13px"></span>
        </div>
        <div id="inviteCodesTable">${codesHtml}</div>
      </div>
    </div>`;
}

async function generateInviteCode() {
  const statusEl = document.getElementById('inviteCodeStatus');
  try {
    const result = await api('/superadmin/invite-codes', { method: 'POST' });
    if (statusEl) {
      statusEl.textContent = 'Generated: ' + (result.code || '');
      statusEl.style.color = 'var(--success)';
      setTimeout(() => { statusEl.textContent = ''; }, 5000);
    }
    const codes = await api('/superadmin/invite-codes');
    const tableEl = document.getElementById('inviteCodesTable');
    if (tableEl && codes.length > 0) {
      tableEl.innerHTML = `<table class="admin-table">
        <thead><tr><th>Code</th><th>Used By</th><th>Created</th></tr></thead>
        <tbody>
          ${codes.map(c => `
            <tr>
              <td class="invite-code-mono">${esc(c.code)}</td>
              <td style="color:var(--muted)">${c.used_by ? esc(c.used_by) : '—'}</td>
              <td style="color:var(--muted);font-size:12px">${esc(fmtTime(c.created_at))}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>`;
    }
  } catch (e) {
    if (statusEl) { statusEl.textContent = 'Error: ' + e.message; statusEl.style.color = 'var(--danger)'; }
  }
}

async function loginAs(userId, username) {
  const ok = await showConfirm('Login As User', `Switch to acting as "${username}"?`, 'Confirm');
  if (!ok) return;
  try {
    await api(`/superadmin/login-as/${encodeURIComponent(userId)}`, { method: 'POST' });
    window.location.reload();
  } catch (e) {
    alert('Failed: ' + e.message);
  }
}

// --- Delete agent ---
async function deleteAgent(agentId, agentName) {
  const ok = await showConfirm(
    '删除 Agent',
    `确定要删除 Agent "${agentName}" 吗？此操作不可撤销。`,
    '删除',
  );
  if (!ok) return;
  try {
    await api(`/admin/agents/${encodeURIComponent(agentId)}`, { method: 'DELETE' });
    if (currentView?.type === 'inbox') {
      currentView = null;
      document.getElementById('main').innerHTML =
        '<div class="empty">Agent has been deleted.</div>';
    }
    await refreshSidebar();
  } catch (e) {
    alert('Delete failed: ' + e.message);
  }
}
