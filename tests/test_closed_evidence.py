"""Closed needs positive evidence: a maintenance, outage or challenge page, a 5xx, a refusal or a redirect to the home
page is 'unknown' (nothing marked, nothing noticed); a 404, a 'position filled' page or an absence from a board that
listed jobs is closed; and a notice needs two looks (and a third, at the popup). Made-up Avature portal and board."""

import contextvars
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest

from jobwatch import closed_notice, config, sources, watch
from jobwatch.models import Job
from jobwatch.store import Store
from jobwatch.web import ApiError, App

BOARD = "globex.avature.net"
LINK = f"https://{BOARD}/careers/JobDetail/Incident-Response-Sr-Staff-Engineer-19166/19166"

# What an Avature portal answers with, status 200, while it is down: a long page, mostly styles.
MAINTENANCE = ("<html><head><title>Maintenance</title><style>"
               + "@font-face { font-family: 'Open Sans'; src: url('/fonts/open.woff') format('woff'); }\n" * 500
               + "</style></head><body><h1>We're sorry</h1><p>The system is currently undergoing maintenance. "
               "Please try again later.</p></body></html>")
POSTING = ('<html><head><title>Incident Response Sr Staff Engineer</title>'
           '<meta property="og:title" content="Incident Response Sr Staff Engineer"></head><body>'
           '<script type="application/ld+json">{"@type": "JobPosting", "title": "Incident Response Sr Staff '
           'Engineer", "description": "Lead incident response at Globex."}</script></body></html>')
FILLED = "<html><head><title>Globex Careers</title></head><body><p>This position has been filled.</p></body></html>"


@pytest.fixture
def cfg(watchlist):
    return config.load(watchlist)


@pytest.fixture
def store(cfg):
    s = Store(cfg.state)
    yield s
    s.close()


def tracked(store, status="applied", source="avature", company=BOARD, pid="19166", url=LINK, title="Incident Response"):
    job = Job(source=source, company=company, id=pid, title=title, url=url, company_name="Globex")
    store.keep(job)
    store.set_status([job.key], status)
    return job


def serving(answer):
    """A page reader answering every address with `answer` (text, or an exception to raise)."""
    def get(url, *args, **kwargs):
        if isinstance(answer, Exception):
            raise answer
        return answer
    return get


def ago(store, job, hours):
    """Make the job's closed mark `hours` old."""
    stamp = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="microseconds")
    store.db.execute("UPDATE jobs SET closed=? WHERE key=?", (stamp, job.key))
    store.db.commit()


def result(store, job, get=None, page=None):
    [c] = watch.check_postings(store, get=get, page=page, jobs=[store.find(job.key)])
    return c.result, c.detail


# -- what is not evidence

def test_a_maintenance_page_is_unknown_never_closed(store):
    j = tracked(store)
    got, detail = result(store, j, get=serving(MAINTENANCE))
    assert got == "unknown" and "Maintenance" in detail
    assert store.find(j.key)[1]["closed"] is None
    assert watch.check_postings(store, jobs=[store.find(j.key)], get=serving(MAINTENANCE))[0].result == "unknown"


def test_the_maintenance_page_is_caught_whichever_way_it_is_read(store):
    for text in (MAINTENANCE, "<title>Service Unavailable</title><p>Back soon</p>",
                 "<html><body><p>Our site is temporarily unavailable. Please try again later.</p></body></html>",
                 "<title>Just a moment...</title><p>Checking your browser before accessing the site.</p>"):
        assert sources.unavailable_page(text)
    assert not sources.unavailable_page(POSTING)
    long_posting = POSTING + "<p>" + "Great work. " * 500 + "If it fails, try again later.</p>"
    assert not sources.unavailable_page(long_posting)  # a real posting may say it in passing
    with pytest.raises(sources.Unavailable):
        watch._guarded(serving(MAINTENANCE))("https://x.test/job/1")


def test_a_503_a_429_and_a_refusal_are_unknown(store):
    j = tracked(store)
    for err in (sources.SourceError(f"{LINK}: HTTP 503"), sources.SourceError(f"{LINK}: HTTP 429"),
                sources.Refused(f"{LINK}: HTTP 403"), sources.SourceError(f"{LINK}: timed out")):
        assert result(store, j, get=serving(err))[0] == "unknown"
    assert store.find(j.key)[1]["closed"] is None


def test_the_real_reader_turns_a_503_and_a_redirect_home_into_errors(monkeypatch):
    class Reply:
        def __init__(self, final, body=b"<html>ok</html>"):
            self.final, self.body, self.headers = final, body, {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def geturl(self):
            return self.final

        def read(self):
            return self.body

    monkeypatch.setattr(sources, "_patience", contextvars.ContextVar("p", default=(0, 1)))  # no waiting on a 503

    def error(*a, **k):
        raise urllib.error.HTTPError(LINK, 503, "Service Unavailable", {}, None)
    monkeypatch.setattr(sources.urllib.request, "urlopen", error)
    with pytest.raises(sources.SourceError) as e:
        sources.get_text(LINK)
    assert not isinstance(e.value, sources.NotFound)

    monkeypatch.setattr(sources.urllib.request, "urlopen", lambda *a, **k: Reply(f"https://{BOARD}/"))
    with pytest.raises(sources.Unavailable, match="home page"):
        sources.get_text(LINK)
    monkeypatch.setattr(sources.urllib.request, "urlopen", lambda *a, **k: Reply(LINK))
    assert sources.get_text(LINK) == "<html>ok</html>"
    monkeypatch.setattr(sources.urllib.request, "urlopen", lambda *a, **k: Reply(f"https://{BOARD}/careers/Search"))
    assert sources.get_text(LINK) == "<html>ok</html>"  # another page, not the home page: for the page to say


def test_a_redirect_to_the_home_page_is_unknown(store):
    j = tracked(store)
    home = sources.Unavailable(f"{LINK}: redirected to the site's home page")
    assert result(store, j, get=serving(home))[0] == "unknown"
    assert store.find(j.key)[1]["closed"] is None


def test_a_board_that_lists_no_jobs_closes_nothing(store, monkeypatch):
    j = tracked(store, source="greenhouse", company="globex", pid="77", url="https://boards.greenhouse.io/globex/jobs/77")
    monkeypatch.setattr(sources, "fetch", lambda *a, **k: [])
    got, detail = result(store, j)
    assert got == "unknown" and "listed no jobs" in detail and store.find(j.key)[1]["closed"] is None


def test_a_sync_of_an_empty_board_closes_nothing(store):
    j = tracked(store, source="greenhouse", company="globex", pid="77", url="https://boards.greenhouse.io/globex/jobs/77")
    store.sync("greenhouse", "globex", [])
    assert store.find(j.key)[1]["closed"] is None
    other = Job(source="greenhouse", company="globex", id="78", title="Other", url="u")
    store.sync("greenhouse", "globex", [other])  # a board that lists jobs, without 77: that one is gone
    assert store.find(j.key)[1]["closed"] is not None


def test_a_searched_boards_listing_never_closes_a_job_you_follow(tmp_path, monkeypatch):
    """A Workday or sitemap board lists only the roles whose titles match the watchlist (up to a cap): a queued job
    that isn't in it may just not match. It stays open (the daily check of its own page decides); one you never
    acted on, missing from the same listing, is still closed."""
    from tests.test_big_boards import eightfold_web
    path = tmp_path / "watchlist.yaml"
    path.write_text("companies:\n  - eightfold:globex\nfilters:\n  titles: [engineer]\n", encoding="utf-8")
    cfg, store = config.load(path), Store(tmp_path / "state.db")
    followed = {s: Job(source="eightfold", company="globex", id=f"90{i}", title=f"Platform Architect {i}", url="u",
                       description="x") for i, s in enumerate(("queued", "applied", "screening", "interviewing",
                                                              "offer", "new"))}
    store.sync("eightfold", "globex", list(followed.values()))
    for status, j in followed.items():
        if status != "new":
            store.set_status([j.key], status)
    monkeypatch.setattr(watch, "check_daily", lambda *a, **k: [])  # the fetch's own listing is what's tested
    watch.fetch_all(cfg, store, get=eightfold_web())
    closed = {s: store.find(j.key)[1]["closed"] is not None for s, j in followed.items()}
    assert closed == {"queued": False, "applied": False, "screening": False, "interviewing": False, "offer": False,
                      "new": True}


def test_a_complete_boards_listing_still_closes_a_dropped_job(store):
    gh = [Job(source="greenhouse", company="globex", id=i, title=f"Engineer {i}", url="u") for i in ("1", "2")]
    store.sync("greenhouse", "globex", gh)
    store.set_status([gh[0].key], "queued")
    store.sync("greenhouse", "globex", [gh[1]])
    assert store.find(gh[0].key)[1]["closed"] is not None  # a complete listing: closed, then to be confirmed
    assert store.closed_notices() == []  # and not a notice until a second look (see test_one_closed_look...)


def test_sync_spares_the_statuses_it_is_told_to(store):
    a, b, c = (Job(source="workday", company="globex.wd1/Site", id=i, title=f"Architect {i}", url="u") for i in "abc")
    store.sync("workday", "globex.wd1/Site", [a, b, c])
    store.set_status([a.key], "queued")
    store.sync("workday", "globex.wd1/Site", [c], spare=("queued",))
    assert [store.find(j.key)[1]["closed"] is not None for j in (a, b, c)] == [False, True, False]


# -- what is

def test_a_404_is_closed(store):
    j = tracked(store)
    assert result(store, j, get=serving(sources.NotFound(f"{LINK}: HTTP 404")))[0] == "closed"
    assert store.find(j.key)[1]["closed"] is not None


def test_a_page_saying_the_position_was_filled_is_closed(store):
    j = tracked(store)
    assert result(store, j, get=serving(FILLED))[0] == "closed"
    other = tracked(store, source="manual", company="globex", pid="x", url="https://jobs.example.com/job/x/1")
    robots = lambda url, *a, **k: "User-agent: *\nAllow: /\n" if url.endswith("robots.txt") else FILLED  # noqa: E731
    assert result(store, other, page=robots)[0] == "closed"
    assert sources.closed_page("<p>Job not found</p>") and sources.closed_page("<p>This job is no longer available</p>")
    assert not sources.closed_page(MAINTENANCE) and not sources.closed_page(POSTING)
    assert not sources.closed_page("<p>" + "We build things. " * 400 + "No longer available in some regions.</p>")


def test_an_open_posting_is_open(store):
    j = tracked(store)
    assert result(store, j, get=serving(POSTING))[0] == "open"


# -- two looks

def test_one_closed_look_is_no_notice_two_are(store):
    j = tracked(store)
    gone = serving(sources.NotFound(LINK))
    assert result(store, j, get=gone)[0] == "closed"  # the first look: the mark
    closed_notice.collect(store)
    assert closed_notice.unseen(store) == [] and len(store.closed_notices(pending=True)) == 1
    result(store, j, get=gone)  # at once again: still one look (a manual check twice is not two)
    assert closed_notice.unseen(store) == []
    ago(store, j, hours=24)  # the next day's check (the mark itself is made to look a day old)
    closed_notice.collect(store)
    result(store, j, get=gone)
    assert [n["key"] for n in closed_notice.unseen(store)] == [j.key]


def test_a_blip_then_open_leaves_no_notice_and_a_new_closing_starts_over(store):
    j = tracked(store)
    gone = serving(sources.NotFound(LINK))
    result(store, j, get=gone)
    ago(store, j, hours=24)
    assert result(store, j, get=serving(POSTING))[0] == "reopened"
    closed_notice.collect(store)
    assert closed_notice.unseen(store) == [] and store.closed_notices(pending=True) == []
    result(store, j, get=gone)  # closed again: a new mark, unconfirmed
    closed_notice.collect(store)
    assert closed_notice.unseen(store) == []


def test_unknown_after_a_closed_mark_does_not_confirm_it(store):
    j = tracked(store)
    result(store, j, get=serving(sources.NotFound(LINK)))
    ago(store, j, hours=24)
    assert result(store, j, get=serving(MAINTENANCE))[0] == "unknown"
    closed_notice.collect(store)
    assert closed_notice.unseen(store) == []


# -- the popup looks once more, and the recheck reopens what isn't positively closed

def confirmed_closed(store, job):
    store.set_closed(job.key, True)
    ago(store, job, hours=48)
    store.confirm_closed([job.key])
    closed_notice.collect(store)


def test_the_popup_looks_again_and_stays_quiet_about_a_blip(cfg, store, monkeypatch):
    j = tracked(store)
    confirmed_closed(store, j)
    told = []
    out = closed_notice.run(cfg, store, get=serving(MAINTENANCE), page=serving(MAINTENANCE),
                            show=lambda t, b: told.append((t, b)))
    assert told == [] and "could not be confirmed" in out
    assert [n["key"] for n in closed_notice.unseen(store)] == [j.key]  # still there, to be told another day
    out = closed_notice.run(cfg, store, get=serving(sources.NotFound(LINK)), page=serving(sources.NotFound(LINK)),
                            show=lambda t, b: told.append((t, b)))
    assert told and "1 posting closed" in told[0][0]


def test_the_popup_drops_a_posting_that_came_back(cfg, store):
    j = tracked(store)
    confirmed_closed(store, j)
    told = []
    out = closed_notice.run(cfg, store, get=serving(POSTING), page=serving(POSTING),
                            show=lambda t, b: told.append((t, b)))
    assert told == [] and store.find(j.key)[1]["closed"] is None
    assert closed_notice.unseen(store) == [] and out.startswith("No newly closed")


def test_recheck_reopens_whatever_is_not_positively_closed(cfg, store):
    maint, back, real = (tracked(store, pid=p, url=LINK.replace("19166", p), title=t) for p, t in
                         (("19166", "Maintenance victim"), ("19612", "Back again"), ("20001", "Really gone")))
    for j in (maint, back, real):
        confirmed_closed(store, j)
    pages = {"19166": MAINTENANCE, "19612": POSTING, "20001": sources.NotFound("gone")}

    def get(url, *a, **k):
        answer = pages[url.rsplit("/", 1)[1]]
        if isinstance(answer, Exception):
            raise answer
        return answer
    text = closed_notice.recheck(cfg, store, get=get, page=get)
    assert "1 still closed" in text and "Really gone" in text
    assert "1 open: reopened" in text and "Back again" in text
    assert "1 could not be told" in text and "Maintenance victim" in text
    assert [store.find(j.key)[1]["closed"] is None for j in (maint, back, real)] == [True, True, False]
    assert [n["title"] for n in closed_notice.unseen(store)] == ["Really gone"]


def test_recheck_is_a_command(cfg, store, capsys):
    from jobwatch.cli import main
    j = tracked(store)
    confirmed_closed(store, j)
    store.db.execute("UPDATE jobs SET closed=NULL WHERE key=?", (j.key,))  # nothing marked: nothing to look at
    store.db.commit()
    main(["-c", str(cfg.path), "notify-closed", "--recheck"])
    assert "Looked again at 0 jobs marked closed." in capsys.readouterr().out


# -- what every tab reads: closed (two looks), checking (one), or open

def queued_jobs(store):
    """Three queued jobs: closed on two looks, closed on one, open."""
    two, one, none = (tracked(store, status="queued", source="greenhouse", company="globex", pid=p,
                              url=f"https://boards.greenhouse.io/globex/jobs/{p}", title=t)
                      for p, t in (("1", "Staff Engineer"), ("2", "Platform Engineer"), ("3", "Data Engineer")))
    store.set_closed(two.key, True)
    store.set_closed(one.key, True)
    store.confirm_closed([two.key])
    return two, one, none


def test_every_record_says_closed_checking_or_open(store):
    from jobwatch.store import closed_state
    two, one, none = queued_jobs(store)
    assert [closed_state(store.find(j.key)[1]) for j in (two, one, none)] == ["closed", "checking", None]
    queued = store.jobs(("queued",), include_closed=True)
    assert [closed_state(r) for j, r in queued if j.key == one.key] == ["checking"]
    assert [closed_state(r) for j, r in store.search("Platform")] == ["checking"]
    store.set_closed(two.key, False)  # reopened and closed again: a new mark, to be confirmed again
    store.set_closed(two.key, True)
    assert closed_state(store.find(two.key)[1]) == "checking"


def test_the_queue_page_and_the_other_tabs_read_the_same_state(cfg, store):
    from jobwatch.web import App
    two, one, none = queued_jobs(store)
    app = App(cfg.path)
    queue = {j["key"]: j for j in app.get_queue({})}
    assert {k: j["closed_state"] for k, j in queue.items()} == {two.key: "closed", one.key: "checking", none.key: None}
    assert queue[two.key]["verdict"] == {"call": "skip", "text": "The posting is closed."}
    assert not (queue[one.key]["verdict"] or {}).get("text", "").startswith("The posting is closed")  # one look: no
    assert {j["key"]: j["closed_state"] for j in app.get_jobs({"status": ["queued"]})} == \
        {two.key: "closed", one.key: "checking", none.key: None}
    assert app.get_job({"key": [one.key]})["closed_state"] == "checking"
    assert app.get_job({"key": [two.key]})["closed_state"] == "closed"
    from jobwatch import company
    view = company.view(cfg, store, "Globex")
    assert {j["key"]: j["closed_state"] for j in view["jobs"]} == {
        two.key: "closed", one.key: "checking", none.key: None}
    assert "posting may have closed" in company.text(view) and "posting closed" in company.text(view)


def test_the_command_line_and_the_queue_text_say_checking_for_one_look(store, cfg, capsys):
    from jobwatch.cli import main
    two, one, none = queued_jobs(store)
    main(["-c", str(cfg.path), "list", "--status", "queued"])
    lines = {line.split("`")[1]: line for line in capsys.readouterr().out.splitlines() if "`" in line}
    assert "[closed]" in lines[two.key] and "[checking" in lines[one.key]
    assert "[closed" not in lines[none.key] and "[checking" not in lines[none.key]


def test_a_queue_card_can_skip_a_confirmed_closed_job_with_undo_and_not_an_unconfirmed_one(cfg, store):
    two, one, _ = queued_jobs(store)
    app = App(cfg.path)
    with pytest.raises(ApiError, match="isn't confirmed closed"):
        app.post_closed_act({"action": "skip", "key": one.key})
    store.dismiss_closed_notices()  # 'Got it' was pressed: the Queue card still skips
    done = app.post_closed_act({"action": "skip", "key": two.key})
    rec = store.find(two.key)[1]
    assert rec["status"] == "skipped" and "Posting closed" in rec["note"] and done["done"] == 1
    app.post_closed_undo({"undo": done["undo"]})
    assert store.find(two.key)[1]["status"] == "queued"


def test_the_queue_page_shows_checking_amber_closed_red_and_skip_with_an_inline_confirm():
    from pathlib import Path
    page = (Path(closed_notice.__file__).parent / "static" / "index.html").read_text()
    for text in (".badge.checking", "badge checking", "`closed ${fmtDay(on)}`", "function skipClosedButton",
                 'closedState(job) === "closed" ? skipClosedButton(job)', '"Undo", 8000', "/api/closed/act",
                 "Skip this job? You can change the status back."):
        assert text in page, text
    assert "window.confirm" not in page[page.index("function skipClosedButton"):page.index("function queueCard")]
    assert 'job.closed ? h("span", { class: "badge closed" }' not in page  # the old unconditional red badge
