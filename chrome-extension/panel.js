/**
 * The side panel, in the page's top frame, inside a shadow root so the site's CSS can't touch it.
 * A view of the review rows the service worker built; the fill itself goes back through the worker.
 * Injected by the toolbar popup; injecting it again just shows it again.
 */
(function () {
  'use strict';
  if (globalThis.JWPanel) {
    globalThis.JWPanel.show();
    return;
  }
  const JW = globalThis.JW;
  const send = (msg) => chrome.runtime.sendMessage(msg);

  const STYLE = `
:host { all: initial; }
* { box-sizing: border-box; }
.panel { --bg: #f3f4fa; --panel: #fff; --text: #141a2e; --muted: #626a84; --line: #e2e5f0; --accent: #5457f0;
  --accent-2: #a14cf2; --soft: rgba(84,87,240,.1); --good: #0c9468; --warn: #c26d00; --bad: #d83450; --chip: #eef0f8;
  --grad: linear-gradient(135deg, #5a5cf2, #a24af0); color-scheme: light; }
@media (prefers-color-scheme: dark) { .panel { --bg: #0a0d16; --panel: #151926; --text: #e9ebf5; --muted: #8f97b2;
  --line: #252a3b; --accent: #8d8fff; --accent-2: #c77dff; --soft: rgba(141,143,255,.14); --good: #3ddc97;
  --warn: #fbbf24; --bad: #ff7a93; --chip: #1e2333; color-scheme: dark; } }
.panel { position: fixed; top: 12px; right: 12px; z-index: 2147483647; width: 420px; max-width: calc(100vw - 24px);
  max-height: calc(100vh - 24px); display: flex; flex-direction: column; color: var(--text); border-radius: 16px;
  font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; overflow: hidden;
  background: radial-gradient(420px 200px at 0% -10%, var(--soft), transparent 70%), var(--bg);
  border: 1px solid var(--line); box-shadow: 0 24px 60px -20px rgba(40,30,120,.45); animation: rise .35s cubic-bezier(.2,.7,.2,1); }
@keyframes rise { from { opacity: 0; transform: translateY(10px) scale(.98); } }
@media (prefers-reduced-motion: reduce) { .panel, .row { animation: none !important; } }
header { display: flex; align-items: center; gap: 8px; padding: 12px 14px; border-bottom: 1px solid var(--line); }
.brand { font-weight: 800; font-size: 16px; letter-spacing: -.02em; background: linear-gradient(120deg, var(--accent), var(--accent-2));
  -webkit-background-clip: text; background-clip: text; color: transparent; }
.sub { color: var(--muted); font-size: 12px; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
button { font: inherit; cursor: pointer; }
.x { background: none; border: 0; color: var(--muted); font-size: 20px; line-height: 1; padding: 2px 6px; border-radius: 8px; }
.x:hover { background: var(--chip); color: var(--text); }
.note { margin: 10px 14px 0; padding: 8px 10px; border-radius: 10px; font-size: 12.5px; background: var(--soft); color: var(--text); }
.note.warn { background: color-mix(in srgb, var(--warn) 14%, transparent); }
.rows { overflow: auto; padding: 10px 14px; display: flex; flex-direction: column; gap: 8px; }
.row { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 9px 10px; animation: rise .3s both;
  transition: box-shadow .15s, transform .15s; }
.row:hover { box-shadow: 0 10px 24px -16px rgba(70,60,190,.5); transform: translateY(-1px); }
.top { display: flex; gap: 8px; align-items: flex-start; }
.top input[type=checkbox] { margin-top: 3px; accent-color: var(--accent); }
.q { flex: 1; font-weight: 600; font-size: 13px; overflow-wrap: anywhere; }
.badge { flex: none; font-size: 10.5px; font-weight: 700; padding: 2px 8px; border-radius: 99px; background: var(--chip); color: var(--muted); }
.badge.details, .badge.resume { background: var(--grad); color: #fff; }
.badge.past { background: color-mix(in srgb, var(--good) 18%, transparent); color: var(--good); }
.badge.draft { background: color-mix(in srgb, var(--warn) 18%, transparent); color: var(--warn); }
.val { width: 100%; margin-top: 6px; padding: 6px 8px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg);
  color: var(--text); font: inherit; resize: vertical; }
.val:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
.meta { margin-top: 5px; font-size: 12px; color: var(--muted); overflow-wrap: anywhere; }
.meta.bad { color: var(--bad); } .meta.good { color: var(--good); }
.small { margin-top: 6px; padding: 3px 10px; border-radius: 8px; border: 1px solid var(--line); background: var(--chip); color: var(--text); font-size: 12px; }
.small:hover { border-color: var(--accent); }
footer { display: flex; gap: 8px; align-items: center; padding: 10px 14px; border-top: 1px solid var(--line); background: var(--panel); }
footer .count { flex: 1; color: var(--muted); font-size: 12px; }
.go { background: var(--grad); color: #fff; border: 0; border-radius: 10px; padding: 8px 16px; font-weight: 700;
  box-shadow: 0 8px 18px -10px rgba(110,70,240,.8); transition: transform .15s, filter .15s; }
.go:hover { transform: translateY(-1px); filter: brightness(1.06); } .go:disabled { opacity: .5; transform: none; }
.ghost { background: none; border: 1px solid var(--line); color: var(--text); border-radius: 10px; padding: 7px 12px; }
.toast { position: absolute; left: 14px; right: 14px; bottom: 62px; padding: 9px 12px; border-radius: 10px; color: #fff; font-size: 13px;
  background: var(--good); animation: rise .25s both; }
.toast.bad { background: var(--bad); }
.empty { padding: 24px 14px; text-align: center; color: var(--muted); }
`;

  const SOURCE = { details: 'Your details', past: 'Past answer', draft: 'Draft', resume: 'Resume', none: 'Not found' };
  let host, root, state;

  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (k === 'class') el.className = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (v !== false && v != null) el[k] = v;
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid);
    return el;
  }

  function mount() {
    host = document.createElement('div');
    host.id = 'jobwatch-panel';
    root = host.attachShadow({ mode: 'open' });
    root.append(h('style', { textContent: STYLE }));
    document.documentElement.append(host);
  }

  function close() {
    if (host) host.remove();
    host = null;
  }

  function toast(text, ok) {
    if (!root) return;
    root.querySelectorAll('.toast').forEach((t) => t.remove());
    const t = h('div', { class: `toast${ok ? '' : ' bad'}`, textContent: text });
    root.querySelector('.panel').append(t);
    setTimeout(() => t.remove(), 6000);
  }

  function shell(sub, ...body) {
    root.querySelectorAll('.panel').forEach((p) => p.remove());
    root.append(h('div', { class: 'panel' },
      h('header', {}, h('span', { class: 'brand', textContent: 'jobwatch' }), h('span', { class: 'sub', textContent: sub || '' }),
        h('button', { class: 'x', title: 'Close', textContent: '×', onclick: close })),
      ...body));
  }

  const pick = (item) => {
    if (!item.options.length || !item.value) return '';
    const i = JW.optionIndex(item.value, item.options);
    return i < 0 ? null : item.options[i];
  };

  function row(item, i) {
    const long = item.kind === 'textarea' || item.value.length > 70;
    const edit = h(long ? 'textarea' : 'input', { class: 'val', value: item.value, rows: 3, disabled: item.kind === 'file',
      placeholder: item.kind === 'file' ? '' : 'Type an answer' });
    const meta = h('div', { class: 'meta' });
    const refresh = () => {
      const p = pick(item);
      meta.className = `meta${p === null ? ' bad' : ''}`;
      meta.textContent = p === null ? 'No option on the page reads like this.'
        : p ? `Will pick: ${p}` : item.kind === 'combobox' && item.value ? `Will pick the option that reads "${item.value}"` : '';
      if (item.result) {
        meta.className = `meta ${item.result.ok ? 'good' : 'bad'}`;
        meta.textContent = item.result.ok ? `Filled${item.result.picked ? `: ${item.result.picked}` : ''}` : item.result.error;
      }
    };
    edit.addEventListener('input', () => {
      item.value = edit.value;
      item.result = null;
      refresh();
      count();
    });
    const box = h('input', { type: 'checkbox', checked: item.checked, onchange: () => { item.checked = box.checked; count(); } });
    item._box = box;
    item._edit = edit;
    refresh();
    const m = item.matched;
    return h('div', { class: 'row', style: `animation-delay:${Math.min(i, 12) * 25}ms` },
      h('div', { class: 'top' }, box, h('div', { class: 'q', textContent: item.question || '(no label)' }),
        h('span', { class: `badge ${item.source}`, textContent: SOURCE[item.source] })),
      item.filled ? h('div', { class: 'meta', textContent: `Already filled on the page${item.current ? `: ${item.current.slice(0, 60)}` : ''}` }) : null,
      item.kind === 'file' && item.source !== 'resume' ? null : edit,
      item.kind === 'file' ? h('div', { class: 'meta', textContent: item.source === 'resume' ? `Attaches ${item.value} from jobwatch` : 'Attach this one yourself' }) : null,
      m ? h('div', { class: 'meta', textContent: `From your answer to "${m.question}"${[m.company, m.title, m.applied_at].some(Boolean) ? ` (${[m.company, m.title, m.applied_at].filter(Boolean).join(', ')})` : ''}, ${Math.round(m.score * 100)}% alike. Check it fits this job.` }) : null,
      meta,
      !item.key && (item.kind === 'text' || item.kind === 'textarea') ? h('button', { class: 'small', textContent: item.source === 'draft' ? 'Draft again' : 'Draft with jobwatch', onclick: (e) => draft(item, e.target) }) : null);
  }

  async function draft(item, btn) {
    btn.disabled = true;
    btn.textContent = 'Drafting...';
    const r = await send({ type: 'draft', question: item.question });
    if (!r.ok) {
      btn.disabled = false;
      btn.textContent = 'Draft with jobwatch';
      toast(r.error, false);
      return;
    }
    Object.assign(item, { value: r.answer, source: 'draft', matched: null, checked: false, result: null });
    render();
    toast('Drafted. Read it, edit it, then tick it to fill.', true);
  }

  function count() {
    const n = state.items.filter((it) => it.checked && it.value).length;
    const el = root.querySelector('.count');
    if (el) el.textContent = `${n} of ${state.items.length} ticked`;
    const go = root.querySelector('.go');
    if (go) go.disabled = !n;
  }

  function render() {
    const { items, info, job } = state;
    const where = job ? `${job.title} at ${job.company}` : info.title ? `${info.title}${info.company ? ` at ${info.company}` : ''}` : 'this application';
    const past = items.filter((it) => it.source === 'past').length;
    shell(where,
      h('div', { class: 'note', textContent: 'Fill the basics with Simplify or Chrome autofill, then jobwatch fills the rest. Fields that already have a value start unticked.' }),
      h('div', { class: 'note', textContent: past ? `${past} question${past === 1 ? '' : 's'} matched an answer from an earlier application.` : 'No earlier answers matched here.' }),
      h('div', { class: 'rows' }, items.map(row)),
      h('footer', {}, h('span', { class: 'count' }),
        h('button', { class: 'ghost', textContent: 'Rescan', onclick: start }),
        h('button', { class: 'go', textContent: 'Fill selected', onclick: fill })));
    count();
  }

  async function fill() {
    const chosen = state.items.filter((it) => it.checked && it.value);
    const go = root.querySelector('.go');
    go.disabled = true;
    go.textContent = 'Filling...';
    const r = await send({ type: 'fill', items: chosen.map(({ id, kind, value, source }) => ({ id, kind, value, source })) });
    go.textContent = 'Fill selected';
    if (!r.ok) {
      go.disabled = false;
      toast(r.error, false);
      return;
    }
    const byId = new Map(r.results.map((x) => [x.id, x]));
    for (const it of chosen) it.result = byId.get(it.id) || null;
    const ok = r.results.filter((x) => x.ok).length;
    render();
    toast(`Filled ${ok} of ${chosen.length}. Review the form, then submit it yourself.`, ok === chosen.length);
  }

  async function start() {
    shell('', h('div', { class: 'empty', textContent: 'Reading the form...' }));
    const r = await send({ type: 'analyze' });
    if (!r.ok) {
      shell('', h('div', { class: 'empty', textContent: r.error }), h('footer', {}, h('span', { class: 'count' }), h('button', { class: 'ghost', textContent: 'Close', onclick: close })));
      return;
    }
    state = r;
    render();
  }

  function show() {
    if (!host || !host.isConnected) mount();
    start();
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg && msg.type === 'toast') toast(msg.text, msg.ok);
  });

  globalThis.JWPanel = { show, close };
  show();
})();
