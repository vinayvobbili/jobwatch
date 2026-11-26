"""The page in a real browser (headless Chromium through Playwright), as a person uses it: every tab opens without
a script error, and pressing Save in Settings writes the watchlist back as it was. Skipped where Playwright or its
browser isn't installed (`pip install -e ".[browser]"` then `playwright install chromium`)."""

import pytest
import yaml

from jobwatch import config
from jobwatch.store import Store
from jobwatch.watch import fetch_all

sync_api = pytest.importorskip("playwright.sync_api")

TABS = ["today", "interviews", "queue", "applied", "comps", "referrals", "skills", "activity", "settings"]
# Patterns with commas of their own, and a place with one: the Settings boxes once split all three at the comma.
FILTERS = {
    "titles": ["engineer", "developer"],
    "exclude_titles": ["contract"],
    "exclude_text": [r"\b(must|need to) be an? U\.?S\.? citizen\b(?![^.\n]{0,40}\bgreen card)",
                     r"\b0\s*[-–]\s*2 years of experience\b"],
    "locations": ["remote", "Boulder, CO"],
    "max_age_days": 30,
}


@pytest.fixture
def watchlist(tmp_path):
    path = tmp_path / "jobwatch.yaml"
    path.write_text(yaml.safe_dump({
        "companies": ["greenhouse:acme", "lever:globex"], "filters": FILTERS,
        "keywords": {"Python": 2, "LLM": 3}, "state": "state.db", "cache": "cache"}))
    return path


@pytest.fixture
def jobs(watchlist, web):
    """The two boards read once, so Today has jobs: Acme's posted 3 days ago and Globex's 10 days ago. List it
    before `page` in a test's arguments, so the page opens with them."""
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    try:
        fetch_all(cfg, store)
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


@pytest.fixture
def page(browser, server):
    """The page, open on Today; `page.errors` collects script errors and failed requests from then on. A company
    with no logo is a 204 by design (the page shows its initials)."""
    page = browser.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.on("response", lambda r: r.status >= 400 and page.errors.append(f"{r.status} {r.url}"))
    page.goto(f"http://127.0.0.1:{server}/#today")
    page.wait_for_load_state("networkidle")
    yield page
    page.close()


def test_every_tab_opens_without_a_script_error(page):
    for tab in TABS:
        page.locator(f'nav [data-tab="{tab}"], [data-tab="{tab}"]').first.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(300)
    assert page.errors == []


def test_saving_settings_writes_the_watchlist_back_as_it_was(page, watchlist):
    before = config.load(watchlist).filters
    page.goto(page.url.split("#")[0] + "#settings/search")
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Save settings").first.click()
    status = page.locator(".snav [role=status]")
    sync_api.expect(status).to_have_text("Saved.", timeout=10000)
    assert config.load(watchlist).filters == before
    saved = yaml.safe_load(watchlist.read_text())["filters"]
    assert {k: saved[k] for k in FILTERS} == FILTERS
    assert page.errors == []


def chip(page, hint, label):
    """The button of the chip group under `hint` (Fit score, Top pay) that says `label`."""
    group = page.locator(".hint", has_text=hint).first.locator("xpath=following-sibling::div[1]")
    return group.get_by_role("button", name=label, exact=True)


def test_today_opens_on_any_chips_unless_the_watchlist_sets_them(page, watchlist):
    sync_api.expect(chip(page, "Fit score", "Any")).to_have_class("on")
    sync_api.expect(chip(page, "Top pay", "Any")).to_have_class("on")
    watchlist.write_text(watchlist.read_text() + "display:\n  today_defaults: {fit: 80, pay: 175000}\n")
    page.reload()
    page.wait_for_load_state("networkidle")
    sync_api.expect(chip(page, "Fit score", "80+")).to_have_class("on")
    sync_api.expect(chip(page, "Top pay", "$175K+")).to_have_class("on")
    chip(page, "Top pay", "Any").click()  # still one click away
    sync_api.expect(chip(page, "Top pay", "Any")).to_have_class("on")
    assert page.errors == []


def reload(page):
    page.reload()
    page.wait_for_load_state("networkidle")


def test_today_opens_on_posted_within_7d_and_a_choice_is_remembered(jobs, page):
    sync_api.expect(chip(page, "Posted within", "7d")).to_have_class("on")
    sync_api.expect(page.locator(".showing")).to_contain_text("posted over 7 days ago hidden")
    sync_api.expect(page.get_by_role("button", name="Clear filters")).to_have_count(0)  # 7d is the default
    chip(page, "Posted within", "Any").click()  # an explicit Any is a choice too
    sync_api.expect(page.locator(".showing")).not_to_contain_text("hidden")
    reload(page)
    sync_api.expect(chip(page, "Posted within", "Any")).to_have_class("on")
    page.get_by_role("button", name="Clear filters").click()  # back to the default, and the choice is forgotten
    sync_api.expect(chip(page, "Posted within", "7d")).to_have_class("on")
    reload(page)
    sync_api.expect(chip(page, "Posted within", "7d")).to_have_class("on")
    assert page.errors == []


def test_the_watchlist_sets_the_posted_default_and_0_is_any(jobs, page, watchlist):
    watchlist.write_text(watchlist.read_text() + "display:\n  today_defaults: {posted: 14}\n")
    reload(page)
    sync_api.expect(chip(page, "Posted within", "14d")).to_have_class("on")
    watchlist.write_text(watchlist.read_text().replace("posted: 14", "posted: 0"))
    page.evaluate("localStorage.clear()")
    reload(page)
    sync_api.expect(chip(page, "Posted within", "Any")).to_have_class("on")
    assert page.errors == []


def test_when_posted_within_hides_everything_the_empty_state_offers_to_widen_it(jobs, page, watchlist):
    watchlist.write_text(watchlist.read_text() + "display:\n  today_defaults: {posted: 1}\n")
    reload(page)
    empty = page.locator(".empty")
    sync_api.expect(empty).to_contain_text("Nothing posted in the last 1 day matches")
    sync_api.expect(empty).to_contain_text("Widen it to 14 days or Any")
    empty.get_by_role("button", name="Widen to 14 days").click()
    sync_api.expect(chip(page, "Posted within", "14d")).to_have_class("on")
    sync_api.expect(page.locator(".card.job").first).to_be_visible()
    page.get_by_role("button", name="Clear filters").click()  # the default again: 1 day, nothing shown
    sync_api.expect(page.locator(".empty").get_by_role("button", name="Show any age")).to_be_visible()
    page.locator(".empty").get_by_role("button", name="Show any age").click()
    sync_api.expect(chip(page, "Posted within", "Any")).to_have_class("on")
    assert page.errors == []


def test_settings_keep_the_age_decay_and_the_posted_default(page, watchlist):
    page.goto(page.url.split("#")[0] + "#settings/today")
    page.wait_for_load_state("networkidle")
    typed = {"Today opens on posted within (days)": "14", "Best fit: points lost a day after that": "1.5"}
    for label, value in typed.items():
        page.locator(".field", has=page.locator("label", has_text=label)).locator("input").fill(value)
    page.get_by_role("button", name="Save settings").first.click()
    sync_api.expect(page.locator(".snav [role=status]")).to_have_text("Saved.", timeout=10000)
    cfg = config.load(watchlist)
    assert cfg.today_posted == 14 and (cfg.age_decay.per_day, cfg.age_decay.cutoff_days) == (1.5, 120)
    assert "grace_days" not in yaml.safe_load(watchlist.read_text())["display"]["age_decay"]  # blank: its default
    assert page.errors == []


@pytest.mark.parametrize(("hint", "default", "chosen"),
                         [("No pay clue", "Hide", "Show"), ("No score yet", "Show", "Hide")])
def test_the_show_hide_choices_for_unknowns_are_remembered(page, hint, default, chosen):
    """Jobs with no fit score yet show until Hide is chosen; jobs with no pay clue are hidden until Show is chosen."""
    sync_api.expect(chip(page, hint, default)).to_have_class("on")
    chip(page, hint, chosen).click()
    page.reload()
    page.wait_for_load_state("networkidle")
    sync_api.expect(chip(page, hint, chosen)).to_have_class("on")
    other, other_default = ("No score yet", "Show") if hint == "No pay clue" else ("No pay clue", "Hide")
    sync_api.expect(chip(page, other, other_default)).to_have_class("on")  # each has its own memory
    assert page.errors == []


DEGREE = "Bachelor of Science degree in Computer Science or a related technical/analytical discipline"
DISTRIBUTED = "Strong distributed-systems background, including retries, idempotency, and recovery"


def test_a_degree_gap_the_profile_meets_leaves_the_card_and_counts_as_met(jobs, page, watchlist):
    """A job card's Gaps row lists a degree requirement your profile's education meets only until the profile says
    so: then the gap is gone, the must-haves count it, and the box says why on hover."""
    from jobwatch.score import resume_id

    cv = watchlist.parent / "cv.md"
    cv.write_text("# Jane Doe")
    config.save(watchlist, {"resume": str(cv)})
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    store.save_score("greenhouse:acme:101", resume_id(cfg.resume), {
        "score": 81.0, "must_haves_met": 5, "must_haves_total": 10, "summary": "Good.", "flags": [],
        "gaps": [f"{DEGREE} · {DISTRIBUTED}"]})
    store.close()
    card = page.locator(".card.job", has=page.locator('[data-fit="greenhouse:acme:101"]'))
    reload(page)
    sync_api.expect(card.locator(".gaps")).to_contain_text("Bachelor of Science degree")
    sync_api.expect(card.locator(".fitbox small").first).to_have_text("must-haves 5/10")
    (watchlist.parent / "profile.yaml").write_text(yaml.safe_dump({"education": [
        {"school": "Initech State University", "degree": "MS in Computer Science"}]}))
    reload(page)
    sync_api.expect(card.locator(".gaps")).to_have_text(DISTRIBUTED)
    sync_api.expect(card.locator(".fitbox small").first).to_have_text("must-haves 6/10")
    sync_api.expect(card.locator(".fitbox small.reconciled")).to_have_attribute(
        "title", "Reconciled with your profile: " + DEGREE + ": met by your MS in Computer Science "
                 "(the score was not made again)")
    assert page.errors == []
