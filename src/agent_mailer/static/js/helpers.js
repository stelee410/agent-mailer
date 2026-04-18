// --- Helpers ---
function esc(str) {
  if (!str) return '';
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
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
      el.textContent = '(Failed to render message body)';
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
  const subject = (m.subject && String(m.subject).trim()) || '(no subject)';
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
    showToast('未找到邮件内容', 'error');
    return;
  }
  const md = buildMessageMarkdown(m);
  const ok = await writeClipboardText(md);
  if (ok) {
    showToast('已复制到剪贴板', 'success');
    return;
  }
  // Last-resort manual fallback: show a prompt so the user can Ctrl+C the text.
  try { window.prompt('复制失败，请手动复制：', md); }
  catch (e) { /* ignore */ }
  showToast('自动复制失败，已打开手动复制窗口', 'error');
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
    showToast('未找到邮件内容', 'error');
    return;
  }
  const teamId = resolveTeamForMessage(m);
  if (!teamId) {
    showToast('当前邮箱未加入任何 Team，无法保存到知识库', 'error');
    return;
  }
  const title = (m.subject && String(m.subject).trim()) || '(no subject)';
  const content = buildMessageMarkdown(m);
  try {
    const res = await upsertTeamMemory(teamId, { title, content });
    showToast('已保存到 Team 知识库', 'success');
    return res;
  } catch (e) {
    const msg = (e && e.message) ? e.message : '保存失败';
    showToast('保存失败：' + msg, 'error');
  }
}

// --- Confirm modal ---
function showConfirm(title, body, confirmLabel) {
  return new Promise(resolve => {
    const overlay = document.getElementById('confirmModal');
    document.getElementById('confirmTitle').textContent = title;
    document.getElementById('confirmBody').textContent = body;
    const okBtn = document.getElementById('confirmOk');
    okBtn.textContent = confirmLabel || '确认';
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
