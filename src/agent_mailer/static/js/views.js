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
    <button class="btn btn-secondary pagination-btn" ${page <= 1 ? 'disabled' : ''} onclick="${onClickFn}(${page - 1})">${esc(t('common.prev'))}</button>
    <span class="pagination-info">${esc(t('common.pageInfo', { page, total: totalPages, count: total }))}</span>
    <button class="btn btn-secondary pagination-btn" ${page >= totalPages ? 'disabled' : ''} onclick="${onClickFn}(${page + 1})">${esc(t('common.next'))}</button>
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
      <h2>${esc(t('search.title'))}</h2>
      <div class="compose-form">
        <div>
          <label>${esc(t('search.keyword'))}</label>
          <input type="text" id="searchInput" placeholder="${esc(t('search.placeholder'))}" value="${esc(q)}">
        </div>
        <div>
          <button class="btn btn-primary" onclick="doSearch()">${esc(t('search.button'))}</button>
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
  results.innerHTML = `<p>${esc(t('search.searching'))}</p>`;
  try {
    const data = await api(`/admin/search?q=${encodeURIComponent(q)}&page=${page}&page_size=20`);
    if (data.messages.length === 0) {
      results.innerHTML = `<p class="empty" style="padding:16px 0">${esc(t('search.noResults'))}</p>`;
      return;
    }
    const highlightSnippet = (text, query) => {
      const re = new RegExp('(' + query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
      return esc(text).replace(re, '<mark>$1</mark>');
    };
    results.innerHTML = `
      <div class="stats-table-wrap" style="margin-top:16px">
      <table class="stats-table">
        <thead><tr><th>${esc(t('search.colSubject'))}</th><th>${esc(t('search.colSnippet'))}</th><th>${esc(t('search.colFrom'))}</th><th>${esc(t('search.colDate'))}</th></tr></thead>
        <tbody>${data.messages.map(m => `
          <tr style="cursor:pointer" onclick="showThreadsThread('${esc(m.thread_id)}')">
            <td><strong>${esc(m.subject) || esc(t('common.noSubject'))}</strong></td>
            <td style="font-size:12px;max-width:300px;overflow:hidden;text-overflow:ellipsis">${highlightSnippet(m.body_snippet, q)}</td>
            <td style="color:var(--muted)">${esc(m.from_agent)}</td>
            <td style="color:var(--muted)">${esc(fmtTime(m.created_at))}</td>
          </tr>
        `).join('')}</tbody>
      </table>
      </div>
      ${data.total_pages > 1 ? `<div class="pagination">
        <button class="btn btn-secondary pagination-btn" ${page <= 1 ? 'disabled' : ''} onclick="doSearch(${page - 1})">${esc(t('common.prev'))}</button>
        <span class="pagination-info">${esc(t('common.pageInfoResults', { page: data.page, total: data.total_pages, count: data.total }))}</span>
        <button class="btn btn-secondary pagination-btn" ${page >= data.total_pages ? 'disabled' : ''} onclick="doSearch(${page + 1})">${esc(t('common.next'))}</button>
      </div>` : ''}`;
  } catch (e) {
    results.innerHTML = `<p class="empty">${esc(t('common.errorPrefix'))}${esc(e.message)}</p>`;
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
  document.getElementById('main').innerHTML = `<div class="card"><h2>${esc(t('threads.title'))}</h2><p>${esc(t('threads.loading'))}</p></div>`;
  try {
    await renderThreadsMain();
  } catch (e) {
    document.getElementById('main').innerHTML = `<div class="card"><h2>${esc(t('threads.title'))}</h2><p class="empty">${esc(t('common.errorPrefix'))}${esc(e.message || e)}</p></div>`;
  }
}

async function renderThreadsMain() {
  if (currentView?.type !== 'threads') return;
  const main = document.getElementById('main');
  try {
    await fetchThreadsSummary({});
  } catch (e) {
    main.innerHTML = `<div class="card"><h2>${esc(t('threads.title'))}</h2><p class="empty">${esc(t('threads.loadFailed', { msg: e.message }))}</p></div>`;
    return;
  }
  if (threadsData.length === 0) {
    main.innerHTML = `<div class="card"><h2>${esc(t('threads.title'))}</h2><p class="empty" style="padding:24px 0;text-align:center">${esc(t('threads.empty'))}</p></div>`;
    return;
  }
  const pg = _paginateList(threadsData, currentView.page || 1);
  main.innerHTML = `
    <div class="card">
      <h2>${esc(t('threads.title'))}</h2>
      <div class="stats-table-wrap">
      <table class="stats-table">
        <thead><tr><th>${esc(t('threads.colSubject'))}</th><th>${esc(t('threads.colMessages'))}</th><th>${esc(t('threads.colUnread'))}</th><th>${esc(t('threads.colLastActivity'))}</th></tr></thead>
        <tbody>${pg.items.map(th => `
          <tr style="cursor:pointer" onclick="showThreadsThread('${esc(th.thread_id)}')">
            <td><strong>${esc(th.preview_subject) || esc(t('common.noSubject'))}</strong></td>
            <td class="stat-num">${th.message_count}</td>
            <td class="stat-num" style="color:${th.unread_count > 0 ? 'var(--danger)' : 'inherit'};font-weight:${th.unread_count > 0 ? '600' : 'normal'}">${th.unread_count}</td>
            <td style="color:var(--muted)">${esc(fmtTime(th.last_activity))}</td>
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
  main.innerHTML = `<div class="card"><p>${esc(t('common.loading'))}</p></div>`;
  try {
    const msgs = await fetchThread(threadId);
    main.innerHTML = _renderThreadDetail(msgs, threadId, 'showThreads()', 'threads');
    hydrateMarkdownBodies(main);
  } catch (e) {
    main.innerHTML = `<div class="card"><button type="button" class="back-btn" onclick="showThreads()">${esc(t('common.back'))}</button><p class="empty">${esc(t('common.errorPrefix'))}${esc(e.message)}</p></div>`;
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
      <button class="btn btn-secondary" onclick="_replyToThread()">${esc(t('thread.reply'))}</button>
      <button class="btn btn-secondary" onclick="_forwardFromThread()">${esc(t('thread.forward'))}</button>
      <button class="btn btn-secondary" onclick="archiveThreadAction('${esc(threadId)}', '${esc(backFn)}')">${esc(t('thread.archive'))}</button>
      <button class="btn btn-danger" onclick="trashThreadAction('${esc(threadId)}', '${esc(backFn)}')">${esc(t('common.delete'))}</button>`;
  } else if (context === 'archive') {
    actionsHtml = `
      <button class="btn btn-secondary" onclick="unarchiveThreadAction('${esc(threadId)}', '${esc(backFn)}')">${esc(t('thread.unarchive'))}</button>
      <button class="btn btn-danger" onclick="trashThreadAction('${esc(threadId)}', '${esc(backFn)}')">${esc(t('common.delete'))}</button>`;
  } else if (context === 'trash') {
    actionsHtml = `
      <button class="btn btn-secondary" onclick="restoreThreadAction('${esc(threadId)}', '${esc(backFn)}')">${esc(t('thread.restore'))}</button>
      <button class="btn btn-danger" onclick="purgeThreadAction('${esc(threadId)}', '${esc(backFn)}')">${esc(t('thread.permanentDelete'))}</button>`;
  }
  return `
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:12px">
        <button type="button" class="back-btn" onclick="${backFn}">${esc(t('common.back'))}</button>
        <div class="thread-actions" style="display:flex;gap:8px;flex-wrap:wrap">${actionsHtml}</div>
      </div>
      <h2>${esc(t('thread.title'))}</h2>
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
  if (!await showConfirm(t('thread.confirmArchiveTitle'), t('thread.confirmArchive'), t('thread.archive'))) return;
  try {
    await api(`/admin/threads/${encodeURIComponent(threadId)}/archive`, { method: 'POST' });
    eval(backFn);
  } catch (e) { alert(e.message); }
}

async function unarchiveThreadAction(threadId, backFn) {
  if (!await showConfirm(t('thread.confirmUnarchiveTitle'), t('thread.confirmUnarchive'), t('thread.unarchive'))) return;
  try {
    await api(`/admin/threads/${encodeURIComponent(threadId)}/unarchive`, { method: 'POST' });
    eval(backFn);
  } catch (e) { alert(e.message); }
}

async function restoreThreadAction(threadId, backFn) {
  if (!await showConfirm(t('thread.confirmRestoreTitle'), t('thread.confirmRestore'), t('thread.restore'))) return;
  try {
    await api(`/admin/threads/${encodeURIComponent(threadId)}/restore`, { method: 'POST' });
    eval(backFn);
  } catch (e) { alert(e.message); }
}

async function purgeThreadAction(threadId, backFn) {
  if (!await showConfirm(t('thread.confirmPurgeTitle'), t('thread.confirmPurge'), t('thread.deleteForever'))) return;
  try {
    await api(`/admin/threads/${encodeURIComponent(threadId)}/purge`, { method: 'POST' });
    eval(backFn);
  } catch (e) { alert(e.message); }
}

async function trashThreadAction(threadId, backFn) {
  if (!await showConfirm(t('thread.confirmDeleteTitle'), t('thread.confirmTrash'), t('common.delete'))) return;
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
  document.getElementById('main').innerHTML = `<div class="card"><h2>${esc(t('archive.title'))}</h2><p>${esc(t('archive.loading'))}</p></div>`;
  try {
    await renderArchiveMain();
  } catch (e) {
    document.getElementById('main').innerHTML = `<div class="card"><h2>${esc(t('archive.title'))}</h2><p class="empty">${esc(t('common.errorPrefix'))}${esc(e.message || e)}</p></div>`;
    console.error('showArchive error:', e);
  }
}

async function renderArchiveMain() {
  if (currentView?.type !== 'archive') return;
  const main = document.getElementById('main');
  try {
    await fetchThreadsSummary({ archived: true });
  } catch (e) {
    main.innerHTML = `<div class="card"><h2>${esc(t('archive.title'))}</h2><p class="empty">${esc(t('archive.loadFailed', { msg: e.message }))}</p></div>`;
    return;
  }
  if (threadsData.length === 0) {
    main.innerHTML = `<div class="card"><h2>${esc(t('archive.title'))}</h2><p class="empty" style="padding:24px 0;text-align:center">${esc(t('archive.empty'))}</p></div>`;
    return;
  }
  const pg = _paginateList(threadsData, currentView.page || 1);
  main.innerHTML = `
    <div class="card">
      <h2>${esc(t('archive.title'))}</h2>
      <div class="stats-table-wrap">
      <table class="stats-table">
        <thead><tr><th>${esc(t('threads.colSubject'))}</th><th>${esc(t('threads.colMessages'))}</th><th>${esc(t('threads.colUnread'))}</th><th>${esc(t('threads.colLastActivity'))}</th></tr></thead>
        <tbody>${pg.items.map(th => `
          <tr style="cursor:pointer" onclick="showArchiveThread('${esc(th.thread_id)}')">
            <td><strong>${esc(th.preview_subject) || esc(t('common.noSubject'))}</strong></td>
            <td class="stat-num">${th.message_count}</td>
            <td class="stat-num">${th.unread_count}</td>
            <td style="color:var(--muted)">${esc(fmtTime(th.last_activity))}</td>
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
  document.getElementById('main').innerHTML = `<div class="card"><h2>${esc(t('trash.title'))}</h2><p>${esc(t('trash.loading'))}</p></div>`;
  try {
    await renderTrashMain();
  } catch (e) {
    document.getElementById('main').innerHTML = `<div class="card"><h2>${esc(t('trash.title'))}</h2><p class="empty">${esc(t('common.errorPrefix'))}${esc(e.message || e)}</p></div>`;
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
    main.innerHTML = `<div class="card"><h2>${esc(t('trash.title'))}</h2><p class="empty">${esc(t('trash.loadFailed', { msg: e.message }))}</p></div>`;
    return;
  }
  if (threadsData.length === 0 && trashedMessagesData.length === 0) {
    main.innerHTML = `<div class="card"><h2>${esc(t('trash.title'))}</h2><p class="empty" style="padding:24px 0;text-align:center">${esc(t('trash.empty'))}</p></div>`;
    return;
  }
  const threadsHtml = threadsData.length === 0
    ? `<div class="empty" style="padding:12px 0">${esc(t('trash.noThreads'))}</div>`
    : `<div class="stats-table-wrap">
      <table class="stats-table">
        <thead><tr><th>${esc(t('threads.colSubject'))}</th><th>${esc(t('threads.colMessages'))}</th><th>${esc(t('threads.colUnread'))}</th><th>${esc(t('threads.colTrashedAt'))}</th></tr></thead>
        <tbody>${threadsData.map(th => `
          <tr style="cursor:pointer" onclick="showTrashThread('${esc(th.thread_id)}')">
            <td><strong>${esc(th.preview_subject) || esc(t('common.noSubject'))}</strong></td>
            <td class="stat-num">${th.message_count}</td>
            <td class="stat-num">${th.unread_count}</td>
            <td style="color:var(--muted)">${esc(fmtTime(th.trashed_at || th.last_activity))}</td>
          </tr>
        `).join('')}</tbody>
      </table>
      </div>`;
  const msgsHtml = trashedMessagesData.length === 0
    ? `<div class="empty" style="padding:12px 0">${esc(t('trash.noMessages'))}</div>`
    : `<div class="stats-table-wrap">
      <table class="stats-table">
        <thead><tr><th>${esc(t('threads.colSubject'))}</th><th>${esc(t('threads.colFrom'))}</th><th>${esc(t('threads.colTrashedAt'))}</th></tr></thead>
        <tbody>${trashedMessagesData.map(tm => `
          <tr style="cursor:pointer" onclick="showTrashMessage('${esc(tm.message_id)}')">
            <td><strong>${esc(tm.subject) || esc(t('common.noSubject'))}</strong></td>
            <td style="color:var(--muted)">${esc(tm.from_agent)}</td>
            <td style="color:var(--muted)">${esc(fmtTime(tm.trashed_at))}</td>
          </tr>
        `).join('')}</tbody>
      </table>
      </div>`;
  main.innerHTML = `
    <div class="card">
      <div class="card-header-row">
        <h2>${esc(t('trash.title'))}</h2>
        <button class="btn btn-danger" onclick="emptyTrash()">${esc(t('trash.emptyBtn'))}</button>
      </div>
      <h3 class="team-section-header">${esc(t('trash.trashedThreads'))}</h3>
      ${threadsHtml}
      <h3 class="team-section-header">${esc(t('trash.trashedMessages'))}</h3>
      ${msgsHtml}
    </div>`;
}

async function emptyTrash() {
  if (!await showConfirm(t('trash.confirmEmptyTitle'), t('trash.confirmEmpty'), t('trash.emptyBtn'))) return;
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
  main.innerHTML = `<div class="card"><p>${esc(t('common.loading'))}</p></div>`;
  try {
    const msgs = await fetchThread(threadId);
    main.innerHTML = _renderThreadDetail(msgs, threadId, 'showTrash()', 'trash');
    hydrateMarkdownBodies(main);
  } catch (e) {
    main.innerHTML = `<div class="card"><button type="button" class="back-btn" onclick="showTrash()">${esc(t('common.back'))}</button><p class="empty">${esc(t('common.errorPrefix'))}${esc(e.message)}</p></div>`;
  }
}

async function showTrashMessage(messageId) {
  currentView = { type: 'trashMessage', messageId };
  await renderTrashedMessageView();
}

async function showArchiveThread(threadId) {
  currentView = { type: 'archiveThread', threadId };
  const main = document.getElementById('main');
  main.innerHTML = `<div class="card"><p>${esc(t('common.loading'))}</p></div>`;
  try {
    const msgs = await fetchThread(threadId);
    main.innerHTML = _renderThreadDetail(msgs, threadId, 'showArchive()', 'archive');
    hydrateMarkdownBodies(main);
  } catch (e) {
    main.innerHTML = `<div class="card"><button type="button" class="back-btn" onclick="showArchive()">${esc(t('common.back'))}</button><p class="empty">${esc(t('common.errorPrefix'))}${esc(e.message)}</p></div>`;
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
        <p class="empty">${esc(t('trash.gone'))}</p>
        <button type="button" class="back-btn" id="tmGoneBack">${esc(t('thread.backTrash'))}</button>
      </div>`;
    document.getElementById('tmGoneBack').onclick = () => {
      void showTrash();
    };
    return;
  }
  const m = data.message;
  main.innerHTML = `
    <button type="button" class="back-btn" id="tmBackBtn">${esc(t('thread.backTrash'))}</button>
    <div class="card">
      <h2>${esc(t('trash.messageInTrash'))}</h2>
      <p class="meta">${esc(t('trash.trashedAt', { time: fmtTime(data.trashed_at) }))}</p>
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
        <button type="button" class="btn btn-secondary" id="tmRestoreBtn">${esc(t('trash.restoreBtn'))}</button>
        <button type="button" class="btn btn-secondary" id="tmPurgeBtn" style="background:var(--danger)">${esc(t('trash.purgeBtn'))}</button>
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
    if (!await showConfirm(t('trash.confirmPurgeMsgTitle'), t('trash.confirmPurgeMsgBody'), t('common.delete'))) return;
    try {
      await api(`/admin/messages/${encodeURIComponent(mid)}/purge`, { method: 'POST' });
      await showTrash();
    } catch (e) {
      alert(e.message);
    }
  };
}

async function trashSingleMessage(messageId, opts = {}) {
  if (!await showConfirm(t('inbox.confirmTrashMsgTitle'), t('inbox.confirmTrashMsgBody'), t('inbox.confirmTrashMsgBtn'))) return;
  try {
    await api(`/admin/messages/${encodeURIComponent(messageId)}/trash`, { method: 'POST' });
    if (opts.fromInbox && expandedMsg === messageId) expandedMsg = null;
    if (currentView?.type === 'trashedMessage') {
      currentView = { type: 'trash' };
      document.getElementById('main').innerHTML =
        `<div class="empty">${esc(t('empty.selectTrashItem'))}</div>`;
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
    currentView = { type: 'inbox', address: HUMAN_OPERATOR_ADDRESS, agentId: HUMAN_OPERATOR_AGENT_ID, fromTeamId: '' };
    document.getElementById('main').innerHTML = '';
    await refreshSidebar();
    await renderInbox();
  } else {
    currentView = null;
    document.getElementById('main').innerHTML =
      `<div class="empty">${esc(t('empty.selectAgent'))}</div>`;
    await refreshSidebar();
  }
}

async function showInbox(address, agentId, page, fromTeamId) {
  clearNav();
  setSidebarSpecialMode('none');
  currentView = { type: 'inbox', address, agentId: agentId || null, page: page || 1, fromTeamId: fromTeamId || '' };
  document.getElementById('main').innerHTML = '';
  await refreshSidebar();
  await renderInbox();
}

function renderTagEditor(agentId, tags) {
  if (!agentId) return '';
  const pills = tags.map((tag, i) =>
    `<span class="tag-pill">${esc(tag)}<button class="tag-remove" data-tag-idx="${i}" onclick="event.stopPropagation(); removeTag(${i})">&times;</button></span>`
  ).join('');
  return `<div class="tag-editor" id="tagEditor">${pills}<div class="tag-input-wrap"><input class="tag-input" id="tagInput" type="text" placeholder="${esc(t('tags.addPlaceholder'))}" data-agent-id="${esc(agentId)}" autocomplete="off"><div class="tag-autocomplete" id="tagAutocomplete"></div></div></div>`;
}

function isHumanInbox(address) {
  return HUMAN_OPERATOR_ADDRESS && address === HUMAN_OPERATOR_ADDRESS;
}

async function renderInboxTeamFilter(address, selectedTeamId) {
  if (!isHumanInbox(address)) return '';
  try {
    await fetchTeams();
  } catch (e) {
    return '';
  }
  if (!teamsData.length) return '';
  const options = [
    `<option value="">${esc(t('inbox.allTeams'))}</option>`,
    ...teamsData.map(tm => `<option value="${esc(tm.id)}" ${tm.id === selectedTeamId ? 'selected' : ''}>${esc(tm.name)}</option>`),
  ].join('');
  return `<label class="inbox-team-filter"><span>${esc(t('inbox.teamFilter'))}</span><select onchange="changeInboxTeamFilter(this.value)">${options}</select></label>`;
}

async function changeInboxTeamFilter(teamId) {
  if (currentView?.type !== 'inbox' || !isHumanInbox(currentView.address)) return;
  currentView.fromTeamId = teamId || '';
  currentView.page = 1;
  expandedMsg = null;
  document.getElementById('main').innerHTML = '';
  await renderInbox();
}

async function renderInbox() {
  if (currentView?.type !== 'inbox') return;
  const address = currentView.address;
  const agentId = currentView.agentId;
  const page = currentView.page || 1;
  const fromTeamId = currentView.fromTeamId || '';
  const data = await fetchInbox(address, page, 20, fromTeamId);
  const main = document.getElementById('main');

  const msgs = data.messages;
  const { total, total_pages } = data;

  msgs.forEach(m => { msgCache[m.id] = m; });

  const paginationHtml = total_pages > 1 ? `
    <div class="pagination">
      <button class="btn btn-secondary pagination-btn" ${page <= 1 ? 'disabled' : ''} onclick="showInbox('${esc(address)}', '${esc(agentId || '')}', ${page - 1}, '${esc(fromTeamId)}')">${esc(t('common.prev'))}</button>
      <span class="pagination-info">${esc(t('common.pageInfoMessages', { page, total: total_pages, count: total }))}</span>
      <button class="btn btn-secondary pagination-btn" ${page >= total_pages ? 'disabled' : ''} onclick="showInbox('${esc(address)}', '${esc(agentId || '')}', ${page + 1}, '${esc(fromTeamId)}')">${esc(t('common.next'))}</button>
    </div>` : '';

  const existingList = main.querySelector('.msg-list');
  if (existingList) {
    existingList.innerHTML = msgs.length === 0
      ? ''
      : msgs.map(m => renderMsgItem(m)).join('');
    const emptyEl = main.querySelector('.inbox-empty');
    if (msgs.length === 0 && !emptyEl) {
      existingList.insertAdjacentHTML('afterend', `<div class="empty inbox-empty">${esc(t('inbox.empty'))}</div>`);
    } else if (msgs.length > 0 && emptyEl) {
      emptyEl.remove();
    }
    const oldPag = main.querySelector('.pagination');
    if (oldPag) oldPag.outerHTML = paginationHtml;
    else if (paginationHtml) main.querySelector('.card').insertAdjacentHTML('beforeend', paginationHtml);
    hydrateMarkdownBodies(main);
    return;
  }

  const agentData = agentId ? statsData.find(a => a.agent_id === agentId) : null;
  const currentTags = agentData ? (agentData.tags || []) : [];
  const tagEditorHtml = renderTagEditor(agentId, currentTags);
  const teamFilterHtml = await renderInboxTeamFilter(address, fromTeamId);

  main.innerHTML = `
    <div class="card">
      <div class="card-header-row">
        <h2>${esc(t('inbox.title', { address }))}</h2>
        ${teamFilterHtml}
      </div>
      ${tagEditorHtml}
      <ul class="msg-list">
        ${msgs.map(m => renderMsgItem(m)).join('')}
      </ul>
      ${msgs.length === 0 ? `<div class="empty inbox-empty">${esc(t('inbox.empty'))}</div>` : ''}
      ${paginationHtml}
    </div>`;
  hydrateMarkdownBodies(main);
  hydrateTagInput();
}

function renderMsgItem(m) {
  const isExpanded = expandedMsg === m.id;
  const readClass = m.is_read ? 'read' : 'unread';
  const subjText = esc(m.subject) || esc(t('common.noSubject'));
  return `
    <li class="msg-item ${readClass}">
      <div class="msg-item-head" onclick="toggleMsg('${m.id}', event)">
        <div class="msg-header">
          <span class="msg-from">${esc(m.from_agent)}</span>
          <span>
            <span class="msg-action-tag ${m.action}">${m.action}</span>
            <span class="msg-time">${fmtTime(m.created_at)}</span>
            ${!isExpanded ? `<span class="thread-link msg-item-copy" title="${esc(t('inbox.copyMdTitle'))}" onclick="copyMessageAsMarkdown('${m.id}', event)">${esc(t('inbox.copyMd'))}</span>
            <span class="thread-link msg-item-copy" title="${esc(t('inbox.saveToTeamTitle'))}" onclick="saveMessageToTeam('${m.id}', event)">${esc(t('inbox.saveToTeam'))}</span>` : ''}
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
      <div class="meta">${esc(t('msg.fromTo', { from: m.from_agent, to: m.to_agent }))}</div>
      <div class="meta">${esc(t('msg.actionThread', { action: m.action, thread: m.thread_id.substring(0, 8) }))}</div>
      ${m.parent_id ? `<div class="meta">${esc(t('msg.replyTo', { parent: m.parent_id.substring(0, 8) }))}</div>` : ''}
      <div class="msg-body markdown-body" data-md-html="${mdDataAttr(m.body_html)}"></div>
      <div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:8px;align-items:center">
        <span class="thread-link" data-thread-id="${m.thread_id}" onclick="event.stopPropagation(); showThreadFromInboxLink(this.dataset.threadId)">${esc(t('inbox.viewFullThread'))}</span>
        <span class="thread-link" onclick="replyToMsg('${m.id}', event)">${esc(t('inbox.replyLink'))}</span>
        <span class="thread-link" onclick="forwardToMsg('${m.id}', event)">${esc(t('inbox.forwardLink'))}</span>
        <span class="thread-link" title="${esc(t('inbox.copyMdTitle'))}" onclick="copyMessageAsMarkdown('${m.id}', event)">${esc(t('inbox.copyMd'))}</span>
        <span class="thread-link" title="${esc(t('inbox.saveToTeamTitle'))}" onclick="saveMessageToTeam('${m.id}', event)">${esc(t('inbox.saveToTeam'))}</span>
        ${m.is_read ? `<span class="thread-link" onclick="markMsgUnread('${m.id}', event)">${esc(t('inbox.markUnread'))}</span>` : ''}
        <button type="button" class="btn btn-secondary msg-trash-action" style="font-size:12px;padding:4px 10px"
          onclick="event.stopPropagation(); trashSingleMessage('${m.id}', { fromInbox: true })">${esc(t('inbox.moveMsgToTrash'))}</button>
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
    parts.push(`<button type="button" class="btn btn-secondary" id="restoreThreadBtn">${esc(t('thread.restore'))}</button>`);
    parts.push(
      `<button type="button" class="btn btn-secondary" id="purgeThreadBtn" style="background:var(--danger)">${esc(t('thread.permanentDelete'))}</button>`,
    );
    return parts.join('');
  }
  if (st.archived) {
    parts.push(`<button type="button" class="btn btn-secondary" id="unarchiveThreadBtn">${esc(t('thread.unarchiveBtn'))}</button>`);
  } else {
    parts.push(`<button type="button" class="btn btn-secondary" id="archiveThreadBtn">${esc(t('thread.archiveBtn'))}</button>`);
  }
  parts.push(
    `<button type="button" class="btn btn-secondary" id="trashThreadBtn" style="background:#64748b">${esc(t('thread.moveToTrash'))}</button>`,
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
  let backLabel = t('thread.backInbox');
  if (fromThreadSidebar) {
    if (fromTrash) backLabel = t('thread.backTrash');
    else if (fromArchive) backLabel = t('thread.backArchive');
    else backLabel = t('thread.backThreads');
  }
  const firstSubject = msgs.length > 0 && String(msgs[0].subject || '').trim()
    ? String(msgs[0].subject).trim()
    : '';
  const threadTitle = firstSubject || t('common.noSubject');
  const actionHtml = buildThreadActionButtons(st);
  main.innerHTML = `
    <button type="button" class="back-btn" id="threadBackBtn">${esc(backLabel)}</button>
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
            <span class="thread-link" onclick="replyToMsg('${m.id}', event)">${esc(t('inbox.replyLink'))}</span>
            <span class="thread-link" onclick="forwardToMsg('${m.id}', event)">${esc(t('inbox.forwardLink'))}</span>
            <span class="thread-link" title="${esc(t('inbox.copyMdTitle'))}" onclick="copyMessageAsMarkdown('${m.id}', event)">${esc(t('inbox.copyMd'))}</span>
            <span class="thread-link" title="${esc(t('inbox.saveToTeamTitle'))}" onclick="saveMessageToTeam('${m.id}', event)">${esc(t('inbox.saveToTeam'))}</span>
            ${m.is_read ? `<span class="thread-link" onclick="markMsgUnread('${m.id}', event)">${esc(t('inbox.markUnread'))}</span>` : ''}
            <button type="button" class="btn btn-secondary" style="font-size:12px;padding:4px 10px" onclick="trashSingleMessage('${m.id}', { fromThread: true })">${esc(t('inbox.moveMsgToTrash'))}</button>
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
            `<div class="empty">${esc(t('empty.selectArchiveThread'))}</div>`;
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
          `<div class="empty">${esc(t('empty.selectTrashItem'))}</div>`;
        await refreshSidebar();
      } catch (e) {
        restoreBtn.insertAdjacentText('afterend', ' ' + e.message);
      }
    };
  }
  const purgeBtn = document.getElementById('purgeThreadBtn');
  if (purgeBtn) {
    purgeBtn.onclick = async () => {
      if (!await showConfirm(t('thread.confirmPurgeThreadTitle'), t('thread.confirmPurgeThreadBody'), t('common.delete'))) return;
      try {
        await api(`/admin/threads/${encodeURIComponent(threadId)}/purge`, { method: 'POST' });
        currentView = { type: 'trash' };
        document.getElementById('main').innerHTML =
          `<div class="empty">${esc(t('empty.selectTrashItem'))}</div>`;
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
      `<div class="empty">${esc(t('empty.selectTrashItem'))}</div>`;
    void refreshSidebar();
    return;
  }
  if (currentView?.fromArchive) {
    currentView = { type: 'archive' };
    document.getElementById('main').innerHTML =
      `<div class="empty">${esc(t('empty.selectArchiveThread'))}</div>`;
    void refreshSidebar();
    return;
  }
  currentView = { type: 'threadList' };
  document.getElementById('main').innerHTML =
    `<div class="empty">${esc(t('empty.selectThread'))}</div>`;
  void refreshSidebar();
}

// --- Compose view ---

async function showCompose(prefillTo, prefillSubject, prefillParentId, originalBody, originalBodyHtml, options) {
  options = options || {};
  const mode = options.mode != null ? options.mode : (prefillParentId ? 'reply' : 'send');

  if (agents.length === 0) await fetchAgents();

  let title = t('compose.titleCompose');
  if (mode === 'reply') title = t('compose.titleReply');
  else if (mode === 'forward') title = t('compose.titleForward');

  const forwardScopeBlock = mode === 'forward' ? `
        <div class="compose-forward-scope">
          <label>${esc(t('compose.forwardContent'))}</label>
          <p class="compose-forward-hint">${esc(t('compose.forwardHint'))}</p>
          <label class="compose-radio-row">
            <input type="radio" name="forwardScope" value="message" checked>
            <span>${esc(t('compose.forwardMessageOnly'))}</span>
          </label>
          <label class="compose-radio-row">
            <input type="radio" name="forwardScope" value="thread">
            <span>${esc(t('compose.forwardFullThread'))}</span>
          </label>
        </div>` : '';

  const bodyPlaceholder = mode === 'forward'
    ? t('compose.bodyPlaceholderForward')
    : t('compose.bodyPlaceholderCompose');

  currentView = { type: 'compose' };
  const container = document.getElementById('main');
  container.innerHTML = `
    <div class="card">
      <h2>${esc(title)}</h2>
      <div class="compose-form">
        <div class="compose-to-wrap">
          <label>${esc(t('compose.labelTo'))}</label>
          <input id="composeTo" type="text" placeholder="${esc(t('compose.toPlaceholder'))}" value="${esc(prefillTo || '')}" autocomplete="off">
          <div class="compose-to-dropdown" id="composeToDropdown"></div>
        </div>
        <div>
          <label>${esc(t('compose.labelSubject'))}</label>
          <input id="composeSubject" type="text" placeholder="${esc(t('compose.subjectPlaceholder'))}" value="${esc(prefillSubject || '')}">
        </div>
        ${forwardScopeBlock}
        <div>
          <label>${esc(t('compose.labelBody'))} <span style="font-weight:normal;color:var(--muted);font-size:11px">${esc(t('compose.labelAtHint'))}</span></label>
          <textarea id="composeBody" placeholder="${esc(bodyPlaceholder)}"></textarea>
          <div class="compose-at-dropdown" id="composeAtDropdown"></div>
        </div>
        <div>
          <label>${esc(t('compose.attachments'))}</label>
          <div class="compose-upload-zone" id="composeUploadZone">
            <div class="upload-hint">${esc(t('compose.uploadHint'))} <label class="upload-browse" for="composeFileInput">${esc(t('compose.uploadBrowse'))}</label></div>
            <input type="file" id="composeFileInput" accept="image/png,image/jpeg,image/gif,image/webp" multiple style="display:none">
          </div>
          <div class="compose-attachments" id="composeAttachments"></div>
        </div>
        ${originalBody ? (originalBodyHtml ? `
        <div>
          <label style="color:var(--muted)">${esc(t('compose.reference'))}</label>
          <div class="markdown-body compose-original-md" data-md-html="${mdDataAttr(originalBodyHtml)}"></div>
        </div>` : `
        <div>
          <label style="color:var(--muted)">${esc(t('compose.reference'))}</label>
          <div class="compose-original-md" style="white-space:pre-wrap;color:var(--muted)">${esc(originalBody)}</div>
        </div>`) : ''}
        <input type="hidden" id="composeParentId" value="${prefillParentId || ''}">
        <input type="hidden" id="composeMode" value="${esc(mode)}">
        <div style="display:flex;gap:12px;align-items:center">
          <button class="btn btn-primary" id="sendBtn" onclick="doSend()">${esc(t('compose.send'))}</button>
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
      <img src="${esc(f.url)}" class="compose-attachment-thumb" alt="${esc(f.filename)}" onclick="previewImage('${esc(f.url)}', '${esc(f.filename)}')" style="cursor:pointer" title="${esc(t('compose.clickPreview'))}">
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
  if (hint) hint.textContent = t('compose.uploading');
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
      throw new Error(err.detail || t('compose.uploadFailed'));
    }
    const data = await resp.json();
    composeUploadedFiles.push(data);
    renderComposeAttachments();
  } catch (e) {
    const status = document.getElementById('composeStatus');
    if (status) {
      status.className = 'compose-status error';
      status.textContent = t('compose.uploadError') + e.message;
    }
  } finally {
    if (hint) hint.innerHTML = esc(t('compose.uploadHint')) + ' <label class="upload-browse" for="composeFileInput">' + esc(t('compose.uploadBrowse')) + '</label>';
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

  function summarizeMemoryContent(content) {
    const text = String(content || '')
      .replace(/\r/g, '')
      .split('\n')
      .map(line => line.trim())
      .filter(Boolean)
      .join(' ');
    if (!text) return t('compose.memoryNoContent');
    return text.length > 180 ? text.slice(0, 177).trimEnd() + '...' : text;
  }

  function escapeMarkdownLinkText(text) {
    return String(text || '')
      .replace(/\\/g, '\\\\')
      .replace(/\[/g, '\\[')
      .replace(/\]/g, '\\]');
  }

  function buildMemoryInsert(memory, url) {
    const title = String(memory.title || t('compose.memoryUntitled')).trim();
    const content = String(memory.content || '').trim();
    const body = content || `_${t('compose.memoryNoContent')}_`;
    return [
      `<!-- memory:start id=${memory.id} -->`,
      `### ${t('compose.memoryBlockTitle')}: [${escapeMarkdownLinkText(title)}](${url})`,
      '',
      `${t('compose.memorySource')}: ${url}`,
      '',
      body,
      `<!-- memory:end id=${memory.id} -->`,
    ].join('\n');
  }

  function padBlockInsert(block, before, after) {
    const prefix = before && !before.endsWith('\n\n') ? (before.endsWith('\n') ? '\n' : '\n\n') : '';
    const suffix = after && !after.startsWith('\n\n') ? (after.startsWith('\n') ? '\n' : '\n\n') : '\n\n';
    return prefix + block + suffix;
  }

  async function loadMemories() {
    if (cachedMemories !== null) return cachedMemories;
    try {
      if (teamsData.length === 0) await fetchTeams();
      const all = [];
      for (const team of teamsData) {
        const mems = await fetchTeamMemories(team.id);
        for (const m of mems) all.push({ ...m, team_name: team.name });
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
      .filter(m => !q || m.title.toLowerCase().includes(q) || String(m.content || '').toLowerCase().includes(q))
      .map(m => {
        const url = location.origin + '/memories/' + m.id;
        const meta = m.team_name ? `${t('compose.memoryTeam')}: ${m.team_name}` : t('compose.memoryReference');
        return `<div class="compose-at-item compose-at-memory-item" data-type="memory" data-memory-id="${esc(m.id)}" data-url="${esc(url)}" data-name="${esc(m.title)}">
          <span class="compose-at-label compose-at-label-mem">MEM</span>
          <span class="compose-at-main">
            <span class="compose-at-title">${esc(m.title)}</span>
            <span class="compose-at-summary">${esc(summarizeMemoryContent(m.content))}</span>
            <span class="compose-at-meta">${esc(meta)}</span>
          </span>
        </div>`;
      });

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
    const memoryId = item.dataset.memoryId;
    const pos = textarea.selectionStart;
    // Replace from @ position to current cursor
    const before = textarea.value.substring(0, atStartPos - 1);
    const after = textarea.value.substring(pos);
    const memory = type === 'memory'
      ? (cachedMemories || []).find(m => String(m.id) === String(memoryId))
      : null;
    const insert = type === 'image'
      ? `![${name}](${url})`
      : padBlockInsert(buildMemoryInsert(memory || { id: memoryId, title: name, content: '' }, url), before, after);
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
      dropdown.innerHTML = `<div class="compose-to-empty">${esc(t('compose.noMatchAgents'))}</div>`;
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
  const fwdSubject = subj && /^fwd:/i.test(subj) ? subj : `Fwd: ${subj || t('common.noSubject')}`;
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
    status.textContent = t('compose.errorAddressInvalid', { addr: toValue });
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
    status.textContent = t('compose.sent');
    document.getElementById('composeBody').value = '';
    document.getElementById('composeSubject').value = '';
    document.getElementById('composeParentId').value = '';
    await refreshSidebar();
  } catch (e) {
    status.className = 'compose-status error';
    status.textContent = t('compose.errorPrefix') + e.message;
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
    main.innerHTML = `<div class="card"><h2>${esc(t('stats.title'))}</h2><div class="empty">${esc(t('stats.empty'))}</div></div>`;
    return;
  }
  main.innerHTML = `
    <div class="card">
      <h2>${esc(t('stats.title'))}</h2>
      <div class="stats-table-wrap">
      <table class="stats-table">
        <thead>
          <tr>
            <th>${esc(t('stats.colName'))}</th><th>${esc(t('stats.colStatus'))}</th><th>${esc(t('stats.colAddress'))}</th><th>${esc(t('stats.colRole'))}</th>
            <th class="stat-num">${esc(t('stats.colReceived'))}</th><th class="stat-num">${esc(t('stats.colRead'))}</th><th class="stat-num">${esc(t('stats.colUnread'))}</th>
            <th class="stat-num">${esc(t('stats.colSent'))}</th><th class="stat-num">${esc(t('stats.colReplied'))}</th><th class="stat-num">${esc(t('stats.colForwarded'))}</th>
          </tr>
        </thead>
        <tbody>
          ${statsData.map(a => `
            <tr>
              <td><strong>${esc(a.name)}</strong></td>
              <td style="text-align:center"><span class="status-dot status-${a.status || 'offline'}" title="${esc(_statusTitle(a.status))}"></span></td>
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
    main.innerHTML = `<div class="card"><p class="empty">${esc(t('apikeys.loadFailed', { msg: e.message }))}</p></div>`;
    return;
  }

  const newKeyHtml = newKeyData ? `
    <div class="apikey-new-box">
      <div class="apikey-warning">${esc(t('apikeys.warnOnce'))}</div>
      <div class="apikey-value" id="newKeyValue">${esc(newKeyData.raw_key)}</div>
      <button class="btn-sm" onclick="copyNewKey()">${esc(t('apikeys.copy'))}</button>
      <span id="newKeyCopyStatus" style="font-size:12px;color:var(--success);margin-left:8px"></span>
    </div>` : '';

  const keysTableHtml = keys.length === 0
    ? `<div class="empty" style="padding:20px 0">${esc(t('apikeys.noKeys'))}</div>`
    : `<div style="overflow-x:auto">
      <table class="apikey-table">
        <thead>
          <tr>
            <th>${esc(t('apikeys.colName'))}</th>
            <th>${esc(t('apikeys.colKey'))}</th>
            <th>${esc(t('apikeys.colCreated'))}</th>
            <th>${esc(t('apikeys.colLastUsed'))}</th>
            <th>${esc(t('apikeys.colStatus'))}</th>
            <th>${esc(t('apikeys.colAction'))}</th>
          </tr>
        </thead>
        <tbody>
          ${keys.map(k => `
            <tr>
              <td><strong>${esc(k.name)}</strong></td>
              <td class="apikey-masked">${esc(k.masked_key || maskKey(k.key_prefix))}</td>
              <td style="color:var(--muted);font-size:12px">${esc(fmtTime(k.created_at))}</td>
              <td style="color:var(--muted);font-size:12px">${k.last_used_at ? esc(fmtTime(k.last_used_at)) : '—'}</td>
              <td><span class="${k.is_active !== false ? 'apikey-status-active' : 'apikey-status-inactive'}">${k.is_active !== false ? esc(t('apikeys.active')) : esc(t('apikeys.inactive'))}</span></td>
              <td style="display:flex;gap:6px;flex-wrap:wrap">
                ${k.is_active !== false
                  ? `<button class="btn-danger-sm" onclick="deactivateApiKey('${esc(k.id)}', '${esc(k.name)}')">${esc(t('apikeys.deactivate'))}</button>`
                  : `<button class="btn-sm" onclick="reactivateApiKey('${esc(k.id)}', '${esc(k.name)}')">${esc(t('apikeys.reactivate'))}</button>`}
                <button class="btn-danger-sm" onclick="deleteApiKey('${esc(k.id)}', '${esc(k.name)}')">${esc(t('apikeys.delete'))}</button>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>`;

  main.innerHTML = `
    <div class="card">
      <h2>${esc(t('apikeys.title'))}</h2>
      ${newKeyHtml}
      <div style="margin-bottom:20px">
        <h3 style="font-size:14px;font-weight:600;margin-bottom:10px">${esc(t('apikeys.createSection'))}</h3>
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
          <input type="text" id="newKeyName" placeholder="${esc(t('apikeys.newKeyPlaceholder'))}" style="padding:8px 12px;border:1px solid var(--border);border-radius:6px;font-size:14px;font-family:inherit;min-width:200px">
          <button class="btn btn-primary" onclick="createApiKey()">${esc(t('apikeys.create'))}</button>
          <span id="createKeyStatus" style="font-size:13px"></span>
        </div>
      </div>
      <h3 style="font-size:14px;font-weight:600;margin-bottom:10px">${esc(t('apikeys.yourKeys'))}</h3>
      ${keysTableHtml}
    </div>
    <div class="card">
      <h2>${esc(t('apikeys.changePassword'))}</h2>
      <div class="compose-form" style="max-width:400px">
        <div>
          <label>${esc(t('apikeys.currentPassword'))}</label>
          <input type="password" id="currentPassword" placeholder="${esc(t('apikeys.currentPasswordPlaceholder'))}">
        </div>
        <div>
          <label>${esc(t('apikeys.newPassword'))}</label>
          <input type="password" id="newPassword" placeholder="${esc(t('apikeys.newPasswordPlaceholder'))}">
        </div>
        <div>
          <label>${esc(t('apikeys.confirmPassword'))}</label>
          <input type="password" id="confirmPassword" placeholder="${esc(t('apikeys.confirmPasswordPlaceholder'))}">
        </div>
        <div style="display:flex;gap:12px;align-items:center">
          <button class="btn btn-primary" onclick="changePassword()">${esc(t('apikeys.updatePassword'))}</button>
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
    if (status) { status.textContent = t('apikeys.copied'); setTimeout(() => { status.textContent = ''; }, 2000); }
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
    if (statusEl) { statusEl.textContent = t('apikeys.enterName'); statusEl.style.color = 'var(--danger)'; }
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
    if (statusEl) { statusEl.textContent = t('common.errorPrefix') + e.message; statusEl.style.color = 'var(--danger)'; }
  }
}

async function deactivateApiKey(keyId, keyName) {
  const ok = await showConfirm(t('apikeys.confirmDeactivateTitle'), t('apikeys.confirmDeactivate', { name: keyName }), t('apikeys.deactivate'));
  if (!ok) return;
  try {
    await api(`/users/api-keys/${encodeURIComponent(keyId)}/deactivate`, { method: 'POST' });
    await renderApiKeys();
  } catch (e) {
    alert(t('common.failedPrefix') + e.message);
  }
}

async function reactivateApiKey(keyId, keyName) {
  try {
    await api(`/users/api-keys/${encodeURIComponent(keyId)}/reactivate`, { method: 'POST' });
    await renderApiKeys();
  } catch (e) {
    alert(t('common.failedPrefix') + e.message);
  }
}

async function deleteApiKey(keyId, keyName) {
  const ok = await showConfirm(t('apikeys.confirmDeleteTitle'), t('apikeys.confirmDelete', { name: keyName }), t('common.delete'));
  if (!ok) return;
  try {
    await api(`/users/api-keys/${encodeURIComponent(keyId)}`, { method: 'DELETE' });
    await renderApiKeys();
  } catch (e) {
    alert(t('common.failedPrefix') + e.message);
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
    status.textContent = t('apikeys.fillAllFields');
    return;
  }
  if (newPw !== confirm) {
    status.className = 'compose-status error';
    status.textContent = t('apikeys.passwordMismatch');
    return;
  }
  if (newPw.length < 8) {
    status.className = 'compose-status error';
    status.textContent = t('apikeys.passwordTooShort');
    return;
  }
  try {
    await api('/users/me/password', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password: current, new_password: newPw }),
    });
    status.className = 'compose-status success';
    status.textContent = t('apikeys.passwordChanged');
    document.getElementById('currentPassword').value = '';
    document.getElementById('newPassword').value = '';
    document.getElementById('confirmPassword').value = '';
  } catch (e) {
    status.className = 'compose-status error';
    status.textContent = t('common.errorPrefix') + e.message;
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
  main.innerHTML = `<div class="empty">${esc(t('common.loading'))}</div>`;

  let users = [], inviteCodes = [], settings = { invite_required: true }, adminAgents = [];
  try {
    [users, inviteCodes, settings, adminAgents] = await Promise.all([
      api('/superadmin/users'),
      api('/superadmin/invite-codes'),
      api('/superadmin/settings'),
      api('/superadmin/agents'),
    ]);
  } catch (e) {
    main.innerHTML = `<div class="card"><p class="empty">${esc(t('admin.loadFailed', { msg: e.message }))}</p></div>`;
    return;
  }
  window._adminAgentsCache = adminAgents;

  const usersHtml = users.length === 0
    ? `<div class="empty" style="padding:16px 0">${esc(t('admin.noUsers'))}</div>`
    : `<table class="admin-table">
        <thead><tr><th>${esc(t('admin.colUsername'))}</th><th>${esc(t('admin.colRole'))}</th><th>${esc(t('admin.colCreated'))}</th><th>${esc(t('admin.colAction'))}</th></tr></thead>
        <tbody>
          ${users.map(u => `
            <tr>
              <td><strong>${esc(u.username)}</strong></td>
              <td>${u.is_superadmin ? `<span class="superadmin-badge">${esc(t('admin.roleSuperadmin'))}</span>` : `<span style="color:var(--muted);font-size:12px">${esc(t('admin.roleUser'))}</span>`}</td>
              <td style="color:var(--muted);font-size:12px">${esc(fmtTime(u.created_at))}</td>
              <td><button class="btn-sm" onclick="loginAs('${esc(u.id)}', '${esc(u.username)}')">${esc(t('admin.loginAs'))}</button></td>
            </tr>
          `).join('')}
        </tbody>
      </table>`;

  const codesHtml = inviteCodes.length === 0
    ? `<div class="empty" style="padding:16px 0">${esc(t('admin.noCodes'))}</div>`
    : `<table class="admin-table">
        <thead><tr><th>${esc(t('admin.colCode'))}</th><th>${esc(t('admin.colUsedBy'))}</th><th>${esc(t('admin.colCreated'))}</th></tr></thead>
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

  const inviteRequired = !!settings.invite_required;
  const settingsHtml = `
    <div class="admin-section">
      <h3>${esc(t('admin.settings'))}</h3>
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <label style="display:inline-flex;align-items:center;gap:8px;cursor:pointer">
          <input type="checkbox" id="settingInviteRequired" ${inviteRequired ? 'checked' : ''} onchange="toggleInviteRequired(this)">
          <span>${esc(t('admin.settingInviteRequired'))}</span>
        </label>
        <span id="settingsStatus" style="font-size:13px"></span>
      </div>
      <div style="font-size:12px;color:var(--muted);margin-top:6px">${esc(t('admin.settingInviteRequiredHint'))}</div>
    </div>`;

  const agentsHtml = renderAdminAgentsSection(adminAgents);

  main.innerHTML = `
    <div class="card">
      <h2>${esc(t('admin.title'))}</h2>

      ${settingsHtml}

      <div class="admin-section">
        <h3>${esc(t('admin.agentsTitle'))}</h3>
        <div style="margin-bottom:14px;display:flex;align-items:center;gap:12px;flex-wrap:wrap">
          <button class="btn btn-primary" onclick="openCreateAdminAgent()">+ ${esc(t('admin.agentsNew'))}</button>
          <label style="display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--muted)">
            <input type="checkbox" id="agentsIncludeDeleted" onchange="reloadAdminAgents()"> ${esc(t('admin.agentsShowDeleted'))}
          </label>
          <span id="adminAgentsStatus" style="font-size:13px"></span>
        </div>
        <div id="adminAgentsTable">${agentsHtml}</div>
      </div>

      <div class="admin-section">
        <h3>${esc(t('admin.users'))}</h3>
        ${usersHtml}
      </div>

      <div class="admin-section">
        <h3>${esc(t('admin.inviteCodes'))}</h3>
        <div style="margin-bottom:14px;display:flex;align-items:center;gap:12px">
          <button class="btn btn-primary" onclick="generateInviteCode()">${esc(t('admin.generateCode'))}</button>
          <span id="inviteCodeStatus" style="font-size:13px"></span>
        </div>
        <div id="inviteCodesTable">${codesHtml}</div>
      </div>
    </div>`;
}


// --- Admin Agents (managed agents) ---

function renderAdminAgentsSection(agents) {
  if (!agents || agents.length === 0) {
    return `<div class="empty" style="padding:16px 0">${esc(t('admin.agentsEmpty'))}</div>`;
  }
  return `<table class="admin-table">
    <thead><tr>
      <th>${esc(t('admin.agentsColName'))}</th>
      <th>${esc(t('admin.agentsColRole'))}</th>
      <th>${esc(t('admin.agentsColAddress'))}</th>
      <th>${esc(t('admin.agentsColApiKey'))}</th>
      <th>${esc(t('admin.agentsColStatus'))}</th>
      <th>${esc(t('admin.colCreated'))}</th>
      <th>${esc(t('admin.colAction'))}</th>
    </tr></thead>
    <tbody>
      ${agents.map(a => `
        <tr${(a.status === 'deleted') ? ' style="opacity:0.5"' : ''}>
          <td><strong>${esc(a.name)}</strong></td>
          <td>${esc(a.role || '')}</td>
          <td class="invite-code-mono">${esc(a.address)}</td>
          <td class="invite-code-mono">${esc(a.api_key_masked || '')}</td>
          <td>${a.status === 'deleted' ? `<span style="color:var(--danger);font-size:12px">${esc(t('admin.agentsStatusDeleted'))}</span>` : `<span style="color:var(--success);font-size:12px">${esc(t('admin.agentsStatusActive'))}</span>`}</td>
          <td style="color:var(--muted);font-size:12px">${esc(fmtTime(a.created_at))}</td>
          <td>
            ${a.status === 'deleted'
              ? `<span style="color:var(--muted);font-size:12px">—</span>`
              : `
                <button class="btn-sm" onclick="openEditAdminAgent('${esc(a.id)}')">${esc(t('admin.agentsEdit'))}</button>
                <button class="btn-sm" onclick="regenerateAdminAgentKey('${esc(a.id)}', '${esc(a.name)}')">${esc(t('admin.agentsRegen'))}</button>
                <button class="btn-sm" onclick="exportAdminAgentMd('${esc(a.id)}', '${esc(a.name)}', 'agent_md')">AGENT.md</button>
                <button class="btn-sm" onclick="exportAdminAgentMd('${esc(a.id)}', '${esc(a.name)}', 'soul_md')">SOUL.md</button>
                <button class="btn-sm" onclick="deleteAdminAgent('${esc(a.id)}', '${esc(a.name)}')">${esc(t('admin.agentsDelete'))}</button>
              `}
          </td>
        </tr>
      `).join('')}
    </tbody>
  </table>`;
}

async function reloadAdminAgents() {
  const tableEl = document.getElementById('adminAgentsTable');
  const includeDeleted = !!document.getElementById('agentsIncludeDeleted')?.checked;
  if (!tableEl) return;
  try {
    const list = await api('/superadmin/agents' + (includeDeleted ? '?include_deleted=true' : ''));
    window._adminAgentsCache = list;
    tableEl.innerHTML = renderAdminAgentsSection(list);
  } catch (e) {
    tableEl.innerHTML = `<div class="empty" style="padding:16px 0;color:var(--danger)">${esc(t('common.errorPrefix'))}${esc(e.message)}</div>`;
  }
}

function _adminAgentsModal(html) {
  let overlay = document.getElementById('adminAgentModal');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'adminAgentModal';
    overlay.className = 'modal-overlay';
    overlay.style.display = 'flex';
    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeAdminAgentModal(); });
    document.body.appendChild(overlay);
  } else {
    overlay.style.display = 'flex';
  }
  overlay.innerHTML = `<div class="compose-modal-box">
    <button class="compose-modal-close" onclick="closeAdminAgentModal()">&times;</button>
    ${html}
  </div>`;
  return overlay;
}

function closeAdminAgentModal() {
  const o = document.getElementById('adminAgentModal');
  if (o) { o.style.display = 'none'; o.innerHTML = ''; }
}

async function _fetchTeamOptions(selectedId) {
  let teams = [];
  try {
    teams = await api('/admin/teams');
  } catch (e) {
    return `<option value="">${esc(t('admin.agentsTeamLoadFailed'))}</option>`;
  }
  const opts = [`<option value="">${esc(t('admin.agentsTeamNone'))}</option>`];
  for (const team of teams) {
    const sel = (team.id === selectedId) ? ' selected' : '';
    opts.push(`<option value="${esc(team.id)}"${sel}>${esc(team.name)}</option>`);
  }
  return opts.join('');
}

async function openCreateAdminAgent() {
  const teamOpts = await _fetchTeamOptions(null);
  _adminAgentsModal(`
    <h3 style="margin-top:0">${esc(t('admin.agentsNewTitle'))}</h3>
    <div class="login-form">
      <div>
        <label>${esc(t('admin.agentsFieldName'))} *</label>
        <input type="text" id="aaName" placeholder="pm">
      </div>
      <div>
        <label>${esc(t('admin.agentsFieldAddress'))}</label>
        <div style="display:flex;align-items:center;gap:6px">
          <input type="text" id="aaAddrLocal" placeholder="${esc(t('admin.agentsAddressDefault'))}" style="flex:1">
          <span style="color:var(--muted);font-size:13px">@admin.amp.linkyun.co</span>
        </div>
      </div>
      <div>
        <label>${esc(t('admin.agentsFieldRole'))}</label>
        <input type="text" id="aaRole" placeholder="coder / pm / reviewer / ...">
      </div>
      <div>
        <label>${esc(t('admin.agentsFieldDescription'))}</label>
        <input type="text" id="aaDescription">
      </div>
      <div>
        <label>${esc(t('admin.agentsFieldSystemPrompt'))}</label>
        <textarea id="aaSystemPrompt" rows="6" style="width:100%;font-family:var(--mono,monospace);font-size:13px"></textarea>
      </div>
      <div>
        <label>${esc(t('admin.agentsFieldTags'))}</label>
        <input type="text" id="aaTags" placeholder="${esc(t('admin.agentsTagsHint'))}">
      </div>
      <div>
        <label>${esc(t('admin.agentsFieldTeam'))}</label>
        <select id="aaTeamId" style="width:100%">${teamOpts}</select>
      </div>
      <div id="aaError" class="login-error" style="display:none"></div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="modal-cancel" onclick="closeAdminAgentModal()">${esc(t('common.cancel'))}</button>
        <button class="login-btn" id="aaSubmit" onclick="submitCreateAdminAgent()">${esc(t('common.create'))}</button>
      </div>
    </div>
  `);
}

async function submitCreateAdminAgent() {
  const errEl = document.getElementById('aaError');
  const btn = document.getElementById('aaSubmit');
  errEl.style.display = 'none';
  const name = document.getElementById('aaName').value.trim();
  if (!name) { errEl.textContent = t('admin.agentsErrorName'); errEl.style.display = ''; return; }
  const local = document.getElementById('aaAddrLocal').value.trim();
  const tagsRaw = document.getElementById('aaTags').value.trim();
  const tags = tagsRaw ? tagsRaw.split(',').map(s => s.trim()).filter(Boolean) : [];
  const teamId = document.getElementById('aaTeamId')?.value || '';
  btn.disabled = true;
  try {
    const created = await api('/superadmin/agents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        address_local: local || null,
        role: document.getElementById('aaRole').value.trim(),
        description: document.getElementById('aaDescription').value.trim(),
        system_prompt: document.getElementById('aaSystemPrompt').value,
        tags,
        team_id: teamId,
      }),
    });
    closeAdminAgentModal();
    showAdminAgentApiKey(created.api_key_plaintext, created.name, t('admin.agentsKeyCreatedTitle'));
    await reloadAdminAgents();
  } catch (e) {
    errEl.textContent = e.message;
    errEl.style.display = '';
    btn.disabled = false;
  }
}

async function openEditAdminAgent(agentId) {
  const agent = (window._adminAgentsCache || []).find(a => a.id === agentId);
  if (!agent) return;
  const teamOpts = await _fetchTeamOptions(agent.team_id);
  _adminAgentsModal(`
    <h3 style="margin-top:0">${esc(t('admin.agentsEditTitle', { name: agent.name }))}</h3>
    <div class="login-form">
      <div>
        <label>${esc(t('admin.agentsFieldAddress'))}</label>
        <input type="text" value="${esc(agent.address)}" disabled style="opacity:0.7">
      </div>
      <div>
        <label>${esc(t('admin.agentsFieldRole'))}</label>
        <input type="text" id="aaRole" value="${esc(agent.role || '')}">
      </div>
      <div>
        <label>${esc(t('admin.agentsFieldDescription'))}</label>
        <input type="text" id="aaDescription" value="${esc(agent.description || '')}">
      </div>
      <div>
        <label>${esc(t('admin.agentsFieldSystemPrompt'))}</label>
        <textarea id="aaSystemPrompt" rows="8" style="width:100%;font-family:var(--mono,monospace);font-size:13px">${esc(agent.system_prompt || '')}</textarea>
      </div>
      <div>
        <label>${esc(t('admin.agentsFieldTags'))}</label>
        <input type="text" id="aaTags" value="${esc((agent.tags || []).join(', '))}">
      </div>
      <div>
        <label>${esc(t('admin.agentsFieldTeam'))}</label>
        <select id="aaTeamId" style="width:100%">${teamOpts}</select>
      </div>
      <div id="aaError" class="login-error" style="display:none"></div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="modal-cancel" onclick="closeAdminAgentModal()">${esc(t('common.cancel'))}</button>
        <button class="login-btn" id="aaSubmit" onclick="submitEditAdminAgent('${esc(agentId)}')">${esc(t('common.save'))}</button>
      </div>
    </div>
  `);
}

async function submitEditAdminAgent(agentId) {
  const errEl = document.getElementById('aaError');
  const btn = document.getElementById('aaSubmit');
  errEl.style.display = 'none';
  btn.disabled = true;
  const tagsRaw = document.getElementById('aaTags').value.trim();
  const tags = tagsRaw ? tagsRaw.split(',').map(s => s.trim()).filter(Boolean) : [];
  const teamId = document.getElementById('aaTeamId')?.value || '';
  try {
    await api(`/superadmin/agents/${encodeURIComponent(agentId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        role: document.getElementById('aaRole').value.trim(),
        description: document.getElementById('aaDescription').value.trim(),
        system_prompt: document.getElementById('aaSystemPrompt').value,
        tags,
        team_id: teamId,
      }),
    });
    closeAdminAgentModal();
    await reloadAdminAgents();
  } catch (e) {
    errEl.textContent = e.message;
    errEl.style.display = '';
    btn.disabled = false;
  }
}

async function deleteAdminAgent(agentId, name) {
  const ok = await showConfirm(
    t('admin.agentsDeleteTitle'),
    t('admin.agentsDeleteConfirm', { name }),
    t('common.confirm'),
  );
  if (!ok) return;
  try {
    await api(`/superadmin/agents/${encodeURIComponent(agentId)}`, { method: 'DELETE' });
    await reloadAdminAgents();
  } catch (e) {
    alert(t('common.failedPrefix') + e.message);
  }
}

async function regenerateAdminAgentKey(agentId, name) {
  const ok = await showConfirm(
    t('admin.agentsRegenTitle'),
    t('admin.agentsRegenConfirm', { name }),
    t('common.confirm'),
  );
  if (!ok) return;
  try {
    const result = await api(`/superadmin/agents/${encodeURIComponent(agentId)}/regenerate-key`, { method: 'POST' });
    showAdminAgentApiKey(result.api_key_plaintext, name, t('admin.agentsKeyRegenTitle'));
    await reloadAdminAgents();
  } catch (e) {
    alert(t('common.failedPrefix') + e.message);
  }
}

function showAdminAgentApiKey(rawKey, name, title) {
  // Cache plaintext briefly so subsequent export-while-modal-open can embed it.
  window._adminAgentLastKey = { name, key: rawKey, ts: Date.now() };
  _adminAgentsModal(`
    <h3 style="margin-top:0">${esc(title)} — ${esc(name)}</h3>
    <p style="color:var(--danger);font-size:13px">${esc(t('admin.agentsKeyOnceWarn'))}</p>
    <div class="step-code" style="user-select:all;word-break:break-all;font-size:13px">${esc(rawKey)}</div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
      <button class="login-btn" onclick="copyText(${JSON.stringify(rawKey)}); this.textContent='${esc(t('splash.copied'))}'">${esc(t('splash.copy'))}</button>
      <button class="modal-cancel" onclick="forgetAdminAgentLastKey(); closeAdminAgentModal()">${esc(t('common.confirm'))}</button>
    </div>
  `);
}

function forgetAdminAgentLastKey() {
  window._adminAgentLastKey = null;
}

function copyText(text) {
  navigator.clipboard.writeText(text).catch(() => {});
}

function downloadTextAs(filename, content) {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 0);
}

function _renderExportModal({ agentId, name, format, filename, content, hasFreshKey }) {
  // Buttons are wired with addEventListener instead of inline onclick so the
  // markdown payload (which carries embedded `"` and `'` from the protocol
  // section + security note) cannot break out of the HTML attribute and
  // silently disable Copy / Download — that class of bug bit us once already.
  const hint = hasFreshKey
    ? t('admin.agentsExportHintWithKey')
    : t('admin.agentsExportHint');
  _adminAgentsModal(`
    <h3 style="margin-top:0">${esc(filename)} — ${esc(name)}</h3>
    <p style="font-size:12px;color:var(--muted)">${esc(hint)}</p>
    <textarea readonly rows="20" style="width:100%;font-family:var(--mono,monospace);font-size:12px">${esc(content)}</textarea>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;flex-wrap:wrap">
      <button id="aaExportCopyBtn" class="login-btn">${esc(t('splash.copy'))}</button>
      <button id="aaExportDownloadBtn" class="login-btn">${esc(t('admin.agentsExportDownloadPlaceholder'))}</button>
      <button id="aaExportRegenBtn" class="login-btn" style="background:var(--danger,#c0392b);color:#fff">${esc(t('admin.agentsExportRegenAndDownload'))}</button>
      <button id="aaExportCloseBtn" class="modal-cancel">${esc(t('common.confirm'))}</button>
    </div>
  `);
  const copyBtn = document.getElementById('aaExportCopyBtn');
  if (copyBtn) {
    copyBtn.addEventListener('click', () => {
      copyText(content);
      copyBtn.textContent = t('splash.copied');
    });
  }
  const downloadBtn = document.getElementById('aaExportDownloadBtn');
  if (downloadBtn) {
    downloadBtn.addEventListener('click', () => downloadTextAs(filename, content));
  }
  const regenBtn = document.getElementById('aaExportRegenBtn');
  if (regenBtn) {
    regenBtn.addEventListener('click', () => regenAndDownloadAdminAgentMd(agentId, name, format, filename));
  }
  const closeBtn = document.getElementById('aaExportCloseBtn');
  if (closeBtn) {
    closeBtn.addEventListener('click', closeAdminAgentModal);
  }
}

async function exportAdminAgentMd(agentId, name, format) {
  try {
    const result = await api(`/superadmin/agents/${encodeURIComponent(agentId)}/export?format=${encodeURIComponent(format)}`);
    let content = result.content;
    let hasFreshKey = false;
    const last = window._adminAgentLastKey;
    if (last && last.name === name && (Date.now() - last.ts) < 5 * 60 * 1000) {
      content = content.split('<your_api_key>').join(last.key);
      hasFreshKey = true;
    }
    _renderExportModal({
      agentId, name, format, filename: result.filename, content, hasFreshKey,
    });
  } catch (e) {
    alert(t('common.failedPrefix') + e.message);
  }
}

async function regenAndDownloadAdminAgentMd(agentId, name, format, filename) {
  // Close the Export Modal before showing the confirm dialog. The two share
  // a `.modal-overlay` z-index, and stacking left the confirm hidden behind
  // the Export Modal in production (user-reported P2).
  closeAdminAgentModal();

  const ok = await showConfirm(
    t('admin.agentsExportRegenConfirmTitle'),
    t('admin.agentsExportRegenConfirmBody', { name }),
    t('admin.agentsExportRegenConfirmCta'),
  );
  if (!ok) {
    // Cancel path: restore the export modal so the admin "feels nothing happened".
    // 5min cache is untouched since regenerate-key was never called.
    await exportAdminAgentMd(agentId, name, format);
    return;
  }

  // Confirmed: rotate the key first; old key is revoked the moment the API returns.
  let regen;
  try {
    regen = await api(
      `/superadmin/agents/${encodeURIComponent(agentId)}/regenerate-key`,
      { method: 'POST' },
    );
  } catch (e) {
    // regenerate-key failed — old key is still valid; do not download anything.
    alert(t('common.failedPrefix') + e.message);
    return;
  }

  // Update the 5min cache + refresh the list to surface the new mask.
  window._adminAgentLastKey = { name, key: regen.api_key_plaintext, ts: Date.now() };
  try { await reloadAdminAgents(); } catch (_) { /* non-critical */ }

  // Fetch fresh export and trigger the file save.
  let downloaded = false;
  try {
    const exp = await api(
      `/superadmin/agents/${encodeURIComponent(agentId)}/export?format=${encodeURIComponent(format)}`,
    );
    const content = exp.content.split('<your_api_key>').join(regen.api_key_plaintext);
    downloadTextAs(filename, content);
    downloaded = true;
  } catch (e) {
    // regen succeeded but the download path failed — surface the new plaintext
    // via the existing reveal modal so the admin doesn't lose access permanently.
    alert(t('common.failedPrefix') + e.message);
    showAdminAgentApiKey(regen.api_key_plaintext, name, t('admin.agentsKeyRegenTitle'));
    return;
  }

  if (downloaded) {
    alert(t('admin.agentsExportRegenSuccess'));
  }
}

async function toggleInviteRequired(checkbox) {
  const statusEl = document.getElementById('settingsStatus');
  const desired = !!checkbox.checked;
  checkbox.disabled = true;
  if (statusEl) { statusEl.textContent = t('common.saving'); statusEl.style.color = 'var(--muted)'; }
  try {
    const result = await api('/superadmin/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ invite_required: desired }),
    });
    checkbox.checked = !!result.invite_required;
    if (statusEl) {
      statusEl.textContent = t('admin.settingsSaved');
      statusEl.style.color = 'var(--success)';
      setTimeout(() => { statusEl.textContent = ''; }, 3000);
    }
  } catch (e) {
    checkbox.checked = !desired;
    if (statusEl) { statusEl.textContent = t('common.errorPrefix') + e.message; statusEl.style.color = 'var(--danger)'; }
  } finally {
    checkbox.disabled = false;
  }
}

async function generateInviteCode() {
  const statusEl = document.getElementById('inviteCodeStatus');
  try {
    const result = await api('/superadmin/invite-codes', { method: 'POST' });
    if (statusEl) {
      statusEl.textContent = t('admin.generated', { code: result.code || '' });
      statusEl.style.color = 'var(--success)';
      setTimeout(() => { statusEl.textContent = ''; }, 5000);
    }
    const codes = await api('/superadmin/invite-codes');
    const tableEl = document.getElementById('inviteCodesTable');
    if (tableEl && codes.length > 0) {
      tableEl.innerHTML = `<table class="admin-table">
        <thead><tr><th>${esc(t('admin.colCode'))}</th><th>${esc(t('admin.colUsedBy'))}</th><th>${esc(t('admin.colCreated'))}</th></tr></thead>
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
    if (statusEl) { statusEl.textContent = t('common.errorPrefix') + e.message; statusEl.style.color = 'var(--danger)'; }
  }
}

async function loginAs(userId, username) {
  const ok = await showConfirm(t('admin.confirmLoginAsTitle'), t('admin.confirmLoginAs', { name: username }), t('common.confirm'));
  if (!ok) return;
  try {
    await api(`/superadmin/login-as/${encodeURIComponent(userId)}`, { method: 'POST' });
    window.location.reload();
  } catch (e) {
    alert(t('common.failedPrefix') + e.message);
  }
}

// --- Delete agent ---
async function deleteAgent(agentId, agentName) {
  const ok = await showConfirm(
    t('agent.deleteTitle'),
    t('agent.deleteConfirm', { name: agentName }),
    t('common.delete'),
  );
  if (!ok) return;
  try {
    await api(`/admin/agents/${encodeURIComponent(agentId)}`, { method: 'DELETE' });
    if (currentView?.type === 'inbox') {
      currentView = null;
      document.getElementById('main').innerHTML =
        `<div class="empty">${esc(t('empty.agentDeleted'))}</div>`;
    }
    await refreshSidebar();
  } catch (e) {
    alert(t('agent.deleteFailed', { msg: e.message }));
  }
}
