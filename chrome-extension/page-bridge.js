/**
 * The bridge between jobwatch's own page (on this computer) and the extension, for one thing: Read posting.
 *
 * A page can only open a tab in front of the person, which takes them away from the card they are looking at. So the
 * jobwatch page asks, with a window message, and the extension opens the LinkedIn or Indeed posting in a background tab,
 * reads it there and tells the page when it is done, so the page updates just that card. This script is the page's end of
 * that: it runs on local addresses only (localhost, *.localhost, 127.0.0.1), passes the request on and the answer back,
 * and reads nothing from the page but the request. The service worker decides whether the page is the person's own
 * jobwatch (the address and port the extension is paired with); on any other local page it refuses.
 *
 * Messages (window.postMessage, same page only):
 *   page -> bridge   { type: 'jobwatch:read-posting', key, url }
 *   bridge -> page   { type: 'jobwatch:read-posting-done', key, ok, said?, closed?, has_text?, error? }
 *   page -> bridge   { type: 'jobwatch:auto-read', command: 'status' | 'pause' | 'resume' | 'off' | 'on' }
 *   bridge -> page   { type: 'jobwatch:auto-read-status', status: { state, done, planned, nextAt, reason, buttons } | null }
 * (the last two: reading postings by itself, see auto-reader.js; the page shows its status and the buttons)
 * The bridge marks the page (<html data-jobwatch-bridge="1">) so the page knows, without waiting, whether to ask, and
 * then asks the service worker what it can do (a `ping`) and writes the answer to <html data-jobwatch-caps="...">, a
 * space-separated list ("readInBackground"; empty for a service worker that does not know `ping`, which is an older
 * extension). The attribute is absent until the answer comes. The page is built to work with every extension version:
 * it reads in the background only when the capability is there, and otherwise opens the posting in front as before.
 */
(function (root) {
  'use strict';

  const REQUEST = 'jobwatch:read-posting';
  const DONE = 'jobwatch:read-posting-done';

  /** The message the page gets for an answer: only the fields the page uses, whatever the service worker sent. */
  function doneMessage(result) {
    const r = result || {};
    const out = { type: DONE, key: String(r.key || ''), ok: r.ok !== false && !r.error };
    for (const f of ['said', 'error']) if (typeof r[f] === 'string') out[f] = r[f];
    for (const f of ['closed', 'has_text']) if (typeof r[f] === 'boolean') out[f] = r[f];
    return out;
  }

  /** The capabilities in the service worker's answer to `ping`, as the attribute's text: an extension that predates
   * `ping` answers "unknown message" (ok: false) or nothing, which is no capabilities. */
  function capsText(answer) {
    const caps = answer && answer.ok !== false && Array.isArray(answer.capabilities) ? answer.capabilities : [];
    return caps.filter((c) => typeof c === 'string' && /^\w+$/.test(c)).join(' ');
  }

  // Automatic reading (auto-reader.js): the page asks for the status, or presses Pause, Resume, Off or On, and gets the
  // status back. Only these fields cross, whatever the service worker sent.
  const AUTO_REQUEST = 'jobwatch:auto-read';
  const AUTO_STATUS = 'jobwatch:auto-read-status';
  const AUTO_COMMANDS = ['status', 'pause', 'resume', 'off', 'on'];
  const AUTO_BUTTONS = ['pause', 'resume', 'off', 'on'];

  function statusMessage(answer) {
    const a = answer && answer.ok !== false && answer.paired ? answer : null;
    if (!a) return { type: AUTO_STATUS, status: null };
    const num = (n) => (Number.isFinite(Number(n)) ? Number(n) : 0);
    return {
      type: AUTO_STATUS,
      status: {
        state: /^\w+$/.test(String(a.state)) ? String(a.state) : '', done: num(a.done), planned: num(a.planned), nextAt: num(a.nextAt),
        reason: typeof a.reason === 'string' ? a.reason.slice(0, 300) : '',
        buttons: (Array.isArray(a.buttons) ? a.buttons : []).filter((b) => AUTO_BUTTONS.includes(b)),
      },
    };
  }

  const api = { REQUEST, DONE, doneMessage, capsText, AUTO_REQUEST, AUTO_STATUS, AUTO_COMMANDS, statusMessage };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.JWBridge = api;

  if (typeof document === 'undefined' || typeof chrome === 'undefined' || !chrome.runtime || !chrome.runtime.id) return;

  const mark = () => { document.documentElement.dataset.jobwatchBridge = '1'; };
  if (document.documentElement) mark(); else document.addEventListener('readystatechange', mark, { once: true });
  const tell = (result) => window.postMessage(doneMessage(result), location.origin);

  // What this extension can do: asked once, as soon as the page loads (the page may be built before it is answered)
  const setCaps = (answer) => { document.documentElement.dataset.jobwatchCaps = capsText(answer); };
  chrome.runtime.sendMessage({ type: 'ping' }).then(setCaps, () => setCaps(null));

  window.addEventListener('message', async (e) => {
    if (e.source !== window || !e.data || e.data.type !== REQUEST) return;
    const key = String(e.data.key || '');
    try {
      const r = await chrome.runtime.sendMessage({ type: 'readInBackground', key, url: String(e.data.url || '') });
      if (!r || !r.ok) tell({ key, ok: false, error: (r && r.error) || 'the extension did not answer' });
    } catch (err) {
      tell({ key, ok: false, error: `couldn't reach the extension: ${err.message}` });
    }
  });

  window.addEventListener('message', async (e) => {
    if (e.source !== window || !e.data || e.data.type !== AUTO_REQUEST || !AUTO_COMMANDS.includes(e.data.command)) return;
    let r = null;
    try {
      r = await chrome.runtime.sendMessage(e.data.command === 'status' ? { type: 'autoReadStatus' } : { type: 'autoReadCommand', command: e.data.command });
    } catch { /* the extension went away: no status */ }
    window.postMessage(statusMessage(r), location.origin);
  });

  // The service worker tells the page how the read went: done (the posting is saved) or why not.
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg && msg.type === 'readPostingDone') tell(msg.result);
  });
})(typeof globalThis !== 'undefined' ? globalThis : this);
