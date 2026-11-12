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


def test_titles_a_board_spells_a_little_differently():
    tier = linkedin.title_tier
    assert tier("Sr. Security Engineer", "Sr. Security Engineer") == 0
    assert tier("Senior Security Engineer", "Senior Security Engineer, DeFi") == 1
    # a bracket on one site is a dash on the other, and the board adds a place
    assert tier("Staff Security Engineer (Blue Team)", "Staff Security Engineer - Blue Team (US)") == 2
    assert tier("Sr. Platform Security Engineer", "Senior Platform Security Engineer - Remote") == 2
    assert tier("Security Engineer", "Staff Software Engineer") is None
    assert tier("Senior Security Engineer", "Senior Security Analyst Intern") is None


def test_a_sitemaps_title_with_the_place_after_it_is_worth_reading():
    assert linkedin.could_be("Security Engineer 5 Cloud Architecture And Tooling Remote United States",
                             "Security Engineer 5 - Cloud Architecture and Tooling")
    assert not linkedin.could_be("Security Engineer 5 Remote United States", "Staff Security Engineer - Cloud")


def test_a_star_rating_after_a_company_name_is_not_part_of_it():
    from jobwatch import alerts, joblist
    assert linkedin.unrated("Initech 3.9") == "Initech" and linkedin.unrated("Globex 5G") == "Globex 5G"
    assert linkedin.unrated("Studio 2000") == "Studio 2000" and linkedin.same_company("Umbrella 2.2", "Umbrella")
    assert alerts.Alert("Engineer", "Initech 3.9").company == "Initech"
    assert joblist.records([{"title": "Engineer", "company": "Globex  4.1", "id": "1"}])[0].company == "Globex"


def test_a_board_is_searched_by_the_titles_words_without_punctuation():
    assert linkedin.search_terms("Cyber - Senior Consultant, AI Data Security (Hybrid)") \
        == ["Cyber Senior Consultant AI Data Security", "Cyber Consultant AI Data Security"]
    assert linkedin.search_terms("Security Engineer") == ["Security Engineer"]


def posting(title, *places, key="1"):
    return Job(source="greenhouse", company="globex", id=key, title=title, url="https://example.com/" + key,
               locations=list(places), description="Text.")


def test_the_exact_title_wins_over_a_close_one():
    found = {j.key: (linkedin.title_tier(j.title, "Systems Engineer"), j) for j in (
        posting("Systems Engineer", key="1"), posting("Distributed Systems Engineer (Data Platform)", key="2"))}
    assert linkedin._pick(found).id == "1"


def test_one_title_posted_per_place_picks_the_place_asked_for():
    def pick(location, *jobs):
        return linkedin._pick({j.key: (0, j) for j in jobs}, location)
    boulder = posting("Application Security Engineer", "Denver, CO", "Boulder, CO", key="1")
    remote = posting("Application Security Engineer", "Remote (United States)", key="2")
    uk = posting("Application Security Engineer", "Remote - United Kingdom", key="3")
    assert pick("Boulder, CO (Hybrid)", boulder, remote, uk).id == "1"
    assert pick("United States (Remote)", boulder, remote, uk).id == "2"
    # two postings in the same places can't be told apart: two openings, neither picked
    assert pick("United States (Remote)", posting("Lead Engineer", "Remote - US", key="4"),
                posting("Lead Engineer", "Remote - US", key="5")) is None
    # the same words outside brackets: what's in the brackets tells
    assert linkedin._pick({j.key: (0, j) for j in (posting("Cybersecurity Engineer (IT Security)", key="6"),
                                                   posting("Cybersecurity Engineer (Research)", key="7"))},
                          "", "Cybersecurity Engineer (Research)").id == "7"
    # different titles tie: neither
    assert linkedin._pick({"a": (1, posting("Senior Security Engineer, DeFi", key="a")),
                           "b": (1, posting("Senior Security Engineer, Cloud", key="b"))}) is None


def test_a_job_whose_board_has_several_places_is_found_by_its_place(monkeypatch):
    def role(i, place):
        return {**GREENHOUSE["jobs"][0], "id": i, "title": f"Staff Security Engineer - Blue Team ({place[:2]})",
                "location": {"name": f"{place} Remote"}, "offices": []}
    board = {"jobs": [role(201, "US"), role(202, "UK")], "meta": {"total": 2}}
    monkeypatch.setattr(sources, "get_text", no_linkedin(FakeWeb({})))
    monkeypatch.setattr(sources, "get_json", no_linkedin(FakeWeb({
        **RESPONSES, sources.SOURCES["greenhouse"].api.format(board="acme"): board})))
    p = linkedin.Posting(id="1", title="Staff Security Engineer (Blue Team)", company="Acme Inc.",
                         location="US (Remote)", description="")
    assert linkedin.on_board(p).key == "greenhouse:acme:201"
