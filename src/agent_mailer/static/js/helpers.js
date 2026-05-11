// --- Helpers ---
function esc(str) {
  if (!str) return '';
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

// FNV-1a 32-bit hash, returned as base36 string. Used to fingerprint rendered HTML
// so the list-diff can short-circuit when an item's content hasn't changed.
function _fnv1aHash(s) {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(36);
}

// Build a single element from an HTML string. Returns the first element child.
function _htmlToElement(html) {
  const tmpl = document.createElement('template');
  tmpl.innerHTML = String(html).trim();
  return tmpl.content.firstElementChild;
}

// Sync attributes from `fresh` onto `live`, preserving data-key/data-fp.
function _syncAttributes(live, fresh) {
  const keep = new Set(['data-key', 'data-fp']);
  for (const attr of Array.from(live.attributes)) {
    if (keep.has(attr.name)) continue;
    if (!fresh.hasAttribute(attr.name)) live.removeAttribute(attr.name);
  }
  for (const attr of Array.from(fresh.attributes)) {
    if (live.getAttribute(attr.name) !== attr.value) live.setAttribute(attr.name, attr.value);
  }
}

/**
 * Reconcile children of `container` to match `items`, keyed by `getKey(item)`.
 * `render(item)` produces an HTML string for one item (must yield exactly one
 * element child). Items whose rendered HTML is unchanged from the previous
 * cycle cause zero DOM mutations; otherwise only the changed item's contents
 * (and any moved nodes) are rewritten — never the whole list.
 *
 * Container children that lack a `data-key` are left in place (so e.g. an
 * `.empty` placeholder sibling won't be clobbered).
 */
function diffList(container, items, getKey, render) {
  const existing = new Map();
  for (const el of Array.from(container.children)) {
    if (el.dataset && el.dataset.key) existing.set(el.dataset.key, el);
  }
  const used = new Set();
  let prev = null;
  for (const item of items) {
    const key = String(getKey(item));
    used.add(key);
    const html = render(item);
    const fp = _fnv1aHash(html);
    let el = existing.get(key);
    if (!el) {
      el = _htmlToElement(html);
      el.dataset.key = key;
      el.dataset.fp = fp;
    } else if (el.dataset.fp !== fp) {
      const fresh = _htmlToElement(html);
      _syncAttributes(el, fresh);
      el.innerHTML = fresh.innerHTML;
      el.dataset.fp = fp;
    }
    // Find the element that *should* sit at this position; only insertBefore
    // when the actual node differs (insertBefore on the same node still moves
    // it, so we must check first).
    const expectedAt = prev ? prev.nextElementSibling : container.firstElementChild;
    if (el !== expectedAt) container.insertBefore(el, expectedAt);
    prev = el;
  }
  for (const [key, el] of existing.entries()) {
    if (!used.has(key)) el.remove();
  }
}

function mdDataAttr(html) {
  if (html == null || html === '') return '';
  return encodeURIComponent(html);
}

function hydrateMarkdownBodies(root) {
  if (!root) return;
  root.querySelectorAll('[data-md-html]').forEach(el => {
    const enc = el.getAttribute('data-md-html');
    el.removeAttribute('data-md-html');
    if (enc == null || enc === '') return;
    try {
      el.innerHTML = decodeURIComponent(enc);
    } catch (err) {
      el.textContent = t('render.mdFailed');
      return;
    }
    el.querySelectorAll('a[href]').forEach(a => {
      a.setAttribute('target', '_blank');
      a.setAttribute('rel', 'noopener noreferrer');
      a.addEventListener('click', e => e.stopPropagation());
    });
  });
}

function fmtTime(iso) {
  const d = new Date(iso);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
         d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// --- Toast ---
function showToast(message, type = 'info') {
  let container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const el = document.createElement('div');
  el.className = 'toast toast-' + type;
  el.textContent = message;
  container.appendChild(el);
  requestAnimationFrame(() => el.classList.add('toast-visible'));
  setTimeout(() => {
    el.classList.remove('toast-visible');
    setTimeout(() => el.remove(), 250);
  }, 2400);
}

// --- Copy message as Markdown ---
function fmtDateLocal(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
         `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

// Minimal HTML -> plain-text fallback when body is empty but body_html exists.
// Intentionally simple: strips tags and decodes entities. Not a full HTML->MD converter.
function htmlToPlainText(html) {
  if (!html) return '';
  const tmp = document.createElement('div');
  tmp.innerHTML = html;
  tmp.querySelectorAll('script,style').forEach(n => n.remove());
  tmp.querySelectorAll('br').forEach(n => n.replaceWith('\n'));
  tmp.querySelectorAll('p,div,li,tr,h1,h2,h3,h4,h5,h6').forEach(n => {
    n.append('\n');
  });
  return (tmp.textContent || '').replace(/\n{3,}/g, '\n\n').trim();
}

function formatAttachmentsMd(attachments) {
  if (!Array.isArray(attachments) || attachments.length === 0) return '';
  const lines = attachments.map(a => {
    if (typeof a === 'string') return `- ${a}`;
    if (a && typeof a === 'object') {
      const name = a.filename || a.name || a.id || 'attachment';
      const url = a.url || '';
      return url ? `- [${name}](${url})` : `- ${name}`;
    }
    return `- ${String(a)}`;
  });
  return '\n\n## 附件\n' + lines.join('\n');
}

function buildMessageMarkdown(m) {
  const subject = (m.subject && String(m.subject).trim()) || t('common.noSubject');
  let body = m.body && String(m.body).trim();
  if (!body && m.body_html) body = htmlToPlainText(m.body_html);
  if (!body) body = '';
  const meta = [
    `- **From:** ${m.from_agent || ''}`,
    `- **To:** ${m.to_agent || ''}`,
    `- **Date:** ${fmtDateLocal(m.created_at)}`,
    `- **Action:** ${m.action || ''}`,
  ].join('\n');
  const attachments = formatAttachmentsMd(m.attachments);
  return `# ${subject}\n\n${meta}\n\n---\n\n${body}${attachments}\n`;
}

async function writeClipboardText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) { /* fall through to legacy */ }
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.top = '-1000px';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, text.length);
    const ok = document.execCommand && document.execCommand('copy');
    document.body.removeChild(ta);
    if (ok) return true;
  } catch (e) { /* fall through */ }
  return false;
}

async function copyMessageAsMarkdown(msgId, ev) {
  if (ev && ev.stopPropagation) ev.stopPropagation();
  const m = (typeof msgCache !== 'undefined') ? msgCache[msgId] : null;
  if (!m) {
    showToast(t('toast.msgNotFound'), 'error');
    return;
  }
  const md = buildMessageMarkdown(m);
  const ok = await writeClipboardText(md);
  if (ok) {
    showToast(t('toast.copied'), 'success');
    return;
  }
  // Last-resort manual fallback: show a prompt so the user can Ctrl+C the text.
  try { window.prompt(t('toast.copyFailed'), md); }
  catch (e) { /* ignore */ }
  showToast(t('toast.autoCopyFailed'), 'error');
}

// --- Save message to team knowledge base ---
function resolveTeamForMessage(m) {
  // Prefer the inbox owner's team (derived from currentView), fall back to
  // the message's to/from agents if we're in a thread view without inbox context.
  if (typeof agents === 'undefined' || !Array.isArray(agents)) return null;
  const byAddress = addr => agents.find(a => a && a.address === addr);
  const byId = id => agents.find(a => a && a.id === id);

  const candidates = [];
  if (typeof currentView !== 'undefined' && currentView) {
    if (currentView.agentId) candidates.push(byId(currentView.agentId));
    if (currentView.address) candidates.push(byAddress(currentView.address));
  }
  if (m) {
    candidates.push(byAddress(m.to_agent));
    candidates.push(byAddress(m.from_agent));
  }
  for (const a of candidates) {
    if (a && a.team_id) return a.team_id;
  }
  return null;
}

async function saveMessageToTeam(msgId, ev) {
  if (ev && ev.stopPropagation) ev.stopPropagation();
  const m = (typeof msgCache !== 'undefined') ? msgCache[msgId] : null;
  if (!m) {
    showToast(t('toast.msgNotFound'), 'error');
    return;
  }
  const teamId = resolveTeamForMessage(m);
  if (!teamId) {
    showToast(t('toast.noTeam'), 'error');
    return;
  }
  const title = (m.subject && String(m.subject).trim()) || t('common.noSubject');
  const content = buildMessageMarkdown(m);
  try {
    const res = await upsertTeamMemory(teamId, { title, content });
    showToast(t('toast.savedToTeam'), 'success');
    return res;
  } catch (e) {
    const msg = (e && e.message) ? e.message : t('toast.saveFailed');
    showToast(t('toast.saveFailedPrefix') + msg, 'error');
  }
}

// --- Confirm modal ---
function showConfirm(title, body, confirmLabel) {
  return new Promise(resolve => {
    const overlay = document.getElementById('confirmModal');
    document.getElementById('confirmTitle').textContent = title;
    document.getElementById('confirmBody').textContent = body;
    const okBtn = document.getElementById('confirmOk');
    okBtn.textContent = confirmLabel || t('common.confirm');
    // Ensure cancel label reflects current language too.
    const cancelBtn = document.getElementById('confirmCancel');
    if (cancelBtn) cancelBtn.textContent = t('common.cancel');
    overlay.classList.add('visible');

    function cleanup(result) {
      overlay.classList.remove('visible');
      okBtn.removeEventListener('click', onOk);
      document.getElementById('confirmCancel').removeEventListener('click', onCancel);
      overlay.removeEventListener('click', onBackdrop);
      resolve(result);
    }
    function onOk() { cleanup(true); }
    function onCancel() { cleanup(false); }
    function onBackdrop(e) { if (e.target === overlay) cleanup(false); }

    okBtn.addEventListener('click', onOk);
    document.getElementById('confirmCancel').addEventListener('click', onCancel);
    overlay.addEventListener('click', onBackdrop);
  });
}
