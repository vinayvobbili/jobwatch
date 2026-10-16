"""iCIMS careers sites: the list of roles a page at a time (in_iframe=1), then each posting's own page."""

from pathlib import Path

import pytest

from jobwatch import sources
from jobwatch.models import Job
from jobwatch.watch import still_open

from .conftest import FakeWeb

FIXTURES = Path(__file__).parent / "fixtures"
# A made-up Initech site in iCIMS's page layout: a list of three roles over two pages ("Page 1 of 2"), a remote
# role's page with its pay, and the page of a closed one.
LIST_0 = (FIXTURES / "icims_list_0.html").read_text(encoding="utf-8")
LIST_1 = (FIXTURES / "icims_list_1.html").read_text(encoding="utf-8")
POSTING = (FIXTURES / "icims_job.html").read_text(encoding="utf-8")
CLOSED = (FIXTURES / "icims_closed.html").read_text(encoding="utf-8")

HOST = "careers-initech.icims.com"
LIST = f"https://{HOST}/jobs/search?ss=1&in_iframe=1&pr="
JOB = f"https://{HOST}/jobs/"
FDE = f"https://{HOST}/jobs/1001/senior-platform-engineer/job"


def initech_web(**more) -> FakeWeb:
    return FakeWeb({f"{LIST}0": LIST_0, f"{LIST}1": LIST_1, f"{JOB}1001/job?in_iframe=1": POSTING,
                    f"{JOB}1002/job?in_iframe=1": CLOSED, **more})


def test_a_site_is_listed_page_by_page_and_wanted_roles_read():
    web = initech_web()
    jobs = {j.id: j for j in sources.fetch("icims", "initech", web, wanted=lambda t: "Platform" in t)}
    assert set(jobs) == {"1001", "1002", "1003"}
    fde = jobs["1001"]
    assert fde.key == "icims:initech:1001" and fde.title == "Senior Platform Engineer" and fde.url == FDE
    assert fde.locations == ["Remote, US"] and fde.remote is True
    assert (fde.company_name, fde.department) == ("Initech", "Engineering/IT")
    assert fde.posted.date().isoformat() == "2026-08-12"
    assert (fde.salary_min, fde.salary_max, fde.currency) == (150_000, 190_000, "USD")
    assert "Terraform" in fde.description and "Build and run the widget platform." in fde.description
    ae = jobs["1002"]  # listed, not read: its place, title and company (the list page's title) are the list's
    assert ae.description == "" and ae.company_name == "Initech" and ae.remote is None
    assert ae.locations == ["Boston, MA, US", "Austin, TX, US"]
    assert jobs["1003"].title == "Data Analyst & Reporting" and jobs["1003"].locations == ["Bengaluru, KA, IN"]
    assert web.calls == [f"{LIST}0", f"{LIST}1", f"{JOB}1001/job?in_iframe=1"]  # no page 2: the site said 2


def test_a_site_that_doesnt_say_how_many_pages_is_paged_until_one_has_no_roles():
    plain = LIST_0.replace("Page 1 of 2", "")
    web = FakeWeb({f"{LIST}0": plain, f"{LIST}1": LIST_1.replace("Page 2 of 2", ""), f"{LIST}2": "<html></html>"})
    assert sorted(j.id for j in sources.fetch("icims", "initech", web, wanted=lambda t: False)) == \
        ["1001", "1002", "1003"]
    assert web.calls[-1] == f"{LIST}2"
    assert len(sources.fetch("icims", "initech", initech_web(), wanted=lambda t: False, cap=2)) == 2


def test_icims_known_postings_are_not_read_again():
    known = Job(source="icims", company="initech", id="1001", title="Senior Platform Engineer", url=FDE,
                description="read before")
    web = initech_web()
    jobs = sources.fetch("icims", "initech", web, known={known.key: known})
    assert next(j for j in jobs if j.id == "1001") is known and f"{JOB}1001/job?in_iframe=1" not in web.calls


def test_a_posting_that_cant_be_read_stays_listed():
    web = initech_web(**{f"{JOB}1001/job?in_iframe=1": sources.SourceError("HTTP 500")})
    fde = next(j for j in sources.fetch("icims", "initech", web) if j.id == "1001")
    assert fde.description == "" and fde.title == "Senior Platform Engineer"


@pytest.mark.parametrize("url, expected, pid", [
    (FDE, ("icims", "initech"), "1001"),
    (FDE + "?in_iframe=1", ("icims", "initech"), "1001"),
    (f"https://{HOST}/jobs/search?ss=1&searchKeyword=platform", ("icims", "initech"), None),
    (f"{HOST}/jobs/intro", ("icims", "initech"), None),
    ("https://jobs-globex.icims.com/jobs/2002/account-executive/job", ("icims", "jobs-globex.icims.com"), "2002"),
    ("https://acme.icims.com/jobs/search", ("icims", "acme.icims.com"), None),
    ("https://www.icims.com/", None, None),
    ("https://careers.initech.example/jobs/1001/job", None, None),
])
def test_icims_links(url, expected, pid):
    assert sources.detect(url) == expected
    if expected:
        assert sources._posting_id("icims", url) == pid


def test_an_icims_link_is_read_from_its_page():
    web = initech_web()
    job = sources.posting(FDE + "?in_iframe=1#top", web)
    assert job.key == "icims:initech:1001" and job.salary_max == 190_000 and job.description
    assert job.url == FDE and web.calls == [f"{JOB}1001/job?in_iframe=1"]
    assert sources.posting(f"https://{HOST}/jobs/search", web) is None
    with pytest.raises(sources.NotFound):  # a closed posting's page says so
        sources.posting(f"https://{HOST}/jobs/1002/account-executive/job", web)
    with pytest.raises(sources.NotFound):  # and the site answers 410 for one it has dropped
        sources.posting(f"https://{HOST}/jobs/1004/job", initech_web(**{f"{JOB}1004/job?in_iframe=1":
                                                                         sources.NotFound("HTTP 410")}))
    with pytest.raises(sources.SourceError) as e:  # a page with no posting on it is unreadable, not closed
        sources.posting(f"https://{HOST}/jobs/1005/job", FakeWeb({f"{JOB}1005/job?in_iframe=1": "<html></html>"}))
    assert not isinstance(e.value, sources.NotFound)


def test_boards_are_careers_hosts_by_slug_or_by_host():
    assert sources.careers_url("icims", "initech") == f"https://{HOST}/jobs/search"
    assert sources.careers_url("icims", "jobs-globex.icims.com") == "https://jobs-globex.icims.com/jobs/search"
    untitled = LIST_0.replace("<title>Job Listings at Initech</title>", "")
    web = FakeWeb({"https://jobs-globex.icims.com/jobs/search?ss=1&in_iframe=1&pr=0": untitled,
                   "https://jobs-globex.icims.com/jobs/search?ss=1&in_iframe=1&pr=1": LIST_1})
    assert len(sources.fetch("icims", "jobs-globex.icims.com", web, wanted=lambda t: False)) == 3
    # pages with no site title: the company is the host's name
    assert sources.fetch("icims", "jobs-globex.icims.com", web, wanted=lambda t: False)[0].company_name == "globex"
    with pytest.raises(sources.SourceError):
        sources.fetch("icims", "globex.example.com", web)


def test_icims_is_found_by_name_and_its_jobs_checked():
    web = initech_web()
    hits = sources.probe("Initech", web)
    assert [(s, b, sources.open_roles(j)) for s, b, j in hits] == [("icims", "initech", "3")]
    assert not any(s == "icims" for s, _, _ in sources.probe("Globex", web))
    assert [(s, b) for s, b, _ in sources.probe(f"https://{HOST}/jobs/search", web)] == [("icims", "initech")]
    job = sources.posting(FDE, web)
    assert still_open(job, web) is True
    job.url = f"https://{HOST}/jobs/1002/account-executive/job"
    assert still_open(job, web) is False
