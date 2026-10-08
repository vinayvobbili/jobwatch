"""Google Careers: every role in one XML feed for job sites, filtered here by title and by place."""

from pathlib import Path

import pytest

from jobwatch import sources
from jobwatch.watch import still_open

from .conftest import FakeWeb

# Four public postings from the feed, their text trimmed: a SOAR role in Austin or remote in the US, one in
# Toronto or Atlanta whose Canadian pay comes before its US pay, a YouTube role, and a DeepMind one in Singapore.
FEED = (Path(__file__).parent / "fixtures" / "google_feed.xml").read_text(encoding="utf-8")
SOAR, ATLANTA, YOUTUBE, SINGAPORE = "109401147709498054", "105534391874134726", "108518356373381830", \
    "85260476568478406"


def google_web():
    return FakeWeb({sources.GOOGLE_FEED: FEED})


def test_google_lists_its_us_roles_from_the_feed():
    web = google_web()
    jobs = {j.id: j for j in sources.fetch("google", "google", web)}
    assert set(jobs) == {SOAR, ATLANTA, YOUTUBE} and web.calls == [sources.GOOGLE_FEED]
    soar = jobs[SOAR]
    assert soar.key == f"google:google:{SOAR}" and soar.title == "Security Consultant, SOAR, Mandiant, Google Cloud"
    assert soar.url == sources.GOOGLE_JOBS + f"{SOAR}-security-consultant"
    assert soar.locations == ["Austin, TX, USA", "United States"] and soar.remote is True
    assert (soar.company_name, soar.department) == ("Google", "Technical Solutions")
    assert (soar.salary_min, soar.salary_max, soar.currency) == (112_000, 161_000, "USD")
    assert "SOAR playbooks written in Python" in soar.description and soar.posted.date().isoformat() == "2026-09-10"
    assert jobs[YOUTUBE].company_name == "YouTube" and jobs[YOUTUBE].remote is None


def test_google_pay_is_the_us_line():
    jobs = {j.id: j for j in sources.fetch("google", "google", google_web())}
    assert (jobs[ATLANTA].salary_min, jobs[ATLANTA].salary_max) == (79_000, 112_000)  # not the CAD line before it


def test_google_keeps_titles_with_a_search_terms_words():
    web = google_web()
    found = sources.fetch("google", "google", web, search=["consultant soar", "ios"])
    assert sorted(j.id for j in found) == sorted([SOAR, YOUTUBE])
    assert sources.fetch("google", "google", web, search=["director"]) == []


def test_google_titles_not_wanted_are_kept_without_their_text():
    jobs = {j.id: j for j in sources.fetch("google", "google", google_web(), wanted=lambda t: "SOAR" in t)}
    assert jobs[SOAR].description and jobs[SOAR].salary_min == 112_000
    assert jobs[YOUTUBE].description == "" and jobs[YOUTUBE].salary_min is None and jobs[YOUTUBE].title


def test_google_any_is_everywhere():
    jobs = {j.id: j for j in sources.fetch("google", "google/any", google_web())}
    assert SINGAPORE in jobs and jobs[SINGAPORE].locations == ["Singapore"] and jobs[SINGAPORE].salary_min is None
    assert jobs[SINGAPORE].key == f"google:google/any:{SINGAPORE}"
    with pytest.raises(sources.SourceError):
        sources.fetch("google", "alphabet", google_web())


def test_google_feed_is_read_once_a_run(monkeypatch):
    calls = []
    monkeypatch.setattr(sources, "get_text", lambda url, timeout=30: calls.append(url) or FEED)
    monkeypatch.setattr(sources, "_google_feed_cache", [])
    sources.fetch("google", "google")
    assert sources.posting(sources.GOOGLE_JOBS + SINGAPORE).id == SINGAPORE
    assert calls == [sources.GOOGLE_FEED]
    monkeypatch.setattr(sources, "GOOGLE_KEEP", -1)  # kept too long: read again
    sources.fetch("google", "google")
    assert len(calls) == 2


def test_a_bad_feed_is_a_source_error():
    with pytest.raises(sources.SourceError):
        sources.fetch("google", "google", FakeWeb({sources.GOOGLE_FEED: "<jobs><job>"}))


@pytest.mark.parametrize("url, expected", [
    (f"https://www.google.com/about/careers/applications/jobs/results/{SOAR}-security-consultant-soar-mandiant"
     "-google-cloud?location=United%20States", ("google", "google")),
    ("https://www.google.com/about/careers/applications/apply/0b7c1d2e-aaaa-bbbb-cccc-1234567890ab/form",
     ("google", "google")),
    (f"https://careers.google.com/jobs/results/{SOAR}-security-consultant/", ("google", "google")),
    ("https://www.google.com/search?q=jobs", None),
])
def test_google_links(url, expected):
    assert sources.detect(url) == expected


def test_a_google_link_is_read_from_the_feed():
    web = google_web()
    link = f"https://www.google.com/about/careers/applications/jobs/results/{SOAR}-security-consultant-soar"
    job = sources.posting(link, web)
    assert job.key == f"google:google:{SOAR}" and job.salary_max == 161_000 and job.description
    assert sources.posting(f"https://careers.google.com/jobs/results/{SINGAPORE}-research-scientist/", web).id == \
        SINGAPORE  # a link can be to a role outside the US
    assert sources.posting("https://www.google.com/about/careers/applications/apply/0b7c1d2e/form", web) is None
    assert sources.posting("https://www.google.com/about/careers/applications/jobs/results/", web) is None
    with pytest.raises(sources.NotFound):
        sources.posting(sources.GOOGLE_JOBS + "100000000000000001-gone", web)
    assert sources.careers_url("google", "google") == sources.GOOGLE_JOBS


def test_google_is_found_by_name_and_its_jobs_checked():
    hits = sources.probe("Google DeepMind", google_web())
    assert [(s, b, sources.open_roles(j)) for s, b, j in hits] == [("google", "google", "3")]
    assert not any(s == "google" for s, _, _ in sources.probe("Globex", google_web()))
    job = sources.posting(sources.GOOGLE_JOBS + SOAR, google_web())
    assert still_open(job, google_web()) is True
    job.id = "100000000000000001"
    assert still_open(job, google_web()) is False
