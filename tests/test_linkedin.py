"""LinkedIn job links: never read (LinkedIn's robots.txt disallows every page), but the same job is looked for on
the company's own board from the company and title the person gives."""

import pytest

from jobwatch import linkedin, sources
from jobwatch.config import Board
from jobwatch.models import Job
from jobwatch.store import Store
from jobwatch.watch import save_job, still_open

from .conftest import GREENHOUSE, RESPONSES, FakeWeb

LINK = "https://www.linkedin.com/jobs/view/4123456789/"


def no_linkedin(fallback):
    """A fetcher that fails the test on any linkedin.com URL, else answers with `fallback`."""
    def fetch(url, *args, **kwargs):
        assert "linkedin.com" not in url, f"jobwatch fetched {url}"
        return fallback(url, *args, **kwargs)
    return fetch


@pytest.fixture
def guarded(monkeypatch, web):
    """Every request goes through `web`'s fake boards, and none may go to linkedin.com."""
    monkeypatch.setattr(sources, "get_json", no_linkedin(web))
    monkeypatch.setattr(sources, "get_text", no_linkedin(FakeWeb({})))
    return web


def test_job_ids_from_every_kind_of_link():
    assert linkedin.job_id(LINK) == "4123456789"
    assert linkedin.job_id("linkedin.com/jobs/view/staff-engineer-at-acme-4123456789") == "4123456789"
    assert linkedin.job_id("https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4123456789") \
        == "4123456789"
    assert linkedin.job_id("https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4123456789") == "4123456789"
    assert linkedin.job_id("https://www.linkedin.com/in/someone") is None
    assert linkedin.job_id("https://linkedin.com.evil.example/jobs/view/4123456789") is None
    assert linkedin.job_id("https://jobs.lever.co/globex/aaaa-1111") is None


def test_nothing_reads_linkedin():
    assert not hasattr(linkedin, "read") and not hasattr(linkedin, "GUEST")


def test_titles_and_names_on_two_sites():
    assert linkedin.same_title("Staff Data Platform Engineer", "Staff Data Platform Engineer (Remote - US) [123]")
    assert linkedin.same_title("Senior Software Engineer, Platform", "Senior Software Engineer")
    assert not linkedin.same_title("Senior Software Engineer", "Senior Software Engineer, Payments Platform")
    assert not linkedin.same_title("Engineer", "Engineer")  # one word isn't enough to tell
    assert linkedin.company_names("Initech Group, Inc.") == ["Initech Group, Inc.", "Initech"]


def test_a_linkedin_link_needs_the_company_and_title(tmp_path, guarded):
    store = Store(tmp_path / "state.db")
    with pytest.raises(ValueError, match=r"robots\.txt"):
        save_job(store, LINK, page=no_linkedin(FakeWeb({})))
    with pytest.raises(ValueError, match=r"robots\.txt"):
        save_job(store, LINK, "Acme", page=no_linkedin(FakeWeb({})))
    assert not list(store.jobs(include_closed=True))


def test_a_linkedin_job_found_on_the_company_board(tmp_path, guarded):
    store = Store(tmp_path / "state.db")
    job, read = save_job(store, LINK, "Acme Inc.", "Senior Software Engineer, Platform",
                         page=no_linkedin(FakeWeb({})), boards=[Board("greenhouse", "acme", "Acme")])
    assert read and job.key == "greenhouse:acme:101"  # the application goes there, and jobwatch can check it
    _, rec = store.find(job.key)
    assert rec["status"] == "queued" and f"Found on LinkedIn: {LINK}" in rec["note"]


def test_a_linkedin_job_found_by_looking_for_the_board(monkeypatch):
    # Not watched: the board is found under the company's name. Two roles that both fit: neither is picked.
    two = {**GREENHOUSE, "jobs": GREENHOUSE["jobs"] + [{**GREENHOUSE["jobs"][0], "id": 103}]}
    # no SmartRecruiters or Avature board under that name either
    monkeypatch.setattr(sources, "get_text", no_linkedin(FakeWeb({})))
    p = linkedin.Posting(id="4123456789", title="Senior Software Engineer, Platform", company="Acme Inc.",
                         location="", description="")
    for jobs, found in ((GREENHOUSE, "greenhouse:acme:101"), (two, None)):
        monkeypatch.setattr(sources, "get_json", no_linkedin(FakeWeb({
            **RESPONSES, sources.SOURCES["greenhouse"].api.format(board="acme"): jobs})))
        j = linkedin.on_board(p)
        assert (j.key if j else None) == found


def test_a_linkedin_job_not_on_a_board_is_kept_with_its_link(tmp_path, guarded):
    store = Store(tmp_path / "state.db")
    job, read = save_job(store, LINK, "Umbrella LLC", "Field Engineer", "Build Python services & agents.",
                         status="applied", page=no_linkedin(FakeWeb({})))
    found, rec = store.find(job.key)
    assert not read and job.source == "manual" and found.title == "Field Engineer"
    assert found.display_company == "Umbrella LLC" and found.url == LINK
    assert found.description.startswith("Build Python services") and rec["status"] == "applied"
    assert f"Found on LinkedIn: {LINK}" in rec["note"]


def test_a_linkedin_job_cant_be_checked():
    job = Job(source="manual", company="umbrella", id="field-engineer", title="Field Engineer", url=LINK)
    assert still_open(job, no_linkedin(FakeWeb({})), no_linkedin(FakeWeb({}))) is None
