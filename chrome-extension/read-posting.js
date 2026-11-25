/**
 * Read posting: the description of a LinkedIn or Indeed job page, for a job jobwatch has from an alert with nothing but
 * its title. jobwatch can't fetch those pages (they need the person's sign-in); this reads the one the person has open.
 *
 * It runs only on a page jobwatch's own Read posting button opened: the address ends in #jobwatch-read, which only that
 * button adds. On any other page of the two sites this script does nothing. It reads the job's description (not the
 * page's menus, "more jobs" or the rest of the page), hands it to the service worker, which gives it to the person's
 * own jobwatch, says so in a small banner, and closes the tab it was opened in.
 *
 * Two halves in one classic script, as passive.js has:
 *  - JWRead.postingFromText / readPage: the pure part, tested with node (tests/test_read_posting.py). The same markers
 *    as jobwatch/filltext.py's posting_from_page, which reads a page's text the same way.
 *  - the content script (runs only where the browser loads it, on #jobwatch-read pages).
 */
(function (root) {
  'use strict';

  const HASH = '#jobwatch-read';
  const MIN_TEXT = 200; // a description shorter than this is not a posting
  const WAIT_MS = 20000; // for the page to draw the description
  const POLL_MS = 500;
  const CLOSE_MS = 2500; // the banner is on screen this long before the tab closes
  const CLOSE_CLOSED_MS = 6000; // ... and this long when the posting is closed

  const LINKEDIN_START = /^About the job\s*$/m;
  const LINKEDIN_END = /^(?:[….]{1,3}\s*more|Benefits found in job post|Set alert for similar jobs|Show more|About the company|More jobs)\s*$/m;
  const INDEED_START = /^Full job description\s*$/m;
  const INDEED_END = /^(?:Report job|Hiring Lab|Career advice)\s*$/m;
  // The banner line saying the posting is closed (LinkedIn's red line under the title, Indeed's expired notice), on a line
  // of its own; a stray space, icon text or a closing dot around it doesn't hide it. Same as jobwatch/filltext.py's _CLOSED.
  const CLOSED = /^[^\w\n]*(?:Not currently accepting applications|No longer accepting applications|This job (?:has expired(?: on Indeed)?|is no longer available))[^\w\n]*$/im;
  const WALLS = [
    [/verify you are (?:a )?human|are you a robot|captcha|security check|just a moment|additional verification required/i, 'it shows a captcha or a security check'],
    [/\b(?:sign in|log in|join now|authwall)\b/i, 'it asks to sign in'],
  ];

  /** 'linkedin' or 'indeed' for the address of one job there, else ''. */
  function siteOf(url) {
    let u;
    try { u = new URL(url); } catch { return ''; }
    const host = u.hostname.toLowerCase();
    if (/(^|\.)linkedin\.com$/.test(host) && /^\/jobs\/view\//.test(u.pathname)) return 'linkedin';
    if (/(^|\.)indeed\.com$/.test(host) && /^\/(?:m\/)?(?:viewjob|rc\/clk)/.test(u.pathname)) return 'indeed';
    return '';
  }

  /** The site's own number for the job: LinkedIn's id from /jobs/view/<id>, Indeed's key from ?jk=<key>. */
  function jobId(site, url) {
    let u;
    try { u = new URL(url); } catch { return ''; }
    if (site === 'linkedin') {
      const m = u.pathname.match(/\/jobs\/view\/(?:[\w%-]*-)?(\d{6,})/);
      return m ? m[1] : '';
    }
    const jk = u.searchParams.get('jk') || '';
    return /^[0-9a-f]{8,}$/i.test(jk) ? jk : '';
  }

  /** The description in a page's text: { text, closed }, or { error: 'why' } when the page has none (a sign-in wall, a
   * captcha, or not the posting). `closed`: LinkedIn says it is not taking applications any more. */
  function postingFromText(site, pageText) {
    const [start, end] = site === 'linkedin' ? [LINKEDIN_START, LINKEDIN_END] : [INDEED_START, INDEED_END];
    const s = start.exec(pageText);
    if (s) {
      const rest = pageText.slice(s.index + s[0].length);
      const e = end.exec(rest);
      const text = (e ? rest.slice(0, e.index) : rest).trim();
      if (text.length >= MIN_TEXT) return { text, closed: CLOSED.test(pageText.slice(0, s.index)) };
    }
    for (const [pattern, why] of WALLS) {
      if (pattern.test(pageText.slice(0, 3000))) return { error: `the page doesn't show the posting: ${why}` };
    }
    return { error: "the page has no posting text on it (is it the job's own page?)" };
  }

  const textOf = (el) => (el ? String(el.innerText || el.textContent || '').trim() : '');

  /** What this page says about the job: { site, id, title, company, text, closed } or { error }. `doc` is the page's
   * document (anything with body.innerText and querySelector, in tests), `url` its address. */
  function readPage(doc, url) {
    const site = siteOf(url);
    if (!site) return { error: "this isn't a LinkedIn or Indeed job page" };
    const id = jobId(site, url);
    if (!id) return { error: "couldn't tell which job this is from its address" };
    // Indeed keeps the description in one element; LinkedIn's class names change, so its text is cut by its headings.
    const own = site === 'indeed' ? textOf(doc.querySelector('#jobDescriptionText')) : '';
    const page = String((doc.body && doc.body.innerText) || '');
    const read = own.length >= MIN_TEXT ? { text: own, closed: CLOSED.test(page.replace(own, '')) } : postingFromText(site, page);
    if (read.error) return { error: read.error };
    const title = textOf(doc.querySelector('h1')).split('\n')[0];
    const company = textOf(doc.querySelector(site === 'indeed'
      ? '[data-testid="inlineHeader-companyName"], [data-company-name="true"]'
      : '.job-details-jobs-unified-top-card__company-name, .jobs-unified-top-card__company-name, a[href*="/company/"]')).split('\n')[0];
    return { site, id, title, company, text: read.text, closed: read.closed };
  }

  const api = { siteOf, jobId, postingFromText, readPage, HASH };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.JWRead = api;

  // --- the content script ---------------------------------------------------------------------------------------

  if (typeof document === 'undefined' || typeof location === 'undefined' || typeof chrome === 'undefined' || !chrome.runtime || !chrome.runtime.id) return;
  if (location.hash !== HASH) return; // a page jobwatch's Read posting button didn't open: read nothing

  function banner(text, ok) {
    let el = document.getElementById('jobwatch-read-banner');
    if (!el) {
      el = document.createElement('div');
      el.id = 'jobwatch-read-banner';
      el.setAttribute('role', 'status');
      el.style.cssText = 'position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:2147483647;max-width:520px;' +
        'padding:10px 16px;border-radius:10px;font:600 14px/1.4 system-ui,sans-serif;color:#fff;box-shadow:0 6px 24px rgba(0,0,0,.3)';
      document.documentElement.appendChild(el);
    }
    el.style.background = ok ? '#1f8f5f' : '#b45309';
    el.textContent = `jobwatch: ${text}`;
  }

  async function run() {
    banner('reading this posting…', true);
    const until = Date.now() + WAIT_MS;
    let read = readPage(document, location.href);
    while (read.error && Date.now() < until && /no posting text/.test(read.error)) {
      await new Promise((r) => setTimeout(r, POLL_MS)); // the page draws the description after it loads
      read = readPage(document, location.href);
    }
    if (read.error) return banner(`${read.error}. Sign in to the site in this tab if needed, then press Read posting again.`, false);
    try { history.replaceState(null, '', location.pathname + location.search); } catch { /* the page is going away */ }
    let r;
    try {
      r = await chrome.runtime.sendMessage({ type: 'readPosting', site: read.site, id: read.id, title: read.title, company: read.company, text: read.text, closed: read.closed, url: location.href });
    } catch (e) {
      return banner(`couldn't reach the extension: ${e.message}`, false);
    }
    if (!r || !r.ok) return banner((r && r.error) || 'jobwatch did not answer', false);
    // A closed posting is said in amber and stays on screen longer: it is the thing the person most needs to see.
    banner(r.said || 'posting saved', !(r.closed || read.closed));
    setTimeout(() => window.close(), r.closed || read.closed ? CLOSE_CLOSED_MS : CLOSE_MS);
  }
  run();
})(typeof globalThis !== 'undefined' ? globalThis : this);
