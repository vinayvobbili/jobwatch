"""The daily check that a posting is still up: a job site's page, and the scheduled check that runs it."""

import json
from datetime import timedelta

import pytest

from jobwatch import alerts, config, sources, watch
from jobwatch.models import Job
from jobwatch.store import Store

SITE = "https://jobs.example.com"
URL = f"{SITE}/job/software-engineer/42"


def posting_page(valid_through: str | None = None) -> str:
    data = {"@context": "https://schema.org", "@type": "JobPosting", "title": "Software Engineer",
            "description": "Build things at Initech."}
    if valid_through:
        data["validThrough"] = valid_through
    return f'<html><head><script type="application/ld+json">{json.dumps(data)}</script></head><body></body></html>'


def pages(**by_url):
    """A page fetcher: robots.txt allows everything, `by_url` serves the rest (an Exception is raised), the
    rest 404."""
    seen = []

    def get(url, *args, **kwargs):
        seen.append(url)
        if url.endswith("/robots.txt"):
            return "User-agent: *\nAllow: /\n"
        if url not in by_url:
            raise sources.NotFound(url)
        if isinstance(by_url[url], Exception):
            raise by_url[url]
        return by_url[url]

    get.seen = seen
    return get


def job(url=URL, description="") -> Job:
    return Job(source="manual", company="initech", id="software-engineer", title="Software Engineer", url=url,
               company_name="Initech", description=description)


def test_a_page_with_a_past_validthrough_is_gone():
    assert alerts.page_open(job(), pages(**{URL: posting_page("2026-10-29T16:50:11+00:00")})) is False
    assert alerts.page_open(job(), pages(**{URL: posting_page("2020-01-01")})) is False
    assert alerts.page_open(job(), pages(**{URL: posting_page("2020-01-01T00:00:00Z")})) is False


def test_a_page_with_a_future_or_no_validthrough_is_open():
    assert alerts.page_open(job(), pages(**{URL: posting_page("2999-01-01T00:00:00Z")})) is True
    assert alerts.page_open(job(), pages(**{URL: posting_page()})) is True
    assert alerts.page_open(job(), pages(**{URL: posting_page("soon")})) is True


def test_a_missing_page_is_gone_and_an_unreadable_one_is_an_error():
    assert alerts.page_open(job(), pages()) is False  # 404
    with pytest.raises(sources.SourceError):
        alerts.page_open(job(), pages(**{URL: sources.SourceError("HTTP 500")}))


def test_a_page_without_posting_data_is_gone_only_for_a_job_read_from_a_page():
    page = pages(**{URL: "<html><body>Search our jobs</body></html>"})
    assert alerts.page_open(job(description="Build things."), page) is False
    assert alerts.page_open(job(), page) is None  # nothing says it was ever a posting


def test_robots_linkedin_and_indeed_are_not_read():
    closed = {"User-agent: *\nDisallow: /job/\n"}
    seen = []

    def get(url, *a, **k):
        seen.append(url)
        return "User-agent: *\nDisallow: /job/\n" if url.endswith("robots.txt") else posting_page("2020-01-01")

    assert alerts.page_open(job(), get) is None and seen == [f"{SITE}/robots.txt"] and closed
    for url in ("https://www.linkedin.com/jobs/view/1", "https://uk.indeed.com/viewjob?jk=1"):
        assert alerts.page_open(job(url), pages(**{url: posting_page("2020-01-01")})) is None


def test_still_open_reads_a_job_sites_page(web):
    assert watch.still_open(job(), page=pages(**{URL: posting_page("2020-01-01")})) is False
    assert watch.still_open(job(), page=pages(**{URL: posting_page()})) is True


def added(store: Store, url=URL, status="shown", title="Software Engineer") -> str:
    j = store.add("Initech", title, url=url, status=status)
    return j.key


def test_check_daily_closes_a_job_whose_page_has_ended_and_checks_each_once_a_day(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    gone, up = added(store), added(store, f"{SITE}/job/qa/7", title="QA Engineer")
    page = pages(**{URL: posting_page("2020-01-01"), f"{SITE}/job/qa/7": posting_page("2999-01-01")})
    got = {c.job.key: c.result for c in watch.check_daily(store, page=page, watched=cfg.boards)}
    assert got == {gone: "closed", up: "open"}
    assert store.find(gone)[1]["closed"] and not store.find(up)[1]["closed"]
    assert watch.check_daily(store, page=page) == []  # both were checked today
    with store.db:
        store.db.execute("UPDATE posting_checked SET checked_at='2020-01-01T00:00:00+00:00'")
    page = pages(**{URL: posting_page("2999-01-01"), f"{SITE}/job/qa/7": posting_page("2999-01-01")})
    got = {c.job.key: c.result for c in watch.check_daily(store, page=page)}
    assert got == {up: "open"} and store.find(gone)[1]["closed"]  # a closed job off Today isn't looked at again
    store.set_status([gone], "queued")  # but a queued one is, and comes back if its page does
    with store.db:
        store.db.execute("DELETE FROM posting_checked")
    assert {c.job.key: c.result for c in watch.check_daily(store, page=page)}[gone] == "reopened"
    assert not store.find(gone)[1]["closed"]


def test_check_daily_covers_queued_jobs_not_other_statuses_and_unreadable_links(web, watchlist):
    store = Store(config.load(watchlist).state)
    queued = added(store, status="queued")
    added(store, f"{SITE}/job/a/1", status="skipped", title="Skipped One")
    added(store, "https://www.linkedin.com/jobs/view/4123456789/", title="Linked One")
    added(store, f"{SITE}/job/b/2", status="rejected", title="Rejected One")
    page = pages(**{URL: posting_page("2020-01-01")})
    assert {c.job.key: c.result for c in watch.check_daily(store, page=page)} == {queued: "closed"}
    assert not any("linkedin.com" in u or "/a/1" in u or "/b/2" in u for u in page.seen)


def test_check_daily_is_capped_and_the_oldest_unchecked_go_first(web, watchlist):
    store = Store(config.load(watchlist).state)
    keys = [added(store, f"{SITE}/job/{n}", title=f"Analyst {n}") for n in range(3)]
    page = pages(**{f"{SITE}/job/{n}": posting_page() for n in range(3)})
    assert len(watch.check_daily(store, page=page, limit=2)) == 2
    [c] = watch.check_daily(store, page=page, limit=2)  # the third, not checked yet, is next
    assert c.job.key in keys and len({*store.posting_checked()}) == 3


def test_a_scheduled_check_closes_a_taken_down_posting_and_says_so(web, watchlist, monkeypatch):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    key = added(store)
    page = pages(**{URL: posting_page("2020-01-01")})
    report = watch.fetch_all(cfg, store, page=page, by="schedule")
    assert store.find(key)[1]["closed"] and "check_postings" not in report.warnings
    [entry] = [e for e in store.activity() if e["text"] == "Found 1 posting taken down"]
    assert entry["detail"] == ["Initech: Software Engineer"]


def test_a_failed_posting_check_is_only_a_warning(web, watchlist, monkeypatch):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    key = added(store)

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(watch, "check_daily", boom)
    report = watch.fetch_all(cfg, store)
    assert report.warnings["check_postings"] == "disk full" and not store.find(key)[1]["closed"]
    assert timedelta(days=1) == watch.CHECK_EVERY
