"""The page's Read posting button in a real browser (headless Chromium through Playwright): with the extension's page
bridge it asks the extension (here a stand-in that answers) and changes only that card, leaving the scroll position and
every other card alone; without it, it opens the posting in a tab and, when the person comes back, redraws the page
where it was. Every job and company is made up. Skipped where Playwright or its browser isn't installed."""

import pytest

from jobwatch import alerts, config
from jobwatch.store import Store

sync_api = pytest.importorskip("playwright.sync_api")

# Stands in for the extension's page-bridge.js and service worker: marks the page, and answers a request after a beat
BRIDGE = """
const mark = () => { document.documentElement.dataset.jobwatchBridge = '1'; };
if (document.documentElement) mark(); else document.addEventListener('readystatechange', mark, { once: true });
window.requests = [];
window.addEventListener('message', (e) => {
  if (e.source !== window || !e.data || e.data.type !== 'jobwatch:read-posting') return;
  window.requests.push(e.data);
  const ok = window.bridgeOk !== false;
  // an extension from before the request existed: its service worker answers every message it does not know like this
  const error = window.bridgeOld ? 'Something went wrong: unknown message readInBackground' : 'sign in first';
  const answer = { type: 'jobwatch:read-posting-done', key: e.data.key, ok: ok && !window.bridgeOld, error,
    closed: true, has_text: true, said: 'Filled in from the pages text; scoring now' };
  setTimeout(() => window.postMessage(answer, location.origin), window.bridgeOld ? 50 : 1500);
});
"""
# What the bridge writes after asking the extension to `ping` (page-bridge.js): an extension that knows the request, and
# an older one, which answers "unknown message ping" and so has no capabilities
CAPS = {"new": "document.documentElement.dataset.jobwatchCaps = 'readInBackground';",
        "old": "document.documentElement.dataset.jobwatchCaps = '';"}


@pytest.fixture
def alert_jobs(watchlist, web):
    """Thirty jobs from a LinkedIn alert (title and company only), so Today has cards to scroll past. With a resume,
    each says it has no posting text, which is when its card offers Read posting."""
    (watchlist.parent / "resume.txt").write_text("Platform engineer with ten years of Python and Rust at Globex.")
    watchlist.write_text(watchlist.read_text() + "resume: resume.txt\n")
    store = Store(config.load(watchlist).state)
    try:
        for n in range(1, 31):
            job = alerts.email_job(alerts.Alert(f"Platform Engineer {n}", "Initech", "Remote (US)",
                                                url=f"https://www.linkedin.com/jobs/view/40000000{n:02d}/",
                                                site="linkedin", via="linkedin-alert"))
            store.keep(job)
            store.set_via(job.key, "linkedin-alert")
    finally:
        store.close()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except sync_api.Error as e:
            pytest.skip(f"no Chromium for Playwright: {e.message.splitlines()[0]}")
        yield b
        b.close()


def open_today(browser, server, bridge: bool, caps: str = "", old: bool = False):
    """Today with the bridge stand-in (`caps`: "new" or "old" for what the ping said, "" for no answer yet; `old`: its
    service worker doesn't know the read request) or without the bridge."""
    page = browser.new_page(viewport={"width": 1100, "height": 600})
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    if bridge:
        page.add_init_script(BRIDGE)
        if old:
            page.add_init_script("window.bridgeOld = true;")
        if caps:
            set_caps = CAPS[caps]
            page.add_init_script(
                f"document.addEventListener('readystatechange', () => {{ {set_caps} }}, {{ once: true }});"
                f" if (document.documentElement) {{ {set_caps} }}")
    page.goto(f"http://127.0.0.1:{server}/#today")
    page.wait_for_load_state("networkidle")
    try:
        page.locator("button", has_text="Read posting").first.wait_for(timeout=5000)
    except sync_api.Error:
        raise AssertionError(f"no card offers Read posting; Today shows:\n{page.inner_text('main')[:1500]}") from None
    return page


def scroll_to_a_lower_card(page):
    """The seventh card, scrolled to and then a little past: returns (that card, its id, the scroll position)."""
    card = page.locator("[id^=job-]").nth(6)
    card.scroll_into_view_if_needed()
    page.evaluate("() => window.scrollBy(0, 150)")
    return card, card.get_attribute("id"), page.evaluate("() => window.scrollY")


def test_with_the_bridge_only_that_card_changes_and_the_place_is_kept(browser, server, alert_jobs):
    page = open_today(browser, server, bridge=True)
    try:
        card, key, before = scroll_to_a_lower_card(page)
        assert before > 0 and page.evaluate("() => document.documentElement.dataset.jobwatchBridge") == "1", page.errors
        others = [page.locator("[id^=job-]").nth(i).get_attribute("id") for i in (0, 1, 5)]
        page.evaluate("(ids) => ids.forEach((i) => { document.getElementById(i).dataset.same = '1'; })", others)
        card.locator("button", has_text="Read posting").click()
        sync_api.expect(card.locator("button", has_text="Reading")).to_be_visible()
        sync_api.expect(page.locator("#toast")).to_contain_text("scoring now")
        sync_api.expect(page.locator(f'[id="{key}"] .badge.closed')).to_be_visible()  # the card says it is closed
        requests = page.evaluate("() => window.requests")
        assert len(requests) == 1 and requests[0]["url"].startswith("https://www.linkedin.com/jobs/view/")
        assert "#" not in requests[0]["url"]  # the extension adds its own marker (see JWRead.readUrl)
        # the page stayed where it was (the card itself is a line shorter now, which can move it by that much)
        assert abs(page.evaluate("() => window.scrollY") - before) <= 40
        # the other cards are the very same elements: nothing re-rendered the list
        assert page.evaluate("(ids) => ids.every((i) => document.getElementById(i).dataset.same === '1')", others)
        assert len(page.context.pages) == 1  # no tab opened from this page
        assert page.errors == []
    finally:
        page.close()


def test_when_the_extension_cannot_read_it_the_page_says_why_and_stays(browser, server, alert_jobs):
    page = open_today(browser, server, bridge=True)
    try:
        page.evaluate("() => { window.bridgeOk = false; }")
        card, key, before = scroll_to_a_lower_card(page)
        card.locator("button", has_text="Read posting").click()
        sync_api.expect(page.locator("#toast")).to_contain_text("Couldn't read the posting: sign in first")
        sync_api.expect(page.locator(f'[id="{key}"] button', has_text="Read posting")).to_be_enabled()
        assert abs(page.evaluate("() => window.scrollY") - before) <= 1
        assert page.errors == []
    finally:
        page.close()


def test_without_the_bridge_the_tab_opens_and_coming_back_keeps_the_place(browser, server, alert_jobs):
    page = open_today(browser, server, bridge=False)
    try:
        page.evaluate("() => { window.opened = []; window.open = (u) => { window.opened.push(u); return null; }; }")
        card, key, before = scroll_to_a_lower_card(page)
        card.locator("button", has_text="Read posting").click()
        opened = page.evaluate("() => window.opened")
        assert len(opened) == 1 and opened[0].startswith("https://www.linkedin.com/jobs/view/")
        assert opened[0].endswith("#jobwatch-read")
        page.evaluate("() => window.dispatchEvent(new Event('focus'))")  # the person comes back
        page.wait_for_timeout(2500)
        page.wait_for_load_state("networkidle")
        # the redraw keeps the place (the page may end a few pixels differently once redrawn) and the same card in view
        assert abs(page.evaluate("() => window.scrollY") - before) <= 40
        box = page.locator(f'[id="{key}"]').bounding_box()
        assert box["y"] + box["height"] > 0 and box["y"] < 600, box
        assert page.errors == []
    finally:
        page.close()


def test_with_an_extension_that_has_the_capability_it_reads_in_the_background(browser, server, alert_jobs):
    page = open_today(browser, server, bridge=True, caps="new")
    try:
        card, _key, _before = scroll_to_a_lower_card(page)
        card.locator("button", has_text="Read posting").click()
        sync_api.expect(page.locator("#toast")).to_contain_text("scoring now")
        assert len(page.evaluate("() => window.requests")) == 1 and len(page.context.pages) == 1
        assert "Update or reload" not in page.inner_text("#toast")
        assert page.errors == []
    finally:
        page.close()


def test_an_extension_that_does_not_answer_the_ping_opens_the_posting_in_front_with_a_hint(browser, server, alert_jobs):
    page = open_today(browser, server, bridge=True, caps="old")
    try:
        page.evaluate("() => { window.opened = []; window.open = (u) => { window.opened.push(u); return null; }; }")
        card, _key, before = scroll_to_a_lower_card(page)
        card.locator("button", has_text="Read posting").click()
        opened = page.evaluate("() => window.opened")
        assert len(opened) == 1 and opened[0].endswith("#jobwatch-read")
        assert page.evaluate("() => window.requests") == []  # the request it can't answer is never sent
        sync_api.expect(page.locator("#toast")).to_contain_text("Update or reload the jobwatch extension")
        page.evaluate("() => window.dispatchEvent(new Event('focus'))")  # the person comes back
        page.wait_for_timeout(2500)
        page.wait_for_load_state("networkidle")
        assert abs(page.evaluate("() => window.scrollY") - before) <= 40
        assert page.errors == []
    finally:
        page.close()


def test_an_extension_that_says_unknown_message_falls_back_and_hints_once(browser, server, alert_jobs):
    """The ping not answered yet (or lost), the request goes out and comes back "unknown message": the posting still
    opens, and the hint is said the first time only."""
    page = open_today(browser, server, bridge=True, old=True)
    try:
        page.evaluate("() => { window.opened = []; window.open = (u) => { window.opened.push(u); return null; }; }")
        card = page.locator("[id^=job-]").nth(2)
        card.locator("button", has_text="Read posting").click()
        sync_api.expect(page.locator("#toast")).to_contain_text("Update or reload the jobwatch extension")
        assert "Couldn't read the posting" not in page.inner_text("#toast")
        assert len(page.evaluate("() => window.opened")) == 1
        sync_api.expect(card.locator("button", has_text="Read posting")).to_be_enabled()
        page.evaluate("() => { document.getElementById('toastText').textContent = ''; }")  # the first toast's words
        card = page.locator("[id^=job-]").nth(3)
        card.locator("button", has_text="Read posting").click()
        sync_api.expect(page.locator("#toast")).to_contain_text("Opened on LinkedIn")
        assert "Update or reload" not in page.inner_text("#toast")
        assert len(page.evaluate("() => window.opened")) == 2
        assert page.errors == []
    finally:
        page.close()
