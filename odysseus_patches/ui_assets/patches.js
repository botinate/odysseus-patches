/**
 * odysseus-patches panel — injected into Odysseus by the install-ui middleware.
 * Self-renders a Tools-section button + a modal reusing Odysseus's existing
 * modal classes and CSS variables (themes apply automatically). Admin-only:
 * if /api/patches/status is forbidden, nothing is shown.
 */
(function () {
  const $ = (id) => document.getElementById(id);
  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
  }
  async function api(path, opts) {
    const res = await fetch(path, opts);
    if (!res.ok) throw new Error(res.status);
    return res.json();
  }

  async function notify(msg, isError) {
    try {
      const ui = await import('/static/js/ui.js');
      if (isError && ui.showError) return ui.showError(String(msg));
      if (ui.showToast) return ui.showToast(String(msg));
    } catch (e) { /* fall through */ }
    if (isError) console.error(msg); else console.log(msg);
  }

  function ensureModal() {
    if ($('odypatch-modal')) return;
    const m = document.createElement('div');
    m.id = 'odypatch-modal';
    m.className = 'modal hidden';
    m.innerHTML = `
      <div class="modal-content" role="dialog" aria-label="Patches" style="background:var(--bg)">
        <div class="modal-header"><h4>Patches</h4>
          <button class="close-btn" id="odypatch-close" aria-label="Close">✖</button></div>
        <div class="modal-body">
          <div class="admin-card" style="border-left:3px solid var(--red)">Patches run with full access to your personal AI system. Apply only PRs you trust or have reviewed.</div>
          <div class="admin-card" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px">
            <input id="odypatch-pr" type="number" min="1" placeholder="PR #" style="width:90px"/>
            <label style="display:inline-flex;align-items:center;gap:4px"><input id="odypatch-review" type="checkbox"/> review</label>
            <button id="odypatch-add">Add PR</button>
            <span style="flex:1"></span>
            <button id="odypatch-settings-btn">Settings</button>
          </div>
          <div id="odypatch-settings" class="admin-card hidden" style="margin-bottom:8px">
            <div style="opacity:.7;margin-bottom:4px">Odysseus API token (for AI review)</div>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
              <input id="odypatch-token" type="password" placeholder="paste token" style="flex:1;min-width:160px"/>
              <button id="odypatch-token-save">Save</button>
              <span id="odypatch-token-state" style="opacity:.6"></span>
            </div>
          </div>
          <div id="odypatch-content"></div>
        </div>
      </div>`;
    document.body.appendChild(m);
    $('odypatch-close').addEventListener('click', () => m.classList.add('hidden'));
    $('odypatch-content').addEventListener('click', (e) => {
      const b = e.target.closest('button[data-act]');
      if (b) onAction(b.dataset.act, b.dataset.pr);
    });
    $('odypatch-add').addEventListener('click', async () => {
      const pr = Number($('odypatch-pr').value);
      if (!pr) { notify('Enter a PR number', true); return; }
      const review = $('odypatch-review').checked;
      try {
        const r = await api('/api/patches/add', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pr, review }) });
        notify(r.ok ? `Added PR #${pr} — restart Odysseus to apply` : (r.message || 'Add failed'), !r.ok);
      } catch (e) { notify('Add failed', true); }
      $('odypatch-pr').value = '';
      render();
    });
    $('odypatch-settings-btn').addEventListener('click', async () => {
      const s = $('odypatch-settings'); s.classList.toggle('hidden');
      if (!s.classList.contains('hidden')) {
        try { const c = await api('/api/patches/config');
          $('odypatch-token-state').textContent = c.config ? `current: ${c.config.api_token}` : ''; }
        catch (e) {}
      }
    });
    $('odypatch-token-save').addEventListener('click', async () => {
      const t = $('odypatch-token').value.trim();
      if (!t) { notify('Enter a token', true); return; }
      try {
        const r = await api('/api/patches/config', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ api_token: t }) });
        notify(r.ok ? 'Token saved' : (r.message || 'Save failed'), !r.ok);
        $('odypatch-token').value = '';
      } catch (e) { notify('Save failed', true); }
    });
  }

  function row(p) {
    const v = (p.review || {}).verdict;
    const badge = v ? ` <span class="odypatch-badge">${esc(v)}</span>` : '';
    const prop = p.proposer && p.proposer !== 'cli' ? ` [${esc(p.proposer)}]` : '';
    const isProp = p.status === 'proposed';
    const acts = isProp
      ? `<button data-act="approve" data-pr="${p.pr}">Approve</button>
         <button data-act="reject" data-pr="${p.pr}">Reject</button>
         <button data-act="review" data-pr="${p.pr}">Review</button>
         <button data-act="diff" data-pr="${p.pr}">Diff</button>`
      : `<button data-act="upgrade" data-pr="${p.pr}">Upgrade</button>
         <button data-act="remove" data-pr="${p.pr}">Remove</button>
         <button data-act="review" data-pr="${p.pr}">Review</button>
         <button data-act="diff" data-pr="${p.pr}">Diff</button>`;
    return `<div class="admin-card" style="margin-bottom:8px">
      <div><strong>#${p.pr}</strong> ${esc(p.title || '')}${prop}
        <span class="odypatch-badge">${esc(p.status || '')}</span>${badge}</div>
      <div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap">${acts}</div>
      <pre class="odypatch-diff hidden" data-diff-for="${p.pr}" style="max-height:300px;overflow:auto;background:var(--bg);border:1px solid var(--border);padding:8px;font-size:12px;white-space:pre;margin-top:6px"></pre>
    </div>`;
  }

  async function render() {
    const root = $('odypatch-content');
    if (!root) return;
    root.innerHTML = '<div style="opacity:.6">Loading…</div>';
    let data;
    try { data = await api('/api/patches/status'); }
    catch (e) { root.innerHTML = '<div class="admin-card">Could not load patch status.</div>'; return; }
    if (!data.cli_available) {
      root.innerHTML = `<div class="admin-card"><strong>Patch manager not available.</strong><div style="opacity:.7">${esc(data.hint || '')}</div></div>`;
      return;
    }
    const st = data.status;
    if (!st) { root.innerHTML = `<div class="admin-card">${esc(data.message || 'No status.')}</div>`; return; }
    const props = (st.patches || []).filter((p) => p.status === 'proposed');
    const applied = (st.patches || []).filter((p) => p.status !== 'proposed');
    let html = '';
    if (props.length) {
      html += `<div style="margin:14px 0 6px;opacity:.7">Proposals awaiting approval (${props.length})</div>` + props.map(row).join('');
    }
    html += `<div style="margin:14px 0 6px;opacity:.7">Applied patches (${applied.length})</div>`;
    html += applied.length ? applied.map(row).join('') : '<div class="admin-card" style="opacity:.6">No patches applied.</div>';
    html += `<div class="admin-card" style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-top:14px">
      <span style="opacity:.8">Applied patches take effect after you restart Odysseus.</span>
      <button data-act="update">Check for updates</button></div>`;
    root.innerHTML = html;
  }

  async function onAction(act, prVal) {
    if (act === 'diff') {
      const id = Number(prVal);
      const el = document.querySelector(`[data-diff-for="${id}"]`);
      if (!el) return;
      if (!el.classList.contains('hidden')) { el.classList.add('hidden'); return; }
      el.textContent = 'Loading diff…'; el.classList.remove('hidden');
      try { el.textContent = (await api(`/api/patches/diff?pr=${id}`)).diff || '(empty)'; }
      catch (e) { el.textContent = 'Could not load diff.'; }
      return;
    }
    if (act === 'update') {
      try { const r = await api('/api/patches/update', { method: 'POST' }); notify(r.report || r.message || 'Update finished.'); }
      catch (e) { notify('Update failed.', true); }
      return render();
    }
    if (act === 'upgrade') {
      try {
        const r = await api('/api/patches/upgrade', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pr: Number(prVal) }) });
        notify(r.message || (r.ok ? 'Upgraded — restart to apply' : 'Upgrade failed'), !r.ok);
      } catch (e) { notify('Upgrade failed', true); }
      return render();
    }
    if ((act === 'remove' || act === 'reject') && !confirm(`${act} patch #${prVal}?`)) return;
    try {
      const r = await api(`/api/patches/${act}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pr: Number(prVal) }) });
      notify(r.message || (r.ok ? `${act} #${prVal} done` : `${act} failed`), !r.ok);
    } catch (e) { notify('Action failed.', true); }
    return render();
  }

  function openPanel() { ensureModal(); $('odypatch-modal').classList.remove('hidden'); render(); }

  async function init() {
    try { const r = await fetch('/api/patches/status'); if (!r.ok) return; }
    catch (e) { return; }
    const tools = document.getElementById('tools-section');
    if (!tools || document.getElementById('odypatch-btn')) return;
    const btn = document.createElement('div');
    btn.className = 'list-item';
    btn.id = 'odypatch-btn';
    btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;opacity:0.5"><line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/></svg><span class="grow">Patches</span>`;
    btn.addEventListener('click', openPanel);
    tools.appendChild(btn);
    const style = document.createElement('style');
    style.textContent = '.odypatch-badge{font-size:11px;opacity:.7;margin-left:6px;border:1px solid var(--border);border-radius:4px;padding:1px 5px}';
    document.head.appendChild(style);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
