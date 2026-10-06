"""LinkedIn job links: read the public posting, then find the same job on the company's own board."""

import pytest

from jobwatch import linkedin, sources
from jobwatch.store import Store
from jobwatch.watch import save_job

from .conftest import GREENHOUSE, RESPONSES, FakeWeb


def page_for(title="Senior Software Engineer, Platform", company="Acme Inc.", closed=False, pay=""):
    """A public posting page, shaped like LinkedIn's."""
    return f"""<section class="top-card-layout">
<h2 class="top-card-layout__title font-sans">{title}</h2>
<a class="topcard__org-name-link topcard__flavor--black-link" href="https://www.linkedin.com/company/acme">
  {company}
</a>
<span class="topcard__flavor topcard__flavor--bullet">Austin, TX</span>
{'<figure class="closed-job"><figcaption>No longer accepting applications</figcaption></figure>' if closed else ''}
{f'<div class="salary compensation__salary">{pay}</div>' if pay else ''}
</section>
<div class="show-more-less-html__markup relative">
  <p>Build <strong>Python</strong> services &amp; agents.</p>
</div>
<button class="show-more-less-html__button">Show more</button>"""


def test_job_ids_from_every_kind_of_link():
    assert linkedin.job_id("https://www.linkedin.com/jobs/view/4123456789/") == "4123456789"
    assert linkedin.job_id("linkedin.com/jobs/view/staff-engineer-at-acme-4123456789") == "4123456789"
    assert linkedin.job_id("https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4123456789") \
        == "4123456789"
    assert linkedin.job_id("https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4123456789") == "4123456789"
    assert linkedin.job_id("https://www.linkedin.com/in/someone") is None
    assert linkedin.job_id("https://linkedin.com.evil.example/jobs/view/4123456789") is None
    assert linkedin.job_id("https://jobs.lever.co/globex/aaaa-1111") is None


def test_read_a_posting():
    pages = []

    def page(url):
        pages.append(url)
        return page_for(pay="$190,000.00/yr - $230,000.00/yr", closed=True)

    p = linkedin.read("https://www.linkedin.com/jobs/view/4123456789/", page)
    assert pages == ["https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4123456789"]
    assert (p.title, p.company, p.location) == ("Senior Software Engineer, Platform", "Acme Inc.", "Austin, TX")
    assert p.description.startswith("Build Python services & agents.") and p.closed
    assert (p.salary_min, p.salary_max) == (190000, 230000) and "$190,000.00 - $230,000.00" in p.description
    assert p.url == "https://www.linkedin.com/jobs/view/4123456789/"
    assert linkedin.read("https://jobs.lever.co/globex/aaaa-1111", page) is None and len(pages) == 1
    with pytest.raises(sources.SourceError, match="sign in"):  # what LinkedIn shows when it's had enough
        linkedin.read("https://www.linkedin.com/jobs/view/4123456789/", lambda url: "<html>Sign in</html>")


def test_titles_and_names_on_two_sites():
    assert linkedin.same_title("Staff Data Platform Engineer", "Staff Data Platform Engineer (Remote - US) [123]")
    assert linkedin.same_title("Senior Software Engineer, Platform", "Senior Software Engineer")
    assert not linkedin.same_title("Senior Software Engineer", "Senior Software Engineer, Payments Platform")
    assert not linkedin.same_title("Engineer", "Engineer")  # one word isn't enough to tell
    assert linkedin.company_names("Initech Group, Inc.") == ["Initech Group, Inc.", "Initech"]


def test_a_linkedin_job_found_on_the_company_board(tmp_path, web):
    store = Store(tmp_path / "state.db")
    from jobwatch.config import Board

    job, read = save_job(store, "https://www.linkedin.com/jobs/view/4123456789/", page=lambda url: page_for(),
                         boards=[Board("greenhouse", "acme", "Acme")])
    assert read and job.key == "greenhouse:acme:101"  # the application goes there, and jobwatch can check it
    _, rec = store.find(job.key)
    assert rec["status"] == "queued" and "Found on LinkedIn: https://www.linkedin.com/jobs/view/4123456789/" \
        in rec["note"]


def test_a_linkedin_job_found_by_looking_for_the_board(tmp_path, monkeypatch):
    # Not watched: the board is found under the company's name. Two roles that both fit: neither is picked.
    two = {**GREENHOUSE, "jobs": GREENHOUSE["jobs"] + [{**GREENHOUSE["jobs"][0], "id": 103}]}
    for jobs, found in ((GREENHOUSE, "greenhouse:acme:101"), (two, None)):
        monkeypatch.setattr(sources, "get_json", FakeWeb({**RESPONSES, sources.SOURCES["greenhouse"].api.format(
            board="acme"): jobs}))
        p = linkedin.read("https://www.linkedin.com/jobs/view/4123456789/", lambda url: page_for())
        j = linkedin.on_board(p)
        assert (j.key if j else None) == found


def test_a_linkedin_job_not_on_a_board_is_kept_from_linkedin(tmp_path, web):
    store = Store(tmp_path / "state.db")
    job, read = save_job(store, "https://www.linkedin.com/jobs/view/4123456789/", status="applied",
                         page=lambda url: page_for("Field Engineer", "Umbrella LLC", closed=True))
    found, rec = store.find(job.key)
    assert read and job.source == "manual" and found.title == "Field Engineer"
    assert found.display_company == "Umbrella LLC" and found.url == "https://www.linkedin.com/jobs/view/4123456789/"
    assert "Build Python services" in found.description and rec["status"] == "applied" and rec["closed"]
    assert "(no longer accepting applications there)" in rec["note"]
