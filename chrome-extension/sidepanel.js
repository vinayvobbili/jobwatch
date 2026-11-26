/**
 * The review panel, in Chrome's docked side panel. A view of the rows the service worker builds for the
 * active tab; scanning, filling and drafting all go back through the worker (background.js).
 *
 * It follows the active tab. When the person switches tabs or the tab loads another page, the rows are dropped
 * and a rescan is asked for, so a row never fills a form that is no longer on screen. A form that is replaced in
 * place (a multi-step application moving to its next step) is told by the page and scanned again. `?tab=<id>` pins
 * it to one tab (the end-to-end test opens this page in an ordinary tab and points it at the form's tab).
 */
(function () {
  'use strict';
  const JW = globalThis.JW;
  // A service worker Chrome stopped mid-call drops the message: say so, or the panel waits for ever
  const send = (msg) => chrome.runtime.sendMessage(msg).then((r) => r || { ok: false, error: STOPPED }, () => ({ ok: false, error: STOPPED }));
  const STOPPED = 'The jobwatch extension stopped before jobwatch answered. Open jobwatch\'s Today to see what it did, then try again.';
  const $ = (id) => document.getElementById(id);

  // This panel's tab: the one it was opened for (background.js pins each tab's panel with ?tab=), else the active one.
  const myTab = async () => (tabId ? chrome.tabs.get(tabId) : (await chrome.tabs.query({ active: true, currentWindow: true }))[0]);

  const SOURCE = { details: 'Your details', past: 'Past answer', draft: 'Draft', resume: 'Resume', none: 'Not found' };
  const pinned = Number(new URLSearchParams(location.search).get('tab')) || null;
  let tabId = pinned;
  let ready = false; // jobwatch is paired and answering
  let features = []; // what that jobwatch offers beyond filling (/ext/ping): an older one has no posting call
  let state = null; // the last scan: { items, info, job }
  let replyState = null; // the draft reply on show: jobwatch's answer with the conversation's fingerprint
  let resultState = null; // the ATS check or cover letter on show: { kind: 'ats' | 'cover', ...jobwatch's answer }
  let busy = false;
  let idleText = ''; // what idle() last said, shown again when the tab loads another page
  let homeShown = null; // the note the home view shows ('' for none) while it is on screen, else null: it is drawn again when the tab or the seen count changes
  let homeToken = 0; // the newest home() call; an older one still reading the page gives up
  const DEFAULT_IDLE = 'Open a job application in this tab, then press Fill this application.';
  let importing = null; // the tab whose job list is being imported: its progress shows

  // The theme (System, Light or Dark) is applied by look.js, from the choice made in Settings.

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
    stopWorking(); // any new view ends the elapsed counter of the one it replaces
    homeShown = null; // home() sets it again after drawing itself
    $('view').replaceChildren(...body);
  }

  // The "working" view of every long action: the message, a spinner and a live elapsed counter, so a slow one reads as busy, not stuck.
  let workingTimer = null;
  function stopWorking() {
    if (workingTimer) clearInterval(workingTimer);
    workingTimer = null;
  }
  function showWorking(message, ...more) {
    view(h('div', { class: 'empty' },
      h('div', { class: 'msg working' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), h('span', { textContent: message }),
        h('span', { id: 'elapsed', class: 'elapsed', textContent: JW.elapsedLabel(0) })),
      ...more));
    const started = Date.now();
    workingTimer = setInterval(() => {
      const el = $('elapsed');
      if (el) el.textContent = JW.elapsedLabel((Date.now() - started) / 1000);
      else stopWorking();
    }, 1000);
  }
  window.addEventListener('pagehide', stopWorking);

  // --- pairing -------------------------------------------------------------------------------------

  async function checkPairing() {
    const pair = $('pair');
    pair.className = '';
    pair.title = '';
    pair.textContent = 'Checking...';
    const s = await send({ type: 'status' });
    ready = !!(s.paired && s.reachable);
    features = s.features || [];
    if (ready) {
      pair.className = 'good';
      pair.textContent = `paired ${s.version}`;
      pair.title = `Paired with jobwatch ${s.version}`;
    } else {
      pair.className = 'warn';
      pair.textContent = !s.paired
        ? 'This needs jobwatch. Run "jobwatch", copy the token from its Settings, and paste it in Settings here.'
        : `jobwatch is not running or did not accept the token (${s.error}). Start it with "jobwatch", then check again.`;
    }
    return ready;
  }

  // --- the views -----------------------------------------------------------------------------------

  // The actions. Each is a tile in the grid under the lead card (ids kept: scan, posting, reply, import-list, passive-import);
  // the lead card's big button runs the same function for the page's own action. A tile that doesn't suit this page is dimmed.

  // Icons are fixed strings of ours (24px, stroked in the tile's colour), never page text.
  const ICONS = {
    scan: '<path d="M9 11l2 2 4-4"/><rect x="4" y="3" width="16" height="18" rx="3"/><path d="M8 17h5"/>',
    reply: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/><path d="M9 11h6M9 14h3"/>',
    posting: '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/>',
    'import-list': '<path d="M8 6h12M8 12h12M8 18h12"/><path d="M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
    'passive-import': '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    idle: '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>',
    ats: '<path d="M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6z"/><path d="M9 12l2 2 4-4"/>',
    cover: '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M3 8l9 6 9-6"/>',
  };
  const icon = (name) => {
    const span = h('span', { class: 'ico' });
    span.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;
    return span;
  };

  // The posting action: on a LinkedIn job it presses Apply to open the company's posting, anywhere else it saves the page's posting.
  const POSTING = { linkedin: "Open the company's posting", site: 'Save this posting to jobwatch' };
  const POSTING_TILE = { linkedin: 'Open company posting', site: 'Save this posting' };

  /** One tile: `lit` says whether the page suits it (a dimmed tile still works), `count` puts a badge on it. */
  function tile({ id, group, label, title, onclick, lit, count, disabled }) {
    return h('button', { id, class: `tile${lit ? '' : ' dim'}`, title, onclick, disabled: !!disabled },
      icon(id), h('span', { class: 'lbl', textContent: label }),
      count != null ? h('span', { class: 'cnt', textContent: String(count) }) : null);
  }

  /** The tiles by group: Apply, Messages, Jobs. What this jobwatch can't do (an older one) has no tile. */
  function tileGroups(ctx, tab, seen, importing) {
    const lit = (id) => ctx.matches.includes(id) || ctx.primary === id;
    const mode = tab ? JW.postingMode(tab.url) : 'site';
    const post = mode === 'linkedin' ? 'linkedin' : 'site';
    const job = ctx.kind === 'form' || ctx.kind === 'posting'; // a page that is a job's application or posting
    const groups = [
      ['Apply', '', [
        tile({ id: 'scan', label: 'Fill this application', title: 'Fill this application', onclick: scan, lit: lit('scan') }),
        features.includes('posting') ? tile({ id: 'posting', label: POSTING_TILE[post], title: POSTING[post], onclick: savePosting, lit: lit('posting') }) : null,
        features.includes('ats') ? tile({ id: 'ats', label: 'ATS check', title: "Check this job's resume against the posting's keywords", onclick: checkAts, lit: job }) : null,
        features.includes('cover') ? tile({ id: 'cover', label: 'Cover letter', title: 'Draft a cover letter for this job', onclick: () => draftCover(), lit: job }) : null]],
      ['Messages', 'msg-g', [
        features.includes('reply') ? tile({ id: 'reply', label: 'Draft reply', title: 'Draft reply to this conversation', onclick: draftReply, lit: lit('reply') }) : null]],
      ['Jobs', 'jobs-g', features.includes('import-list') ? [
        tile({ id: 'import-list', label: 'Read job list', title: 'Read the jobs on this list', onclick: importList, lit: lit('import-list'),
          disabled: importing || (ctx.kind === 'list' && !JW.listSupported(ctx.list, features)) }),
        tile({ id: 'passive-import', label: 'Seen while browsing', title: `Read the ${seen} job${seen === 1 ? '' : 's'} seen while browsing`, onclick: importSeen,
          lit: lit('passive-import') || seen > 0, count: seen, disabled: !seen })] : []],
    ];
    return groups.map(([name, cls, tiles], i) => {
      const some = tiles.filter(Boolean);
      return some.length ? h('section', { class: `group ${cls}`, style: `animation-delay:${80 + i * 50}ms` }, h('h3', { textContent: name }), h('div', { class: 'tiles' }, some)) : null;
    });
  }
  // Import-list settings: how many pages the button reads, and passive mode (jobs seen while browsing, imported
  // on request). Both are kept in chrome.storage.local; passive.js and background.js read them from there.
  const listOptions = (site) => {
    const pages = h('input', { id: 'list-pages', type: 'number', min: '1', max: '10', step: '1', value: '4', title: 'Pages read from a list (1-10)' });
    const on = h('input', { id: 'passive-on', type: 'checkbox', checked: false });
    const refresh = async () => {
      const s = await chrome.storage.local.get(['listPages', 'passiveOn']);
      if (document.activeElement !== pages) pages.value = String(s.listPages || 4);
      on.checked = s.passiveOn === true; // off by default; the person opts in
    };
    pages.addEventListener('change', () => {
      const n = Math.min(10, Math.max(1, Math.round(Number(pages.value)) || 4));
      pages.value = String(n);
      chrome.storage.local.set({ listPages: n });
    });
    on.addEventListener('change', () => chrome.storage.local.set({ passiveOn: on.checked }));
    refresh();
    return h('div', { class: 'list-options' },
      h('label', {}, 'Pages to read ', pages),
      site === 'ladders' ? null : h('label', { title: 'Keeps the jobs shown on LinkedIn and Indeed lists while you browse, on this computer, until you press Import.' },
        on, ' Note jobs while I browse'));
  };

  // What each lead card's big button says, and does (the same functions the tiles run).
  const LEAD = {
    scan: ['Fill this application', () => scan()],
    reply: ['Draft reply to this conversation', () => draftReply()],
    'import-list': ['Read the jobs on this list', () => importList()],
    posting: [null, () => savePosting()],
  };
  const KICKER = { form: 'scan', thread: 'reply', list: 'import-list', posting: 'posting', bubble: 'reply', idle: 'idle' };
  const WHY = {
    bubble: '',
    form: 'Fields that already have a value start unticked. You review every field before anything is filled.',
    thread: 'jobwatch reads the open conversation and drafts a reply. It never presses Send.',
    list: 'Every page of the list is scrolled and read; jobwatch tracks the jobs it did not have.',
    posting: '',
    idle: 'Open an application, a LinkedIn conversation or a list of jobs. The tiles below work on any page.',
  };

  /** The card at the top: what this page is and the one thing to do about it. `importing`: a list import is already running here. */
  function leadCard(ctx, tab, importing) {
    const action = LEAD[ctx.primary];
    const oldList = ctx.kind === 'list' && features.includes('import-list') && !JW.listSupported(ctx.list, features); // a jobwatch that doesn't know this site
    const offered = action && !oldList && (ctx.primary === 'scan' || features.includes(ctx.primary === 'reply' ? 'reply' : ctx.primary === 'posting' ? 'posting' : 'import-list'));
    const label = ctx.primary === 'posting'
      ? POSTING[tab && JW.postingMode(tab.url) === 'linkedin' ? 'linkedin' : 'site'] : action && action[0];
    const kicker = h('div', { class: 'kicker' }, icon(KICKER[ctx.kind]).firstChild, { form: 'Application', thread: 'Message', list: 'Jobs', posting: 'Posting', bubble: 'Message', idle: 'Idle' }[ctx.kind]);
    return h('div', { id: 'lead', class: `lead ${ctx.kind}` }, kicker,
      h('h2', { textContent: ctx.heading }),
      ctx.detail ? h('div', { class: 'detail', textContent: ctx.detail }) : null,
      WHY[ctx.kind] ? h('div', { class: 'why', textContent: WHY[ctx.kind] }) : null,
      oldList ? h('div', { id: 'list-old', class: 'why', textContent: `This jobwatch is too old to read ${JW.LIST_SITES[ctx.list]} lists. Update jobwatch (pip install -U jobwatch), then reopen this panel.` }) : null,
      offered ? h('button', { id: 'lead-go', class: 'go', textContent: label, onclick: action[1], disabled: ctx.primary === 'import-list' && importing }) : null,
      ctx.kind === 'list' && features.includes('import-list') && !oldList ? listOptions(ctx.list) : null,
      importing ? h('div', { id: 'import-busy', class: 'busy', textContent: JW.IMPORT_RUNNING }) : null);
  }

  /** The view when nothing has been read: a note (what just happened), the lead card for this tab, then every action as a tile. */
  async function home(message) {
    const mine = ++homeToken;
    const tab = await myTab().catch(() => null);
    const ctx = JW.pageContext(tab && tab.url, tab && tab.title);
    const importing = ctx.kind === 'list' && features.includes('import-list') && tab
      ? JW.importOnTab((await send({ type: 'importState' })).running, tab.id) : false;
    const s = await chrome.storage.local.get('passiveSeen');
    const seen = Object.keys(s.passiveSeen || {}).length;
    if (busy || mine !== homeToken) return; // the person pressed something, or the page changed again, while this was reading the page
    const cards = [leadCard(ctx, tab, importing), ...tileGroups(ctx, tab, seen, importing)];
    view(h('div', { class: 'scroll' }, h('div', { class: 'empty home' }, message ? h('div', { class: 'msg', textContent: message }) : null, cards)));
    homeShown = message || '';
  }

  function idle(text) {
    state = null;
    replyState = null;
    resultState = null;
    idleText = text;
    $('where').textContent = '';
    if (!ready) {
      homeShown = null;
      view(h('div', { class: 'empty' }, h('div', { textContent: 'Nothing to fill from until jobwatch is running.' }),
        h('button', { id: 'recheck', class: 'ghost', textContent: 'Check again', onclick: async () => { if (await checkPairing()) idle(text); } })));
      return;
    }
    home(text === DEFAULT_IDLE ? '' : text);
  }

  function failed(message) {
    home(message);
  }

  /** What the posting action did, with a link to the job on jobwatch's page. */
  function posted(r) {
    $('where').textContent = `${r.title} at ${r.company}`;
    view(h('div', { class: 'empty done' }, h('div', { class: 'msg good', textContent: r.said + '.' }),
      h('a', { class: 'go linkbtn', href: r.link, target: '_blank', rel: 'noopener', textContent: 'See it in jobwatch' }),
      h('div', { class: 'msg small', textContent: r.has_text ? '' : 'Press Apply on the company\'s site, then use "Save this posting to jobwatch" on its page.' })));
  }

  /**
   * A drafted reply: where it was written (on this Mac, or by a cloud model the person chose), jobwatch's warnings, the
   * draft in a box that can be edited, and the "check this" notes. "Put in the message box" fills LinkedIn's box and
   * stops there: nothing here presses Send.
   */
  function replied(r) {
    replyState = r;
    $('where').textContent = r.sender ? `Reply to ${r.sender}` : 'Reply';
    const cloud = r.local === false;
    const model = r.model || 'a cloud model';
    const pill = cloud
      ? h('div', { id: 'reply-where', class: 'pill cloud', textContent: r.drafted ? `This thread was sent to ${model}, off this Mac.` : `Replies are set to use ${model}, off this Mac.` })
      : h('div', { id: 'reply-where', class: 'pill local', textContent: r.drafted ? `Written on this Mac by ${model}. The thread did not leave it.` : 'Nothing was sent off this Mac.' });
    const box = h('textarea', { id: 'reply-text', class: 'val', rows: 9, value: r.reply || '' });
    const replace = h('button', { id: 'reply-replace', class: 'ghost', textContent: 'Replace what is in the box', hidden: true, onclick: () => putInBox(box, replace, true) });
    const put = h('button', { id: 'reply-fill', class: 'go', textContent: 'Put in the message box', onclick: () => putInBox(box, replace, false) });
    const copy = h('button', { id: 'reply-copy', class: 'ghost', textContent: 'Copy', onclick: () => navigator.clipboard.writeText(box.value).then(() => toast('Copied.', true), () => toast("Couldn't copy. Select the text and copy it.", false)) });
    view(
      h('div', { class: 'scroll' },
        h('div', { class: 'rows' },
          pill,
          (r.warnings || []).map((w) => h('div', { class: 'row warnrow', textContent: w })),
          r.drafted ? h('div', { class: 'row' }, h('div', { class: 'q', textContent: 'Draft' }), box) : null,
          (r.notes || []).length ? h('div', { class: 'row' }, h('div', { class: 'q', textContent: 'Check this before you send' }),
            h('ul', { class: 'checks' }, r.notes.map((n) => h('li', { textContent: n })))) : null,
          r.drafted ? h('div', { class: 'meta', textContent: `Read from ${r.count} message${r.count === 1 ? '' : 's'} in the open conversation. jobwatch never presses Send: you do.` }) : null)),
      h('footer', {}, h('span', { class: 'count', textContent: r.drafted ? 'Edit it, then put it in the box.' : r.waiting ? 'Waiting on them.' : 'No draft for this one.' }),
        r.waiting ? h('button', { id: 'reply-followup', class: 'go', textContent: 'Draft a follow-up', onclick: () => draftReply(true) }) : null,
        h('button', { id: 'reply-again', class: 'ghost', textContent: 'Draft again', onclick: () => draftReply(!!r.followup) }),
        r.drafted ? [copy, replace, put] : null));
  }

  async function putInBox(box, replaceButton, replace) {
    const text = box.value.trim();
    if (!text) return toast('The draft is empty.', false);
    const r = await send({ type: 'fillReply', tabId, text, fingerprint: replyState && replyState.fingerprint, replace });
    if (!r.ok) return toast(r.error, false);
    if (r.filled) return toast('In the message box. Read it, then press Send yourself.', true);
    if (r.reason === 'has-text') replaceButton.hidden = false;
    toast(r.reason === 'has-text' ? 'The message box already has text. Replace it, or copy the draft instead.' : r.error, false);
  }

  /** Which job the answer is for, said once at the top: its name, and how jobwatch told it when that was by name only. */
  const jobNote = (r) => (r.matched_by === 'name'
    ? h('div', { id: 'matched-by', class: 'row', textContent: 'jobwatch matched this page to the job by its company and title, not by its address. Check it is the right one.' }) : null);

  /**
   * The ATS check: the score, which resume was read, the keywords a screener would miss (* is one the posting asks for),
   * and what would trip a parser. Offers a tailored resume when the check read the general one. A prompt to look at
   * the resume, never a change to it.
   */
  function atsShown(r) {
    resultState = { kind: 'ats', ...r };
    $('where').textContent = `${r.title} at ${r.company}`;
    const total = r.found.length + r.missing.length;
    const good = r.score != null && r.score >= 70 && !r.checks.length;
    const kws = (list) => h('div', { class: 'kws' }, list.map((m) => h('span', { class: `kw${m.kind === 'must' ? ' must' : ''}`, title: `${m.count}x in the posting`, textContent: m.term + (m.kind === 'must' ? ' *' : '') })));
    view(
      h('div', { class: 'scroll' },
        h('div', { class: 'rows' },
          h('div', { id: 'ats-score', class: `pill${good ? '' : ' cloud'}`, textContent: r.score == null ? 'The posting names no keywords to check.' : `ATS ${r.score}%: ${r.found.length} of ${total} keywords found` }),
          jobNote(r),
          h('div', { class: 'row' }, h('div', { class: 'q', textContent: 'Resume checked' }),
            h('div', { id: 'ats-file', class: 'meta', textContent: `${r.file}${r.tailored ? ', tailored for this job' : ", your general resume (not tailored for this job)"}` }),
            !r.tailored && r.can_tailor ? h('button', { id: 'ats-tailor', class: 'small', textContent: 'Tailor a resume for this job, then check it', onclick: tailorThenCheck }) : null),
          r.missing.length ? h('div', { class: 'row' }, h('div', { class: 'q', textContent: "What a screener would miss" }), kws(r.missing),
            h('div', { class: 'meta', textContent: "* is asked for in the posting. Add a keyword only where it is true of you." })) : null,
          r.found.length ? h('div', { class: 'row' }, h('div', { class: 'q', textContent: 'Found in the resume' }), kws(r.found)) : null,
          r.checks.length ? h('div', { class: 'row' }, h('div', { class: 'q', textContent: 'How a parser reads it' }),
            h('ul', { class: 'checks' }, r.checks.map((c) => h('li', { textContent: c })))) : null,
          h('div', { class: 'meta', textContent: 'Checked by jobwatch on this computer, with no model. Nothing was changed.' }))),
      h('footer', {}, h('span', { class: 'count', textContent: r.missing.length ? `${r.missing.length} missing` : 'Nothing missing.' }),
        h('button', { id: 'ats-again', class: 'ghost', textContent: 'Check again', onclick: checkAts })));
  }

  /**
   * A drafted cover letter: where it was written (on this Mac, or by a cloud model the person chose), jobwatch's warnings,
   * the letter in a box that can be edited, a tone to draft again in, and, when the form has a cover letter box, a button
   * that puts it there. That button never presses Submit; it fills an empty box, and replaces text only when asked.
   */
  function coverShown(r, tone, emphasis) {
    resultState = { kind: 'cover', ...r };
    $('where').textContent = `${r.title} at ${r.company}`;
    const box = r.box || {};
    const model = r.model || 'a cloud model';
    const pill = r.local === false
      ? h('div', { id: 'cover-where', class: 'pill cloud', textContent: r.drafted ? `This letter was written by ${model}, off this Mac.` : `Drafts are set to use ${model}, off this Mac.` })
      : h('div', { id: 'cover-where', class: 'pill local', textContent: r.drafted ? `Written on this Mac by ${model}. Nothing left it.` : 'Nothing was sent off this Mac.' });
    const text = h('textarea', { id: 'cover-text', class: 'val', rows: 12, value: r.letter || '' });
    const toneBox = h('select', { id: 'cover-tone', title: 'Tone for the next draft' },
      ['direct', 'warm', 'formal', 'concise'].map((t) => h('option', { value: t, selected: t === (tone || r.tone || 'direct'), textContent: t[0].toUpperCase() + t.slice(1) })));
    const lean = h('input', { id: 'cover-emphasis', type: 'text', class: 'val', maxLength: 300, placeholder: 'Lean on... (optional)', value: emphasis || r.emphasis || '' });
    const replace = h('button', { id: 'cover-replace', class: 'ghost', textContent: 'Replace what is in the box', hidden: true, onclick: () => putCover(text, replace, true) });
    const put = box.found ? h('button', { id: 'cover-fill', class: 'go', textContent: 'Fill the cover letter box', onclick: () => putCover(text, replace, false) }) : null;
    const copy = h('button', { id: 'cover-copy', class: 'ghost', textContent: 'Copy', onclick: () => navigator.clipboard.writeText(text.value).then(() => toast('Copied.', true), () => toast("Couldn't copy. Select the text and copy it.", false)) });
    const where = box.found ? (box.filled ? 'The form has a cover letter box with text in it already: it is left alone unless you replace it.' : 'The form has a cover letter box. It is filled only when you press the button.')
      : box.file ? 'This form takes the cover letter as a file: copy the letter and attach it yourself.'
        : box.unreadable ? "This page can't be read for a cover letter box. Copy the letter instead." : 'No cover letter box on this page. Copy the letter instead.';
    view(
      h('div', { class: 'scroll' },
        h('div', { class: 'rows' },
          pill,
          jobNote(r),
          (r.warnings || []).map((w) => h('div', { class: 'row warnrow', textContent: w })),
          r.drafted ? h('div', { class: 'row' }, h('div', { class: 'q', textContent: 'Draft' }), text,
            h('div', { class: 'meta', textContent: `Saved with the job as version ${r.version || 1} (${r.tone}). A draft: edit it here, edits are not saved. Read it, then submit the form yourself.` })) : null,
          r.drafted ? h('div', { id: 'cover-box', class: 'meta', textContent: where }) : null,
          h('div', { class: 'row' }, h('div', { class: 'q', textContent: 'Draft again' }), toneBox, lean))),
      h('footer', {}, h('span', { class: 'count', textContent: r.drafted ? 'Edit it, then use it.' : 'No draft for this one.' }),
        h('button', { id: 'cover-again', class: 'ghost', textContent: 'Draft again', onclick: () => draftCover(toneBox.value, lean.value) }),
        r.drafted ? [copy, replace, put] : null));
  }

  async function putCover(text, replaceButton, replace) {
    const letter = text.value.trim();
    if (!letter) return toast('The letter is empty.', false);
    const r = await send({ type: 'fillCover', tabId, text: letter, replace });
    if (!r.ok) return toast(r.error, false);
    if (r.filled) return toast('In the cover letter box. Read it, then submit the form yourself.', true);
    if (r.reason === 'has-text') replaceButton.hidden = false;
    toast(r.reason === 'has-text' ? 'The cover letter box already has text. Replace it, or copy the letter instead.' : r.error || "Couldn't fill the box. Copy the letter instead.", false);
  }

  async function onTab(none) {
    if (!tabId) {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      tabId = tab && tab.id;
    }
    return tabId || failed(none);
  }

  async function checkAts() {
    if (busy || !(await onTab('No tab to read. Open the job\'s page and try again.'))) return;
    busy = true;
    const readId = tabId;
    showWorking('Checking the resume against the posting...');
    const r = await send({ type: 'ats', tabId: readId });
    busy = false;
    if (readId !== tabId) return;
    if (!r.ok) return failed(r.error);
    atsShown(r);
  }

  /** The ATS check's button for a general resume: tailor one for this job (a minute or two), then check that one. */
  async function tailorThenCheck() {
    if (busy) return;
    busy = true;
    const readId = tabId;
    showWorking('Tailoring a resume for this job...', h('div', { class: 'msg small', textContent: 'A minute or two.' }));
    const made = await send({ type: 'tailor', tabId: readId });
    const r = made.ok ? await send({ type: 'ats', tabId: readId }) : made;
    busy = false;
    if (readId !== tabId) return;
    if (!r.ok) return failed(r.error);
    atsShown(r);
    if (!made.checked) toast(`Tailored, but check it in jobwatch first: ${(made.problems || [])[0] || "resume-kit's checks didn't pass"}`, false);
  }

  async function draftCover(tone, emphasis) {
    if (busy || !(await onTab("No tab to read. Open the job's page and try again."))) return;
    busy = true;
    resultState = null;
    const readId = tabId;
    showWorking('Drafting a cover letter for this job...', h('div', { class: 'msg small', textContent: 'A local model can take a minute.' }));
    const r = await send({ type: 'cover', tabId: readId, tone, emphasis });
    busy = false;
    if (readId !== tabId) return;
    if (!r.ok) return failed(r.error);
    coverShown(r, tone, emphasis);
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
      item.kind === 'file' ? h('div', { class: 'meta', textContent: item.source === 'resume' ? `Attaches ${item.value} from jobwatch${state.resume && state.resume.tailored ? ', tailored for this job' : ', your default resume'}` : 'Attach this one yourself' }) : null,
      item.source === 'resume' && state.canTailor && !(state.resume && state.resume.tailored)
        ? h('button', { class: 'small', textContent: 'Tailor a resume for this job', onclick: (e) => tailorResume(item, e.target) }) : null,
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
    showWorking('Reading the form...');
    const opened = await send({ type: 'open', tabId: scanId });
    const r = opened.ok ? await send({ type: 'analyze', tabId: scanId }) : opened;
    busy = false;
    if (scanId !== tabId) return; // the person moved on while it was reading; idle() already said so
    if (!r.ok) return failed(r.error);
    state = r;
    render();
  }

  async function draftReply(followup) {
    if (busy) return;
    if (!tabId) {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      tabId = tab && tab.id;
    }
    if (!tabId) return failed('No tab to read. Open a conversation on LinkedIn and try again.');
    busy = true;
    replyState = null;
    const readId = tabId;
    showWorking('Reading the open conversation and drafting a reply...',
      h('div', { class: 'msg small', textContent: 'A local model can take a minute.' }));
    const r = await send({ type: 'draftReply', tabId: readId, followup: followup === true });
    busy = false;
    if (readId !== tabId) return;
    if (!r.ok) return failed(r.error);
    replied(r);
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
    showWorking('Reading the posting...');
    const r = await send({ type: 'posting', tabId: readId });
    busy = false;
    if (readId !== tabId) return;
    if (!r.ok) return failed(r.error);
    if (r.stage === 'opened') return opened();
    posted(r);
  }

  const SITE = JW.LIST_SITES;
  const pct = (x) => (x == null ? '-' : `${Math.round(x * 100)}%`);

  /** What Read the jobs on this list did: per site, how many jobwatch had (its coverage), what it added, what it couldn't place. */
  function imported(r) {
    $('where').textContent = 'Job list imported';
    const sites = Object.entries(r.by_source || {}).map(([src, c]) => h('div', { class: 'row' },
      h('div', { class: 'q', textContent: `${SITE[src] || src}: ${c.seen} jobs` }),
      h('span', { class: 'badge details', textContent: `Coverage ${pct(c.coverage)}` }),
      c.note ? h('div', { class: 'meta', textContent: c.note }) : null,
      h('div', { class: 'meta', textContent: `${c.tracked + c.earlier} already tracked${c.earlier ? ` (${c.earlier} by an earlier import)` : ''}, ${c.added} added from the company's board, ${c.unplaced} couldn't place.` })));
    const unplaced = (r.unplaced || []).map((j, i) => h('div', { class: 'row', style: `animation-delay:${Math.min(i, 12) * 25}ms` },
      h('div', { class: 'q', textContent: `${j.company}: ${j.title}` }),
      h('div', { class: 'meta', textContent: [j.location, j.why].filter(Boolean).join(' · ') })));
    view(h('div', { class: 'scroll' },
      r.stopped ? h('div', { class: 'note', textContent: r.stopped }) : null,
      h('div', { class: 'rows' }, sites),
      unplaced.length ? h('div', { class: 'note', textContent: "Couldn't place these on their company's board. They're tracked from the list; watch the company's board in jobwatch and they're filled in." }) : null,
      unplaced.length ? h('div', { class: 'rows' }, unplaced) : null),
    h('footer', {}, h('span', { class: 'count', textContent: `${(r.added || []).length} added` }),
      h('a', { class: 'go linkbtn', href: r.link, target: '_blank', rel: 'noopener', textContent: 'See them in jobwatch' })));
  }

  async function importList() {
    if (busy) return;
    if (!tabId) {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      tabId = tab && tab.id;
    }
    if (!tabId) return failed('No tab to read. Open a job list on LinkedIn, Indeed or Ladders and try again.');
    busy = true;
    const readId = tabId;
    importing = readId;
    showWorking('Reading the list...',
      h('div', { id: 'progress', class: 'msg small', textContent: 'Each page is scrolled to its end, then the next one is opened.' }));
    const r = await send({ type: 'importList', tabId: readId });
    busy = false;
    importing = null;
    if (readId !== tabId) return;
    if (!r.ok) return failed(r.error);
    imported(r);
  }

  /** Import the jobs passive mode noted while browsing (nothing is read from any page now). */
  async function importSeen() {
    if (busy) return;
    busy = true;
    view(h('div', { class: 'empty' }, h('div', { class: 'msg', textContent: 'Sending the jobs you saw to jobwatch...' }),
      h('div', { class: 'msg small', textContent: 'Looking for each on its company\'s own board. This can take a few minutes.' })));
    const r = await send({ type: 'importPassive' });
    busy = false;
    if (!r.ok) return failed(r.error);
    imported(r);
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

  async function tailorResume(item, btn) {
    btn.disabled = true;
    btn.textContent = 'Tailoring... (a minute or two)';
    const r = await send({ type: 'tailor', tabId });
    if (!r.ok) {
      btn.disabled = false;
      btn.textContent = 'Tailor a resume for this job';
      toast(r.error, false);
      return;
    }
    if (!state) return;
    state.resume = r.resume;
    Object.assign(item, { value: r.resume.name, result: null });
    render();
    // resume-kit's verdict: a version that missed its page target or a fact check is kept, but flagged
    toast(!r.checked ? `Tailored, but check it in jobwatch first: ${r.problems[0] || "resume-kit's checks didn't pass"}`
      : `Tailored ${r.resume.name}${r.pages ? ` (${r.pages} pages)` : ''}. Review it in jobwatch before you submit.`, r.checked);
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
    else if (replyState) idle('This tab changed since the draft was written. Press Draft reply to read the conversation again.');
    else if (resultState) idle('This tab changed since that was made. Press ATS check or Cover letter to do it for this page.');
  }

  if (!pinned) {
    chrome.tabs.onActivated.addListener(({ tabId: now }) => {
      if (now === tabId) return;
      tabId = now;
      if (!busy) idle(DEFAULT_IDLE);
    });
  }
  chrome.tabs.onUpdated.addListener((id, change) => {
    if (id !== tabId) return;
    if (change.status === 'loading' || change.url) tabChanged();
    // the lead card and the lit tiles follow the page: its address, and its title (LinkedIn names a conversation late)
    if ((change.status === 'complete' || change.url || change.title) && !state && !replyState && !resultState && !busy && homeShown !== null) home(homeShown);
  });
  chrome.tabs.onRemoved.addListener((id) => {
    if (id === tabId) idle(DEFAULT_IDLE);
  });

  // A multi-step form that swaps its step in place (no navigation): the page says so, and the new step is read
  // again. Scanning only reads (answers come from jobwatch, nothing is drafted), so it is safe to repeat; if the
  // new step has no fields yet, the person is asked to scan once it is there.
  async function stepChanged() {
    if (!state || busy) return;
    const old = state;
    const id = tabId;
    await scan();
    if (state === old && id === tabId) idle(CHANGED);
  }

  chrome.runtime.onMessage.addListener((msg, sender) => {
    if (msg && msg.type === 'formChanged' && sender.tab && sender.tab.id === tabId) stepChanged();
    if (msg && msg.type === 'toast' && (!tabId || msg.tabId === tabId)) toast(msg.text, msg.ok);
    if (msg && JW.progressIsMine(msg, importing) && $('progress')) $('progress').textContent = msg.text;
  });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && changes.settings && !busy && !state) init();
    if (area === 'local' && changes.passiveSeen && !busy && !state && !replyState && !resultState && homeShown !== null) home(homeShown); // the badge
  });

  $('options').addEventListener('click', (e) => {
    e.preventDefault();
    chrome.runtime.openOptionsPage();
  });

  async function init() {
    await checkPairing();
    idle(DEFAULT_IDLE);
  }

  init();
})();
