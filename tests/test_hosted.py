"""A board whose hosted job pages are switched off while its API still lists the jobs (Ashby): each job's link
then shows "Page not found". jobwatch reads the board's own page once a day, and points its jobs at the
company's careers site (the watchlist's careers: link), or says to apply there."""

import io
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from jobwatch import cli, config, report, sources, watch
from jobwatch.store import Store
from jobwatch.web import App

from .conftest import FakeWeb

FIXTURES = Path(__file__).parent / "fixtures"
# A hosted Ashby board's page, trimmed: a live one names its organization; one switched off has null there.
OFFLINE = (FIXTURES / "ashby_board_offline.html").read_text(encoding="utf-8")
LIVE = (FIXTURES / "ashby_board_live.html").read_text(encoding="utf-8")

BOARD = "https://jobs.ashbyhq.com/initech"
ROBOTS = "https://jobs.ashbyhq.com/robots.txt"
JOB_URL = "https://jobs.ashbyhq.com/initech/c1"
CAREERS = "https://initech.example/careers"
KEY = "ashby:initech:c1"


@pytest.fixture
def pages(web, monkeypatch):
    """Stands in for sources.get_text: the hosted board's page (offline unless a test changes it) and the host's
    robots.txt, which allows it as the real one does."""
    fake = FakeWeb({ROBOTS: "User-agent: *\nDisallow: /meeting/\nDisallow: /b/\nDisallow: /api/\n", BOARD: OFFLINE})
    monkeypatch.setattr(sources, "get_text", fake)
    return fake


def with_careers(watchlist, careers=CAREERS):
    raw = yaml.safe_load(watchlist.read_text())
    raw["companies"] = [c for c in raw["companies"] if "initech" not in str(c)] + [
        {"board": "ashby:initech", "name": "Initech", "careers": careers}]
    watchlist.write_text(yaml.safe_dump(raw))
    return watchlist


def fetch(watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    r = watch.fetch_all(cfg, store)
    return cfg, store, r


def age_hosted_answer(store, days=2):
    when = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with store.db:
        store.db.execute("UPDATE hosted_pages SET checked_at=?", (when,))


def test_the_board_page_says_whether_it_is_up():
    assert sources.ashby_up(LIVE) is True
    assert sources.ashby_up(OFFLINE) is False
    assert sources.ashby_up("<html><body>Something else</body></html>") is None  # doesn't say: not known
    assert sources.hosted_url("ashby", "initech") == BOARD
    assert sources.hosted_url("greenhouse", "acme") is None  # only Ashby has the check, for now
    assert sources.hosted_up("lever", "globex", page=lambda url: 1 / 0) is None  # nothing is asked


def test_the_page_is_read_with_jobwatchs_own_user_agent(monkeypatch):
    seen = []

    def urlopen(req: urllib.request.Request, timeout):
        seen.append((req.full_url, req.get_header("User-agent")))
        return io.BytesIO(OFFLINE.encode())

    monkeypatch.setattr(sources.urllib.request, "urlopen", urlopen)
    assert sources.hosted_up("ashby", "initech") is False
    assert seen == [(BOARD, sources.USER_AGENT)] and sources.USER_AGENT.startswith("jobwatch/")


def test_an_offline_board_without_a_careers_link_keeps_its_links_and_says_where_to_apply(watchlist, pages, capsys):
    _, store, r = fetch(watchlist)
    job, _ = store.find(KEY)
    assert job.url == JOB_URL and job.posting_url == ""
    assert job.link_note == ("Initech's Ashby job pages are offline (its link shows \"Page not found\"): apply "
                             "through Initech's own careers site.")
    assert set(r.warnings) == {"ashby:initech"} and "careers: https://" in r.warnings["ashby:initech"]
    assert pages.calls == [ROBOTS, BOARD]  # robots.txt first; one page per board
    # Boards on other systems are left alone.
    assert store.find("lever:globex:aaaa-1111")[0].link_note == ""
    summary = report.fetch_summary(r).splitlines()
    assert summary[1].startswith("  warning ashby:initech: its Ashby job pages are offline") and len(summary) == 2
    cli.main(["-c", str(watchlist), "fetch"])
    assert "warning ashby:initech" in capsys.readouterr().out  # the answer is kept: still offline
    store.close()


def test_a_careers_link_takes_the_jobs_there(watchlist, pages):
    _, store, r = fetch(with_careers(watchlist))
    job, _ = store.find(KEY)
    assert (job.url, job.posting_url) == (CAREERS, JOB_URL)
    assert job.link_note == "Initech's Ashby job pages are offline: this job's link goes to Initech's own careers site."
    assert r.warnings == {}  # nothing to do about it
    store.close()


def test_the_answer_is_kept_for_a_day_and_the_links_come_back_with_the_pages(watchlist, pages):
    watchlist = with_careers(watchlist)
    cfg, store, _ = fetch(watchlist)
    pages.calls.clear()
    watch.fetch_all(cfg, store)
    assert pages.calls == [] and store.find(KEY)[0].url == CAREERS  # asked once a day at most
    pages.responses[BOARD] = LIVE
    age_hosted_answer(store)
    watch.fetch_all(cfg, store)
    assert pages.calls == [ROBOTS, BOARD]
    job, _ = store.find(KEY)
    assert (job.url, job.posting_url, job.link_note) == (JOB_URL, "", "")
    store.close()


def test_a_page_that_cant_be_read_changes_nothing(watchlist, pages):
    pages.responses[BOARD] = sources.SourceError("timed out")
    cfg, store, r = fetch(watchlist)
    assert store.find(KEY)[0].link_note == "" and r.warnings == {} and store.hosted_page("ashby", "initech") is None
    pages.responses[BOARD] = OFFLINE  # found offline once...
    watch.fetch_all(cfg, store)
    pages.responses[BOARD] = sources.SourceError("timed out")  # ...then can't be read: still offline
    age_hosted_answer(store)
    r = watch.fetch_all(cfg, store)
    assert store.find(KEY)[0].link_note and "ashby:initech" in r.warnings
    # A 404 or a page that doesn't say is no answer either.
    assert sources.hosted_up("ashby", "initech", page=FakeWeb({})) is None
    store.close()


def test_robots_txt_is_followed(watchlist, pages):
    pages.responses[ROBOTS] = "User-agent: *\nDisallow: /\n"
    _, store, _ = fetch(watchlist)
    assert pages.calls == [ROBOTS] and store.find(KEY)[0].link_note == ""
    store.close()


def test_a_board_that_fails_is_not_asked_about(watchlist, pages, web):
    web.responses["https://api.ashbyhq.com/posting-api/job-board/initech?includeCompensation=true"] = \
        sources.SourceError("HTTP 500")
    _, store, r = fetch(watchlist)
    assert BOARD not in pages.calls and "ashby:initech" in r.errors
    store.close()


def test_the_note_shows_wherever_the_job_does(watchlist, pages, capsys, monkeypatch):
    cli.main(["-c", str(watchlist), "fetch"])
    capsys.readouterr()
    cli.main(["-c", str(watchlist), "show", KEY])
    assert "\nLink: Initech's Ashby job pages are offline" in capsys.readouterr().out
    cli.main(["-c", str(watchlist), "digest"])
    assert "**Link:** Initech's Ashby job pages are offline" in capsys.readouterr().out
    app = App(watchlist)
    today = {j["key"]: j for j in app.get_digest({})["jobs"]}
    assert today[KEY]["link_note"].startswith("Initech's Ashby")
    assert today["lever:globex:aaaa-1111"]["link_note"] is None
    assert app.get_job({"key": [KEY]})["link_note"].startswith("Initech's Ashby")
    mcp = pytest.importorskip("jobwatch.mcp_server")
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    assert mcp.get_job(KEY)["link_note"].startswith("Initech's Ashby")
    assert "warning ashby:initech" in mcp.fetch_jobs()
    page = (Path(sources.__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    assert "linkNote(job)" in page and "linkNote(j)" in page  # the card and the details


def test_check_keeps_a_listed_job_open_with_the_note(watchlist, pages, capsys):
    cli.main(["-c", str(watchlist), "fetch"])
    store = Store(config.load(watchlist).state)
    store.set_status([KEY], "applied")
    [c] = watch.check_postings(store)
    assert c.result == "open" and c.detail.startswith("Initech's Ashby job pages are offline")
    # The board's careers link, once the watchlist has one, is used by the check too.
    with_careers(watchlist)
    [c] = watch.check_postings(store, watched=config.load(watchlist).boards)
    assert c.result == "open" and store.find(KEY)[0].url == CAREERS and "goes to Initech's own" in c.detail
    store.close()
    capsys.readouterr()
    cli.main(["-c", str(watchlist), "check", "--all"])
    assert "open      ashby:initech:c1" in capsys.readouterr().out


def test_check_asks_about_a_board_that_isnt_watched(watchlist, pages, web):
    _, store, _ = fetch(watchlist)
    store.set_status([KEY], "queued")
    with store.db:
        store.db.execute("DELETE FROM hosted_pages")
        store.db.execute("UPDATE jobs SET data=json_set(data, '$.link_note', '') WHERE key=?", (KEY,))
    pages.calls.clear()
    [c] = watch.check_postings(store)
    assert pages.calls == [ROBOTS, BOARD] and store.find(KEY)[0].link_note == c.detail != ""
    store.close()


def test_mark_hosted_round_trips():
    job = sources.parse_ashby({"jobs": [{"id": "c1", "title": "Engineer", "jobUrl": JOB_URL}]}, "initech")[0]
    assert not watch.mark_hosted(job, None, CAREERS)  # not known: nothing changes
    assert watch.mark_hosted(job, False, CAREERS) and job.url == CAREERS
    assert not watch.mark_hosted(job, False)  # again, without the link: the careers link it has is kept
    assert watch.mark_hosted(job, True) and (job.url, job.posting_url, job.link_note) == (JOB_URL, "", "")
    assert json.loads(json.dumps(job.to_dict()))["link_note"] == ""


# -- the careers: link in the watchlist


def test_a_board_entry_can_carry_a_careers_link(tmp_path):
    path = tmp_path / "w.yaml"
    path.write_text("companies:\n  - ashby:initech\n  - {board: 'lever:globex', careers: 'https://globex.example/jobs'}\n"
                    "  - {source: greenhouse, board: acme, name: Acme, careers: 'https://acme.example/careers'}\n")
    boards = {b.entry: b for b in config.load(path).boards}
    assert boards["ashby:initech"].careers == ""
    assert (boards["lever:globex"].source, boards["lever:globex"].board) == ("lever", "globex")
    assert boards["lever:globex"].careers == "https://globex.example/jobs"
    assert (boards["greenhouse:acme"].name, boards["greenhouse:acme"].careers) == ("Acme", "https://acme.example/careers")
    path.write_text("companies:\n  - {board: 'ashby:initech', careers: initech.example}\n")
    with pytest.raises(config.ConfigError, match="careers is a link"):
        config.load(path)
    path.write_text("companies:\n  - ashby:initech\n  - {board: 'ashby:initech', careers: 'https://initech.example'}\n")
    with pytest.raises(config.ConfigError, match="listed twice"):  # the link doesn't make it another board
        config.load(path)


def test_rewriting_the_watchlist_keeps_careers_links(watchlist, monkeypatch):
    with_careers(watchlist)
    labels = lambda cfg: {b.entry: (b.name, b.careers) for b in cfg.boards}  # noqa: E731
    assert labels(config.add_board(watchlist, "workable:hooli"))["ashby:initech"] == ("Initech", CAREERS)
    assert labels(config.add_board(watchlist, "ashby:initech", "Initech Corp"))["ashby:initech"] == (
        "Initech Corp", CAREERS)  # a new name keeps the link
    cfg = config.add_board(watchlist, "workable:hooli", careers="https://hooli.example/careers")
    assert labels(cfg)["workable:hooli"] == ("", "https://hooli.example/careers")
    with pytest.raises(config.ConfigError, match="careers is a link"):
        config.add_board(watchlist, "workable:hooli", careers="not a link")
    assert labels(config.remove_board(watchlist, "lever:globex"))["ashby:initech"] == ("Initech Corp", CAREERS)
    assert "workable:hooli" not in labels(config.remove_board(watchlist, "workable:hooli"))
    # The page's Settings: what it shows is what it saves back.
    app = App(watchlist)
    s = app.get_settings({})
    assert {"source": "ashby", "board": "initech", "name": "Initech Corp", "careers": CAREERS} in s["companies"]
    app.post_settings({"companies": s["companies"]})
    assert labels(config.load(watchlist))["ashby:initech"] == ("Initech Corp", CAREERS)
    mcp = pytest.importorskip("jobwatch.mcp_server")
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    listed = {b["entry"]: b for b in mcp.list_boards()["boards"]}
    assert listed["ashby:initech"]["careers_link"] == CAREERS and listed["greenhouse:acme"]["careers_link"] == ""
    assert listed["ashby:initech"]["careers"] == BOARD  # the board's own page, as before
    added = mcp.add_board("ashby:initech", careers="https://initech.example/jobs")
    assert {b["entry"]: b["careers_link"] for b in added["boards"]}["ashby:initech"] == "https://initech.example/jobs"
