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
    ? `<div class="empty" style="padding:32px 0;text-align:center">
        <p>No teams yet.</p>
        <p class="team-empty-hint">Create a team to organize your agents into groups with isolated contact visibility.</p>
        <button class="btn btn-primary" onclick="showCreateTeamForm()">+ Create Your First Team</button>
      </div>`
    : `<div class="teams-grid">${teamsData.map(t => `
        <div class="team-card" onclick="showTeamDetail('${esc(t.id)}')">
          <div class="team-card-icon">${t.agent_count > 0
            ? `<span class="team-card-avatar-count">${t.agent_count}</span>`
            : '<span class="team-card-avatar-empty">0</span>'}</div>
          <div class="team-card-name">${esc(t.name)}</div>
          <div class="team-card-desc">${esc(t.description) || '<span class="text-muted">No description</span>'}</div>
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
        ${teamsData.length > 0 ? '<button class="btn btn-primary" onclick="showCreateTeamForm()">+ Create Team</button>' : ''}
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
      <div class="compose-form">
        <div>
          <label for="teamName">Team Name</label>
          <input type="text" id="teamName" placeholder="e.g. Frontend, Backend, DevOps...">
        </div>
        <div>
          <label for="teamDesc">Description</label>
          <input type="text" id="teamDesc" placeholder="Brief description of this team's purpose (optional)">
        </div>
        <div id="teamFormError" class="login-error" style="display:none"></div>
        <div>
          <button class="btn btn-primary" id="createTeamBtn" onclick="doCreateTeam()">Create Team</button>
        </div>
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
    main.innerHTML = `<div class="card">
      <button type="button" class="back-btn" onclick="showTeams()">&larr; Back to Teams</button>
      <p class="empty">Team not found.</p></div>`;
    return;
  }

  // Fetch all agents to find unassigned ones
  const allAgents = await api('/admin/agents');
  const unassigned = allAgents.filter(a => !a.team_id && a.role !== 'operator');

  // Members table
  const membersHtml = team.agents.length === 0
    ? '<div class="empty" style="padding:16px 0">暂无成员，请在下方添加 Agent</div>'
    : `<div class="stats-table-wrap">
        <table class="stats-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Role</th>
              <th>Address</th>
              <th>Status</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            ${team.agents.map(a => `
              <tr>
                <td><strong>${esc(a.name)}</strong></td>
                <td>${esc(a.role)}</td>
                <td class="text-muted">${esc(a.address)}</td>
                <td><span class="status-dot status-${a.status || 'offline'}" title="${a.status === 'online' ? '在线' : a.status === 'idle' ? '空闲' : '离线'}"></span> ${a.status || 'offline'}</td>
                <td><button class="btn-danger-sm" onclick="removeAgentFromTeam('${esc(team.id)}', '${esc(a.id)}', '${esc(a.name)}')">Remove</button></td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>`;

  // Add agent section
  let addAgentHtml;
  if (unassigned.length === 0) {
    addAgentHtml = '<div class="empty" style="padding:12px 0;font-size:12px">All agents are already assigned to teams. Create new agents or remove existing ones from other teams first.</div>';
  } else {
    addAgentHtml = `
      <p class="team-section-hint">Select an unassigned agent to add to this team. Each agent can only belong to one team.</p>
      <div class="compose-form">
        <div>
          <label for="addAgentSelect">Agent</label>
          <select id="addAgentSelect">
            <option value="">-- Select an agent to add --</option>
            ${unassigned.map(a => `<option value="${esc(a.id)}">${esc(a.name)} (${esc(a.role)}) — ${esc(a.address)}</option>`).join('')}
          </select>
        </div>
        <div>
          <button class="btn btn-primary" onclick="addAgentToTeam('${esc(team.id)}')">Add to Team</button>
        </div>
      </div>`;
  }

  main.innerHTML = `
    <div class="card">
      <button type="button" class="back-btn" onclick="showTeams()">&larr; Back to Teams</button>
      <div class="card-header-row">
        <div>
          <h2>${esc(team.name)}</h2>
          <p class="team-detail-desc">${esc(team.description) || '<span class="text-muted">No description</span>'}</p>
        </div>
        <div class="team-detail-actions">
          <button class="btn btn-secondary" onclick="showEditTeamForm('${esc(team.id)}')">Edit</button>
          <button class="btn btn-danger" onclick="deleteTeam('${esc(team.id)}', '${esc(team.name)}')">Delete</button>
        </div>
      </div>
      <h3 class="team-section-header">团队成员 (${team.agents.length})</h3>
      ${membersHtml}
      <h3 class="team-section-header">添加成员</h3>
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
      <div class="compose-form">
        <div>
          <label for="editTeamName">Team Name</label>
          <input type="text" id="editTeamName" value="${esc(team.name)}">
        </div>
        <div>
          <label for="editTeamDesc">Description</label>
          <input type="text" id="editTeamDesc" value="${esc(team.description)}" placeholder="Brief description of this team's purpose (optional)">
        </div>
        <div id="editTeamError" class="login-error" style="display:none"></div>
        <div>
          <button class="btn btn-primary" onclick="doUpdateTeam('${esc(teamId)}')">Save Changes</button>
        </div>
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
