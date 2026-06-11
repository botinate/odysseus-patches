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
          <div id="odypatch-content"></div>
        </div>
      </div>`;
    document.body.appendChild(m);
    $('odypatch-close').addEventListener('click', () => m.classList.add('hidden'));
    $('odypatch-content').addEventListener('click', (e) => {
      const b = e.target.closest('button[data-act]');
      if (b) onAction(b.dataset.act, b.dataset.pr);
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
      : `<button data-act="remove" data-pr="${p.pr}">Remove</button>
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
      try { const r = await api('/api/patches/update', { method: 'POST' }); alert(r.report || r.message || 'Done.'); }
      catch (e) { alert('Update failed.'); }
      return render();
    }
    if ((act === 'remove' || act === 'reject') && !confirm(`${act} patch #${prVal}?`)) return;
    try {
      const r = await api(`/api/patches/${act}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pr: Number(prVal) }) });
      if (r.message) alert(r.message);
    } catch (e) { alert('Action failed.'); }
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
