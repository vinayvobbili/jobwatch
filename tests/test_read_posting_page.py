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
  setTimeout(() => window.postMessage({ type: 'jobwatch:read-posting-done', key: e.data.key, ok, error: 'sign in first',
    closed: true, has_text: true, said: 'Filled in from the pages text; scoring now' }, location.origin), 1500);
});
"""


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


def open_today(browser, server, bridge: bool):
    page = browser.new_page(viewport={"width": 1100, "height": 600})
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    if bridge:
        page.add_init_script(BRIDGE)
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
