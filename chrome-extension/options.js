/** Options page: the pairing with jobwatch (server address and token), and the page's look. */
import { getSettings } from './lib.js';

const result = document.getElementById('result');
const root = document.documentElement;

function say(text, ok) {
  result.textContent = text;
  result.className = ok ? 'ok' : 'bad';
}

// Theme (System first) and Width, remembered in the browser

function look(name, fallback) {
  try {
    return localStorage.getItem(name) || fallback;
  } catch {
    return fallback;
  }
}

for (const [id, attr, fallback] of [['theme', 'data-theme', 'system'], ['width', 'data-width', 'standard']]) {
  const select = document.getElementById(id);
  const apply = (v) => (v === fallback ? root.removeAttribute(attr) : root.setAttribute(attr, v));
  select.value = look(id, fallback);
  apply(select.value);
  select.addEventListener('change', () => {
    apply(select.value);
    try {
      localStorage.setItem(id, select.value);
    } catch {
      /* private window: the choice just isn't remembered */
    }
  });
}

const server = document.getElementById('serverUrl');
const token = document.getElementById('token');

async function save() {
  await chrome.storage.local.set({ settings: { serverUrl: server.value.trim(), token: token.value.trim() } });
  return getSettings();
}

document.getElementById('form').addEventListener('submit', async (e) => {
  e.preventDefault();
  say('Checking...', true);
  const settings = await save();
  const r = await chrome.runtime.sendMessage({ type: 'test', settings });
  say(r.ok ? `Saved. Connected to jobwatch ${r.version}.` : `Saved, but ${r.error}`, r.ok);
});

document.getElementById('test').addEventListener('click', async () => {
  say('Checking...', true);
  const settings = await save();
  const r = await chrome.runtime.sendMessage({ type: 'test', settings });
  say(r.ok ? `Connected to jobwatch ${r.version}.` : r.error, r.ok);
});

getSettings().then((s) => {
  server.value = s.serverUrl;
  token.value = s.token;
});
