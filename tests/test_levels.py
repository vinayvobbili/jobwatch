"""Expected pay from Levels.fyi. The pages here are made up (tests/fixtures/levels), and nothing reaches the network."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jobwatch import cli, config, levels, report, sources, watch
from jobwatch.config import ConfigError, Pay
from jobwatch.models import Job
from jobwatch.store import Store
from jobwatch.web import App

from .conftest import FakeWeb

PAGES = Path(__file__).parent / "fixtures" / "levels"
SE = f"{levels.SITE}/companies/{{}}/salaries/software-engineer"
ROBOTS = f"{levels.SITE}/robots.txt"


def page(name: str) -> str:
    return (PAGES / f"{name}.md").read_text()


def site(**extra) -> dict:
    """Levels.fyi as the tests see it: robots.txt lets everyone in, and the made-up pages."""
    return {ROBOTS: "User-agent: *\nAllow: /\n",
            SE.format("acme") + ".md": page("acme-software-engineer"),
            SE.format("acme") + "/levels/a3.md": page("acme-software-engineer-a3"),
            SE.format("globex") + ".md": page("globex-software-engineer-abroad"),
            SE.format("initech") + ".md": page("initech-software-engineer"), **extra}


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(levels, "PAUSE", 0.0)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state.db")
    yield s
    s.close()


def job(title="Senior Software Engineer", company="Acme", low=None, high=None, where=("Austin, TX",), remote=None):
    return Job(source="greenhouse", company=company.lower(), id="1", title=title, url="u", company_name=company,
               locations=list(where), remote=remote, salary_min=low, salary_max=high, currency="USD" if low else "")


def reader(store, responses=None, budget=10, **kw):
    return levels.Reader(store, budget, get=FakeWeb(site() if responses is None else responses), **kw)


# -- reading the pages

def test_a_family_page():
    fam = levels.parse_family(page("acme-software-engineer"), "Software Engineer")
    assert (fam.company, fam.location, fam.currency, fam.senior) == ("Acme", "United States", "USD", "A3")
    assert fam.levels[2] == ("A3", 190_000) and fam.levels[-1] == ("A6|Acme Fellow", 400_000)
    assert fam.years == {"A2": (2, 4), "A3": (5, 8), "A4": (9, 13)} and fam.mix == (150_000, 30_000, 20_000)
    assert levels.level_base(page("acme-software-engineer-a3")) == 160_000
    assert levels.parse_family("Nothing here") is None and levels.parse_family("") is None
    no_bonus = page("acme-software-engineer").replace(", and $20,000 bonus", ". Stock is the first year's.")
    assert levels.parse_family(no_bonus).mix == (150_000, 30_000, 0)


def test_family_company_and_seniority_from_a_job():
    assert levels.family_for("Senior Software Engineer, Platform") == "software-engineer"
    assert levels.family_for("Engineering Manager, Payments") == "software-engineering-manager"
    assert levels.family_for("Staff Data Scientist") == "data-scientist"
    assert levels.family_for("SOC Analyst II") == "security-analyst"
    assert levels.family_for("Account Executive") is None
    assert levels.seniority("Principal Engineer") == (2, "Principal")
    assert levels.seniority("Sr. Staff Engineer")[0] == 1 and levels.seniority("Engineer") is None
    assert levels.company_slugs(job(company="Hooli Technologies, Inc.")) == ["hooli-technologies-inc", "hooli"]
    assert levels.company_slugs(job(company="Acme")) == ["acme"]


def test_the_level_follows_the_title_and_the_years():
    fam = levels.parse_family(page("acme-software-engineer"), "Software Engineer")
    pick = lambda title, years: fam.levels[levels._pick(fam, title, years)[0]][0]  # noqa: E731
    assert pick("Senior Software Engineer", 20) == "A3"
    assert pick("Staff Software Engineer", 20) == "A4"
    assert pick("Staff Software Engineer", 6) == "A3"   # A4 typically has 9+ years
    assert pick("Software Engineer", 3) == "A2"         # no seniority word: the years decide, up to Senior
    assert pick("Software Engineer", 20) == "A3"
    assert pick("Software Engineer", None) == "A3"
    assert pick("Distinguished Engineer", 30) == "A6|Acme Fellow"


# -- the estimate

def test_an_estimate_from_the_us_page_and_its_level_page(store):
    e = levels.estimate(job(low=150_000, high=240_000), Pay(levels=True, years=20), None, reader(store))
    assert (e.level, e.total, e.base, e.ask, e.where) == ("A3", 190_000, 160_000, 180_000, "US-wide")
    assert e.url == SE.format("acme") and e.credit == "Data: Levels.fyi"
    assert e.line("$150K–$240K") == \
        "Ask ~$180K base · Levels.fyi A3 median $160K base / $190K total (US-wide) · posted $150K–$240K"
    assert any("its level page" in w for w in e.why) and any("10% over" in w for w in e.why)


def test_the_ask_stays_within_a_posted_range(store):
    e = levels.estimate(job(low=120_000, high=170_000), Pay(levels=True), None, reader(store))
    assert e.ask == 170_000 and any("capped at the posting's top" in w for w in e.why)
    e = levels.estimate(job(low=200_000, high=260_000), Pay(levels=True), None, reader(store))
    assert e.ask == 200_000 and any("raised to the posting's bottom" in w for w in e.why)


def test_a_remote_job_uses_the_home_region_first(store):
    responses = site(**{SE.format("acme") + "/locations/test-metro-area.md": page("acme-software-engineer-region")})
    pay = Pay(levels=True, years=20, region="test-metro-area")
    e = levels.estimate(job(where=("Remote",), remote=True), pay, None, reader(store, responses))
    # A region has no level pages: its total, and the all-levels median base for context, but nothing to ask.
    assert (e.where, e.total, e.base, e.ask, e.company_base) == ("Test Metro Area", 170_000, None, None, 150_000)
    assert e.url.endswith("/locations/test-metro-area")
    assert e.line() == \
        "Levels.fyi A3 median $170K total, base not given; $150K base across all levels (Test Metro Area)"
    # A job in another state isn't the region's: the US page.
    assert levels.estimate(job(where=("Austin, TX",)), pay, "NC", reader(store, responses)).where == "US-wide"
    # A job in the home state is.
    assert levels.estimate(job(where=("Raleigh, NC",)), pay, "NC", reader(store, responses)).where == \
        "Test Metro Area"


def test_no_regional_numbers_falls_back_to_us_wide(store):
    pay = Pay(levels=True, years=20, region="test-metro-area")
    e = levels.estimate(job(where=("Remote",), remote=True), pay, None, reader(store))
    assert e.where == "US-wide" and e.base == 160_000


def test_a_page_about_another_country_is_not_used(store):
    assert levels.estimate(job(company="Globex"), Pay(levels=True), None, reader(store)) is None


def test_totals_only_means_no_ask(store):
    e = levels.estimate(job("Staff AI Engineer", "Initech"), Pay(levels=True, years=20), None, reader(store))
    assert (e.level, e.total, e.base, e.ask) == ("I4", 260_000, None, None)
    assert e.line() == "Levels.fyi I4 median $260K total, base not given (US-wide)"
    assert any("no number to ask" in w for w in e.why)


def test_nothing_known_shows_nothing(store):
    assert levels.estimate(job(company="Nobody Corp"), Pay(levels=True), None, reader(store)) is None
    assert levels.estimate(job("Account Executive"), Pay(levels=True), None, reader(store)) is None


# -- asking Levels.fyi, politely

NOBODY = "companies/nobody/salaries/software-engineer"   # a 404
BLANK = "companies/blank/salaries/software-engineer"     # an empty answer: not ready on Levels.fyi's side yet
ACME = "companies/acme/salaries/software-engineer"


def _later(store, get, robots, hours, **kw):
    return levels.Reader(store, 10, get=get, robots=robots, now=datetime.now(timezone.utc) + timedelta(hours=hours),
                         **kw)


def _asked(get, since):
    return [c.removeprefix(levels.SITE + "/").removesuffix(".md") for c in get.calls[since:]]


def test_pages_are_kept_and_a_missing_page_asked_again_after_a_few_days(store):
    get = FakeWeb(site(**{f"{levels.SITE}/{BLANK}.md": "  \n"}))
    r = levels.Reader(store, 10, get=get)
    assert (r.page(NOBODY), r.page(BLANK)) == ("", "") and r.page(ACME).startswith("# Levels.fyi")
    assert [hit[2] for hit in map(store.pay_page, (f"{levels.SITE}/{p}.md" for p in (NOBODY, BLANK, ACME)))] == \
        [True, False, False]   # only the 404 is "gone"
    asked = len(get.calls)
    assert (r.page(NOBODY), r.page(BLANK), r.page(ACME)[:1]) == ("", "", "#")   # kept: nothing asked
    assert len(get.calls) == asked
    for p in (NOBODY, BLANK, ACME):
        _later(store, get, r.robots, 4 * 24).page(p)   # 404s are old after 3 days, pages good for 30
    assert _asked(get, asked) == [NOBODY, BLANK]


def test_an_empty_answer_is_asked_again_after_hours(store):
    get = FakeWeb(site(**{f"{levels.SITE}/{BLANK}.md": ""}))
    r = levels.Reader(store, 10, get=get)
    r.page(BLANK), r.page(NOBODY)
    asked = len(get.calls)
    _later(store, get, r.robots, 2).page(BLANK)                                     # 2 hours: still kept
    assert _asked(get, asked) == []
    _later(store, get, r.robots, 7).page(BLANK)                                     # 7: asked again
    assert _asked(get, asked) == [BLANK]
    store.save_pay_page(f"{levels.SITE}/{BLANK}.md", "")
    get.responses[f"{levels.SITE}/{BLANK}.md"] = page("acme-software-engineer")   # Levels.fyi has it now
    one_job = dict(empty=levels.EMPTY_ONE_JOB)
    assert _later(store, get, r.robots, 0.5, **one_job).page(BLANK) == ""         # one job: kept for an hour
    assert _later(store, get, r.robots, 2, **one_job).page(BLANK).startswith("# Levels.fyi")
    _later(store, get, r.robots, 2, **one_job).page(NOBODY)                         # a 404 still waits 3 days
    assert _asked(get, asked) == [BLANK, BLANK]


def test_an_old_empty_answer_is_not_known_yet_without_a_budget(store):
    store.save_pay_page(f"{levels.SITE}/{BLANK}.md", "")
    store.save_pay_page(f"{levels.SITE}/{NOBODY}.md", "", gone=True)
    old = levels.Reader(store, 0, get=FakeWeb({}), now=datetime.now(timezone.utc) + timedelta(hours=7))
    assert old.page(BLANK) is None and old.page(NOBODY) == ""


def test_show_retries_an_empty_answer_an_hour_old(store, tmp_path, monkeypatch):
    s = tmp_path / "w.yaml"
    s.write_text("companies: [greenhouse:acme]\nstate: state.db\npay: {levels: true, years: 20}\n")  # `store`'s
    cfg = config.load(s)
    store.save_pay_page(SE.format("acme") + ".md", "")
    store.db.execute("UPDATE pay_pages SET fetched_at=?", ((datetime.now(timezone.utc) - timedelta(hours=2))
                                                           .isoformat(),))
    get = FakeWeb(site())
    monkeypatch.setattr(sources, "get_text", get)
    assert levels.expected(cfg, store, job(), budget=levels.ONE_JOB) is None   # a queue look waits 6 hours
    assert levels.for_one_job(cfg, store, job()).level == "A3"                 # one job: asked again
    assert len([c for c in get.calls if c != ROBOTS]) == 2                     # the family page and A3's


def test_an_older_store_gets_the_gone_column(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE pay_pages (url TEXT PRIMARY KEY, body TEXT NOT NULL, fetched_at TEXT NOT NULL)")
    db.execute("INSERT INTO pay_pages VALUES ('u', '', '2026-01-01T00:00:00+00:00')")
    db.commit()
    db.close()
    s = Store(path)
    assert s.pay_page("u")[2] is False   # kept as an empty answer, so it's asked again soon
    s.close()


def test_no_budget_asks_nothing_and_says_pending(store):
    get = FakeWeb(site())
    assert levels.estimate(job(), Pay(levels=True), None, levels.Reader(store, 0, get=get)) == levels.PENDING
    assert get.calls == []
    assert levels.as_dict(levels.PENDING, job()) == {"pending": True}


def test_the_budget_caps_the_pages_asked_for(store):
    get = FakeWeb(site())
    r = levels.Reader(store, 1, get=get)
    assert levels.estimate(job(), Pay(levels=True), None, r) == levels.PENDING   # the level page waits
    assert [c for c in get.calls if c != ROBOTS] == [SE.format("acme") + ".md"]


def test_robots_txt_is_obeyed(store):
    get = FakeWeb(site(**{ROBOTS: "User-agent: *\nDisallow: /companies/\n"}))
    assert levels.estimate(job(), Pay(levels=True), None, levels.Reader(store, 10, get=get)) is None
    assert get.calls == [ROBOTS] and store.pay_page(SE.format("acme") + ".md")[2] is True   # kept out for days


def test_a_failed_request_is_not_kept(store):
    get = FakeWeb(site(**{SE.format("acme") + ".md": sources.SourceError("timed out")}))
    r = levels.Reader(store, 10, get=get)
    assert r.page("companies/acme/salaries/software-engineer") is None
    assert store.pay_page(SE.format("acme") + ".md") is None


# -- the watchlist

def test_pay_settings(tmp_path):
    path = tmp_path / "w.yaml"
    path.write_text("companies: [greenhouse:acme]\n")
    assert config.load(path).pay == Pay()
    path.write_text("companies: [greenhouse:acme]\npay: {levels: true, years: 12, region: test-metro-area}\n")
    assert config.load(path).pay == Pay(levels=True, years=12, region="test-metro-area")
    for bad in ("pay: {levels: yes please}", "pay: {years: lots}", "pay: {level: true}", "pay: true"):
        path.write_text(f"companies: [greenhouse:acme]\n{bad}\n")
        with pytest.raises(ConfigError, match="pay"):
            config.load(path)


@pytest.fixture
def levels_site(web, monkeypatch):
    """The test boards (`web`), and Levels.fyi as text pages."""
    fake = FakeWeb(site())
    monkeypatch.setattr(sources, "get_text", fake)
    return fake


def _fetch_and_queue(watchlist, capsys, pay="", min_salary=None):
    extra = (f"pay: {pay}\n" if pay else "")
    text = watchlist.read_text() + extra
    if min_salary:
        text = text.replace("filters:\n", f"filters:\n  min_salary: {min_salary}\n")
    watchlist.write_text(text)
    cli.main(["-c", str(watchlist), "fetch"])
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    store.set_status(["greenhouse:acme:101", "ashby:initech:c1"], "queued")
    store.close()
    capsys.readouterr()
    return cfg


def _levels_calls(fake) -> list[str]:
    return [c for c in fake.calls if "levels.fyi" in c]


def test_off_asks_levels_fyi_nothing(levels_site, watchlist, capsys, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    cfg = _fetch_and_queue(watchlist, capsys)
    assert cfg.pay.levels is False
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    cli.main(["-c", str(watchlist), "show", "101"])
    cli.main(["-c", str(watchlist), "queue"])
    out = capsys.readouterr().out
    job = mcp.get_job("101")
    queued = mcp.list_queued_jobs()
    app = App(watchlist, background=True)
    today = app.get_digest({})["jobs"]
    queue_page = app.get_queue({})
    details = app.get_job({"key": ["101"]})
    lookup = app.post_pay({"keys": ["greenhouse:acme:101"]})
    assert not app.pay.running
    assert _levels_calls(levels_site) == []
    assert "Expected pay" not in out and "Levels.fyi" not in out
    assert "expected_pay" not in job and all("expected_pay" not in q for q in queued)
    assert all("expected_pay" not in j for j in today + queue_page) and "expected_pay" not in details
    assert lookup == {"enabled": False, "running": False, "pay": {}}


def test_queued_jobs_show_expected_pay_and_warn_below_the_minimum(levels_site, watchlist, capsys, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    _fetch_and_queue(watchlist, capsys, pay="{levels: true, years: 20}", min_salary=170000)
    cli.main(["-c", str(watchlist), "queue"])
    out = capsys.readouterr().out
    assert "Expected pay: Ask ~$180K base · Levels.fyi A3 median $160K base / $190K total (US-wide)" in out
    assert "Levels.fyi: A3 median base $160K (US-wide) is below $170K" in out
    assert f"Data: Levels.fyi: {SE.format('acme')}" in out
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    queued = {q["key"]: q for q in mcp.list_queued_jobs()}
    acme = queued["greenhouse:acme:101"]["expected_pay"]
    assert (acme["ask"], acme["level"], acme["url"]) == (180_000, "A3", SE.format("acme"))
    assert queued["ashby:initech:c1"]["expected_pay"]["level"] == "I4"
    assert mcp.get_job("101")["expected_pay"]["line"] == acme["line"]
    cli.main(["-c", str(watchlist), "show", "101"])
    out = capsys.readouterr().out
    assert "Expected pay: Ask ~$180K" in out and "  - Level A3: the title says Senior" in out


def test_the_digest_never_has_expected_pay(levels_site, watchlist, capsys):
    cfg = _fetch_and_queue(watchlist, capsys, pay="{levels: true, years: 20}")
    cli.main(["-c", str(watchlist), "queue"])  # the pages are now kept
    store = Store(cfg.state)
    store.set_status(["greenhouse:acme:101", "ashby:initech:c1"], "shown")
    d = watch.build_digest(cfg, store, include_seen=True, score_top=0)
    store.close()
    assert d.entries
    for text in (report.to_markdown(d), report.to_json(d)):
        assert "Levels.fyi" not in text and "expected_pay" not in text and "Expected pay" not in text
    assert all("expected_pay" not in j for j in json.loads(report.to_json(d))["jobs"])


def test_the_page_looks_pay_up_in_the_background(levels_site, watchlist, capsys):
    _fetch_and_queue(watchlist, capsys, pay="{levels: true, years: 20}")
    app = App(watchlist, background=True)
    first = {j["key"]: j for j in app.get_queue({})}
    assert first["greenhouse:acme:101"]["expected_pay"] == {"pending": True}  # the page doesn't wait
    app.pay.wait(10)
    done = app.post_pay({"keys": ["greenhouse:acme:101", "ashby:initech:c1", "no-such-job"]})
    assert done["enabled"] and not done["running"]
    assert done["pay"]["greenhouse:acme:101"]["ask"] == 180_000
    assert app.get_job({"key": ["101"]})["expected_pay"]["level"] == "A3"
    # Without background work (as in tests of the page), nothing is asked for at all.
    quiet = App(watchlist)
    before = len(_levels_calls(levels_site))
    assert quiet.post_pay({"keys": ["lever:globex:aaaa-1111"]})["pay"]["lever:globex:aaaa-1111"] == {"pending": True}
    assert len(_levels_calls(levels_site)) == before
