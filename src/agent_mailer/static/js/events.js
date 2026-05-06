// --- Polling ---
function startPolling() {
  stopPolling();
  if (pollInterval === 0 || tagEditingActive) return;
  pollTimer = setInterval(async () => {
    const tasks = [['sidebar', refreshSidebar()]];
    const t = currentView?.type;
    if (t === 'inbox') tasks.push(['inbox', renderInbox()]);
    else if (t === 'stats') tasks.push(['stats', renderStats()]);
    else if (t === 'thread') tasks.push(['thread', renderThreadView()]);
    else if (t === 'trashedMessage') tasks.push(['trashedMessage', renderTrashedMessageView()]);
    const results = await Promise.allSettled(tasks.map(([, p]) => p));
    results.forEach((r, i) => {
      if (r.status === 'rejected') console.warn(`[poll] ${tasks[i][0]} refresh failed:`, r.reason);
    });
  }, pollInterval);
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

function toggleNavPanel() {
  document.getElementById('navButtons').classList.toggle('collapsed');
}

// --- Event listeners ---
document.getElementById('sidebarModeSelect').addEventListener('change', async (e) => {
  sidebarMode = e.target.value;
  filterTags.clear();
  updateFilterBtn();
  clearNav();
  setSidebarSpecialMode('none');
  currentView = null;
  document.getElementById('main').innerHTML =
    `<div class="empty">${esc(t('empty.selectAgentShort'))}</div>`;
  await refreshSidebar();
});

document.getElementById('pollSelect').addEventListener('change', (e) => {
  pollInterval = parseInt(e.target.value);
  const indicator = document.getElementById('pollIndicator');
  if (pollInterval === 0) {
    indicator.classList.add('paused');
    indicator.title = t('header.pollPaused');
    stopPolling();
  } else {
    indicator.classList.remove('paused');
    indicator.title = t('header.pollActive');
    startPolling();
  }
});

// Enter key support for login form
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter') return;
  const loginPage = document.getElementById('loginPage');
  if (!loginPage.classList.contains('visible')) return;
  const loginWrap = document.getElementById('loginFormWrap');
  const regWrap = document.getElementById('registerFormWrap');
  if (loginWrap.style.display !== 'none') doLogin();
  else if (regWrap.style.display !== 'none') doRegister();
});

// --- Mobile sidebar drawer ---
const _sidebar = document.getElementById('sidebar');
const _backdrop = document.getElementById('sidebarBackdrop');
const _hamburger = document.getElementById('hamburgerBtn');

function isMobile() { return window.matchMedia('(max-width: 768px)').matches; }

function openSidebar() {
  _sidebar.classList.add('open');
  _backdrop.classList.add('visible');
}

function closeSidebar() {
  _sidebar.classList.remove('open');
  _backdrop.classList.remove('visible');
}

_hamburger.addEventListener('click', () => {
  _sidebar.classList.contains('open') ? closeSidebar() : openSidebar();
});

_backdrop.addEventListener('click', closeSidebar);

_sidebar.addEventListener('click', (e) => {
  if (isMobile() && e.target.closest('.agent-item')) {
    closeSidebar();
  }
});

document.getElementById('navButtons').addEventListener('click', () => {
  if (isMobile()) closeSidebar();
});

// --- Init ---
(async () => {
  const authed = await checkAuth();
  if (!authed) return;
  await refreshSidebar();
  startPolling();
})();
