"""Rippling boards, and finding a board from a company's own careers page."""

import pytest

from jobwatch import sources
from jobwatch.text import parse_salary

from .conftest import FakeWeb

LIST = "https://api.rippling.com/platform/api/ats/v1/board/acme-corp/jobs"
ONE = "d1f0c2aa-0000-4000-8000-000000000001"
TWO = "d1f0c2aa-0000-4000-8000-000000000002"

RIPPLING = {
    # The board lists a role once per place it's open in.
    LIST: [
        {"uuid": ONE, "name": "Staff AI Platform Engineer", "department": {"label": "Engineering"},
         "url": f"https://ats.rippling.com/acme-corp/jobs/{ONE}", "workLocation": {"label": "Remote (United States)"}},
        {"uuid": ONE, "name": "Staff AI Platform Engineer", "department": {"label": "Engineering"},
         "url": f"https://ats.rippling.com/acme-corp/jobs/{ONE}", "workLocation": {"label": "Denver, CO"}},
        {"uuid": TWO, "name": "Office Manager", "department": {"label": "G&A"},
         "url": f"https://ats.rippling.com/acme-corp/jobs/{TWO}", "workLocation": {"label": "Denver, CO"}},
    ],
    f"{LIST}/{ONE}": {
        "name": "Staff AI Platform Engineer", "companyName": "Acme Corp", "createdOn": "2026-09-01T12:00:00Z",
        "workLocations": ["Remote (United States)", "Denver, CO"], "department": {"name": "Engineering"},
        "description": {"company": "<p>Acme builds rockets.</p>",
                        "role": "<p>Build our internal LLM platform in Python.</p>"
                                "<p>The base pay range is 180,000 - 220,000 USD.</p>"},
    },
}


@pytest.fixture
def rippling(monkeypatch):
    fake = FakeWeb(RIPPLING)
    monkeypatch.setattr(sources, "get_json", fake)
    return fake


def test_a_role_open_in_two_places_is_one_job(rippling):
    jobs = sources.fetch("rippling", "acme-corp", wanted=lambda t: "Engineer" in t)
    one, two = sorted(jobs, key=lambda j: j.title, reverse=True)
    assert one.key == f"rippling:acme-corp:{ONE}" and one.company_name == "Acme Corp"
    assert one.locations == ["Remote (United States)", "Denver, CO"] and one.remote
    assert "internal LLM platform" in one.description and (one.salary_min, one.salary_max) == (180000, 220000)
    assert one.posted.year == 2026 and one.department == "Engineering"
    assert two.title == "Office Manager" and not two.description  # unwanted: listed, not read
    assert f"{LIST}/{TWO}" not in rippling.calls


def test_rippling_links(rippling):
    assert sources.detect(f"https://ats.rippling.com/acme-corp/jobs/{ONE}") == ("rippling", "acme-corp")
    assert sources.detect(f"https://ats.rippling.com/en-GB/acme-corp/jobs/{ONE}/apply") == ("rippling", "acme-corp")
    assert sources.detect(LIST) == ("rippling", "acme-corp")
    assert sources.detect("https://ats.rippling.com/api/whatever") is None
    j = sources.posting(f"https://ats.rippling.com/acme-corp/jobs/{ONE}")
    assert j.title == "Staff AI Platform Engineer" and j.url.endswith(ONE)
    assert sources.posting("https://ats.rippling.com/acme-corp/jobs") is None  # the whole board
    with pytest.raises(sources.NotFound):
        sources.posting("https://ats.rippling.com/acme-corp/jobs/gone-0000")


def test_pay_written_before_usd():
    assert parse_salary("The base pay range is 180,000 - 220,000 USD.") == (180000, 220000)
    assert parse_salary("Between 95,000 to 120,000 USD per year") == (95000, 120000)


PAGE = """<html><body>
<a href="https://acme.example/about">About</a>
<a class="btn" href="https://ats.rippling.com/acme-corp/jobs">Open roles</a>
<a href="https://ats.rippling.com/acme-corp/jobs?dept=eng">Engineering</a>
<script>var board = "https:\\/\\/boards.greenhouse.io\\/embed\\/job_board?for=acmeco&amp;b=x";</script>
</body></html>"""


def test_a_careers_page_links_to_the_board(rippling):
    pages = []

    def page(url):
        pages.append(url)
        return PAGE

    assert sources.boards_on_page("careers.acme.example/jobs", page) == [("rippling", "acme-corp"),
                                                                        ("greenhouse", "acmeco")]
    assert pages == ["https://careers.acme.example/jobs"]
    hits = sources.probe("https://careers.acme.example/jobs", page=page)  # the Greenhouse board isn't there
    assert [(s, b, len(jobs)) for s, b, jobs in hits] == [("rippling", "acme-corp", 2)]
    assert sources.probe("https://careers.acme.example/nothing", page=lambda url: "<p>No jobs.</p>") == []
