/**
 * Auto-read: the rules for reading LinkedIn and Indeed postings by itself, as pure functions.
 *
 * With "Read postings automatically" on in jobwatch's Settings, the extension opens the job pages jobwatch hands it
 * (GET /ext/read-queue), one at a time, and copies each posting's text to jobwatch, as the Read posting button does.
 * Everything here exists to keep the person's signed-in account from looking automated, so the limits are the defaults
 * and the hard ceilings, and no setting from jobwatch can go past the ceilings (limitsFrom clamps whatever it is told):
 *
 *  - slow: one page at a time, a random pause of 2 to 3 minutes between two (never a fixed interval, never under 60 s),
 *  - small: at most 25 reads a day for each site, and 50 a day for both together, whatever any setting says,
 *  - polite: nothing is read while the person is active on a LinkedIn or Indeed tab,
 *  - careful: the first sign of trouble (a sign-in or security page, HTTP 403/429/999, an account notice, two pages in a
 *    row with no posting) stops the reading for the rest of the day, until the person presses Resume.
 *
 * The state is a plain object kept in chrome.storage.local by auto-reader.js, which does the tabs, alarms and calls;
 * nothing here touches chrome.* or the clock, so tests/test_auto_read.py runs it all with node. A classic script, like
 * logic.js: `JWAuto` is global in the service worker and `module.exports` in node.
 */
(function (root) {
  'use strict';

  const LIMITS = Object.freeze({
    DAILY_DEFAULT: 25,   // reads a day for each site, unless jobwatch says fewer (or more, up to DAILY_MAX)
    DAILY_MAX: 50,       // the hard ceiling for each site...
    TOTAL_MAX: 50,       // ...and for both together, whatever any setting says
    PAUSE_MIN: 120,      // seconds between two reads: a random time from PAUSE_MIN to PAUSE_MAX
    PAUSE_MAX: 180,
    PAUSE_FLOOR: 60,     // no setting pauses less than this
    PAUSE_CEIL: 7200,
    SPREAD: 30,          // the two ends of the pause are at least this far apart: never a fixed interval
    NO_TEXT_STOP: 2,     // pages in a row with no posting text that stop the day
    TAB_MS: 75000,       // a page that has not shown its posting by now counts as one with no text
    DEFER_MS: 30000,     // how long to wait before looking again at whether the person is busy
    EMPTY_MS: 600000,    // how long to wait before asking jobwatch again when nothing is waiting
    OFF_MS: 300000,      // ... and when jobwatch's setting is off
    IDLE_S: 30,          // chrome.idle's detection interval: the person is idle after this many seconds
  });
  const SITES = { linkedin: 'LinkedIn', indeed: 'Indeed' };
  const BLOCKED_STATUS = [403, 429, 999];
  const TRIED_KEPT = 200; // job keys remembered for a day, so one never opens twice

  const clamp = (n, low, high) => Math.min(high, Math.max(low, n));
  const whole = (n, fallback) => (Number.isFinite(Number(n)) && n !== null && n !== '' ? Math.floor(Number(n)) : fallback);

  /** The limits jobwatch's answer asks for, never past the ceilings: { perDay, pauseMin, pauseMax } (seconds). */
  function limitsFrom(info) {
    const l = (info && info.limits) || {};
    const perDay = clamp(whole(l.per_day, LIMITS.DAILY_DEFAULT), 1, LIMITS.DAILY_MAX);
    const pauseMin = clamp(whole(l.pause_min, LIMITS.PAUSE_MIN), LIMITS.PAUSE_FLOOR, LIMITS.PAUSE_CEIL);
    const pauseMax = Math.max(pauseMin + LIMITS.SPREAD, Math.min(whole(l.pause_max, LIMITS.PAUSE_MAX), LIMITS.PAUSE_CEIL));
    return { perDay, pauseMin, pauseMax };
  }

  /** The local calendar day of a Date, "2026-11-28": the day the counters belong to. */
  function localDay(date) {
    const p = (n) => String(n).padStart(2, '0');
    return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}`;
  }

  /** What the state is before anything has been read. `mode` is the person's own switch: on, paused or off. */
  function freshState(day) {
    return {
      day, linkedin: 0, indeed: 0, tried: [], noText: 0, mode: 'on', nextAt: 0, current: null,
      pausedDay: '', pausedKind: '', pausedReason: '', queued: 0, serverOn: null, deferred: false, last: null,
    };
  }

  /** The state on `day`: a new day starts the counters again and clears the day's stop (it "resumes tomorrow"). */
  function rollDay(state, day) {
    if (state.day === day) return state;
    return { ...state, day, linkedin: 0, indeed: 0, tried: [], noText: 0, pausedDay: '', pausedKind: '', pausedReason: '' };
  }

  /** The reads left today: { linkedin, indeed }, each under its own cap and both under the ceiling for the two together. */
  function remaining(state, limits) {
    const room = Math.max(0, LIMITS.TOTAL_MAX - state.linkedin - state.indeed);
    return {
      linkedin: Math.min(Math.max(0, limits.perDay - state.linkedin), room),
      indeed: Math.min(Math.max(0, limits.perDay - state.indeed), room),
    };
  }

  /** The pause before the next read, in ms: uniformly random from pauseMin to pauseMax seconds. `rand` gives [0, 1). */
  function pauseMs(limits, rand = Math.random) {
    return Math.round((limits.pauseMin + rand() * (limits.pauseMax - limits.pauseMin)) * 1000);
  }

  /** The one job to read next from jobwatch's list, or null: the first whose site has reads left today, that was not
   * opened already today and whose address is one the reader may open (`readUrl`: JWRead.readUrl). */
  function pick(jobs, state, limits, readUrl) {
    const left = remaining(state, limits);
    for (const j of Array.isArray(jobs) ? jobs : []) {
      if (j && SITES[j.site] && left[j.site] > 0 && !state.tried.includes(j.key) && readUrl(String(j.url || ''))) return j;
    }
    return null;
  }

  /** Whether the address is on LinkedIn or Indeed (any page of the two), for the not-while-they-are-busy-there rule. */
  function onJobSite(url) {
    let u;
    try { u = new URL(url); } catch { return false; }
    return /(^|\.)(linkedin|indeed)\.com$/i.test(u.hostname);
  }

  /** A trouble from the address a read tab is at, or null: LinkedIn's authwall, login and checkpoint pages and Indeed's
   * sign-in. { kind: 'signin' | 'captcha', why }. A page that is merely somewhere else is not trouble (it has no text). */
  function troubleFromUrl(url) {
    let u;
    try { u = new URL(url); } catch { return null; }
    const host = u.hostname.toLowerCase();
    const path = u.pathname.toLowerCase();
    if (/(^|\.)linkedin\.com$/.test(host)) {
      if (/^\/checkpoint\b/.test(path)) return { kind: 'captcha', why: 'LinkedIn showed a security check' };
      if (/^\/(?:authwall|login|uas\/|signup|m\/login)/.test(path)) return { kind: 'signin', why: 'LinkedIn asked for a sign-in' };
    }
    if (/(^|\.)indeed\.com$/.test(host) && (host.startsWith('secure.') || /^\/(?:account\/login|auth)/.test(path))) {
      return { kind: 'signin', why: 'Indeed asked for a sign-in' };
    }
    return null;
  }

  const WALL_WHY = {
    signin: (site) => `${site} asked for a sign-in`,
    captcha: (site) => `${site} showed a security check`,
    restricted: (site) => `${site} showed an account notice (unusual activity or a restriction)`,
    blocked: (site) => `${site} said too many requests or refused access`,
  };

  /** A trouble from what the page's script saw ({ status, wall }), or null when it is only a page with no text:
   * { kind: 'blocked' | 'signin' | 'captcha' | 'restricted', why }. */
  function troubleFromPage(site, seen) {
    const name = SITES[site] || 'The site';
    const status = Number(seen && seen.status) || 0;
    if (BLOCKED_STATUS.includes(status)) return { kind: 'blocked', why: `${name} refused the page (HTTP ${status})` };
    const wall = seen && seen.wall;
    if (WALL_WHY[wall]) return { kind: wall, why: WALL_WHY[wall](name) };
    return null;
  }

  /** The words for a stop, as the popup, the jobwatch page and the Activity tab show them. */
  function stopText(why, site) {
    return `Auto-read paused: ${why}. Resumes tomorrow, or press Resume after you check ${SITES[site] || 'the site'}.`;
  }

  function stopped(state, trouble, site) {
    return { ...state, pausedDay: state.day, pausedKind: trouble.kind, pausedReason: stopText(trouble.why, site) };
  }

  /**
   * The state after a read ended: { kind: 'read' | 'no_text' | 'trouble' | 'cancelled' | 'error', site, trouble? }.
   * The next read waits a fresh random pause whatever happened. Trouble stops the day; so do two pages in a row with no
   * posting text (a read, or a page that could not be reached, in between starts the count again).
   */
  function afterRead(state, outcome, now, limits, rand = Math.random) {
    let next = { ...state, current: null, nextAt: now + pauseMs(limits, rand), deferred: false };
    if (outcome.kind === 'read') return { ...next, noText: 0 };
    if (outcome.kind === 'trouble') return stopped(next, outcome.trouble, outcome.site);
    if (outcome.kind === 'no_text') {
      next = { ...next, noText: state.noText + 1 };
      if (next.noText >= LIMITS.NO_TEXT_STOP) {
        return stopped(next, { kind: 'no_text', why: `${LIMITS.NO_TEXT_STOP} pages in a row had no posting text` }, outcome.site);
      }
    }
    return next;
  }

  /** The state after a page was opened to be read: it counts against today's caps from this moment, whatever comes of it. */
  function opened(state, job, tabId, now, limits, rand = Math.random) {
    return {
      ...state, [job.site]: state[job.site] + 1, tried: [...state.tried, job.key].slice(-TRIED_KEPT),
      queued: Math.max(0, (state.queued || 0) - 1), // this one is no longer waiting
      current: { tabId, key: job.key, site: job.site, id: job.id || '', startedAt: now },
      // a provisional wait, in case this worker is stopped before the page answers
      nextAt: now + LIMITS.TAB_MS + pauseMs(limits, rand), deferred: false,
    };
  }

  /**
   * What to do now: { action }, one of
   *   off, paused, stopped   the person's switch, or the day's stop: nothing is read, nothing is asked of jobwatch
   *   busy                   a page is being read: never two at once
   *   stale                  the page being read has taken too long: end it as one with no text
   *   capped                 today's caps are used up
   *   wait (until)           the pause between two reads has not passed
   *   defer (until)          the person is active on LinkedIn or Indeed (or there is no window): look again soon
   *   read                   ask jobwatch for the next job and open it
   * ctx: { now, day, limits, active: { onSite, idle }, haveWindow }.
   */
  function decide(state, ctx) {
    if (state.mode === 'off') return { action: 'off' };
    if (state.mode === 'paused') return { action: 'paused' };
    if (state.pausedDay === ctx.day) return { action: 'stopped' };
    if (state.current) return { action: ctx.now - state.current.startedAt < LIMITS.TAB_MS ? 'busy' : 'stale' };
    const left = remaining(state, ctx.limits);
    if (left.linkedin <= 0 && left.indeed <= 0) return { action: 'capped' };
    if (state.nextAt > ctx.now) return { action: 'wait', until: state.nextAt };
    const active = ctx.active || {};
    if (active.onSite && active.idle === 'active') return { action: 'defer', until: ctx.now + LIMITS.DEFER_MS, why: 'busy' };
    if (ctx.haveWindow === false) return { action: 'defer', until: ctx.now + LIMITS.DEFER_MS, why: 'no window' };
    return { action: 'read' };
  }

  /** The person's own commands: pause, resume (also clears the day's stop), off, on. Resume and on wait a fresh pause. */
  function command(state, name, now, limits, rand = Math.random) {
    const again = { ...state, nextAt: now + pauseMs(limits, rand), deferred: false };
    switch (name) {
      case 'pause': return { ...state, mode: 'paused' };
      case 'off': return { ...state, mode: 'off' };
      case 'resume': return { ...again, mode: 'on', pausedDay: '', pausedKind: '', pausedReason: '', noText: 0 };
      case 'on': return { ...again, mode: 'on' };
      default: throw new Error(`unknown command ${name}`);
    }
  }

  /** What the popup and the jobwatch page show: { state, done, planned, nextAt, reason, buttons }.
   * state: disabled (jobwatch's setting is off), off, paused, stopped, capped, reading, deferred, empty or waiting. */
  function view(state, ctx) {
    const done = state.linkedin + state.indeed;
    const left = remaining(state, ctx.limits);
    const planned = done + Math.min(state.queued || 0, left.linkedin + left.indeed);
    let name;
    if (state.mode === 'off') name = 'off';
    else if (state.mode === 'paused') name = 'paused';
    else if (state.serverOn === false) name = 'disabled';
    else if (state.pausedDay === ctx.day) name = 'stopped';
    else if (state.current) name = 'reading';
    else if (left.linkedin <= 0 && left.indeed <= 0) name = 'capped';
    else if (state.deferred) name = 'deferred';
    else if (state.serverOn && !state.queued) name = 'empty';
    else name = 'waiting';
    const buttons = { off: ['on'], paused: ['resume', 'off'], stopped: ['resume', 'off'], disabled: [] }[name] || ['pause', 'off'];
    return { state: name, done, planned, nextAt: state.nextAt, reason: name === 'stopped' ? state.pausedReason : '', buttons };
  }

  /** "2m" or "45s": how long until `ms` from now has passed. */
  function countdown(ms) {
    const s = Math.max(1, Math.ceil(ms / 1000));
    return s < 60 ? `${s}s` : `${Math.ceil(s / 60)}m`;
  }

  /** The status in a line: "Reading postings: 3 of 12 today · next in 2m". The jobwatch page words it the same way
   * (autoReadLine in its script; tests/test_auto_read.py holds the two to the same text). */
  function statusLine(v, now) {
    if (v.state === 'off') return 'Auto-read is off in this browser.';
    if (v.state === 'paused') return 'Reading postings is paused. Press Resume to continue.';
    if (v.state === 'disabled') return "Reading postings is off in jobwatch's Settings.";
    if (v.state === 'stopped') return v.reason;
    const head = `Reading postings: ${v.planned > v.done ? `${v.done} of ${v.planned} today` : `${v.done} today`}`;
    const tail = {
      capped: 'done for today, back tomorrow', reading: 'reading one now',
      deferred: 'waiting until you leave LinkedIn or Indeed', empty: 'nothing waiting',
    }[v.state] || `next in ${countdown(Math.max(0, v.nextAt - now))}`;
    return `${head} · ${tail}`;
  }

  const api = {
    LIMITS, SITES, limitsFrom, localDay, freshState, rollDay, remaining, pauseMs, pick, onJobSite, troubleFromUrl,
    troubleFromPage, stopText, afterRead, opened, decide, command, view, countdown, statusLine,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.JWAuto = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
