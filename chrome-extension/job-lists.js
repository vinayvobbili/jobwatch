/**
 * The jobs on a job site's list page, read from the page the person has open, as records for
 * `jobwatch import-list`: { source, id, title, company, location, pay, posted }. jobwatch never fetches the job
 * site; this runs in the person's own browser, on the list they are looking at. Sites:
 *  - linkedin: "Jobs based on your preferences", "Jobs that match your profile", a search's results. id: the job id.
 *  - indeed: the "Jobs for you" feed on the home page, a search's results (/jobs?q=...). id: the job key (jk).
 *
 * Running this file defines JWList; nothing is read until one of its calls is made:
 *  - JWList.readPage(): the current page (its results scrolled to the end first: cards render as they scroll into
 *    view). JWList.next(): moves to the next page. true: the next page is on screen (LinkedIn swaps it in place);
 *    a link: go there and read again (Indeed loads a new page, which ends this script); false: no next page.
 *  - JWList.readAll({ maxPages: 4 }): every page, while next() stays on this page (LinkedIn), each job once;
 *    JWList.lastRun.nextUrl is the link to go to when a page had to be loaded (Indeed). Paced like a person skimming (PACING): about a minute a page.
 *  - JWList.readList(document): the cards as they are now, with no scrolling
 *    (passive.js uses it while the person browses).
 * The site is told from the page's address; pass { source } to say it.
 *
 * Who runs it:
 *  - The extension's "Read the jobs on this list" button injects this file, then calls readPage and next page by page.
 *  - A Claude session runs this file's text followed by `await JWList.readAll()` through Chrome's javascript tool
 *    on the list's tab (on Indeed: `await JWList.readPage()`, then navigate to `JWList.next()`'s link and run it
 *    again, page by page), and passes the records to `jobwatch import-list` or the MCP tool import_job_list.
 *    `jobwatch import-list --script` prints this file.
 *
 * LinkedIn: each card is a div whose componentkey is "job-card-component-ref-<job id>" (older pages:
 * data-occludable-job-id or data-job-id), in the page twice; the copy with the most lines is read. Its text runs:
 * the title (then the title again, maybe with "(Verified job)"), the company, the place, then the pay when posted
 * ("$120K/yr - $180K/yr"), benefits, connections, how long ago it was posted, Saved or Viewed.
 * Indeed: each card is a div.job_seen_beacon (or the element around a [data-jk] link); the company is in
 * [data-testid="company-name"], the place in [data-testid="text-location"], the pay in a salary snippet. Any of
 * them can be missing.
 */
(function (root) {
  'use strict';

  const VERIFIED = /\s*(?:\((?:verified job|verified)\)|with verification)\s*$/i;
  const PAY = /^\$\s?[\d,.]+\s*[KkMm]?(?:\s*(?:\/\s*|an? |per )(?:yr|year|hr|hour|mo|month|week|day))?(?:\s*(?:[-–—]|to)\s*\$\s?[\d,.]+\s*[KkMm]?(?:\s*(?:\/\s*|an? |per )(?:yr|year|hr|hour|mo|month|week|day))?)?/;
  const POSTED = /\b(\d+\+?\s+(?:second|minute|hour|day|week|month|year)s?\s+ago|just now|just posted|today)\b/i;
  // How a person skims, not how a script scrolls: every wait is a random draw from its [min, max] (ms), so a run of
  // pages doesn't look like a machine on the person's logged-in account. One place for all of it; opts.pacing
  // overrides single entries, opts.sleep / opts.random replace the clock and the dice (tests).
  const PACING = {
    scrollMs: [1500, 4000], // between scroll steps
    stepFrac: [0.6, 0.9], // each step scrolls this share of the visible height
    nextMs: [4000, 9000], // before pressing Next (or opening the next page)
    settleMs: [800, 1600], // after a new page's cards are there
    pollMs: 300, // how often to look for the new page's cards (not a human-visible pause)
  };
  const DEFAULT_MAX_PAGES = 4; // lists are sorted by relevance: later pages matter less
  const STEADY_ROUNDS = 3; // at the bottom with no new card this many times running: the page is all there
  const MAX_SCROLLS = 40;
  const NEXT_WAIT_MS = 15000; // for the next page's cards after Next is pressed

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  /** The clock and dice of one call: its pacing (defaults plus opts.pacing), a sleep, and a draw from [min, max]. */
  function pacer(opts) {
    const pacing = { ...PACING, ...((opts && opts.pacing) || {}) };
    const random = (opts && opts.random) || Math.random;
    return {
      pacing,
      sleep: (opts && opts.sleep) || sleep,
      between: ([lo, hi]) => lo + random() * (hi - lo),
    };
  }
  const squash = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const cleanTitle = (line) => squash(line).replace(VERIFIED, '').trim();
  const linesOf = (text) => String(text || '').split('\n').map(squash).filter((s) => s && s !== '·');
  const textOf = (el) => (el ? squash(el.innerText !== undefined ? el.innerText : el.textContent) : '');

  // --- LinkedIn -------------------------------------------------------------------------------------------------

  const LI_PREFIX = 'job-card-component-ref-';

  /** One LinkedIn card's text as a record, or null when it has no title and company (a card not rendered yet). */
  function parseLinkedIn(text, id) {
    const lines = linesOf(text);
    const title = cleanTitle(lines[0]);
    let i = 1;
    if (lines[i] !== undefined && cleanTitle(lines[i]) === title) i += 1;
    const company = lines[i] || '';
    const location = lines[i + 1] || '';
    const rest = lines.slice(i + 2);
    const payLine = rest.find((l) => PAY.test(l));
    const postedLine = rest.find((l) => POSTED.test(l));
    if (!title || !company) return null;
    return {
      source: 'linkedin', id: String(id || ''), title, company,
      location: PAY.test(location) || POSTED.test(location) ? '' : location,
      pay: payLine ? payLine.match(PAY)[0].trim() : PAY.test(location) ? location.match(PAY)[0].trim() : '',
      posted: postedLine ? postedLine.match(POSTED)[1] : '',
    };
  }

  function linkedinCards(doc) {
    const best = new Map();
    const keep = (id, el) => {
      if (!id) return;
      const old = best.get(id);
      if (!old || linesOf(el.innerText).length > linesOf(old.innerText).length) best.set(id, el);
    };
    for (const el of doc.querySelectorAll(`[componentkey^="${LI_PREFIX}"]`)) {
      const m = el.getAttribute('componentkey').slice(LI_PREFIX.length).match(/\d+/);
      keep(m && m[0], el);
    }
    if (!best.size) {
      for (const el of doc.querySelectorAll('[data-occludable-job-id], [data-job-id]')) {
        keep(el.getAttribute('data-occludable-job-id') || el.getAttribute('data-job-id'), el);
      }
    }
    return [...best];
  }

  // --- Indeed ---------------------------------------------------------------------------------------------------

  function indeedCards(doc) {
    const best = new Map();
    const boxes = new Set();
    for (const el of doc.querySelectorAll('div.job_seen_beacon, [data-jk]')) {
      boxes.add((el.closest && (el.closest('div.job_seen_beacon') || el.closest('li'))) || el);
    }
    for (const box of boxes) {
      const own = box.getAttribute && box.getAttribute('data-jk');
      const link = own ? box : box.querySelector('[data-jk]');
      const id = own || (link && link.getAttribute('data-jk'));
      if (id && !best.has(id)) best.set(id, box);
    }
    return [...best];
  }

  /** One Indeed card as a record, or null when it has no title. */
  function parseIndeed(box, id) {
    const pick = (...sels) => {
      for (const s of sels) {
        const el = box.querySelector(s);
        if (el && textOf(el)) return el;
      }
      return null;
    };
    const titleEl = pick('h2.jobTitle span[title]', 'h2.jobTitle', '[id^="jobTitle-"]', 'a[data-jk] span[title]', 'a[data-jk]', 'h2');
    const title = cleanTitle((titleEl && (titleEl.getAttribute('title') || textOf(titleEl))) || '').replace(/^new\s+/i, '');
    if (!title) return null;
    const payEl = pick('[data-testid="salary-snippet"]', '.salary-snippet-container', '[data-testid="attribute_snippet_testid"]', '.metadata.salary-snippet-container');
    let pay = payEl && PAY.test(textOf(payEl)) ? textOf(payEl).match(PAY)[0] : '';
    if (!pay) {
      const any = [...box.querySelectorAll('div, span, li')].map(textOf).find((t) => PAY.test(t));
      pay = any ? any.match(PAY)[0] : '';
    }
    const postedEl = pick('[data-testid="myJobsStateDate"]', 'span.date', '.date');
    const posted = postedEl && POSTED.test(textOf(postedEl)) ? textOf(postedEl).match(POSTED)[1] : '';
    return {
      source: 'indeed', id: String(id || ''), title,
      company: textOf(pick('[data-testid="company-name"]', '.companyName')),
      location: textOf(pick('[data-testid="text-location"]', '.companyLocation')),
      pay: pay.trim(), posted,
    };
  }

  // --- The site's page ------------------------------------------------------------------------------------------

  const SITES = {
    linkedin: { cards: linkedinCards, parse: (el, id) => parseLinkedIn(el.innerText || '', id), spa: true },
    indeed: { cards: indeedCards, parse: parseIndeed, spa: false },
  };

  function sourceOf(opts) {
    if (opts && opts.source) return opts.source;
    const host = (root.location && root.location.hostname) || '';
    return /(^|\.)indeed\.[a-z.]+$/i.test(host) ? 'indeed' : 'linkedin';
  }

  /** Every job card on the page as it is now, one record per id, in the order they're listed. */
  function readList(doc, opts) {
    const site = SITES[sourceOf(opts)];
    const out = [];
    for (const [id, el] of site.cards(doc || document)) {
      const r = site.parse(el, id);
      if (r) out.push(r);
    }
    return out;
  }

  /** The element that scrolls the results: the cards' nearest scrolling ancestor, else the page. */
  function scroller(doc, opts) {
    const first = SITES[sourceOf(opts)].cards(doc)[0];
    for (let el = first && first[1].parentElement; el && el !== doc.body; el = el.parentElement) {
      const style = getComputedStyle(el);
      if (/(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 10) return el;
    }
    return doc.scrollingElement || doc.documentElement;
  }

  /** Scroll the results to their end, until no more cards render; then read them. */
  async function readPage(opts) {
    const doc = (opts && opts.doc) || document;
    const box = scroller(doc, opts);
    const clock = pacer(opts);
    let steady = 0;
    let seen = -1;
    for (let i = 0; i < MAX_SCROLLS && steady < STEADY_ROUNDS; i += 1) {
      box.scrollTop = Math.min(box.scrollTop + Math.max(box.clientHeight * clock.between(clock.pacing.stepFrac), 300), box.scrollHeight);
      await clock.sleep(clock.between(clock.pacing.scrollMs));
      const n = readList(doc, opts).length;
      const atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 4;
      steady = atEnd && n === seen ? steady + 1 : 0;
      seen = n;
    }
    return readList(doc, opts);
  }

  const usable = (el) => !el.disabled && el.getAttribute('aria-disabled') !== 'true';

  /** The list's Next control, or null: by its test id or label ("Next", "View next page", "Next Page"), else the
   * control for the page after the current one. */
  function findNext(doc) {
    doc = doc || document;
    const byId = doc.querySelector('[data-testid="pagination-page-next"]');
    if (byId) return usable(byId) ? byId : null;
    const controls = [...doc.querySelectorAll('button, a')];
    const label = (el) => squash(el.getAttribute('aria-label'));
    const isNext = (s) => /^(?:view )?next(?: page)?$/i.test(s);
    const next = controls.find((el) => isNext(label(el)) || isNext(textOf(el)));
    if (next) return usable(next) ? next : null;
    const current = [...doc.querySelectorAll('[aria-current="true"], [aria-current="page"]')].find((el) => /^\d+$/.test(textOf(el)));
    if (!current) return null;
    const want = String(Number(textOf(current)) + 1);
    const after = controls.find((el) => textOf(el) === want || new RegExp(`\\bpage ${want}$`, 'i').test(label(el)));
    return after && usable(after) ? after : null;
  }

  /** Move to the next page: true once its cards are on screen (swapped in place), its link when a page has to be
   * loaded (nothing is pressed then), false when there's no next page (or it never came). */
  async function next(opts) {
    const doc = (opts && opts.doc) || document;
    const site = SITES[sourceOf(opts)];
    const button = findNext(doc);
    if (!button) return false;
    const clock = pacer(opts);
    await clock.sleep(clock.between(clock.pacing.nextMs)); // a person looks the page over before turning it
    const href = button.getAttribute('href');
    if (!site.spa && href && !href.startsWith('#') && !/^javascript:/i.test(href)) {
      return new URL(href, root.location ? root.location.href : 'https://example.com/').href;
    }
    const before = new Set(site.cards(doc).map(([id]) => id));
    button.click();
    for (let waited = 0; waited < NEXT_WAIT_MS; waited += clock.pacing.pollMs) {
      await clock.sleep(clock.pacing.pollMs);
      const now = site.cards(doc).map(([id]) => id);
      if (now.length && now.some((id) => !before.has(id))) {
        await clock.sleep(clock.between(clock.pacing.settleMs));
        return true;
      }
    }
    return false;
  }

  /** Every page while they're swapped in place, up to maxPages, each job once. onProgress({ page, jobs }) after
   * each page. lastRun: { pages, jobs, nextUrl: the next page's link, when it has to be loaded }. */
  async function readAll(opts) {
    const { maxPages = DEFAULT_MAX_PAGES, onProgress = null } = opts || {};
    const byId = new Map();
    let page = 0;
    let moved = false;
    for (;;) {
      page += 1;
      for (const r of await readPage(opts)) if (!byId.has(r.id)) byId.set(r.id, r);
      if (onProgress) {
        try {
          onProgress({ page, jobs: byId.size });
        } catch {
          /* a progress listener that went away doesn't stop the reading */
        }
      }
      if (page >= maxPages) break;
      moved = await next(opts);
      if (moved !== true) break;
    }
    api.lastRun = { pages: page, jobs: byId.size, nextUrl: typeof moved === 'string' ? moved : null };
    return [...byId.values()];
  }

  const api = { parseLinkedIn, parseIndeed, readList, readPage, next, readAll, findNext, cleanTitle, sourceOf, PACING, DEFAULT_MAX_PAGES, lastRun: null };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.JWList = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
