// --- Polling ---
function startPolling() {
  stopPolling();
  if (pollInterval === 0 || tagEditingActive) return;
  pollTimer = setInterval(async () => {
    await refreshSidebar();
    if (currentView?.type === 'inbox') await renderInbox();
    if (currentView?.type === 'stats') await renderStats();
    if (currentView?.type === 'thread') await renderThreadView();
    if (currentView?.type === 'trashedMessage') await renderTrashedMessageView();
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
    '<div class="empty">Select an agent or thread, or open Inbox/Compose / Stats.</div>';
  await refreshSidebar();
});

document.getElementById('pollSelect').addEventListener('change', (e) => {
  pollInterval = parseInt(e.target.value);
  const indicator = document.getElementById('pollIndicator');
  if (pollInterval === 0) {
    indicator.classList.add('paused');
    indicator.title = 'Auto-refresh paused';
    stopPolling();
  } else {
    indicator.classList.remove('paused');
    indicator.title = 'Auto-refresh active';
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
