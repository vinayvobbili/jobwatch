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
 * The bridge marks the page (<html data-jobwatch-bridge="1">) so the page knows, without waiting, whether to ask.
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

  const api = { REQUEST, DONE, doneMessage };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.JWBridge = api;

  if (typeof document === 'undefined' || typeof chrome === 'undefined' || !chrome.runtime || !chrome.runtime.id) return;

  const mark = () => { document.documentElement.dataset.jobwatchBridge = '1'; };
  if (document.documentElement) mark(); else document.addEventListener('readystatechange', mark, { once: true });
  const tell = (result) => window.postMessage(doneMessage(result), location.origin);

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

  // The service worker tells the page how the read went: done (the posting is saved) or why not.
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg && msg.type === 'readPostingDone') tell(msg.result);
  });
})(typeof globalThis !== 'undefined' ? globalThis : this);
