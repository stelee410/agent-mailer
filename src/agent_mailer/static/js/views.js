// --- Archive & Trash views ---

async function showArchive() {
  clearNav();
  document.getElementById('navArchive').classList.add('active');
  setSidebarSpecialMode('archive');
  currentView = { type: 'archive' };
  document.getElementById('main').innerHTML =
    '<div class="empty">Select an archived thread from the sidebar.</div>';
  await refreshSidebar();
}

async function showTrash() {
  clearNav();
  document.getElementById('navTrash').classList.add('active');
  setSidebarSpecialMode('trash');
  currentView = { type: 'trash' };
  document.getElementById('main').innerHTML =
    '<div class="empty">Select a deleted thread or message from the sidebar.</div>';
  await refreshSidebar();
}

async function showTrashedMessageFromTrash(messageId) {
  clearNav();
  document.getElementById('navTrash').classList.add('active');
  setSidebarSpecialMode('trash');
  currentView = { type: 'trashedMessage', messageId };
  await refreshSidebar();
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
      currentView = { type: 'trash' };
      main.innerHTML =
        '<div class="empty">Select a deleted thread or message from the sidebar.</div>';
      void refreshSidebar();
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
    currentView = { type: 'trash' };
    main.innerHTML =
      '<div class="empty">Select a deleted thread or message from the sidebar.</div>';
    void refreshSidebar();
  };
  document.getElementById('tmRestoreBtn').onclick = async () => {
    try {
      await api(`/admin/messages/${encodeURIComponent(mid)}/restore`, { method: 'POST' });
      currentView = { type: 'trash' };
      main.innerHTML =
        '<div class="empty">Select a deleted thread or message from the sidebar.</div>';
      await refreshSidebar();
    } catch (e) {
      alert(e.message);
    }
  };
  document.getElementById('tmPurgeBtn').onclick = async () => {
    if (!await showConfirm('永久删除消息', '确定要永久删除这条消息吗？此操作不可撤销。', '删除')) return;
    try {
      await api(`/admin/messages/${encodeURIComponent(mid)}/purge`, { method: 'POST' });
      currentView = { type: 'trash' };
      main.innerHTML =
        '<div class="empty">Select a deleted thread or message from the sidebar.</div>';
      await refreshSidebar();
    } catch (e) {
      alert(e.message);
    }
  };
}

async function trashSingleMessage(messageId, opts = {}) {
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

async function showInbox(address, agentId) {
  clearNav();
  setSidebarSpecialMode('none');
  currentView = { type: 'inbox', address, agentId: agentId || null };
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
  const msgs = await fetchInbox(address);
  const main = document.getElementById('main');

  msgs.forEach(m => { msgCache[m.id] = m; });

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
  clearNav();
  setSidebarSpecialMode('none');
  document.getElementById('navCompose').classList.add('active');
  currentView = { type: 'compose' };

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

  const main = document.getElementById('main');
  main.innerHTML = `
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
          <label>Body</label>
          <textarea id="composeBody" placeholder="${esc(bodyPlaceholder)}"></textarea>
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
  hydrateMarkdownBodies(main);
  hydrateComposeToInput();
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
            <th>Name</th><th>Address</th><th>Role</th>
            <th class="stat-num">Received</th><th class="stat-num">Read</th><th class="stat-num">Unread</th>
            <th class="stat-num">Sent</th><th class="stat-num">Replied</th><th class="stat-num">Forwarded</th>
          </tr>
        </thead>
        <tbody>
          ${statsData.map(a => `
            <tr>
              <td><strong>${esc(a.name)}</strong></td>
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
      <div class="apikey-value" id="newKeyValue">${esc(newKeyData.key)}</div>
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
              <td><button class="btn-danger-sm" onclick="deactivateApiKey('${esc(k.id)}', '${esc(k.name)}')">Deactivate</button></td>
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
    await api(`/users/api-keys/${encodeURIComponent(keyId)}`, { method: 'DELETE' });
    await renderApiKeys();
  } catch (e) {
    alert('Failed: ' + e.message);
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
