/**
 * Service worker: the only part that talks to jobwatch, and the one that knows what's going on in a tab.
 *
 * The panel (panel.js, in the page) asks it to scan, fill and draft. Content scripts tell it when the
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

chrome.tabs.onRemoved.addListener((tabId) => chrome.storage.session.remove([pendingKey(tabId), ctxKey(tabId)]));

async function handle(msg, tabId, sender) {
  switch (msg.type) {
    case 'open': return open(tabId);
    case 'status': return status();
    case 'test': return { ...(await api('/ext/ping', { settings: msg.settings })) };
    case 'analyze': return analyze(tabId);
    case 'fill': return fill(tabId, msg.items);
    case 'draft': return draft(tabId, msg.question, msg.words);
    case 'captured': return captured(tabId, msg, sender);
    case 'looksSubmitted': return record(tabId);
    default: throw new Error(`unknown message ${msg.type}`);
  }
}

class Expected extends Error {
  expected = true;
}

// --- the panel -------------------------------------------------------------------------------------

async function open(tabId) {
  const t = { tabId, allFrames: true };
  try {
    await chrome.scripting.executeScript({ target: t, files: ['logic.js', 'page.js'] });
    await chrome.scripting.executeScript({ target: { tabId }, files: ['panel.js'] });
    await chrome.scripting.executeScript({ target: t, func: () => globalThis.JWPage && globalThis.JWPage.watch() });
  } catch {
    throw new Expected("This page can't be filled. Open the application form and try again.");
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

async function draft(tabId, question, words) {
  const r = await api('/ext/draft', { method: 'POST', body: { url: await tabUrl(tabId), question, words: words || 150 } });
  return { answer: r.answer, model: r.model };
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
    await chrome.tabs.sendMessage(tabId, { type: 'toast', text, ok }, { frameId: 0 });
  } catch {
    /* the panel is gone after a navigation; the badge still shows */
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
