/** Toolbar popup: pairing status, and the button that opens the panel in the page. */
const state = document.getElementById('state');
const err = document.getElementById('err');

function say(text, kind) {
  state.textContent = text;
  state.className = kind || '';
}

// The extension works with jobwatch: without it there is nothing to fill from.
async function init() {
  const s = await chrome.runtime.sendMessage({ type: 'status' });
  if (s.paired && s.reachable) return say(`Paired with jobwatch ${s.version}.`, 'good');
  document.getElementById('fill').hidden = true;
  if (!s.paired) say('This needs jobwatch. Run "jobwatch ui", copy the token from its Settings, and paste it in the options.', 'warn');
  else say('jobwatch is not running. Start it with "jobwatch ui", then open this again.', 'warn');
}

document.getElementById('fill').addEventListener('click', async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const r = await chrome.runtime.sendMessage({ type: 'open', tabId: tab.id });
  if (!r.ok) {
    err.textContent = r.error;
    return;
  }
  window.close();
});

document.getElementById('options').addEventListener('click', (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
  window.close();
});

init();
