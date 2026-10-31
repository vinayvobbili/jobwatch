/**
 * Settings and server calls shared by the service worker and the options page.
 *
 * The pairing (server address and token) lives in chrome.storage.local, so it is not synced to a Google
 * account. The only server the extension talks to is the jobwatch one on this computer.
 */

export const DEFAULTS = Object.freeze({ serverUrl: 'http://127.0.0.1:8765', token: '' });

const TIMEOUT_MS = 20_000;
const DRAFT_TIMEOUT_MS = 120_000;

export async function getSettings() {
  const { settings } = await chrome.storage.local.get('settings');
  const s = { ...DEFAULTS, ...(settings || {}) };
  s.serverUrl = String(s.serverUrl).trim().replace(/\/+$/, '') || DEFAULTS.serverUrl;
  s.token = String(s.token || '').trim();
  return s;
}

/** An error whose message is safe to show a non-technical person as-is. */
export class ApiError extends Error {}

/**
 * Call jobwatch. Resolves with parsed JSON (or the ArrayBuffer and its headers when `raw`);
 * rejects with an ApiError that says what went wrong in plain words.
 */
export async function api(path, { method = 'GET', body, settings, raw = false, timeout } = {}) {
  const cfg = settings || (await getSettings());
  const headers = { Accept: raw ? '*/*' : 'application/json', 'X-Jobwatch-Extension': cfg.token };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout || (path.startsWith('/ext/draft') ? DRAFT_TIMEOUT_MS : TIMEOUT_MS));
  let res;
  try {
    res = await fetch(cfg.serverUrl + path, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal,
    });
  } catch (err) {
    if (err.name === 'AbortError') throw new ApiError('jobwatch took too long to answer.');
    throw new ApiError(`Can't reach jobwatch at ${cfg.serverUrl}. Is "jobwatch ui" running?`);
  } finally {
    clearTimeout(timer);
  }
  if (res.ok && raw) return { bytes: await res.arrayBuffer(), type: res.headers.get('Content-Type') || '', disposition: res.headers.get('Content-Disposition') || '' };
  let data = null;
  try {
    data = await res.json();
  } catch {
    /* not JSON; handled below */
  }
  if (!res.ok) {
    if (res.status === 403) throw new ApiError('jobwatch did not accept the token. Copy it again from Settings in jobwatch.');
    throw new ApiError((data && data.error) || `jobwatch answered with an error (HTTP ${res.status}).`);
  }
  return data;
}

export function toBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}
