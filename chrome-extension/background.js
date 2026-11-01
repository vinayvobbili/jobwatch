/**
 * Service worker: the only part that talks to jobwatch, and the one that knows what's going on in a tab.
 *
 * The side panel (sidepanel.js) asks it to scan, fill and draft. Content scripts tell it when the
 * person submits; it keeps those answers as pending per tab (chrome.storage.session) and posts them to
 * jobwatch only once the page looks like a finished submission.
 */
import './logic.js';
import { ApiError, api, getSettings, toBase64 } from './lib.js';

const JW = globalThis.JW;
const PENDING_MAX_MS = 30 * 60 * 1000;
const pendingKey = (tabId) => `pending:${tabId}`;
const ctxKey = (tabId) => `ctx:${tabId}`;

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const tabId = msg.tabId || (sender.tab && sender.tab.id);
  handle(msg, tabId, sender)
    .then((r) => sendResponse({ ok: true, ...(r || {}) }))
    .catch((e) => sendResponse({ ok: false, error: e instanceof ApiError || e.expected ? e.message : `Something went wrong: ${e.message}` }));
  return true;
});

// The toolbar button opens the side panel. Handling the click ourselves (rather than setPanelBehavior's
// openPanelOnActionClick) is what makes the grant of activeTab certain: onClicked is "executing an action".
// sidePanel.open must be called straight away, while the click's user gesture is still alive.
chrome.action.onClicked.addListener((tab) => {
  chrome.sidePanel.open({ tabId: tab.id }).catch(() => {});
});

chrome.tabs.onRemoved.addListener((tabId) => chrome.storage.session.remove([pendingKey(tabId), ctxKey(tabId)]));

async function handle(msg, tabId, sender) {
  switch (msg.type) {
    case 'open': return open(tabId);
    case 'status': return status();
    case 'test': return { ...(await api('/ext/ping', { settings: msg.settings })) };
    case 'analyze': return analyze(tabId);
    case 'fill': return fill(tabId, msg.items);
    case 'draft': return draft(tabId, msg.question, msg.words, msg.others);
    case 'posting': return posting(tabId);
    case 'captured': return captured(tabId, msg, sender);
    case 'looksSubmitted': return record(tabId);
    default: throw new Error(`unknown message ${msg.type}`);
  }
}

class Expected extends Error {
  expected = true;
}

// --- the side panel -------------------------------------------------------------------------------------

async function open(tabId) {
  const t = { tabId, allFrames: true };
  try {
    await chrome.scripting.executeScript({ target: t, files: ['logic.js', 'page.js'] });
    await chrome.scripting.executeScript({ target: t, func: () => globalThis.JWPage && globalThis.JWPage.watch() });
  } catch {
    throw new Expected("This page can't be filled. Open the application form, click the jobwatch icon on that tab, and try again.");
  }
}

async function status() {
  const s = await getSettings();
  if (!s.token) return { paired: false };
  try {
    const p = await api('/ext/ping', { settings: s, timeout: 4000 });
    return { paired: true, reachable: true, version: p.version };
  } catch (e) {
    return { paired: true, reachable: false, error: e.message };
  }
}

async function tabUrl(tabId) {
  return (await chrome.tabs.get(tabId)).url || '';
}

/**
 * Scan every frame, gather what jobwatch knows, and build the review rows. Fields another tool
 * (Simplify, Chrome autofill, a password manager) already filled come back as "filled" and start unticked.
 */
async function analyze(tabId) {
  const url = await tabUrl(tabId);
  const settings = await getSettings();
  if (!settings.token) throw new Expected('Pair the extension with jobwatch first: run "jobwatch ui", then paste its token into this extension\'s options.');
  const ctx = await api(`/ext/context?url=${encodeURIComponent(url)}`, { settings });
  const details = ctx.applicant || {};

  const results = await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, func: () => (globalThis.JWPage ? globalThis.JWPage.scan() : null) });
  const fields = [];
  let info = { company: '', title: '' };
  for (const r of results) {
    if (!r.result || !r.result.fields.length) continue;
    for (const f of r.result.fields) fields.push({ ...f, id: `${r.frameId}:${f.id}`, frameId: r.frameId });
    info = { company: info.company || r.result.info.company, title: info.title || r.result.info.title };
  }
  if (!fields.length) throw new Expected('No form fields found on this page. Open the application form and try again.');

  const resume = ctx.resume;
  const items = JW.buildPlan(fields, details, ctx.answers || [], { resume: resume && resume.name });
  items.forEach((it, i) => { it.frameId = fields[i].frameId; });
  await chrome.storage.session.set({ [ctxKey(tabId)]: { job: ctx.job, resume: resume || null, url } });
  return {
    items, info,
    job: ctx.job ? { title: ctx.job.title, company: ctx.job.company } : null,
    answers: (ctx.answers || []).length,
  };
}

async function fill(tabId, items) {
  const url = await tabUrl(tabId);
  const byFrame = new Map();
  let resume = null;
  for (const it of items) {
    const [frame, id] = it.id.split(':');
    const out = { id, kind: it.kind, value: it.value };
    if (it.source === 'resume') {
      if (!resume) resume = await fetchResume(url, tabId);
      out.resume = resume;
    }
    if (!byFrame.has(+frame)) byFrame.set(+frame, []);
    byFrame.get(+frame).push(out);
  }
  const done = [];
  for (const [frameId, list] of byFrame) {
    const [r] = await chrome.scripting.executeScript({ target: { tabId, frameIds: [frameId] }, func: (l) => globalThis.JWPage.fill(l), args: [list] });
    for (const res of r.result) done.push({ ...res, id: `${frameId}:${res.id}` });
  }
  return { results: done };
}

async function fetchResume(url, tabId) {
  const ctx = (await chrome.storage.session.get(ctxKey(tabId)))[ctxKey(tabId)] || {};
  const got = await api(`/ext/resume?url=${encodeURIComponent(url)}`, { raw: true });
  const name = (ctx.resume && ctx.resume.name) || 'resume.pdf';
  return { name, type: (ctx.resume && ctx.resume.type) || got.type, b64: toBase64(got.bytes) };
}

async function draft(tabId, question, words, others) {
  const r = await api('/ext/draft', { method: 'POST', body: { url: await tabUrl(tabId), question, words: words || 150, others: others || [] } });
  return { answer: r.answer, model: r.model };
}

// --- the job posting on screen ----------------------------------------------------------------------

const LINKEDIN_KEY = 'lastLinkedIn';
const LINKEDIN_MAX_MS = 30 * 60 * 1000; // a company page opened this soon after a LinkedIn job is probably that job's

const AWAITING_KEY = 'awaitingCompanyTab';
const AWAIT_MAX_MS = 2 * 60 * 1000; // how long after Apply is pressed a tab it opens is taken to be the company's
const EASY = "This job applies on LinkedIn (Easy Apply), so there's no company page to read. Use Add the posting on Today to paste it.";

async function pairedSettings() {
  const settings = await getSettings();
  if (!settings.token) throw new Expected('Pair the extension with jobwatch first: run "jobwatch ui", then paste its token into this extension\'s options.');
  return settings;
}

/**
 * On a LinkedIn job: presses LinkedIn's offsite Apply button, for the person who asked, so the company's site opens in
 * a new tab. Nothing is read from the LinkedIn page and nothing is sent from it: only its address is kept, for the job
 * id. The button is found by its label (JW.isOffsiteApply); Easy Apply is never pressed, nor anything that submits.
 * The tab it opens is followed by followOpened().
 */
async function openCompany(tabId) {
  await pairedSettings();
  const url = await tabUrl(tabId);
  const id = JW.linkedinJobId(url);
  if (!id) throw new Expected('Open a job on LinkedIn (its own page, or select one in the list), then try again.');
  await chrome.storage.session.set({ [AWAITING_KEY]: { opener: tabId, id, at: Date.now() },
    [LINKEDIN_KEY]: { id, at: Date.now() } });
  let pressed;
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ['logic.js'] });
    [pressed] = await chrome.scripting.executeScript({ target: { tabId }, func: () => {
      const JW = globalThis.JW;
      const found = [...document.querySelectorAll('a, button')].filter((el) => el.getClientRects().length)
        .map((el) => ({ el, label: el.getAttribute('aria-label') || '', text: (el.textContent || '').trim() }));
      const apply = found.find(JW.isOffsiteApply);
      if (apply) { apply.el.click(); return 'pressed'; }
      return found.some(JW.isEasyApply) ? 'easy' : 'none';
    } });
  } catch {
    await chrome.storage.session.remove(AWAITING_KEY);
    throw new Expected("This page can't be used. Click the jobwatch icon on the job's tab, and try again.");
  }
  if (pressed.result !== 'pressed') {
    await chrome.storage.session.remove(AWAITING_KEY);
    throw new Expected(pressed.result === 'easy' ? EASY : "Couldn't find LinkedIn's Apply button for the company's site on this page. Press it yourself, then use Save this posting to jobwatch on the company's page.");
  }
  return { stage: 'opened' };
}

// The tab Apply opened: remember it while it is the awaited one's child, and once it has loaded a page that isn't
// LinkedIn's (Apply goes through LinkedIn's redirect first), give jobwatch its address and the LinkedIn job id. jobwatch
// reads the posting itself when it is on a job site it supports; otherwise the person uses Save this posting there.
chrome.tabs.onCreated.addListener(async (tab) => {
  if (!tab.openerTabId) return;
  const w = (await chrome.storage.session.get(AWAITING_KEY))[AWAITING_KEY];
  if (w && w.opener === tab.openerTabId && !w.child && Date.now() - w.at < AWAIT_MAX_MS) {
    await chrome.storage.session.set({ [AWAITING_KEY]: { ...w, child: tab.id } });
  }
});

chrome.tabs.onUpdated.addListener(async (tabId, change, tab) => {
  if (change.status !== 'complete') return;
  const w = (await chrome.storage.session.get(AWAITING_KEY))[AWAITING_KEY];
  if (!w || w.child !== tabId || JW.postingMode(tab.url) !== 'site') return;
  await chrome.storage.session.remove(AWAITING_KEY);
  if (Date.now() - w.at > AWAIT_MAX_MS) return;
  try {
    const r = await api('/ext/posting', { method: 'POST', body: { linkedin: w.id, page_url: tab.url } });
    await toast(tabId, `${r.said}. See it in jobwatch's ${r.where} tab.`, true);
  } catch (e) {
    await toast(tabId, e.message, false);
  }
});

/**
 * On a company's page: sends jobwatch its address and the job text the page shows (the person pressed the button),
 * to fill in the job it has from an alert, or to add one. The LinkedIn job id goes along when the person pressed
 * Apply on LinkedIn a moment ago.
 */
async function posting(tabId) {
  const settings = await pairedSettings();
  const url = await tabUrl(tabId);
  const mode = JW.postingMode(url);
  if (mode === 'linkedin') return openCompany(tabId);
  if (mode !== 'site') throw new Expected("This page isn't a job posting. Open a job on LinkedIn, or the company's page for it, and try again.");
  let read;
  try {
    const t = { tabId };
    await chrome.scripting.executeScript({ target: t, files: ['logic.js', 'page.js'] });
    [read] = await chrome.scripting.executeScript({ target: t, func: () => (globalThis.JWPage && globalThis.JWPage.readPosting ? globalThis.JWPage.readPosting() : null) });
  } catch {
    throw new Expected("This page can't be read. Click the jobwatch icon on the job's tab, and try again.");
  }
  const page = read && read.result;
  if (!page) throw new Expected('Reload this page, then try again.');
  if (page.text.length < 200) throw new Expected("This page doesn't show a job posting's text. Open the posting itself and try again.");
  const body = { company: page.company, title: page.title, text: page.text, page_url: url };
  const last = (await chrome.storage.session.get(LINKEDIN_KEY))[LINKEDIN_KEY];
  if (last && Date.now() - last.at < LINKEDIN_MAX_MS) body.linkedin = last.id;
  const r = await api('/ext/posting', { method: 'POST', body, settings });
  return { stage: 'done', ...r, link: `${settings.serverUrl}/#${r.where}` };
}

// --- recording the application ---------------------------------------------------------------------

async function captured(tabId, msg, sender) {
  if (!(await getSettings()).token) return;
  const url = (sender.tab && sender.tab.url) || sender.url || '';
  const pending = { url, pairs: msg.pairs || [], info: msg.info || {}, resume: msg.resume || '', at: Date.now() };
  await chrome.storage.session.set({ [pendingKey(tabId)]: pending });
}

async function toast(tabId, text, ok) {
  try {
    await chrome.action.setBadgeText({ tabId, text: ok ? '✓' : '!' });
    await chrome.action.setBadgeBackgroundColor({ tabId, color: ok ? '#0c9468' : '#d83450' });
    await chrome.runtime.sendMessage({ type: 'toast', tabId, text, ok });
  } catch {
    /* the side panel is closed; the badge still shows */
  }
}

const recording = new Set();

async function record(tabId) {
  if (recording.has(tabId)) return;
  recording.add(tabId);
  try {
    await recordNow(tabId);
  } finally {
    recording.delete(tabId);
  }
}

async function recordNow(tabId) {
  const stored = await chrome.storage.session.get([pendingKey(tabId), ctxKey(tabId)]);
  const pending = stored[pendingKey(tabId)];
  if (!pending || Date.now() - pending.at > PENDING_MAX_MS) return;
  await chrome.storage.session.remove(pendingKey(tabId));
  const job = (stored[ctxKey(tabId)] || {}).job || {};
  const body = { url: pending.url, answers: pending.pairs };
  const company = pending.info.company || job.company;
  const title = pending.info.title || job.title;
  if (company) body.company = company;
  if (title) body.title = title;
  if (pending.resume) body.resume = pending.resume;
  try {
    const r = await api('/ext/submitted', { method: 'POST', body });
    await toast(tabId, r.added ? 'Recorded in jobwatch (added as a new job).' : 'Recorded in jobwatch as applied.', true);
  } catch (e) {
    await toast(tabId, `Couldn't record this in jobwatch: ${e.message}`, false);
  }
}

// A page that navigated after the person pressed Submit (Lever's thank-you page, say).
chrome.tabs.onUpdated.addListener(async (tabId, change) => {
  if (change.status !== 'complete') return;
  const pending = (await chrome.storage.session.get(pendingKey(tabId)))[pendingKey(tabId)];
  if (!pending) return;
  let seen = false;
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      func: () => {
        const errors = [...document.querySelectorAll('[aria-invalid="true"], [role="alert"], [class*="error" i]')]
          .some((n) => n.getClientRects().length && (n.getAttribute('aria-invalid') === 'true' || n.textContent.trim()));
        return { text: document.body ? document.body.innerText : '', errors };
      },
    });
    seen = results.some((r) => r.result && JW.looksSubmitted(r.result.text) && !r.result.errors);
  } catch {
    const tab = await chrome.tabs.get(tabId).catch(() => null);
    seen = !!tab && JW.looksSubmitted(`${tab.title || ''} ${(tab.url || '').replace(/[/_-]+/g, ' ')}`);
  }
  if (seen) await record(tabId);
});
