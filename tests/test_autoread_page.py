"""Reading postings by itself, on jobwatch's page: the status chip on Today with Pause, Resume and Off (it asks the
extension through the page bridge; here a stand-in answers), the Settings card (off at first, the limits in plain words and
the account-risk note), and the words the page and the extension use for the same status. Every job and company is made
up. The browser tests are skipped where Playwright or its Chromium isn't installed."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from jobwatch import config

from .test_page_js import page_function
from .test_read_posting_page import alert_jobs, browser, sync_api  # noqa: F401  (fixtures)

EXT = Path(__file__).resolve().parent.parent / "chrome-extension"
needs_node = pytest.mark.skipif(not shutil.which("node"), reason="needs node")

# The extension's page bridge and service worker, as a stand-in: it marks the page, says what the extension can do, and
# answers 'jobwatch:auto-read' with the status in window.autoStatus (a command changes it the way the extension would)
BRIDGE = """
const mark = () => { document.documentElement.dataset.jobwatchBridge = '1'; document.documentElement.dataset.jobwatchCaps = 'readInBackground autoRead'; };
if (document.documentElement) mark(); else document.addEventListener('readystatechange', mark, { once: true });
window.autoCommands = [];
window.autoStatus = %s;
const NEXT = { pause: { state: 'paused', buttons: ['resume', 'off'] }, resume: { state: 'waiting', buttons: ['pause', 'off'] }, off: { state: 'off', buttons: ['on'] }, on: { state: 'waiting', buttons: ['pause', 'off'] } };
window.addEventListener('message', (e) => {
  if (e.source !== window || !e.data || e.data.type !== 'jobwatch:auto-read') return;
  window.autoCommands.push(e.data.command);
  if (NEXT[e.data.command]) window.autoStatus = { ...window.autoStatus, ...NEXT[e.data.command] };
  window.postMessage({ type: 'jobwatch:auto-read-status', status: window.autoStatus }, location.origin);
});
"""
WAITING = '{ state: "waiting", done: 3, planned: 12, nextAt: Date.now() + 119000, reason: "", buttons: ["pause", "off"] }'
STOPPED = ('{ state: "stopped", done: 4, planned: 12, nextAt: 0, buttons: ["resume", "off"], '
           'reason: "Auto-read paused: LinkedIn asked for a sign-in. Resumes tomorrow, or press Resume after you check LinkedIn." }')
DISABLED = '{ state: "disabled", done: 0, planned: 0, nextAt: 0, reason: "", buttons: [] }'


def open_today(browser, server, status: str | None):
    page = browser.new_page(viewport={"width": 1100, "height": 700})
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    if status:
        page.add_init_script(BRIDGE % status)
    page.goto(f"http://127.0.0.1:{server}/#today")
    page.wait_for_load_state("networkidle")
    return page


def test_today_shows_how_far_reading_has_got_and_when_the_next_read_is(browser, server, alert_jobs):
    page = open_today(browser, server, WAITING)
    try:
        chip = page.locator("#autoread")
        sync_api.expect(chip).to_be_visible()
        sync_api.expect(chip).to_contain_text("Reading postings: 3 of 12 today · next in 2m")
        assert chip.get_attribute("data-state") == "waiting"
        assert [b.inner_text() for b in chip.locator("button").all()] == ["Pause", "Off"]
        assert page.errors == []
    finally:
        page.close()


def test_pause_resume_and_off_go_to_the_extension_and_the_chip_follows_its_answer(browser, server, alert_jobs):
    page = open_today(browser, server, WAITING)
    try:
        chip = page.locator("#autoread")
        chip.locator("button", has_text="Pause").click()
        sync_api.expect(chip).to_contain_text("Reading postings is paused. Press Resume to continue.")
        assert [b.inner_text() for b in chip.locator("button").all()] == ["Resume", "Off"]
        chip.locator("button", has_text="Resume").click()
        sync_api.expect(chip).to_contain_text("Reading postings: 3 of 12 today")
        chip.locator("button", has_text="Off").click()
        sync_api.expect(chip).to_contain_text("Auto-read is off in this browser.")
        assert [b.inner_text() for b in chip.locator("button").all()] == ["Turn on"]
        assert page.evaluate("() => window.autoCommands").count("status") >= 1
        assert [c for c in page.evaluate("() => window.autoCommands") if c != "status"] == ["pause", "resume", "off"]
        assert page.errors == []
    finally:
        page.close()


def test_a_stop_for_the_day_is_said_in_amber_with_why_and_the_way_back(browser, server, alert_jobs):
    page = open_today(browser, server, STOPPED)
    try:
        chip = page.locator("#autoread")
        sync_api.expect(chip).to_contain_text("Auto-read paused: LinkedIn asked for a sign-in. Resumes tomorrow, or press Resume after you check LinkedIn.")
        assert chip.get_attribute("data-state") == "stopped"
        assert [b.inner_text() for b in chip.locator("button").all()] == ["Resume", "Off"]
    finally:
        page.close()


def test_no_chip_without_the_extension_or_when_jobwatchs_setting_is_off(browser, server, alert_jobs):
    for status in (None, DISABLED):
        page = open_today(browser, server, status)
        try:
            page.wait_for_timeout(300)
            assert page.locator("#autoread").count() == 1 and not page.locator("#autoread").is_visible()
        finally:
            page.close()


def test_settings_offers_it_off_with_the_limits_in_plain_words_and_the_risk_note(browser, server, alert_jobs):
    page = browser.new_page(viewport={"width": 1100, "height": 900})
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    try:
        page.goto(f"http://127.0.0.1:{server}/#settings/apply")
        card = page.locator("#set-autoread")
        sync_api.expect(card).to_be_visible()
        assert not card.locator("input[type=checkbox]").is_checked()  # off at first: a new user opts in
        text = card.inner_text()
        assert "LinkedIn may restrict accounts that look automated. These limits keep reading slow and small; you can turn it off anytime." in text
        assert "a random 2 to 3 minutes apart" in text and "At most 25 a day for each site" in text and "never more than 50 a day in all" in text
        assert "at the first sign of trouble" in text
        card.locator("input[type=number]").first.fill("10")
        sync_api.expect(card.locator("#autoread-words")).to_contain_text("At most 10 a day for each site")
        assert page.errors == []
    finally:
        page.close()


def test_saving_the_card_writes_the_setting_and_a_ceiling_is_refused(server, watchlist, alert_jobs):
    from .conftest import TOKEN, request
    status, _ = request(server, "POST", "/api/settings", {"autoread": {"enabled": True, "per_day": 10}}, headers={"X-Jobwatch-Token": TOKEN})
    assert status == 200
    saved = yaml.safe_load(watchlist.read_text())["autoread"]
    assert saved == {"enabled": True, "per_day": 10} and config.load(watchlist).autoread.enabled is True
    status, data = request(server, "POST", "/api/settings", {"autoread": {"enabled": True, "per_day": 80}}, headers={"X-Jobwatch-Token": TOKEN})
    assert status == 400 and "per_day must be a whole number from 1 to 50" in json.loads(data)["error"]
    status, data = request(server, "GET", "/api/settings", headers={"X-Jobwatch-Token": TOKEN})
    assert json.loads(data)["autoread"] == {"enabled": True, "per_day": 10} and json.loads(data)["defaults"]["autoread"]["per_day"] == 25


# --- the page and the extension say the same thing -------------------------------------------------------------------


@needs_node
def test_the_page_and_the_extension_word_the_status_alike(tmp_path):
    cases = [
        {"state": "waiting", "done": 3, "planned": 12, "nextAt": 120000, "reason": ""},
        {"state": "waiting", "done": 3, "planned": 12, "nextAt": 45000, "reason": ""},
        {"state": "waiting", "done": 3, "planned": 3, "nextAt": 130000, "reason": ""},
        {"state": "empty", "done": 3, "planned": 3, "nextAt": 0, "reason": ""},
        {"state": "reading", "done": 3, "planned": 7, "nextAt": 0, "reason": ""},
        {"state": "capped", "done": 50, "planned": 50, "nextAt": 0, "reason": ""},
        {"state": "deferred", "done": 1, "planned": 4, "nextAt": 0, "reason": ""},
        {"state": "paused", "done": 1, "planned": 4, "nextAt": 0, "reason": ""},
        {"state": "off", "done": 1, "planned": 4, "nextAt": 0, "reason": ""},
        {"state": "disabled", "done": 0, "planned": 0, "nextAt": 0, "reason": ""},
        {"state": "stopped", "done": 1, "planned": 4, "nextAt": 0, "reason": "Auto-read paused: x."},
    ]
    js = tmp_path / "words.js"
    js.write_text(f"""const A = require({json.dumps(str(EXT / 'auto-read.js'))});
{page_function('autoReadCountdown')}
{page_function('autoReadLine')}
console.log(JSON.stringify({json.dumps(cases)}.map((c) => [A.statusLine(c, 0), autoReadLine(c, 0)])));""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    pairs = json.loads(r.stdout)
    assert len(pairs) == len(cases) and all(ext == page for ext, page in pairs), pairs
    assert pairs[0][1] == "Reading postings: 3 of 12 today · next in 2m"


@needs_node
def test_the_settings_words_follow_the_numbers(tmp_path):
    js = tmp_path / "limits.js"
    js.write_text(f"""{page_function('autoreadWords')}
console.log(JSON.stringify([autoreadWords(25, 120, 180), autoreadWords(5, 90, 600)]));""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    default, slow = json.loads(r.stdout)
    assert default.startswith("One job at a time, a random 2 to 3 minutes apart. At most 25 a day for each site")
    assert slow.startswith("One job at a time, a random 1.5 to 10 minutes apart. At most 5 a day for each site")
