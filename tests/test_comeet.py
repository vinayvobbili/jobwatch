"""Comeet careers pages: every open role, with its text, is JSON in the one page."""

import json

import pytest

from jobwatch import sources
from jobwatch.watch import still_open

from .conftest import FakeWeb

SITE = "https://www.comeet.com/jobs/initech/12.345"
FDE = f"{SITE}/senior-platform-engineer/A1.B23"


def position(uid, name, **more) -> dict:
    return {
        "name": name, "department": "Engineering", "uid": uid, "company_name": "Initech",
        "location": {"name": "United States", "city": "Austin", "state": "TX", "country": "US", "is_remote": False},
        "url_comeet_hosted_page": f"{SITE}/{name.lower().replace(' ', '-')}/{uid}",
        "workplace_type": "Hybrid", "time_updated": "2026-10-01T12:00:00Z",
        "custom_fields": {"details": [
            {"name": "Requirements", "value": "<ul><li>Terraform</li></ul>", "order": 2},
            {"name": "Description", "value": "<p>Build the widget platform &amp; its tooling.</p><p>$150,000 - "
                                              "$190,000 a year</p>", "order": 1}]},
        **more,
    }


def page(*positions) -> str:
    return ('<script>COMPANY_DATA =  {"name": "Initech"};\n'
            f"COMPANY_POSITIONS_DATA =  {json.dumps(list(positions))};\nPOSITION_DATA = null;</script>")


PAGE = page(
    position("A1.B23", "Senior Platform Engineer"),
    position("C4.D56", "Account Executive", department="Sales", workplace_type="Remote",
             location={"name": "Israel", "city": "", "state": "", "country": "", "is_remote": True}),
)


def test_a_board_is_read_from_its_one_page():
    web = FakeWeb({SITE: PAGE})
    jobs = {j.id: j for j in sources.fetch("comeet", "initech/12.345", web)}
    assert web.calls == [SITE] and set(jobs) == {"A1.B23", "C4.D56"}
    fde = jobs["A1.B23"]
    assert fde.key == "comeet:initech/12.345:A1.B23" and fde.title == "Senior Platform Engineer"
    assert fde.url == FDE and (fde.company_name, fde.department) == ("Initech", "Engineering")
    assert fde.locations == ["Austin, TX, US"] and fde.remote is None
    assert fde.description.startswith("Description\nBuild the widget platform & its tooling.")
    assert "Terraform" in fde.description
    assert (fde.salary_min, fde.salary_max) == (150_000, 190_000) and fde.posted.year == 2026
    ae = jobs["C4.D56"]
    assert ae.remote is True and ae.locations == ["Israel"] and ae.department == "Sales"
    assert len(sources.fetch("comeet", "initech/12.345", web, cap=1)) == 1


def test_a_page_without_positions_is_unreadable():
    with pytest.raises(sources.SourceError):
        sources.fetch("comeet", "initech/12.345", FakeWeb({SITE: "<html>Not Found</html>"}))
    with pytest.raises(sources.SourceError):
        sources.fetch("comeet", "initech", FakeWeb())  # no uid


@pytest.mark.parametrize("url, expected, pid", [
    (FDE, ("comeet", "initech/12.345"), "A1.B23"),
    (FDE + "?utm_source=x", ("comeet", "initech/12.345"), "A1.B23"),
    (SITE, ("comeet", "initech/12.345"), None),
    ("comeet.com/jobs/initech/12.345/", ("comeet", "initech/12.345"), None),
    ("https://www.comeet.co/jobs/initech/12.345", ("comeet", "initech/12.345"), None),
    ("https://www.comeet.com/jobs/initech", None, None),  # no uid: not a board
    ("https://www.comeet.com/pricing", None, None),
])
def test_comeet_links(url, expected, pid):
    assert sources.detect(url) == expected
    if expected:
        assert sources._posting_id("comeet", url) == pid


def test_a_link_to_a_job_is_read_from_the_board_and_checked():
    web = FakeWeb({SITE: PAGE})
    job = sources.posting(FDE, web)
    assert job.key == "comeet:initech/12.345:A1.B23" and job.salary_max == 190_000
    assert still_open(job, web) is True
    job.id = "Z9.Z99"
    assert still_open(job, web) is False
    with pytest.raises(sources.NotFound):
        sources.posting(f"{SITE}/gone/Z9.Z99", web)


def test_a_name_is_not_guessed_but_a_careers_link_finds_the_board():
    web = FakeWeb({SITE: PAGE})
    assert sources.probe("Initech", web) == []
    assert not any("comeet" in c for c in web.calls)
    careers = "https://initech.example/careers"
    found = sources.probe(careers, web, page=lambda url: f'<a href="{FDE}?utm_source=x">Open roles</a>')
    assert [(s, b, len(j)) for s, b, j in found] == [("comeet", "initech/12.345", 2)]
