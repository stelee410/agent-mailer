// --- Sidebar ---

function _statusTitle(status) {
  if (status === 'online') return t('sidebar.statusOnline');
  if (status === 'idle') return t('sidebar.statusIdle');
  return t('sidebar.statusOffline');
}

function _renderSidebarAgent(a, activeAddr, indented) {
  const indent = indented ? ' sidebar-agent-indented' : '';
  return `
    <div class="agent-item${indent} ${a.address === activeAddr ? 'active' : ''}"
         onclick='showInbox(${JSON.stringify(a.address)}, ${JSON.stringify(a.agent_id || a.id)})'>
      <div class="agent-info">
        <div class="agent-name"><span class="status-dot status-${a.status || 'offline'}" title="${esc(_statusTitle(a.status))}"></span>${esc(a.name)}</div>
        <div class="agent-role">${esc(a.role)} &middot; ${esc(a.address)}</div>
      </div>
      <span class="badge ${(a.messages_unread || 0) === 0 ? 'zero' : ''}">${a.messages_unread || 0}</span>
    </div>`;
}

// Reset the sidebar list container into a known shape and return it. If the
// container's data-shape already matches the requested shape, the existing
// children are preserved so diffList can patch them in place.
function _ensureSidebarShape(list, shape, scaffoldHtml) {
  if (list.dataset.shape === shape) return;
  list.dataset.shape = shape;
  list.innerHTML = scaffoldHtml || '';
}

// Render a list whose only child is a single empty-state element when items is
// empty. Returns the keyed container element used for diffing.
function _renderKeyedList(list, items, getKey, renderItem, emptyHtml) {
  if (items.length === 0) {
    if (list.dataset.shape !== 'empty') {
      list.dataset.shape = 'empty';
      list.innerHTML = emptyHtml;
    }
    return null;
  }
  if (list.dataset.shape !== 'keyed') {
    list.dataset.shape = 'keyed';
    list.innerHTML = '';
  }
  diffList(list, items, getKey, renderItem);
  return list;
}

/** @param {'none'|'archive'|'trash'} mode */
function setSidebarSpecialMode(mode) {
  const sel = document.getElementById('sidebarModeSelect');
  const lab = document.getElementById('sidebarModeLabel');
  if (!sel || !lab) return;
  if (mode === 'none') {
    sel.disabled = false;
    lab.textContent = t('sidebar.label');
  } else {
    sel.disabled = true;
    lab.textContent = mode === 'archive' ? t('sidebar.archive') : t('sidebar.trash');
  }
  updateFilterVisibility();
}

async function refreshSidebar() {
  const list = document.getElementById('agentList');
  const sel = document.getElementById('sidebarModeSelect');
  const sidebarInSpecialMode = sel && sel.disabled;
  const inTrashContext = sidebarInSpecialMode && (
    currentView?.type === 'trash' ||
    currentView?.type === 'trashedMessage' ||
    (currentView?.type === 'thread' && currentView.fromTrash));
  const inArchiveContext = sidebarInSpecialMode && (
    currentView?.type === 'archive' ||
    (currentView?.type === 'thread' && currentView.fromArchive));

  const noSubj = t('sidebar.noSubject');
  const msgSuffix = t('sidebar.msgCountSuffix');

  const renderThreadItem = (th, activeTid, context) => `
    <div class="agent-item thread-sidebar-item ${th.thread_id === activeTid ? 'active' : ''}"
         data-thread-id="${th.thread_id}"
         onclick="showThreadFromSidebar(this.dataset.threadId, ${context === null ? 'null' : `'${context}'`})">
      <div class="agent-info">
        <div class="agent-name">${esc(th.preview_subject) || esc(noSubj)}</div>
        <div class="agent-role">${esc(th.thread_id.substring(0, 8))}&hellip; &middot; ${th.message_count} ${esc(msgSuffix)}</div>
      </div>
      <span class="badge ${th.unread_count === 0 ? 'zero' : ''}">${th.unread_count}</span>
    </div>`;

  if (inTrashContext) {
    await Promise.allSettled([
      fetchThreadsSummary({ trashed: true }),
      fetchTrashedMessages(),
    ]);
    const activeTid = currentView?.type === 'thread' ? currentView.threadId : null;
    const activeMid = currentView?.type === 'trashedMessage' ? currentView.messageId : null;
    if (threadsData.length === 0 && trashedMessagesData.length === 0) {
      _ensureSidebarShape(list, 'trashEmpty',
        `<div class="empty" style="padding:20px 16px;font-size:12px">${esc(t('sidebar.emptyTrash'))}</div>`);
      return;
    }
    _ensureSidebarShape(list, 'trashSplit',
      `<div class="trash-split-title">${esc(t('sidebar.threadsDeleted'))}</div>` +
      `<div class="trash-section" data-trash-section="threads"></div>` +
      `<div class="trash-split-title">${esc(t('sidebar.messagesDeleted'))}</div>` +
      `<div class="trash-section" data-trash-section="messages"></div>`);
    const threadsBox = list.querySelector('[data-trash-section="threads"]');
    const msgsBox = list.querySelector('[data-trash-section="messages"]');
    _renderKeyedList(threadsBox, threadsData, th => th.thread_id,
      th => renderThreadItem(th, activeTid, 'trash'),
      `<div class="empty" style="padding:8px 16px 12px;font-size:12px">${esc(t('sidebar.emptyNoThreadsTrash'))}</div>`);
    _renderKeyedList(msgsBox, trashedMessagesData, tm => tm.message_id, tm => `
      <div class="agent-item thread-sidebar-item trash-msg-item ${tm.message_id === activeMid ? 'active' : ''}"
           data-message-id="${tm.message_id}"
           onclick="showTrashedMessageFromTrash(this.dataset.messageId)">
        <div class="agent-info">
          <div class="agent-name">${esc(tm.subject) || esc(noSubj)}</div>
          <div class="agent-role">${esc(tm.from_agent)} &middot; ${esc(tm.thread_id.substring(0, 8))}&hellip;</div>
        </div>
      </div>`,
      `<div class="empty" style="padding:8px 16px 12px;font-size:12px">${esc(t('sidebar.emptyNoMessagesTrash'))}</div>`);
    return;
  }

  if (inArchiveContext) {
    await fetchThreadsSummary({ archived: true });
    const activeTid = currentView?.type === 'thread' ? currentView.threadId : null;
    _renderKeyedList(list, threadsData, th => th.thread_id,
      th => renderThreadItem(th, activeTid, 'archive'),
      `<div class="empty" style="padding:20px 16px;font-size:12px">${esc(t('sidebar.emptyArchive'))}</div>`);
    return;
  }

  if (sidebarMode === 'threads') {
    updateFilterVisibility();
    await fetchThreadsSummary({});
    const activeTid = currentView?.type === 'thread' ? currentView.threadId : null;
    _renderKeyedList(list, threadsData, th => th.thread_id,
      th => renderThreadItem(th, activeTid, null),
      `<div class="empty" style="padding:20px 16px;font-size:12px">${esc(t('sidebar.emptyThreads'))}</div>`);
    return;
  }

  if (sidebarMode === 'teams') {
    updateFilterVisibility();
    // Run independent fetches in parallel; isolate failures so one slow/failing endpoint doesn't block the rest.
    const [statsRes, teamsRes, agentsRes] = await Promise.allSettled([
      fetchStats(), fetchTeams(), fetchAgents(),
    ]);
    if (statsRes.status === 'rejected') console.warn('[sidebar] fetchStats failed:', statsRes.reason);
    if (teamsRes.status === 'rejected') console.warn('[sidebar] fetchTeams failed:', teamsRes.reason);
    if (agentsRes.status === 'rejected') console.warn('[sidebar] fetchAgents failed:', agentsRes.reason);
    // Fetch team details for member lists in parallel.
    const teamDetailResults = await Promise.allSettled(
      teamsData.map(tm => fetchTeamDetail(tm.id))
    );
    const teamDetails = [];
    teamDetailResults.forEach((r, i) => {
      if (r.status === 'fulfilled') teamDetails.push(r.value);
      else console.warn(`[sidebar] fetchTeamDetail(${teamsData[i]?.id}) failed:`, r.reason);
    });
    const agentsList = agentsRes.status === 'fulfilled' ? agentsRes.value : [];
    const activeAddr = currentView?.type === 'inbox' ? currentView.address : null;

    // Build stats lookup for unread counts
    const statsMap = {};
    for (const s of statsData) statsMap[s.address] = s;

    // Build the desired group list: optional human operator pseudo-group + real teams + unassigned.
    const opAgent = statsData.find(a => a.address === HUMAN_OPERATOR_ADDRESS);
    const assignedIds = new Set();
    for (const tm of teamDetails) for (const a of tm.agents) assignedIds.add(a.id);
    const unassigned = agentsList.filter(a => !assignedIds.has(a.id) && a.address !== HUMAN_OPERATOR_ADDRESS && a.role !== 'operator');

    const groups = [];
    if (opAgent) {
      groups.push({ kind: 'op', key: '__op', agent: opAgent });
    }
    for (const team of teamDetails) {
      groups.push({ kind: 'team', key: team.id, name: team.name, agents: team.agents });
    }
    if (unassigned.length > 0) {
      groups.push({ kind: 'team', key: '__unassigned', name: t('sidebar.unassigned'), agents: unassigned });
    }

    if (groups.length === 0) {
      _ensureSidebarShape(list, 'teamsEmpty',
        `<div class="empty" style="padding:20px 16px;font-size:12px">${esc(t('sidebar.emptyAgents'))}</div>`);
      return;
    }
    if (list.dataset.shape !== 'teams') {
      list.dataset.shape = 'teams';
      list.innerHTML = '';
    }

    diffList(list, groups, g => g.key, g => {
      if (g.kind === 'op') {
        return _renderSidebarAgent(g.agent, activeAddr);
      }
      return `<div class="sidebar-team-group" data-team-id="${g.key}">
        <div class="sidebar-team-header" onclick="this.parentElement.classList.toggle('collapsed')">
          <span class="sidebar-team-arrow"></span>
          <span class="sidebar-team-header-name">${esc(g.name)}</span>
          <span class="sidebar-team-header-count">(${g.agents.length})</span>
        </div>
        <div class="sidebar-team-agents"></div>
      </div>`;
    });

    // After the outer diff, refresh each team group's inner agent list. The
    // header may need its count refreshed; do so without clobbering the
    // collapsed class the user toggled.
    for (const g of groups) {
      if (g.kind !== 'team') continue;
      const groupEl = list.querySelector(`.sidebar-team-group[data-team-id="${CSS.escape(g.key)}"]`);
      if (!groupEl) continue;
      const countEl = groupEl.querySelector('.sidebar-team-header-count');
      const wantCount = `(${g.agents.length})`;
      if (countEl && countEl.textContent !== wantCount) countEl.textContent = wantCount;
      const nameEl = groupEl.querySelector('.sidebar-team-header-name');
      if (nameEl && nameEl.textContent !== g.name) nameEl.textContent = g.name;
      const inner = groupEl.querySelector('.sidebar-team-agents');
      if (!inner) continue;
      _renderKeyedList(inner, g.agents, a => a.id || a.address, a => {
        const s = statsMap[a.address] || a;
        return _renderSidebarAgent({ ...s, ...a, agent_id: a.id, messages_unread: s.messages_unread || 0 }, activeAddr, true);
      }, `<div class="empty" style="padding:6px 16px 8px 32px;font-size:11px">${esc(t('sidebar.noAgentsInTeam'))}</div>`);
    }
    return;
  }

  // Default mode: flat agent list with team tags. Run independent fetches in parallel.
  const [statsRes, teamsRes, agentsRes] = await Promise.allSettled([
    fetchStats(),
    typeof fetchTeams === 'function' ? fetchTeams() : Promise.resolve(),
    fetchAgents(),
  ]);
  if (statsRes.status === 'rejected') console.warn('[sidebar] fetchStats failed:', statsRes.reason);
  if (teamsRes.status === 'rejected') console.warn('[sidebar] fetchTeams failed:', teamsRes.reason);
  if (agentsRes.status === 'rejected') console.warn('[sidebar] fetchAgents failed:', agentsRes.reason);
  const teamNameMap = {};
  for (const tm of (teamsData || [])) teamNameMap[tm.id] = tm.name;
  const agentTeamMap = {};
  const agentsList = agentsRes.status === 'fulfilled' ? (agentsRes.value || []) : [];
  for (const a of agentsList) if (a.team_id) agentTeamMap[a.address] = a.team_id;
  updateFilterVisibility();
  const activeAddr = currentView?.type === 'inbox' ? currentView.address : null;
  const filtered = filterTags.size > 0
    ? statsData.filter(a => a.address === HUMAN_OPERATOR_ADDRESS || (a.tags || []).some(tag => filterTags.has(tag)))
    : [...statsData];
  // Human Operator always first
  const filteredStats = filtered.sort((a, b) => {
    if (a.address === HUMAN_OPERATOR_ADDRESS) return -1;
    if (b.address === HUMAN_OPERATOR_ADDRESS) return 1;
    return 0;
  });
  const emptyHtml = filteredStats.length === 0 && filterTags.size > 0
    ? `<div class="empty" style="padding:20px 16px;font-size:12px">${esc(t('sidebar.emptyFilter'))}</div>`
    : `<div class="empty" style="padding:20px 16px;font-size:12px">${esc(t('sidebar.emptyAgents'))}</div>`;
  _renderKeyedList(list, filteredStats, a => a.agent_id || a.address, a => {
    const tagsHtml = (a.tags || []).length > 0
      ? `<div class="sidebar-tags">${a.tags.map(tag => `<span class="sidebar-tag">${esc(tag)}</span>`).join('')}</div>`
      : '';
    const teamId = agentTeamMap[a.address];
    const teamTag = teamId && teamNameMap[teamId]
      ? ` <span class="sidebar-team-tag">${esc(teamNameMap[teamId])}</span>`
      : '';
    return `
    <div class="agent-item ${a.address === activeAddr ? 'active' : ''}"
         onclick='showInbox(${JSON.stringify(a.address)}, ${JSON.stringify(a.agent_id)})'>
      <div class="agent-info">
        <div class="agent-name"><span class="status-dot status-${a.status || 'offline'}" title="${esc(_statusTitle(a.status))}"></span>${esc(a.name)}${teamTag}</div>
        <div class="agent-role">${esc(a.role)} &middot; ${esc(a.address)}</div>
        ${tagsHtml}
      </div>
      <div style="display:flex;align-items:center;gap:6px">
        <span class="badge ${a.messages_unread === 0 ? 'zero' : ''}">${a.messages_unread}</span>
        <button class="agent-delete-btn" onclick="event.stopPropagation(); deleteAgent('${esc(a.agent_id)}', '${esc(a.name)}')" title="${esc(t('sidebar.deleteAgent'))}">&times;</button>
      </div>
    </div>`;
  }, emptyHtml);
}

function clearNav() {
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.agent-item').forEach(b => b.classList.remove('active'));
  expandedMsg = null;
}
