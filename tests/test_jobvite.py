"""Jobvite careers sites: the list of every role on one page, then each posting's own page."""

from pathlib import Path

import pytest

from jobwatch import sources
from jobwatch.models import Job
from jobwatch.watch import still_open

from .conftest import FakeWeb

FIXTURES = Path(__file__).parent / "fixtures"
# A made-up Initech site in Jobvite's page layout: a list of three roles (one with two places, listed as
# "2 Locations") and the page of that first role, with its pay. A closed role's link sends on to the list.
LIST = (FIXTURES / "jobvite_list.html").read_text(encoding="utf-8")
POSTING = (FIXTURES / "jobvite_job.html").read_text(encoding="utf-8")

SITE = "https://jobs.jobvite.com/initech"
FDE = f"{SITE}/job/oAbC1dEf"


def initech_web(**more) -> FakeWeb:
    return FakeWeb({f"{SITE}/jobs": LIST, FDE: POSTING, **more})


def test_a_site_is_listed_and_wanted_roles_read():
    web = initech_web()
    jobs = {j.id: j for j in sources.fetch("jobvite", "initech", web, wanted=lambda t: "Platform" in t)}
    assert set(jobs) == {"oAbC1dEf", "oGhI2jKl", "oMnO3pQr"}
    fde = jobs["oAbC1dEf"]
    assert fde.key == "jobvite:initech:oAbC1dEf" and fde.title == "Senior Platform Engineer" and fde.url == FDE
    assert fde.locations == ["Austin, Texas", "Remote, United States"] and fde.remote is True
    assert (fde.company_name, fde.department) == ("Initech", "Engineering")
    assert (fde.salary_min, fde.salary_max, fde.currency) == (150_000, 190_000, "USD")
    assert "Terraform" in fde.description and "Build and run the widget platform & its tooling." in fde.description
    assert "E-Verify" not in fde.description and "base64" not in fde.description
    da = jobs["oGhI2jKl"]  # listed, not read: its title, department and place are the list's
    assert da.description == "" and da.company_name == "Initech" and da.title == "Data Analyst & Reporting"
    assert (da.department, da.locations, da.remote) == ("Finance", ["Remote, United States"], True)
    ae = jobs["oMnO3pQr"]
    assert (ae.department, ae.locations, ae.remote) == ("Sales", ["Boston, Massachusetts"], None)
    assert web.calls == [f"{SITE}/jobs", FDE]
    assert len(sources.fetch("jobvite", "initech", initech_web(), wanted=lambda t: False, cap=2)) == 2


def test_jobvite_known_postings_are_not_read_again():
    known = Job(source="jobvite", company="initech", id="oAbC1dEf", title="Senior Platform Engineer", url=FDE,
                description="read before")
    web = initech_web()
    jobs = sources.fetch("jobvite", "initech", web, known={known.key: known})
    assert next(j for j in jobs if j.id == "oAbC1dEf") is known and FDE not in web.calls


def test_a_posting_that_cant_be_read_stays_listed():
    web = initech_web(**{FDE: sources.SourceError("HTTP 500")})
    fde = next(j for j in sources.fetch("jobvite", "initech", web) if j.id == "oAbC1dEf")
    assert fde.description == "" and fde.title == "Senior Platform Engineer"


@pytest.mark.parametrize("url, expected, pid", [
    (FDE, ("jobvite", "initech"), "oAbC1dEf"),
    (FDE + "?nl=1", ("jobvite", "initech"), "oAbC1dEf"),
    (FDE + "/apply?nl=1", ("jobvite", "initech"), "oAbC1dEf"),
    (f"{SITE}/jobs", ("jobvite", "initech"), None),
    ("jobs.jobvite.com/initech", ("jobvite", "initech"), None),
    ("https://jobs.jobvite.com/careers/initech/jobs?error=404", ("jobvite", "initech"), None),
    ("https://jobs.jobvite.com/careers/initech/job/oAbC1dEf", ("jobvite", "initech"), "oAbC1dEf"),
    ("https://jobs.jobvite.com/", None, None),
    ("https://www.jobvite.com/support/", None, None),
    ("https://careers.initech.example/job/oAbC1dEf", None, None),
])
def test_jobvite_links(url, expected, pid):
    assert sources.detect(url) == expected
    if expected:
        assert sources._posting_id("jobvite", url) == pid


def test_a_jobvite_link_is_read_from_its_page():
    web = initech_web()
    job = sources.posting(FDE + "/apply?nl=1#top", web)
    assert job.key == "jobvite:initech:oAbC1dEf" and job.salary_max == 190_000 and job.description
    assert job.url == FDE and web.calls == [FDE]
    assert sources.posting(f"{SITE}/jobs", web) is None
    closed = f"{SITE}/job/oZzZ9yXw"
    with pytest.raises(sources.NotFound):  # a closed posting's link sends on to the list, which has no posting
        sources.posting(closed, initech_web(**{closed: LIST}))
    with pytest.raises(sources.NotFound):
        sources.posting(closed, initech_web())
    with pytest.raises(sources.SourceError) as e:  # a posting page with no text is unreadable, not closed
        empty = '<h2 class="jv-header">Role</h2><div class="jv-job-detail-description"></div>'
        sources.posting(closed, FakeWeb({closed: empty}))
    assert not isinstance(e.value, sources.NotFound)


def test_a_single_place_page_has_no_department_guess():
    page = POSTING.replace("Engineering<span class='jv-inline-separator'></span>", "") \
        .replace('    <span class="jv-inline-separator"></span>\n    Remote, United States\n', "")
    job = sources.posting(FDE, FakeWeb({FDE: page}))
    assert job.locations == ["Austin, Texas"] and job.department == ""


def test_boards_are_company_names_on_jobs_jobvite_com():
    assert sources.careers_url("jobvite", "initech") == f"{SITE}/jobs"
    with pytest.raises(sources.SourceError):
        sources.fetch("jobvite", "initech.example.com", initech_web())


def test_jobvite_is_found_by_name_and_its_jobs_checked():
    web = initech_web()
    hits = sources.probe("Initech", web)
    assert [(s, b, sources.open_roles(j)) for s, b, j in hits] == [("jobvite", "initech", "3")]
    assert not any(s == "jobvite" for s, _, _ in sources.probe("Globex", web))
    assert [(s, b) for s, b, _ in sources.probe(f"{SITE}/jobs", web)] == [("jobvite", "initech")]
    job = sources.posting(FDE, web)
    assert still_open(job, web) is True
    job.url = f"{SITE}/job/oZzZ9yXw"
    assert still_open(job, web) is False
