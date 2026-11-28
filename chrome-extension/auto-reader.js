/**
 * Auto-read, the part that touches the browser: opens the LinkedIn and Indeed pages jobwatch hands it, one at a time and
 * slowly, and hands the postings' text back (read-posting.js reads the page, as it does for the Read posting button).
 * The rules (pace, daily caps, ceilings, when to stop, when the person is busy) are all in auto-read.js as pure
 * functions; this file only asks them what to do and does it with tabs, alarms and calls to the local jobwatch.
 *
 * The state lives in chrome.storage.local ("autoRead"): the service worker is stopped and started all day. Every change
 * goes through `serial`, so two events never change it at once. A page is opened with active: false in the person's last
 * used window, once, with the reader's marker in its address; nothing is clicked or scrolled and no link is followed.
 * The tab closes as soon as the text is copied; after a sign of trouble it stays open behind the others, for the person.
 */
import { ApiError, api, getSettings } from './lib.js';

const JWAuto = globalThis.JWAuto;
const JWRead = globalThis.JWRead;
const KEY = 'autoRead';
const TICK = 'autoread-tick';   // every minute: the worker may have been stopped since the last event
const NEXT = 'autoread-next';   // at the moment the pause between two reads ends
const WATCH = 'autoread-watch'; // when the page being read has had its time
const QUEUE_TIMEOUT_MS = 8000;
const POSTING_TIMEOUT_MS = 90 * 1000;
const NOT_A_PAGE = /^(?:about:|chrome:|chrome-error:|edge:)/i;

let chain = Promise.resolve();
let openTab; // the tab being read, as of the last save (undefined: not known yet: read the state to see)

/** Run `fn` after everything queued before it: the state is read, changed and written by one event at a time. */
function serial(fn) {
  const run = chain.then(() => fn());
  chain = run.catch(() => {});
  return run;
}

// --- the state ---------------------------------------------------------------------------------------------

const limitsOf = (s) => JWAuto.limitsFrom({ limits: s.server });

async function load() {
  const { [KEY]: kept } = await chrome.storage.local.get(KEY);
  const now = Date.now();
  const day = JWAuto.localDay(new Date(now));
  let s = { ...JWAuto.freshState(day), ...(kept || {}) };
  if (!kept) s.nextAt = now + JWAuto.pauseMs(limitsOf(s)); // the first read waits a pause too
  s = JWAuto.rollDay(s, day);
  openTab = s.current ? s.current.tabId : null;
  return s;
}

async function save(s) {
  openTab = s.current ? s.current.tabId : null;
  await chrome.storage.local.set({ [KEY]: s });
  await badge(s);
}

/** A "!" on the toolbar button while today's reading is stopped; nothing else of ours is ever shown there. */
async function badge(s) {
  const stoppedNow = s.pausedDay === s.day;
  try {
    await chrome.action.setBadgeText({ text: stoppedNow ? '!' : '' });
    if (stoppedNow) {
      await chrome.action.setBadgeBackgroundColor({ color: '#d97706' });
      await chrome.action.setTitle({ title: s.pausedReason });
    } else {
      await chrome.action.setTitle({ title: 'jobwatch: fill this application' });
    }
  } catch { /* no toolbar button to mark */ }
}

function schedule(at) {
  if (at) chrome.alarms.create(NEXT, { when: Math.max(at, Date.now() + 1000) });
}

/** Whether the person is busy on LinkedIn or Indeed now: their active tab is on one of them and they are using the computer. */
async function activity() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true }).catch(() => []);
  const idle = await chrome.idle.queryState(JWAuto.LIMITS.IDLE_S).catch(() => 'idle');
  return { onSite: !!(tab && JWAuto.onJobSite(tab.url || '')), idle };
}

async function lastWindow() {
  try {
    return await chrome.windows.getLastFocused({ windowTypes: ['normal'] });
  } catch {
    return null; // Chrome is running with no window of its own to open a tab in
  }
}

// --- one step ----------------------------------------------------------------------------------------------

/** Look at the state and do what it says: nothing, wait, or open the next page. Called by every alarm and event. */
export function tick() {
  return serial(async () => {
    let s = await load();
    const now = Date.now();
    const limits = limitsOf(s);
    const ctx = { now, day: s.day, limits, active: await activity(), haveWindow: !!(await lastWindow()) };
    const todo = JWAuto.decide(s, ctx);
    if (todo.action !== 'defer' && s.deferred) s = { ...s, deferred: false };
    switch (todo.action) {
      case 'stale': return end(s, { kind: 'no_text', site: s.current.site, reason: "the page didn't show a posting in time" }, { close: true });
      case 'busy': return chrome.alarms.create(WATCH, { when: s.current.startedAt + JWAuto.LIMITS.TAB_MS + 1000 });
      case 'wait': await save(s); return schedule(todo.until);
      case 'defer': await save({ ...s, deferred: true }); return schedule(todo.until);
      case 'read': return readNext(s, ctx);
      default: return save(s); // off, paused, stopped, capped: nothing to do
    }
  });
}

/** Ask jobwatch for the jobs worth reading, take the first the caps allow, and open its page. */
async function readNext(s, ctx) {
  const { now, limits } = ctx;
  const settings = await getSettings();
  if (!settings.token) return save({ ...s, nextAt: now + JWAuto.LIMITS.OFF_MS });
  const left = JWAuto.remaining(s, limits);
  let info;
  try {
    info = await api(`/ext/read-queue?linkedin=${left.linkedin}&indeed=${left.indeed}&limit=5`, { settings, timeout: QUEUE_TIMEOUT_MS });
  } catch {
    return later(s, now + JWAuto.LIMITS.OFF_MS); // jobwatch is not running: ask again in a while
  }
  s = { ...s, server: info.limits || null, serverOn: !!info.enabled, queued: Number(info.waiting) || 0 };
  const lim = limitsOf(s); // jobwatch's own limits, from now on (never past the ceilings)
  if (!info.enabled) return later(s, now + JWAuto.LIMITS.OFF_MS);
  const job = JWAuto.pick(info.jobs, s, lim, JWRead.readUrl);
  if (!job) return later(s, now + JWAuto.LIMITS.EMPTY_MS);
  const win = await lastWindow();
  if (!win) return later(s, now + JWAuto.LIMITS.DEFER_MS);
  const url = JWRead.readUrl(job.url);
  const id = JWRead.jobId(JWRead.siteOf(url), url);
  const tab = await chrome.tabs.create({ url, active: false, windowId: win.id });
  s = JWAuto.opened(s, { ...job, id }, tab.id, Date.now(), lim);
  await save(s);
  chrome.alarms.create(WATCH, { when: s.current.startedAt + JWAuto.LIMITS.TAB_MS + 1000 });
}

async function later(s, at) {
  await save({ ...s, nextAt: at });
  schedule(at);
}

/** Best-effort word to jobwatch's Activity tab; a jobwatch that isn't running is not a reason to stop. */
async function report(body) {
  try {
    await api('/ext/read-report', { method: 'POST', body, settings: await getSettings(), timeout: QUEUE_TIMEOUT_MS });
  } catch { /* the Activity entry is a nicety */ }
}

/** A read has ended: the state moves on (a pause, maybe the day's stop), jobwatch hears of what went wrong, the tab closes. */
async function end(s, outcome, { close }) {
  const cur = s.current;
  const next = JWAuto.afterRead(s, outcome, Date.now(), limitsOf(s));
  await save(next);
  schedule(next.nextAt);
  if (cur && close) await chrome.tabs.remove(cur.tabId).catch(() => {});
  if (!cur) return;
  const base = { key: cur.key, site: cur.site, reason: outcome.reason || '' };
  if (outcome.kind === 'no_text' || outcome.kind === 'cancelled') await report({ outcome: outcome.kind, ...base });
  if (outcome.kind === 'trouble') await report({ outcome: 'trouble', ...base, reason: outcome.trouble.why });
  if (next.pausedDay === next.day && s.pausedDay !== s.day) await report({ event: 'paused', site: cur.site, reason: next.pausedReason });
}

// --- what the page being read says ------------------------------------------------------------------------

/** Whether this message comes from the page being read automatically (then read-posting.js's answers are ours). */
export async function owns(sender) {
  if (!sender || !sender.tab) return false;
  if (openTab !== undefined && openTab !== sender.tab.id) return false;
  const s = await load();
  return !!s.current && s.current.tabId === sender.tab.id;
}

/** The page showed its posting: copy it to jobwatch, as Read posting does, then close the tab. */
export function onPosting(msg, sender) {
  return serial(async () => {
    const s = await load();
    const cur = s.current;
    if (!cur || cur.tabId !== sender.tab.id) throw new ApiError('This page is not being read.');
    const url = sender.tab.url || '';
    const site = JWRead.siteOf(url);
    const id = site && JWRead.jobId(site, url);
    const text = String(msg.text || '');
    if (site !== cur.site || (cur.id && id !== cur.id) || text.length < 200) {
      await end(s, { kind: 'no_text', site: cur.site, reason: "the page wasn't the job's posting" }, { close: true });
      throw new ApiError("This page doesn't show the job's posting.");
    }
    const body = { [site]: id, company: msg.company, title: msg.title, text, closed: !!msg.closed, auto: true };
    let r;
    try {
      r = await api('/ext/posting', { method: 'POST', body, settings: await getSettings(), timeout: POSTING_TIMEOUT_MS });
    } catch (e) {
      await end(s, { kind: 'error', site, reason: e.message }, { close: true }); // jobwatch's trouble, not the site's
      throw e;
    }
    await end({ ...s, last: { at: Date.now(), key: cur.key, site } }, { kind: 'read', site }, { close: true });
    return r;
  });
}

/** The page showed no posting: a sign of trouble (a sign-in or security page, HTTP 429/999/403, an account notice) stops
 * the day and leaves the tab open for the person; a page that is only empty counts toward two in a row. */
export function onFailed(msg, sender) {
  return serial(async () => {
    const s = await load();
    const cur = s.current;
    if (!cur || cur.tabId !== sender.tab.id) return {};
    const trouble = JWAuto.troubleFromPage(cur.site, { status: msg.status, wall: msg.wall });
    if (trouble) await end(s, { kind: 'trouble', site: cur.site, trouble }, { close: false });
    else await end(s, { kind: 'no_text', site: cur.site, reason: String(msg.error || 'the page had no posting text') }, { close: true });
    return {};
  });
}

/** The tab's address changed: to a sign-in or security page (trouble, the tab stays), or away from the job (no text). */
export function onTabUpdated(tabId, change, tab) {
  if (openTab !== undefined && openTab !== tabId) return;
  if (!change.url && change.status !== 'complete') return;
  return serial(async () => {
    const s = await load();
    const cur = s.current;
    if (!cur || cur.tabId !== tabId) return;
    const url = (tab && tab.url) || change.url || '';
    const trouble = JWAuto.troubleFromUrl(url);
    if (trouble) return end(s, { kind: 'trouble', site: cur.site, trouble }, { close: false });
    if (change.status === 'complete' && url && !NOT_A_PAGE.test(url) && !JWRead.siteOf(url)) {
      return end(s, { kind: 'no_text', site: cur.site, reason: 'the page went somewhere else' }, { close: true });
    }
  });
}

/** The person closed the page being read: not a sign of trouble, but not a read either. */
export function onTabRemoved(tabId) {
  if (openTab !== undefined && openTab !== tabId) return;
  return serial(async () => {
    const s = await load();
    if (s.current && s.current.tabId === tabId) await end(s, { kind: 'cancelled', site: s.current.site, reason: 'the tab was closed' }, { close: false });
  });
}

// --- the person's controls, and what is shown -----------------------------------------------------------------

/** The status for the popup and the jobwatch page: { paired, state, done, planned, nextAt, reason, buttons }. */
export async function status() {
  const settings = await getSettings();
  if (!settings.token) return { paired: false };
  const s = await load();
  return { paired: true, ...JWAuto.view(s, { limits: limitsOf(s), day: s.day }) };
}

/** pause, resume, off or on (the person pressed it in the popup or on jobwatch's page); the new status. */
export function command(name) {
  return serial(async () => {
    const s = await load();
    const next = JWAuto.command(s, name, Date.now(), limitsOf(s));
    await save(next);
    schedule(next.nextAt);
    await report({ event: { pause: 'paused', resume: 'resumed', off: 'off', on: 'on' }[name] });
    const settings = await getSettings();
    return settings.token ? { paired: true, ...JWAuto.view(next, { limits: limitsOf(next), day: next.day }) } : { paired: false };
  });
}

/** Chrome has just started: the first read waits a pause, as if reading had just been turned on. */
export function startup() {
  return serial(async () => {
    const s = await load();
    await save({ ...s, nextAt: Math.max(s.nextAt, Date.now() + JWAuto.pauseMs(limitsOf(s))) });
  });
}

/** The alarms the worker needs every time it starts. */
export async function ensureAlarms() {
  chrome.idle.setDetectionInterval(JWAuto.LIMITS.IDLE_S);
  if (!(await chrome.alarms.get(TICK))) chrome.alarms.create(TICK, { periodInMinutes: 1 });
}

export function isAutoAlarm(alarm) {
  return alarm.name === TICK || alarm.name === NEXT || alarm.name === WATCH;
}
