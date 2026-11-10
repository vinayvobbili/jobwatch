"""Gem job boards: jobs.gem.com/<company>, a public JSON list with each role's text."""

import pytest

from jobwatch import sources
from jobwatch.watch import still_open

from .conftest import FakeWeb

API = "https://api.gem.com/job_board/v0/initech/job_posts/"
FDE = "https://jobs.gem.com/initech/am9icG9zdDpBYmMx"

POSTS = [
    {"id": "am9icG9zdDpBYmMx", "title": "Senior Platform Engineer ", "absolute_url": FDE,
     "content": "<p>Build widgets.</p>", "content_plain": "Build widgets. Pay: $150,000 - $190,000 a year.",
     "first_published_at": "2026-09-22T01:02:11.972Z", "created_at": "2026-05-29T17:50:59.850Z",
     "location": {"name": "Austin, United States"}, "location_type": "hybrid",
     "offices": [{"location": {"name": "Austin, United States"}}, {"location": {"name": "Boulder, United States"}}],
     "departments": [{"id": "1", "name": "Engineering"}]},
    {"id": "am9icG9zdDpEZWY2", "title": "Account Executive", "content": "<p>Sell <b>widgets</b>.</p>",
     "created_at": "2026-10-01T00:00:00.000Z", "location": {"name": "Remote, United States"},
     "location_type": "remote", "offices": [], "departments": []},
]


def test_a_board_is_listed_with_its_text():
    web = FakeWeb({API: POSTS})
    jobs = {j.id: j for j in sources.fetch("gem", "initech", web)}
    fde = jobs["am9icG9zdDpBYmMx"]
    assert fde.key == "gem:initech:am9icG9zdDpBYmMx" and fde.title == "Senior Platform Engineer" and fde.url == FDE
    assert fde.locations == ["Austin, United States", "Boulder, United States"] and fde.remote is None
    assert fde.department == "Engineering" and fde.posted.year == 2026
    assert (fde.salary_min, fde.salary_max) == (150_000, 190_000) and fde.description.startswith("Build widgets.")
    ae = jobs["am9icG9zdDpEZWY2"]
    assert ae.remote is True and ae.department == "" and "Sell" in ae.description
    assert ae.url == "https://jobs.gem.com/initech/am9icG9zdDpEZWY2"


@pytest.mark.parametrize("url, expected, pid", [
    (FDE, ("gem", "initech"), "am9icG9zdDpBYmMx"),
    (FDE + "?utm_source=x", ("gem", "initech"), "am9icG9zdDpBYmMx"),
    ("https://jobs.gem.com/initech", ("gem", "initech"), None),
    ("jobs.gem.com/initech/", ("gem", "initech"), None),
    (API, ("gem", "initech"), None),
    ("https://jobs.gem.com/", None, None),
    ("https://www.gem.com/product", None, None),
])
def test_gem_links(url, expected, pid):
    assert sources.detect(url) == expected
    if expected:
        assert sources._posting_id("gem", url) == pid


def test_gem_is_found_by_name_and_its_jobs_checked():
    web = FakeWeb({API: POSTS})
    hits = sources.probe("Initech", web)
    assert [(s, b, sources.open_roles(j)) for s, b, j in hits] == [("gem", "initech", "2")]
    assert not any(s == "gem" for s, _, _ in sources.probe("Globex", web))
    job = sources.posting(FDE, web)
    assert job.title == "Senior Platform Engineer" and still_open(job, web) is True
    job.id = "gone"
    assert still_open(job, web) is False


def test_a_rate_limited_gem_is_not_guessed_again():
    web = FakeWeb({API: sources.SourceError("HTTP 429")})
    limited: set[str] = set()
    assert not any(s == "gem" for s, _, _ in sources.probe("Initech", web, limited=limited))
    assert "gem" in limited
    calls = len(web.calls)
    sources.probe("Umbrella Corp", web, limited=limited)
    assert not any("gem.com" in c for c in web.calls[calls:])
