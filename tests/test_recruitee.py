"""Recruitee careers sites: <company>.recruitee.com, a public JSON list (/api/offers/) with each role's text."""

import pytest

from jobwatch import sources
from jobwatch.watch import still_open

from .conftest import FakeWeb

API = "https://initech.recruitee.com/api/offers/"
FDE = "https://initech.recruitee.com/o/senior-platform-engineer"

OFFERS = {"offers": [
    {"id": 1001, "slug": "senior-platform-engineer", "title": "Senior Platform Engineer ", "careers_url": FDE,
     "company_name": "Initech", "department": "Engineering", "remote": False, "hybrid": True,
     "location": "Austin, Texas, United States", "published_at": "2026-09-22 13:43:34 UTC",
     "created_at": "2026-09-01 08:00:00 UTC",
     "locations": [{"name": "Austin", "city": "Austin", "state": "Texas", "country": "United States"},
                   {"name": "Boulder", "city": "Boulder", "state": "Colorado", "country": "United States"}],
     "description": "<p>Build widgets.</p>", "requirements": "<ul><li>Terraform</li></ul>",
     "salary": {"min": "150000", "max": "190000", "period": "year", "currency": "USD"}},
    {"id": 1002, "slug": "account-executive", "title": "Account Executive", "company_name": "Initech",
     "remote": True, "location": "Remote job", "published_at": "2026-10-01 00:00:00 UTC", "locations": [],
     "description": "<p>Sell <b>widgets</b>. Pay: $120,000 - $140,000 a year.</p>",
     "salary": {"min": None, "max": None, "period": None, "currency": None}},
]}


def test_a_board_is_listed_with_its_text_and_pay():
    jobs = {j.id: j for j in sources.fetch("recruitee", "initech", FakeWeb({API: OFFERS}))}
    fde = jobs["senior-platform-engineer"]
    assert fde.key == "recruitee:initech:senior-platform-engineer" and fde.title == "Senior Platform Engineer"
    assert fde.url == FDE and fde.company_name == "Initech" and fde.department == "Engineering"
    assert fde.locations == ["Austin, Texas, United States", "Boulder, Colorado, United States"]
    assert fde.remote is None and (fde.posted.year, fde.posted.month, fde.posted.day) == (2026, 9, 22)
    assert (fde.salary_min, fde.salary_max, fde.currency) == (150_000, 190_000, "USD")
    assert "Build widgets." in fde.description and "Terraform" in fde.description
    ae = jobs["account-executive"]
    assert ae.remote is True and ae.locations == ["Remote job"]
    assert ae.url == "https://initech.recruitee.com/o/account-executive"
    assert (ae.salary_min, ae.salary_max) == (120_000, 140_000)  # from the text, with no salary fields


@pytest.mark.parametrize("url, expected, pid", [
    (FDE, ("recruitee", "initech"), "senior-platform-engineer"),
    (FDE + "/c/new", ("recruitee", "initech"), "senior-platform-engineer"),
    ("https://initech.recruitee.com/", ("recruitee", "initech"), None),
    (API, ("recruitee", "initech"), None),
    ("https://www.recruitee.com/pricing", None, None),
    ("https://app.recruitee.com/", None, None),
])
def test_recruitee_links(url, expected, pid):
    assert sources.detect(url) == expected
    if expected:
        assert sources._posting_id("recruitee", url) == pid


def test_recruitee_is_found_by_name_and_its_jobs_checked():
    web = FakeWeb({API: OFFERS})
    hits = sources.probe("Initech", web)
    assert [(s, b, sources.open_roles(j)) for s, b, j in hits] == [("recruitee", "initech", "2")]
    assert sources.careers_url("recruitee", "initech") == "https://initech.recruitee.com/"
    job = sources.posting(FDE, web)
    assert job.title == "Senior Platform Engineer" and still_open(job, web) is True
    job.id = "gone"
    assert still_open(job, web) is False
