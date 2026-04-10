// --- Teams management ---

let teamsData = [];

async function fetchTeams() {
  teamsData = await api('/admin/teams');
  return teamsData;
}

async function fetchTeamDetail(teamId) {
  return api(`/admin/teams/${encodeURIComponent(teamId)}`);
}

async function showTeams() {
  clearNav();
  setSidebarSpecialMode('none');
  document.getElementById('navTeams').classList.add('active');
  currentView = { type: 'teams' };
  await renderTeams();
}

async function renderTeams() {
  if (currentView?.type !== 'teams' && currentView?.type !== 'teamDetail') return;
  const main = document.getElementById('main');

  if (currentView?.type === 'teamDetail') {
    await renderTeamDetail(currentView.teamId);
    return;
  }

  await fetchTeams();

  const teamsHtml = teamsData.length === 0
    ? '<div class="empty" style="padding:20px 0">No teams yet. Create one to get started.</div>'
    : `<div class="teams-grid">${teamsData.map(t => `
        <div class="team-card" onclick="showTeamDetail('${esc(t.id)}')">
          <div class="team-card-name">${esc(t.name)}</div>
          <div class="team-card-desc">${esc(t.description) || '<span style="color:var(--muted)">No description</span>'}</div>
          <div class="team-card-footer">
            <span class="team-agent-count">${t.agent_count} agent${t.agent_count !== 1 ? 's' : ''}</span>
            <span class="team-card-time">${esc(fmtTime(t.created_at))}</span>
          </div>
        </div>
      `).join('')}</div>`;

  main.innerHTML = `
    <div class="card">
      <div class="card-header-row">
        <h2>Teams</h2>
        <button class="btn btn-primary" onclick="showCreateTeamForm()">+ Create Team</button>
      </div>
      ${teamsHtml}
    </div>`;
}

function showCreateTeamForm() {
  const main = document.getElementById('main');
  main.innerHTML = `
    <div class="card">
      <button type="button" class="back-btn" onclick="showTeams()">&larr; Back to Teams</button>
      <h2>Create Team</h2>
      <div class="team-form">
        <div class="form-group">
          <label for="teamName">Name</label>
          <input type="text" id="teamName" placeholder="Enter team name" class="form-input">
        </div>
        <div class="form-group">
          <label for="teamDesc">Description (optional)</label>
          <input type="text" id="teamDesc" placeholder="Brief description" class="form-input">
        </div>
        <div id="teamFormError" class="login-error" style="display:none"></div>
        <button class="btn btn-primary" id="createTeamBtn" onclick="doCreateTeam()">Create</button>
      </div>
    </div>`;
}

async function doCreateTeam() {
  const name = document.getElementById('teamName').value.trim();
  const description = document.getElementById('teamDesc').value.trim();
  const errEl = document.getElementById('teamFormError');
  if (!name) {
    errEl.textContent = 'Team name is required';
    errEl.style.display = 'block';
    return;
  }
  try {
    await api('/admin/teams', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description }),
    });
    await showTeams();
  } catch (e) {
    errEl.textContent = e.message;
    errEl.style.display = 'block';
  }
}

async function showTeamDetail(teamId) {
  clearNav();
  document.getElementById('navTeams').classList.add('active');
  currentView = { type: 'teamDetail', teamId };
  await renderTeamDetail(teamId);
}

async function renderTeamDetail(teamId) {
  const main = document.getElementById('main');
  let team;
  try {
    team = await fetchTeamDetail(teamId);
  } catch (e) {
    main.innerHTML = `<div class="card"><p class="empty">Team not found.</p>
      <button type="button" class="back-btn" onclick="showTeams()">&larr; Back to Teams</button></div>`;
    return;
  }

  // Fetch all agents to find unassigned ones
  const allAgents = await api('/admin/agents');
  const unassigned = allAgents.filter(a => !a.team_id && a.role !== 'operator');

  const membersHtml = team.agents.length === 0
    ? '<div class="empty" style="padding:12px 0">No agents in this team yet.</div>'
    : `<div class="team-members-list">${team.agents.map(a => `
        <div class="team-member-item">
          <div class="agent-info">
            <div class="agent-name"><span class="status-dot status-${a.status || 'offline'}"></span>${esc(a.name)}</div>
            <div class="agent-role">${esc(a.role)} &middot; ${esc(a.address)}</div>
          </div>
          <button class="btn-sm btn-danger" onclick="removeAgentFromTeam('${esc(team.id)}', '${esc(a.id)}', '${esc(a.name)}')">&times; Remove</button>
        </div>
      `).join('')}</div>`;

  const addAgentHtml = unassigned.length === 0
    ? '<div class="empty" style="padding:8px 0;font-size:12px">All agents are assigned to teams.</div>'
    : `<div class="team-add-agent-row">
        <select id="addAgentSelect" class="form-input" style="flex:1">
          <option value="">-- Select agent --</option>
          ${unassigned.map(a => `<option value="${esc(a.id)}">${esc(a.name)} (${esc(a.role)})</option>`).join('')}
        </select>
        <button class="btn btn-primary btn-sm" onclick="addAgentToTeam('${esc(team.id)}')">Add</button>
      </div>`;

  main.innerHTML = `
    <div class="card">
      <button type="button" class="back-btn" onclick="showTeams()">&larr; Back to Teams</button>
      <div class="card-header-row">
        <div>
          <h2 id="teamDetailName">${esc(team.name)}</h2>
          <p class="team-detail-desc" id="teamDetailDesc">${esc(team.description) || '<span style="color:var(--muted)">No description</span>'}</p>
        </div>
        <div class="team-detail-actions">
          <button class="btn btn-secondary btn-sm" onclick="showEditTeamForm('${esc(team.id)}')">Edit</button>
          <button class="btn btn-sm" style="background:var(--danger);color:#fff" onclick="deleteTeam('${esc(team.id)}', '${esc(team.name)}')">Delete</button>
        </div>
      </div>
      <h3 style="margin-top:20px;margin-bottom:8px">Members (${team.agents.length})</h3>
      ${membersHtml}
      <h3 style="margin-top:20px;margin-bottom:8px">Add Agent</h3>
      ${addAgentHtml}
    </div>`;
}

async function showEditTeamForm(teamId) {
  let team;
  try {
    team = await fetchTeamDetail(teamId);
  } catch { return; }

  const main = document.getElementById('main');
  main.innerHTML = `
    <div class="card">
      <button type="button" class="back-btn" onclick="showTeamDetail('${esc(teamId)}')">&larr; Back</button>
      <h2>Edit Team</h2>
      <div class="team-form">
        <div class="form-group">
          <label for="editTeamName">Name</label>
          <input type="text" id="editTeamName" value="${esc(team.name)}" class="form-input">
        </div>
        <div class="form-group">
          <label for="editTeamDesc">Description</label>
          <input type="text" id="editTeamDesc" value="${esc(team.description)}" class="form-input">
        </div>
        <div id="editTeamError" class="login-error" style="display:none"></div>
        <button class="btn btn-primary" onclick="doUpdateTeam('${esc(teamId)}')">Save</button>
      </div>
    </div>`;
}

async function doUpdateTeam(teamId) {
  const name = document.getElementById('editTeamName').value.trim();
  const description = document.getElementById('editTeamDesc').value.trim();
  const errEl = document.getElementById('editTeamError');
  if (!name) {
    errEl.textContent = 'Team name is required';
    errEl.style.display = 'block';
    return;
  }
  try {
    await api(`/admin/teams/${encodeURIComponent(teamId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description }),
    });
    await showTeamDetail(teamId);
  } catch (e) {
    errEl.textContent = e.message;
    errEl.style.display = 'block';
  }
}

async function deleteTeam(teamId, teamName) {
  if (!await showConfirm('Delete Team', `Delete team "${teamName}"? Agents will be unassigned.`, 'Delete')) return;
  try {
    await api(`/admin/teams/${encodeURIComponent(teamId)}`, { method: 'DELETE' });
    await showTeams();
  } catch (e) {
    alert(e.message);
  }
}

async function addAgentToTeam(teamId) {
  const select = document.getElementById('addAgentSelect');
  const agentId = select.value;
  if (!agentId) return;
  try {
    await api(`/admin/teams/${encodeURIComponent(teamId)}/agents`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_id: agentId }),
    });
    await renderTeamDetail(teamId);
  } catch (e) {
    alert(e.message);
  }
}

async function removeAgentFromTeam(teamId, agentId, agentName) {
  if (!await showConfirm('Remove Agent', `Remove "${agentName}" from this team?`, 'Remove')) return;
  try {
    await api(`/admin/teams/${encodeURIComponent(teamId)}/agents/${encodeURIComponent(agentId)}`, {
      method: 'DELETE',
    });
    await renderTeamDetail(teamId);
  } catch (e) {
    alert(e.message);
  }
}
