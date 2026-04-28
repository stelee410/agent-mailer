// --- Auth helpers ---
function clearSessionCookie() {
  document.cookie = 'session_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
}

function showLoginPage() {
  stopPolling();
  document.getElementById('loginPage').classList.add('visible');
}

function hideLoginPage() {
  document.getElementById('loginPage').classList.remove('visible');
}

function showLoginForm() {
  document.getElementById('loginFormWrap').style.display = '';
  document.getElementById('registerFormWrap').style.display = 'none';
  document.getElementById('loginError').style.display = 'none';
  document.getElementById('loginSubtitle').textContent = t('login.subtitleSignIn');
}

async function showRegisterForm() {
  document.getElementById('loginFormWrap').style.display = 'none';
  document.getElementById('registerFormWrap').style.display = '';
  document.getElementById('registerError').style.display = 'none';
  document.getElementById('loginSubtitle').textContent = t('login.subtitleRegister');
  await refreshRegistrationConfig();
}

let _registrationInviteRequired = true;

async function refreshRegistrationConfig() {
  try {
    const resp = await fetch(BASE + '/users/registration-config', { credentials: 'same-origin' });
    if (!resp.ok) return;
    const cfg = await resp.json();
    _registrationInviteRequired = !!cfg.invite_required;
  } catch (e) { /* keep last known value */ }
  applyInviteCodeVisibility();
}

function applyInviteCodeVisibility() {
  const wrap = document.getElementById('regInviteCodeWrap');
  if (!wrap) return;
  wrap.style.display = _registrationInviteRequired ? '' : 'none';
}

async function doLogin() {
  const btn = document.getElementById('loginBtn');
  const errEl = document.getElementById('loginError');
  const username = document.getElementById('loginUsername').value.trim();
  const password = document.getElementById('loginPassword').value;
  errEl.style.display = 'none';
  if (!username || !password) {
    errEl.textContent = t('login.errorMissingCredentials');
    errEl.style.display = '';
    return;
  }
  btn.disabled = true;
  btn.textContent = t('login.signingIn');
  try {
    const resp = await fetch(BASE + '/users/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ username, password }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || t('login.errorLoginFailed'));
    }
    window.location.reload();
  } catch (e) {
    errEl.textContent = e.message;
    errEl.style.display = '';
    btn.disabled = false;
    btn.textContent = t('login.signIn');
  }
}

async function doRegister() {
  const btn = document.getElementById('registerBtn');
  const errEl = document.getElementById('registerError');
  const username = document.getElementById('regUsername').value.trim();
  const password = document.getElementById('regPassword').value;
  const invite_code = document.getElementById('regInviteCode').value.trim();
  errEl.style.display = 'none';
  const needsInvite = _registrationInviteRequired;
  if (!username || !password || (needsInvite && !invite_code)) {
    errEl.textContent = t('login.errorMissingFields');
    errEl.style.display = '';
    return;
  }
  btn.disabled = true;
  btn.textContent = t('login.creatingAccount');
  try {
    const payload = needsInvite
      ? { username, password, invite_code }
      : { username, password };
    const resp = await fetch(BASE + '/users/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || t('login.errorRegisterFailed'));
    }
    // After registration, attempt login
    const loginResp = await fetch(BASE + '/users/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ username, password }),
    });
    if (!loginResp.ok) {
      errEl.textContent = t('login.accountCreated');
      errEl.style.display = '';
      showLoginForm();
      return;
    }
    window.location.reload();
  } catch (e) {
    errEl.textContent = e.message;
    errEl.style.display = '';
    btn.disabled = false;
    btn.textContent = t('login.createAccount');
  }
}

async function doLogout() {
  await fetch(BASE + '/users/logout', { method: 'POST', credentials: 'same-origin' }).catch(() => {});
  showLoginPage();
}

function exitImpersonation() {
  clearSessionCookie();
  window.location.reload();
}

async function checkAuth() {
  try {
    const resp = await fetch(BASE + '/users/me', { credentials: 'same-origin' });
    if (resp.status === 401) {
      showLoginPage();
      return false;
    }
    if (!resp.ok) {
      showLoginPage();
      return false;
    }
    currentUser = await resp.json();
    // Show impersonation banner if applicable
    if (currentUser.impersonated_by) {
      const banner = document.getElementById('impersonateBanner');
      document.getElementById('impersonateLabel').textContent =
        t('header.impersonating', { name: currentUser.username });
      banner.style.display = '';
    }
    // Show username in header
    document.getElementById('headerUsername').textContent = currentUser.username;
    // Show admin nav if superadmin
    if (currentUser.is_superadmin) {
      document.getElementById('navAdmin').style.display = '';
    }
    // Fetch human operator info
    try {
      const opResp = await fetch(BASE + '/admin/human-operator', { credentials: 'same-origin' });
      if (opResp.ok) {
        const opData = await opResp.json();
        currentUser._humanOperator = opData;
        HUMAN_OPERATOR_ADDRESS = opData.address;
        HUMAN_OPERATOR_AGENT_ID = opData.agent_id;
      }
    } catch (e) { /* ignore */ }
    // Restore saved filter tags
    if (currentUser.filter_tags && currentUser.filter_tags.length > 0) {
      filterTags = new Set(currentUser.filter_tags);
      updateFilterBtn();
    }
    return true;
  } catch (e) {
    showLoginPage();
    return false;
  }
}
