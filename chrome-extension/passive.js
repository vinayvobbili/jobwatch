/**
 * Passive mode: the job cards that render on a LinkedIn or Indeed list while the person browses it normally, kept
 * in the extension's own storage until they press Import in the side panel. This script never scrolls, clicks or
 * opens anything, and sends nothing anywhere: it reads the cards the page has already drawn (job-lists.js's
 * readList) and hands them to the service worker, which keeps them in chrome.storage.local.
 *
 * Two halves in one classic script:
 *  - JWPassive.merge(store, records): the pure part, tested with node. The store maps "<site>:<job id>" to a
 *    record; a job seen again is kept once (the latest read wins, so a pay that appears later is filled in), and
 *    the store holds at most MAX_KEPT jobs (the oldest go first).
 *  - the content script (runs only where the browser loads it, on LinkedIn and Indeed pages, and only reads when the
 *    address is a list of jobs and the passive toggle is on): watches the page for new cards and reports them.
 */
(function (root) {
  'use strict';

  const MAX_KEPT = 1000;
  const QUIET_MS = 2500; // after the page stops changing, read what's there once
  const KEY = 'passiveSeen'; // chrome.storage.local: { "<site>:<id>": { ...record, seenAt } }
  const ON_KEY = 'passiveOn'; // chrome.storage.local: false turns passive mode off; absent means on

  const keyOf = (r) => `${r.source}:${r.id}`;

  /** The store with `records` added: { store, added } (added: how many were not in it before). Pure; `store` is
   * not changed. Records without a site or job id are skipped. */
  function merge(store, records, now) {
    const out = { ...(store || {}) };
    let added = 0;
    for (const r of records || []) {
      if (!r || !r.source || !r.id) continue;
      const key = keyOf(r);
      if (!(key in out)) added += 1;
      const seenAt = key in out ? out[key].seenAt : now || 0;
      delete out[key]; // re-inserted last: insertion order is the age order
      out[key] = { ...r, seenAt };
    }
    const keys = Object.keys(out);
    for (const key of keys.slice(0, Math.max(0, keys.length - MAX_KEPT))) delete out[key];
    return { store: out, added };
  }

  /** The records in the store, oldest first, as `jobwatch import-list` takes them (without the bookkeeping). */
  function records(store) {
    return Object.values(store || {}).sort((a, b) => (a.seenAt || 0) - (b.seenAt || 0))
      .map(({ seenAt, ...r }) => r); // eslint-disable-line no-unused-vars
  }

  const api = { merge, records, keyOf, KEY, ON_KEY, MAX_KEPT };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.JWPassive = api;

  // --- the content script ---------------------------------------------------------------------------------------

  if (typeof document === 'undefined' || typeof chrome === 'undefined' || !chrome.runtime || !chrome.runtime.id) return;
  if (!root.JW || !root.JWList) return;

  const reported = new Set(); // keys already handed over from this page, so a re-render doesn't repeat them
  let timer = null;

  async function flush() {
    timer = null;
    try {
      const source = root.JW.listMode(location.href);
      if (!source) return;
      const stored = await chrome.storage.local.get(ON_KEY);
      if (stored[ON_KEY] === false) return;
      const fresh = root.JWList.readList(document, { source }).filter((r) => r.id && !reported.has(keyOf(r)));
      if (!fresh.length) return;
      for (const r of fresh) reported.add(keyOf(r));
      await chrome.runtime.sendMessage({ type: 'passiveSeen', records: fresh });
    } catch {
      /* the extension was reloaded under this page, or the page is going away: nothing to do */
    }
  }

  const schedule = () => {
    if (timer === null) timer = setTimeout(flush, QUIET_MS);
  };
  new MutationObserver(schedule).observe(document.documentElement, { childList: true, subtree: true });
  schedule();
})(typeof globalThis !== 'undefined' ? globalThis : this);
