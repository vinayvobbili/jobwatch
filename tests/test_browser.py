"""The page in a real browser (headless Chromium through Playwright), as a person uses it: every tab opens without
a script error, and pressing Save in Settings writes the watchlist back as it was. Skipped where Playwright or its
browser isn't installed (`pip install -e ".[browser]"` then `playwright install chromium`)."""

import re

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


def test_settings_show_each_quota_pool_as_a_dot_and_a_paused_one_with_when_it_is_back(page, watchlist):
    from datetime import UTC, datetime

    from jobwatch import watch
    store = Store(config.load(watchlist).state)
    store.set_scorer_down(watch.pool_id("agy_gemini"), "out of quota", datetime(2099, 12, 1, 22, tzinfo=UTC))
    store.close()
    page.goto(page.url.split("#")[0] + "#settings/ai")
    page.wait_for_load_state("networkidle")
    flags = page.locator(".ai-chain .pool-flag")
    sync_api.expect(flags.first).to_be_visible(timeout=10000)
    assert flags.count() >= 4
    sync_api.expect(page.locator(".ai-chain .pool-flag.off")).to_have_count(1)
    off = page.locator(".ai-chain .pool-flag.off").inner_text()
    assert off.startswith("agy_gemini") and "back" in off and "Dec" in off
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


def test_a_fit_minimum_hides_jobs_with_no_score_until_show_is_picked_by_hand(jobs, page, watchlist):
    """Fit 80+ turns "No score yet" to Hide, so the unscored job leaves with the Showing line counting it out. Show
    brought back by hand lasts until the fit changes; Fit Any gives the switch back the value this browser kept."""
    from jobwatch.score import resume_id

    cv = watchlist.parent / "cv.md"
    cv.write_text("# Jane Doe")
    config.save(watchlist, {"resume": str(cv)})
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    store.save_score("greenhouse:acme:101", resume_id(cfg.resume), {
        "score": 85.0, "must_haves_met": 3, "must_haves_total": 3, "gaps": [], "summary": "Strong.", "flags": []})
    store.close()
    scored = page.locator(".card.job", has=page.locator('[data-fit="greenhouse:acme:101"]'))
    unscored = page.locator(".card.job", has_text="Machine Learning Engineer")  # Globex's, 10 days old, never scored
    showing = page.locator(".showing")
    reload(page)
    chip(page, "Posted within", "14d").click()
    sync_api.expect(unscored).to_have_count(1)
    sync_api.expect(showing).to_contain_text("Showing 2 of 2")

    chip(page, "Fit score", "80+").click()
    sync_api.expect(chip(page, "No score yet", "Hide")).to_have_class("on")
    sync_api.expect(scored).to_have_count(1)
    sync_api.expect(unscored).to_have_count(0)
    sync_api.expect(showing).to_contain_text("Showing 1 of 2")

    chip(page, "No score yet", "Show").click()
    sync_api.expect(unscored).to_have_count(1)
    sync_api.expect(showing).to_contain_text("Showing 2 of 2")
    chip(page, "Where", "Remote").click()  # another filter redraws the page: the choice stays
    sync_api.expect(chip(page, "No score yet", "Show")).to_have_class("on")
    sync_api.expect(unscored).to_have_count(1)
    chip(page, "Where", "Any").click()

    chip(page, "Fit score", "70+").click()  # the fit changed: Hide again
    sync_api.expect(chip(page, "No score yet", "Hide")).to_have_class("on")
    sync_api.expect(unscored).to_have_count(0)

    chip(page, "Fit score", "Any").click()  # nothing was kept but the default
    sync_api.expect(chip(page, "No score yet", "Show")).to_have_class("on")
    sync_api.expect(unscored).to_have_count(1)

    chip(page, "No score yet", "Hide").click()  # kept with no fit chip on ...
    chip(page, "Fit score", "60+").click()
    chip(page, "No score yet", "Show").click()  # ... and not overwritten by a Show picked under a fit chip
    chip(page, "Fit score", "Any").click()
    sync_api.expect(chip(page, "No score yet", "Hide")).to_have_class("on")
    sync_api.expect(unscored).to_have_count(1)  # with no fit chip on, the switch changes nothing
    reload(page)
    sync_api.expect(chip(page, "No score yet", "Hide")).to_have_class("on")
    assert page.errors == []


def test_a_weak_fit_with_no_must_haves_shows_what_it_found_missing_on_the_card(jobs, page, watchlist):
    """Not a dash in the Gaps row next to a 46: a posting with only an "ideal candidate has" list has no must-haves,
    so the row lists the requirements judged missing, then the partly shown, each marked a nice to have."""
    from jobwatch.score import resume_id

    cv = watchlist.parent / "cv.md"
    cv.write_text("# Jane Doe")
    config.save(watchlist, {"resume": str(cv)})
    cfg = config.load(watchlist)
    ask = {"kind": "nice_to_have", "evidence": [], "evidence_verified": True, "reasoning": "why"}
    store = Store(cfg.state)
    store.save_score("greenhouse:acme:101", resume_id(cfg.resume), {
        "score": 46.0, "must_haves_met": 0, "must_haves_total": 0, "gaps": [], "summary": "Weak.", "flags": [],
        "requirements": [{**ask, "id": "a", "requirement": "Umbrella industry experience", "verdict": "partial"},
                         {**ask, "id": "b", "requirement": "Two embedded deployments", "verdict": "not_met"}]})
    store.close()
    card = page.locator(".card.job", has=page.locator('[data-fit="greenhouse:acme:101"]'))
    reload(page)
    sync_api.expect(card.locator(".gaps")).to_have_text(
        "Two embedded deployments (nice to have, missing) · Umbrella industry experience (nice to have, partly)")
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


def test_a_stale_score_shows_with_a_badge_and_the_resume_decision_is_made_on_the_page(jobs, page, watchlist):
    """A rebuilt resume hides no score and asks for none: the card keeps its ring, flagged stale with the reason on
    hover, and Today says how many predate the resume. Keep scores clears the flags with nothing scored; Mark stale
    flags the scores again as marked (to be scored again, with the reason and day on hover)."""
    from jobwatch.score import resume_id

    acme, globex = "greenhouse:acme:101", "lever:globex:aaaa-1111"
    cv = watchlist.parent / "cv.md"
    cv.write_text("# Jane Doe")
    config.save(watchlist, {"resume": str(cv), "scoring": {"auto": False}})  # nothing may score on its own here
    cfg = config.load(watchlist)
    fit = {"score": 85.0, "must_haves_met": 3, "must_haves_total": 3, "gaps": [], "summary": "Strong.", "flags": []}
    store = Store(cfg.state)
    store.save_score(acme, "cv.md:000000000000:scorer-00000000", fit)  # made under an earlier resume
    store.save_score(globex, resume_id(cfg.resume), {**fit, "score": 66.0})
    store.close()
    old = page.locator(f'.fitbox[data-fit="{acme}"]')
    fresh = page.locator(f'.fitbox[data-fit="{globex}"]')
    strip = page.locator(".stale-scores")
    reload(page)
    chip(page, "Posted within", "14d").click()
    sync_api.expect(old).to_have_class("fitbox stale")
    sync_api.expect(old.locator(".ring span").first).to_have_text("85")  # the score, not "not scored yet"
    sync_api.expect(old.locator(".stale-badge")).to_have_attribute("title", "scored under an older resume")
    sync_api.expect(fresh.locator(".stale-badge")).to_have_count(0)
    # The ring says only the score; the badge is a small clock on its rim with no word, clear of the number
    sync_api.expect(old.locator(".ring")).to_have_text("85")
    sync_api.expect(old.locator(".stale-badge")).to_have_text("")
    sync_api.expect(old.locator(".stale-badge svg")).to_have_count(1)
    number, badge = old.locator(".ring span").first.bounding_box(), old.locator(".stale-badge").bounding_box()
    assert badge["width"] < 26 and badge["height"] < 26
    assert not (badge["x"] <= number["x"] + number["width"] / 2 <= badge["x"] + badge["width"]
                and badge["y"] <= number["y"] + number["height"] / 2 <= badge["y"] + badge["height"])
    sync_api.expect(strip).to_contain_text("1 score predates your resume")

    strip.get_by_role("button", name="Decide…").click()
    dialog = page.get_by_role("dialog", name="Scores and your resume")
    sync_api.expect(dialog.locator("[data-scores-line]")).to_have_text(
        "1 of 2 fit scores were made under an older resume.")
    dialog.get_by_role("button", name="Keep scores").click()
    sync_api.expect(old.locator(".stale-badge")).to_have_count(0)
    sync_api.expect(strip).to_have_text("")
    store = Store(cfg.state)
    assert [r["action"] for r in store.db.execute("SELECT action FROM score_decisions")] == ["keep"]
    store.close()

    cv.write_text("# Jane Doe\nrebuilt")  # another resume
    reload(page)
    chip(page, "Posted within", "14d").click()
    sync_api.expect(old.locator(".stale-badge")).to_have_attribute("title", "scored under an older resume")
    sync_api.expect(strip).to_contain_text("2 scores predate your resume")
    strip.get_by_role("button", name="Decide…").click()
    dialog.get_by_placeholder("What changed? (kept in the log)").fill("new summary")
    dialog.get_by_label("Which scores").select_option("all")
    dialog.get_by_role("button", name="Mark stale").click()
    sync_api.expect(old.locator(".stale-badge.marked")).to_have_attribute(
        "title", re.compile(r"^marked stale on \d{4}-\d\d-\d\d: new summary$"))
    sync_api.expect(old.locator(".ring span").first).to_have_text("85")  # still shown, and so is the other
    sync_api.expect(fresh.locator(".stale-badge.marked")).to_have_count(1)
    store = Store(cfg.state)
    assert store.db.execute("SELECT COUNT(*) FROM score_stale").fetchone()[0] == 2
    store.close()
    assert page.errors == []


def test_scoring_shows_a_spinner_that_clears_on_a_score_or_a_failure(jobs, page, watchlist):
    """Pressing Score turns the card's corner button into a disabled spinner until the server answers; a failure puts
    the button back with the error, a score replaces it with the ring. A job being scored (the background scorer's, or a
    posting just read) shows a ring spinner in the score's place with no small print."""
    key = "greenhouse:acme:101"
    card = page.locator(f'[id="job-{key}"]')
    cv = watchlist.parent / "cv.md"
    cv.write_text("# Jane Doe")
    config.save(watchlist, {"resume": str(cv), "scoring": {"auto": False}})
    held = []
    page.route("**/api/score", lambda route: held.append(route))
    reload(page)
    chip(page, "Posted within", "14d").click()
    corner = card.locator(".score-corner")
    corner.click()
    sync_api.expect(corner).to_be_disabled()
    sync_api.expect(corner.locator(".spin")).to_have_count(1)
    sync_api.expect(corner).to_have_attribute("title", re.compile("Compare this posting"))
    held.pop().fulfill(status=502, json={"error": "agy is out of quota"})  # a failure: the button is back
    sync_api.expect(corner).to_be_enabled()
    sync_api.expect(corner.locator(".spin")).to_have_count(0)
    sync_api.expect(page.locator(".toast", has_text="agy is out of quota")).to_be_visible()
    assert page.errors == [f"502 {page.url.split('#')[0]}api/score"]  # the failure we sent, nothing else
    page.errors.clear()
    corner.click()
    sync_api.expect(corner.locator(".spin")).to_have_count(1)
    held.pop().fulfill(json={"score": 71.0, "must_haves_met": 3, "must_haves_total": 4, "gaps": [], "summary": "ok"})
    sync_api.expect(card.locator(".ring span").first).to_have_text("71")  # the score is drawn; the spinner is gone
    sync_api.expect(card.locator(".spin, .score-spin")).to_have_count(0)

    def being_scored(route):  # the server says this job is being scored now (the list: no score; the extra: why)
        got = route.fetch()
        body = got.json()
        if "part=extra" in route.request.url:
            body["jobs"][key] = {**body["jobs"].get(key, {}),
                                 "unscored": {"code": "scoring", "text": "Posting read: scoring it now…"}}
        else:
            for j in body["jobs"]:
                if j["key"] == key:
                    j.update(fit=None)
        route.fulfill(response=got, json=body)

    page.route(re.compile(r"/api/digest\?part="), being_scored)
    reload(page)
    chip(page, "Posted within", "14d").click()
    spinner = card.locator(".fitbox.scoring-now")
    sync_api.expect(spinner).to_have_attribute("aria-label", "Scoring…")
    sync_api.expect(spinner.locator(".score-spin")).to_be_visible()
    sync_api.expect(spinner).to_have_text("")  # no small print
    sync_api.expect(card.get_by_text("scoring it now")).to_have_count(0)
    assert page.errors == []


def open_company(page, name):
    page.goto(page.url.split("#")[0] + "#company/" + name)
    reload(page)


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_a_company_page_folds_skipped_and_closed_jobs_into_one_closed_group(jobs, page, watchlist, scheme):
    """Skipped jobs and closed postings leave the live cards for one dimmed "Closed (N)" group: collapsed by default,
    a click opens it, and whether it's open is remembered by the browser. The tiles above still count them."""
    store = Store(config.load(watchlist).state)
    store.set_status(["greenhouse:acme:102"], "skipped")
    store.set_status(["lever:globex:aaaa-1111"], "queued")
    store.set_closed("lever:globex:aaaa-1111", True)
    store.confirm_closed(["lever:globex:aaaa-1111"])
    store.set_status(["lever:globex:bbbb-2222"], "skipped")
    store.close()
    page.emulate_media(color_scheme=scheme)
    group, head = page.locator(".closed-group"), page.locator(".closed-head")
    live, skipped = page.locator('[id="job-greenhouse:acme:101"]'), page.locator('[id="job-greenhouse:acme:102"]')

    open_company(page, "Acme")  # one live card above, one skipped job folded away
    sync_api.expect(live).to_be_visible()
    sync_api.expect(head).to_have_text("Closed (1)")
    sync_api.expect(head).to_have_attribute("aria-expanded", "false")
    sync_api.expect(skipped).to_have_count(0)
    sync_api.expect(page.locator(".hero .stat .lbl", has_text="skipped")).to_have_count(1)  # the tile stays
    assert live.bounding_box()["y"] < head.bounding_box()["y"]  # the group sits below the live cards
    head.click()
    sync_api.expect(head).to_have_attribute("aria-expanded", "true")
    sync_api.expect(skipped).to_be_visible()
    sync_api.expect(page.locator(".closed-cards")).to_have_css("opacity", re.compile(r"^0\.6"))  # dimmed
    reload(page)  # remembered
    sync_api.expect(skipped).to_be_visible()
    head.click()
    sync_api.expect(skipped).to_have_count(0)
    reload(page)
    sync_api.expect(head).to_have_attribute("aria-expanded", "false")

    open_company(page, "Globex")  # a skipped job and a queued one whose posting closed: both in the group
    sync_api.expect(head).to_have_text("Closed (2)")
    sync_api.expect(page.locator(".empty")).to_have_count(0)
    head.click()
    sync_api.expect(group.locator('[id="job-lever:globex:aaaa-1111"]')).to_be_visible()
    sync_api.expect(group.locator('[id="job-lever:globex:bbbb-2222"]')).to_be_visible()
    assert page.errors == []


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_job_details_close_button_has_an_x_and_the_word_and_esc_closes_the_dialog_too(jobs, page, scheme):
    """The Close button of the job details is the one shared look (.btn-close): an X and the word, a tooltip that names
    Esc, a ring when it has the keyboard's focus; the button and Esc both close the dialog, in either theme."""
    page.emulate_media(color_scheme=scheme)
    chip(page, "Posted within", "14d").click()
    overlay, close = page.locator("#overlay"), page.locator("#dialog .btn-close")
    for how in ("click", "Escape"):
        page.locator(".btn.act-details").first.click()
        sync_api.expect(close).to_have_count(1)
        sync_api.expect(close).to_have_text("Close")
        sync_api.expect(close.locator("svg.ico")).to_have_count(1)
        sync_api.expect(close).to_have_attribute("title", "Close (Esc)")
        sync_api.expect(page.locator("#dialog .job-chat")).to_have_count(1)  # the card with the chat panel beside it
        page.keyboard.press("Tab")  # the keyboard's focus, so :focus-visible applies
        close.focus()
        sync_api.expect(close).to_have_css("outline-style", "solid")
        if how == "click":
            close.click()
        else:
            page.keyboard.press("Escape")
        sync_api.expect(overlay).to_be_hidden()
    assert page.errors == []
