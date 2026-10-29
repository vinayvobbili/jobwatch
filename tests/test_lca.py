"""Base pay filed for H-1B hires, from the DOL's LCA disclosure data. The workbook here is a tiny made-up one built in
the test, and nothing reaches the network."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from jobwatch import cli, lca, report, sources  # noqa: E402
from jobwatch import web as ui  # noqa: E402
from jobwatch.models import Job  # noqa: E402

from .conftest import FakeWeb  # noqa: E402

HEAD = ["CASE_NUMBER", "CASE_STATUS", "FULL_TIME_POSITION", "EMPLOYER_NAME", "JOB_TITLE", "SOC_TITLE",
        "WORKSITE_CITY", "WORKSITE_STATE", "WAGE_RATE_OF_PAY_FROM", "WAGE_RATE_OF_PAY_TO", "WAGE_UNIT_OF_PAY",
        "PW_WAGE_LEVEL", "BEGIN_DATE", "EMPLOYER_POC_EMAIL"]
LINKS = ("""<a href="/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2025_Q3.xlsx">FY25 Q3</a>
<a href="/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2025_Q4.xlsx">FY25 Q4</a>
<a href="https://www.dol.gov//media/LCA_Disclosure_Data_FY2026_Q2.xlsx">FY26 Q2</a>
<a href="/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2024_Q4.xlsx">FY24 Q4</a>
<a href="/sites/dolgov/files/ETA/oflc/pdfs/FY26Q3/CW-1_Disclosure_Data_FY2026_Q3.xlsx">another program</a>""")
ROBOTS = f"{lca.SITE}/robots.txt"
FY26 = "https://www.dol.gov//media/LCA_Disclosure_Data_FY2026_Q2.xlsx"  # the page really links it with two slashes


def filing(n, employer, title, city, state, wage, unit="Year", status="Certified", full="Y", level="II",
           year=2026, high=None):
    return [f"I-200-{n:05d}", status, full, employer, title, "Software Developers", city, state, wage, high, unit,
            level, datetime(year, 3, 1), "someone@example.com"]


def acme(n, title, city, state, wage, **kw):
    return filing(n, "Acme Corp", title, city, state, wage, **kw)


ROWS = [
    acme(1, "Senior Software Engineer", "AUSTIN", "TX", 150_000),
    acme(2, "Senior Software Engineer", "Austin", "TX", 160_000),
    acme(3, "Senior Software Engineer", "Austin", "TX", 170_000, level="III", year=2025),
    acme(4, "Senior Software Engineer", "Austin", "TX", 80, unit="Hour"),
    acme(5, "Senior Software Engineer", "Dallas", "TX", 140_000),
    acme(6, "Senior Software Engineer", "Seattle", "WA", 200_000),
    acme(7, "Senior Software Engineer", "Austin", "TX", 999_000, status="Certified - Withdrawn"),
    acme(8, "Senior Software Engineer", "Austin", "TX", 999_000, full="N"),
    acme(9, "Accounts Clerk", "Austin", "TX", 45_000),
    acme(10, "Software Engineer", "Austin", "TX", 120_000), acme(11, "Software Engineer", "Austin", "TX", 125_000),
    acme(12, "Software Engineer", "Austin", "TX", 130_000),
    filing(13, "Initech, Inc.", "Data Analyst", "Denver", "CO", 90_000),
    filing(14, "Initech, Inc.", "Data Analyst", "Denver", "CO", 95_000),
    filing(15, "Globex Systems, Inc.", "Staff Software Engineer", "Reno", "NV", 15_000, unit="Month"),
    filing(16, "Globex Systems, Inc.", "Staff Software Engineer", "Reno", "NV", 3_500, unit="Week"),
    filing(17, "Globex Systems, Inc.", "Staff Software Engineer", "Reno", "NV", 7_000, unit="Bi-Weekly"),
]


def workbook(path: Path, rows=ROWS, head=HEAD) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(head)
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


def job(title="Senior Software Engineer", company="Acme", where=("Austin, TX",)):
    return Job(source="greenhouse", company=company.lower(), id="1", title=title, url="u", company_name=company,
               locations=list(where))


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(lca, "PAUSE", 0.0)


@pytest.fixture
def cache(tmp_path):
    """A cache made from the made-up workbook, through update() with the DOL's page and downloads faked."""
    src = workbook(tmp_path / "source.xlsx")
    return update_from(tmp_path / "lca.db", src)


def update_from(path, src, page=None, **kw):
    said = []
    fetched = []

    def fetch(url, dest):
        fetched.append(url)
        dest.write_bytes(src.read_bytes())
        return dest.stat().st_size

    fake = FakeWeb({ROBOTS: "User-agent: *\nAllow: /\n", lca.PAGE: LINKS if page is None else page})
    out = lca.update(path, say=said.append, get_text=fake, fetch=fetch, **kw)
    return path, out, said, fetched, fake


# -- which files, which wages

def test_the_newest_file_of_the_last_two_fiscal_years_is_found_on_the_page():
    assert lca.find_files(LINKS) == [
        (2026, 2, "https://www.dol.gov//media/LCA_Disclosure_Data_FY2026_Q2.xlsx"),
        (2025, 4, "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2025_Q4.xlsx")]
    assert lca.find_files("<p>nothing</p>") == []


def test_wages_become_yearly():
    assert lca.yearly(80, "Hour") == 166_400 and lca.yearly("3,500", "week") == 182_000
    assert lca.yearly(7000, "Bi-Weekly") == 182_000 and lca.yearly(15000, "Month") == 180_000
    assert lca.yearly(150_000, "Year") == 150_000
    assert lca.yearly(5, "Hour") is None and lca.yearly("n/a", "Year") is None and lca.yearly(100_000, "") is None


def test_employer_names_match_the_boards_names():
    for filed, board in (("Initech Systems, Inc.", "Initech"), ("Umbrella, Inc.", "Umbrella"),
                         ("Hooli USA, Inc.", "Hooli"), ("ACME CORP", "Acme"), ("Globex Systems, Inc.", "globex")):
        assert lca.employer_key(filed) == lca.employer_key(board), (filed, board)
    assert lca.job_keys(job(company="Initech Systems")) == ["initech"]


# -- the cache

def test_update_keeps_certified_full_time_rows_only(cache):
    path, out, said, fetched, _ = cache
    # The page names FY2026 Q2 and FY2025 Q4; the same workbook is read for both, so each case is kept once.
    assert fetched == [FY26, "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2025_Q4.xlsx"]
    assert [(f["fy"], f["quarter"], f["rows"]) for f in out["files"]] == [(2026, 2, 15), (2025, 4, 0)]
    assert out["rows"] == 15 and out["bytes"] == path.stat().st_size
    assert any("filings kept" in s for s in said) and said[-1].startswith("Done: 15 filings")
    assert not list(path.parent.glob("lca-download*")) and not list(path.parent.glob("*.new"))
    index = lca.Index.open(path)
    assert index.info()["rows"] == 15 and index.info()["years"] == {2026: 15}
    stored = [tuple(r) for r in index.db.execute("SELECT * FROM filings WHERE case_no='I-200-00004'")]
    assert stored[0][2:5] == ("Acme Corp", "acme", "Senior Software Engineer") and stored[0][7] == 166_400
    assert "someone@example.com" not in json.dumps([tuple(r) for r in index.db.execute("SELECT * FROM filings")])
    index.close()


def test_robots_txt_is_obeyed(tmp_path):
    src = workbook(tmp_path / "source.xlsx")
    fake = FakeWeb({ROBOTS: "User-agent: *\nDisallow: /agencies/\n", lca.PAGE: LINKS})
    with pytest.raises(lca.LcaError, match="robots"):
        lca.update(tmp_path / "lca.db", say=lambda s: None, get_text=fake, fetch=lambda u, d: 0)
    assert fake.calls == [ROBOTS] and not (tmp_path / "lca.db").exists() and src.exists()


def test_a_page_without_files_or_a_changed_layout_is_said_plainly(tmp_path):
    with pytest.raises(lca.LcaError, match="links no LCA disclosure files"):
        update_from(tmp_path / "lca.db", workbook(tmp_path / "s.xlsx"), page="<p>moved</p>")
    bad = workbook(tmp_path / "bad.xlsx", rows=[], head=["CASE_NUMBER", "EMPLOYER_NAME"])
    with pytest.raises(lca.LcaError, match="no CASE_STATUS"):
        update_from(tmp_path / "lca.db", bad)


def test_a_failed_update_keeps_the_old_cache(cache, tmp_path):
    path, *_ = cache
    before = path.read_bytes()
    bad = workbook(tmp_path / "bad.xlsx", rows=[], head=["CASE_NUMBER"])
    with pytest.raises(lca.LcaError):
        update_from(path, bad)
    assert path.read_bytes() == before and not list(path.parent.glob("*.new"))


def test_the_cache_is_stale_after_30_days_only_once_it_exists(cache, tmp_path):
    path, *_ = cache
    now = datetime.now(timezone.utc)
    assert not lca.stale(path, now) and lca.stale(path, now + timedelta(days=31))
    assert not lca.stale(tmp_path / "never.db")
    assert lca.Index.open(tmp_path / "never.db") is None


# -- the estimate

def test_a_title_in_the_jobs_city_comes_first(cache):
    path, *_ = cache
    index = lca.Index.open(path)
    est = lca.for_job(index, job())
    assert (est.where, est.count, est.median, est.p25, est.p75) == ("Austin, TX", 4, 163_200, 157_500, 167_300)
    assert est.levels == {"II": 3, "III": 1} and est.company == "Acme Corp"
    assert [(e["wage"], e["year"]) for e in est.examples] == [(166_400, 2026), (160_000, 2026), (150_000, 2026)]
    assert est.line() == "H-1B filings: median $163K base (25th–75th $158K–$167K), 4 filings (Austin, TX)"
    assert est.credit == "Data: U.S. DOL LCA disclosures" and "not total compensation" in est.label
    assert est.to_dict()["line"] == est.line() and "rows" not in est.to_dict()
    # the senior filings at other worksites stay out of an Austin estimate, and withdrawn or part-time ones everywhere
    assert max(r["wage"] for r in est.rows) == 170_000
    index.close()


def test_with_too_few_in_the_city_the_state_then_the_country_is_used(cache):
    index = lca.Index.open(cache[0])
    assert lca.for_job(index, job(where=("Houston, TX",))).where == "TX"
    assert lca.for_job(index, job(where=("Houston, TX",))).count == 5
    us = lca.for_job(index, job(where=("Remote - United States",)))
    assert (us.where, us.count, us.median) == (lca.US, 6, 163_200)
    assert lca.for_job(index, job(where=("Remote (United States)",))).count == 6
    index.close()


def test_seniority_and_the_kind_of_work_have_to_match(cache):
    index = lca.Index.open(cache[0])
    plain = lca.for_job(index, job(title="Software Engineer, Payments"))
    assert (plain.count, plain.median) == (3, 125_000)  # not the senior filings
    assert lca.for_job(index, job(title="Principal Software Engineer")) is None
    assert lca.for_job(index, job(title="Account Executive")) is None
    assert lca.for_job(index, job(title="Senior Software Engineer", company="Hooli")) is None
    staff = lca.for_job(index, job(title="Staff Software Engineer", company="Globex", where=("Remote",)))
    assert (staff.where, staff.count, staff.median) == (lca.US, 3, 182_000)  # month, week and bi-week, as years
    index.close()


def test_title_readings_drop_the_team_ids_and_filler():
    sw = frozenset({"software", "engineer"})
    team = frozenset({"software", "engineer", "platform"})
    assert lca.title_words("Senior Software Engineer, Platform") == [sw, team]
    assert lca.title_words("Software Engineer Hybrid 19166") == [sw]
    # the role can come after the team: "Incident Response, Sr Staff Engineer"
    after = lca.title_words("Incident Response, Sr Staff Engineer")
    assert after[-1] == frozenset({"incident", "response", "engineer"})
    assert lca.title_words("SDE III") == [frozenset({"software", "engineer"})]
    assert lca.same_work([sw], [frozenset({"software", "development", "engineer"})])
    assert not lca.same_work([sw], [frozenset({"software", "quality", "assurance", "engineer", "lead"})])


def test_fewer_than_three_filings_is_no_estimate(cache):
    index = lca.Index.open(cache[0])
    assert lca.for_job(index, job(title="Data Analyst", company="Initech")) is None
    assert index.estimate(["initech"], "Data Analyst") is None
    assert lca.for_job(None, job()) is None
    assert index.titles(["acme"])[0] == {"title": "senior software engineer", "count": 6, "median": 163_200}
    index.close()


# -- where it shows

def _cache_next_to_state(watchlist, tmp_path):
    src = workbook(tmp_path / "source.xlsx")
    return update_from(tmp_path / "lca.db", src)


def test_lookups_without_a_cache_say_how_to_make_one(web, watchlist, capsys):
    cli.main(["-c", str(watchlist), "fetch"])
    capsys.readouterr()
    with pytest.raises(SystemExit, match="jobwatch lca update"):
        cli.main(["-c", str(watchlist), "lca", "acme"])
    cli.main(["-c", str(watchlist), "show", "101"])
    assert "H-1B" not in capsys.readouterr().out


def test_lca_shows_wherever_expected_pay_does(web, watchlist, tmp_path, capsys, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    cli.main(["-c", str(watchlist), "fetch"])
    _cache_next_to_state(watchlist, tmp_path)
    store_path = tmp_path / "lca.db"
    assert store_path.is_file()
    capsys.readouterr()

    cli.main(["-c", str(watchlist), "show", "101"])
    out = capsys.readouterr().out
    assert "H-1B filings: median $" in out and "Data: U.S. DOL LCA disclosures" in out
    assert "not total compensation" in out
    cli.main(["-c", str(watchlist), "lca", "acme", "senior", "software", "engineer"])
    out = capsys.readouterr().out
    assert "6 filings (US-wide)" in out and "Senior Software Engineer, Austin TX: $170,000 (level III) 2025" in out
    cli.main(["-c", str(watchlist), "lca", "acme"])
    assert "senior software engineer" in capsys.readouterr().out
    cli.main(["-c", str(watchlist), "lca"])
    assert "15 certified full-time filings" in capsys.readouterr().out

    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    got = mcp.get_job("101")
    assert got["lca_pay"]["count"] == 4 and got["lca_pay"]["credit"] == lca.CREDIT and "expected_pay" not in got
    from jobwatch.config import load
    from jobwatch.store import Store
    store = Store(load(watchlist).state)
    store.set_status(["greenhouse:acme:101"], "queued")
    store.close()
    assert mcp.list_queued_jobs()[0]["lca_pay"]["median"] == got["lca_pay"]["median"]
    cli.main(["-c", str(watchlist), "queue"])
    assert "H-1B filings: median" in capsys.readouterr().out
    assert report.lca_lines(None) == []


def test_the_page_gets_lca_pay_with_or_without_levels(web, watchlist, tmp_path, monkeypatch):
    cli.main(["-c", str(watchlist), "fetch"])
    _cache_next_to_state(watchlist, tmp_path)
    app = ui.App(watchlist)
    job_ = app.get_job({"key": ["101"]})
    assert job_["lca_pay"]["count"] == 4 and "expected_pay" not in job_  # pay.levels is off
    today = {j["key"]: j for j in app.get_digest({})["jobs"]}
    assert today["greenhouse:acme:101"]["lca_pay"]["where"] == "Austin, TX"
    assert "lca_pay" not in today["lever:globex:aaaa-1111"]  # filed by no one the cache knows
    # with Levels.fyi refusing (or off), the H-1B estimate is all there is, and it's still there
    watchlist.write_text(watchlist.read_text() + "pay: {levels: true}\n")
    monkeypatch.setattr(sources, "get_text", FakeWeb({}))
    both = ui.App(watchlist).post_pay({"keys": ["greenhouse:acme:101"]})
    assert both["enabled"] and both["pay"]["greenhouse:acme:101"] is not None


# -- the schedule

def test_the_schedule_refreshes_an_old_cache_once_a_day_at_most(cache, watchlist, monkeypatch, tmp_path):
    app = ui.App(watchlist, background=False)
    refresher = ui.Refresher(app)
    calls = []
    monkeypatch.setattr(lca, "update", lambda path, say=print, **kw: calls.append(path) or {"rows": 7})
    now = datetime.now(timezone.utc)
    assert not refresher.refresh_lca(now) and calls == []  # fresh
    assert refresher.refresh_lca(now + timedelta(days=31)) and calls == [tmp_path / "lca.db"]
    assert not refresher.refresh_lca(now + timedelta(days=31, hours=2))  # not again within a day
    monkeypatch.setattr(sources, "get_text", FakeWeb({}))


def test_without_a_cache_the_schedule_downloads_nothing(watchlist, monkeypatch):
    refresher = ui.Refresher(ui.App(watchlist, background=False))
    monkeypatch.setattr(lca, "update", lambda *a, **k: pytest.fail("downloaded without being asked"))
    assert not refresher.refresh_lca(datetime.now(timezone.utc) + timedelta(days=90))
