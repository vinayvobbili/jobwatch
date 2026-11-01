/**
 * The review panel, in Chrome's docked side panel. A view of the rows the service worker builds for the
 * active tab; scanning, filling and drafting all go back through the worker (background.js).
 *
 * It follows the active tab. When the person switches tabs or the tab loads another page, the rows are dropped
 * and a rescan is asked for, so a row never fills a form that is no longer on screen. `?tab=<id>` pins it to one
 * tab (the end-to-end test opens this page in an ordinary tab and points it at the form's tab).
 */
(function () {
  'use strict';
  const JW = globalThis.JW;
  const send = (msg) => chrome.runtime.sendMessage(msg);
  const $ = (id) => document.getElementById(id);

  const SOURCE = { details: 'Your details', past: 'Past answer', draft: 'Draft', resume: 'Resume', none: 'Not found' };
  const pinned = Number(new URLSearchParams(location.search).get('tab')) || null;
  let tabId = pinned;
  let ready = false; // jobwatch is paired and answering
  let state = null; // the last scan: { items, info, job }
  let busy = false;

  try {
    const theme = localStorage.getItem('theme');
    if (theme && theme !== 'system') document.documentElement.setAttribute('data-theme', theme);
  } catch {
    /* no stored choice: follow the system */
  }

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

  function toast(text, ok) {
    const old = $('toast');
    if (old) old.remove();
    const t = h('div', { id: 'toast', class: ok ? '' : 'bad', textContent: text, role: 'status' });
    document.body.append(t);
    setTimeout(() => t.isConnected && t.remove(), 7000);
  }

  function view(...body) {
    $('view').replaceChildren(...body);
  }

  // --- pairing -------------------------------------------------------------------------------------

  async function checkPairing() {
    const pair = $('pair');
    pair.className = '';
    pair.textContent = 'Checking...';
    const s = await send({ type: 'status' });
    ready = !!(s.paired && s.reachable);
    if (ready) {
      pair.className = 'good';
      pair.textContent = `Paired with jobwatch ${s.version}.`;
    } else {
      pair.className = 'warn';
      pair.textContent = !s.paired
        ? 'This needs jobwatch. Run "jobwatch ui", copy the token from its Settings, and paste it in Settings here.'
        : `jobwatch is not running or did not accept the token (${s.error}). Start it with "jobwatch ui", then check again.`;
    }
    return ready;
  }

  // --- the views -----------------------------------------------------------------------------------

  const scanButton = () => h('button', { id: 'scan', class: 'go', textContent: 'Fill this application', onclick: scan });

  // The posting action: on a LinkedIn job it presses Apply to open the company's posting, anywhere else it saves the page's posting.
  const POSTING = { linkedin: "Open the company's posting", site: 'Save this posting to jobwatch' };
  const postingButton = () => {
    const b = h('button', { id: 'posting', class: 'ghost', textContent: POSTING.site, onclick: savePosting });
    chrome.tabs.query({ active: true, currentWindow: true }).then(([tab]) => {
      if (JW.postingMode(pinned || !tab ? '' : tab.url) === 'linkedin') b.textContent = POSTING.linkedin;
    }, () => {});
    return b;
  };
  const actions = () => h('div', { class: 'actions' }, scanButton(), postingButton());

  function idle(text) {
    state = null;
    $('where').textContent = '';
    if (!ready) {
      view(h('div', { class: 'empty' }, h('div', { textContent: 'Nothing to fill from until jobwatch is running.' }),
        h('button', { id: 'recheck', class: 'ghost', textContent: 'Check again', onclick: async () => { if (await checkPairing()) idle(text); } })));
      return;
    }
    view(h('div', { class: 'empty' }, h('div', { class: 'msg', textContent: text }), actions()));
  }

  function failed(message) {
    view(h('div', { class: 'empty' }, h('div', { class: 'msg', textContent: message }), actions()));
  }

  /** What the posting action did, with a link to the job on jobwatch's page. */
  function posted(r) {
    $('where').textContent = `${r.title} at ${r.company}`;
    view(h('div', { class: 'empty done' }, h('div', { class: 'msg good', textContent: r.said + '.' }),
      h('a', { class: 'go linkbtn', href: r.link, target: '_blank', rel: 'noopener', textContent: 'See it in jobwatch' }),
      h('div', { class: 'msg small', textContent: r.has_text ? '' : 'Press Apply on the company\'s site, then use "Save this posting to jobwatch" on its page.' })));
  }

  /** LinkedIn's Apply button was pressed: the company's site opens in a new tab, and jobwatch follows it there. */
  function opened() {
    view(h('div', { class: 'empty' }, h('div', { class: 'msg good', textContent: "Opening the company's posting in a new tab." }),
      h('div', { class: 'msg small', textContent: 'jobwatch fills the job in when that page has loaded, if it is a job site it can read. If not, use "Save this posting to jobwatch" on that page.' })));
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
    refresh();
    const m = item.matched;
    return h('div', { class: 'row', style: `animation-delay:${Math.min(i, 12) * 25}ms` },
      h('div', { class: 'top' }, box, h('div', { class: 'q', textContent: item.question || '(no label)' })),
      h('span', { class: `badge ${item.source}`, textContent: SOURCE[item.source] }),
      item.filled ? h('div', { class: 'meta', textContent: `Already filled on the page${item.current ? `: ${item.current.slice(0, 60)}` : ''}` }) : null,
      item.kind === 'file' && item.source !== 'resume' ? null : edit,
      item.kind === 'file' ? h('div', { class: 'meta', textContent: item.source === 'resume' ? `Attaches ${item.value} from jobwatch` : 'Attach this one yourself' }) : null,
      m ? h('div', { class: 'meta', textContent: `From your answer to "${m.question}"${[m.company, m.title, m.applied_at].some(Boolean) ? ` (${[m.company, m.title, m.applied_at].filter(Boolean).join(', ')})` : ''}, ${Math.round(m.score * 100)}% alike. Check it fits this job.` }) : null,
      meta,
      !item.key && (item.kind === 'text' || item.kind === 'textarea') ? h('button', { class: 'small', textContent: item.source === 'draft' ? 'Draft again' : 'Draft with jobwatch', onclick: (e) => draft(item, e.target) }) : null);
  }

  function count() {
    const n = state.items.filter((it) => it.checked && it.value).length;
    $('count').textContent = `${n} of ${state.items.length} ticked`;
    $('fill').disabled = !n || busy;
  }

  function render() {
    const { items, info, job } = state;
    const where = job ? `${job.title} at ${job.company}` : info.title ? `${info.title}${info.company ? ` at ${info.company}` : ''}` : 'this application';
    $('where').textContent = where;
    $('where').title = where;
    const past = items.filter((it) => it.source === 'past').length;
    view(
      h('div', { class: 'scroll' },
        h('div', { class: 'note', textContent: 'Fill the basics with Simplify or Chrome autofill, then jobwatch fills the rest. Fields that already have a value start unticked.' }),
        h('div', { class: 'note', textContent: past ? `${past} question${past === 1 ? '' : 's'} matched an answer from an earlier application.` : 'No earlier answers matched here.' }),
        h('div', { class: 'rows' }, items.map(row))),
      h('footer', {}, h('span', { id: 'count', class: 'count' }),
        h('button', { id: 'rescan', class: 'ghost', textContent: 'Rescan', onclick: scan }),
        h('button', { id: 'fill', class: 'go', textContent: 'Fill selected', onclick: fill })));
    count();
  }

  // --- actions -------------------------------------------------------------------------------------

  async function scan() {
    if (busy) return;
    if (!tabId) {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      tabId = tab && tab.id;
    }
    if (!tabId) return failed('No tab to read. Open the application form and try again.');
    busy = true;
    const scanId = tabId;
    view(h('div', { class: 'empty', textContent: 'Reading the form...' }));
    const opened = await send({ type: 'open', tabId: scanId });
    const r = opened.ok ? await send({ type: 'analyze', tabId: scanId }) : opened;
    busy = false;
    if (scanId !== tabId) return; // the person moved on while it was reading; idle() already said so
    if (!r.ok) return failed(r.error);
    state = r;
    render();
  }

  async function savePosting() {
    if (busy) return;
    if (!tabId) {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      tabId = tab && tab.id;
    }
    if (!tabId) return failed('No tab to read. Open a job posting and try again.');
    busy = true;
    const readId = tabId;
    view(h('div', { class: 'empty', textContent: 'Reading the posting...' }));
    const r = await send({ type: 'posting', tabId: readId });
    busy = false;
    if (readId !== tabId) return;
    if (!r.ok) return failed(r.error);
    if (r.stage === 'opened') return opened();
    posted(r);
  }

  async function draft(item, btn) {
    btn.disabled = true;
    btn.textContent = 'Drafting...';
    // The form's other written answers go along, so the draft doesn't retell a story one of them already tells.
    const others = state.items.filter((it) => it !== item && !it.key && (it.kind === 'text' || it.kind === 'textarea') && (it.value || '').trim())
      .map((it) => ({ question: it.question, answer: it.value }));
    const r = await send({ type: 'draft', tabId, question: item.question, others });
    if (!r.ok) {
      btn.disabled = false;
      btn.textContent = 'Draft with jobwatch';
      toast(r.error, false);
      return;
    }
    if (!state) return;
    Object.assign(item, { value: r.answer, source: 'draft', matched: null, checked: false, result: null });
    render();
    toast('Drafted. Read it, edit it, then tick it to fill.', true);
  }

  async function fill() {
    const chosen = state.items.filter((it) => it.checked && it.value);
    const go = $('fill');
    busy = true;
    go.disabled = true;
    go.textContent = 'Filling...';
    const r = await send({ type: 'fill', tabId, items: chosen.map(({ id, kind, value, source }) => ({ id, kind, value, source })) });
    busy = false;
    if (!state) return;
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

  // --- following the tab ---------------------------------------------------------------------------

  const CHANGED = 'This tab changed since the last scan. Press Fill this application to read it again.';

  function tabChanged() {
    if (state) idle(CHANGED);
  }

  if (!pinned) {
    chrome.tabs.onActivated.addListener(({ tabId: now }) => {
      if (now === tabId) return;
      tabId = now;
      if (!busy) idle('Open a job application in this tab, then press Fill this application.');
    });
  }
  chrome.tabs.onUpdated.addListener((id, change) => {
    if (id === tabId && (change.status === 'loading' || change.url)) tabChanged();
  });
  chrome.tabs.onRemoved.addListener((id) => {
    if (id === tabId) idle('Open a job application in this tab, then press Fill this application.');
  });

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg && msg.type === 'toast' && (!tabId || msg.tabId === tabId)) toast(msg.text, msg.ok);
  });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && changes.settings && !busy && !state) init();
  });

  $('options').addEventListener('click', (e) => {
    e.preventDefault();
    chrome.runtime.openOptionsPage();
  });

  async function init() {
    await checkPairing();
    idle('Open a job application in this tab, then press Fill this application.');
  }

  init();
})();
