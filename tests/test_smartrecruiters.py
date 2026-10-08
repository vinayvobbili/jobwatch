"""SmartRecruiters: the careers site's list of titles, a page at a time, then each posting's own page."""

from pathlib import Path

import pytest

from jobwatch import sources
from jobwatch.models import Job
from jobwatch.text import parse_salary
from jobwatch.watch import still_open

from .conftest import FakeWeb

FIXTURES = Path(__file__).parent / "fixtures"
# Two public ServiceNow postings, trimmed: a remote Forward Deployed role with its pay, and an expired one.
POSTING = (FIXTURES / "smartrecruiters_posting.html").read_text(encoding="utf-8")
EXPIRED = (FIXTURES / "smartrecruiters_expired.html").read_text(encoding="utf-8")

LIST = "https://careers.smartrecruiters.com/ServiceNow/api/more"
JOB = "https://jobs.smartrecruiters.com/ServiceNow/"
FDE, APPS, CSM, VOICE, HRBP, GONE = ("744000154154044", "744000154008529", "744000154203269", "744000154007140",
                                     "744000154493219", "744000011970750")


def item(pid: str, slug: str, title: str, board: str = "ServiceNow") -> str:
    """One role as the careers site lists it."""
    return (f'<li class="opening-job job column wide-7of16 medium-1of2"><a href="https://jobs.smartrecruiters.com/'
            f'{board}/{pid}-{slug}" aria-label="{title} - undefined" class="link--block details js-job-ad-link">'
            f'<h4 class="details-title job-title link--block-target spl-text-h6">{title}</h4></a></li>')


FDE_ITEM = item(FDE, "forward-deployed-solution-engineer-applied-ai-fde",
                "Forward Deployed Solution Engineer – Applied AI FDE")
PAGES = {
    # The first page is longer than the rest; the site doesn't say how many there are, so paging stops at one
    # that adds nothing new.
    f"{LIST}?page=0": FDE_ITEM + item(APPS, "senior-staff-applications-development-engineer",
                                      "Senior Staff Applications Development Engineer")
    + item(CSM, "sr-customer-success-manager", "Sr Customer Success Manager"),
    f"{LIST}?page=1": item(VOICE, "staff-software-engineer-voice-connectivity-",
                           "Staff Software Engineer_Voice Connectivity ") + FDE_ITEM,
    f"{LIST}?page=2": "",
    # The site's search is loose: it finds roles that only mention the words.
    f"{LIST}?search=forward%20deployed&page=0": FDE_ITEM + item(HRBP, "senior-hrbp-manager", "Senior HRBP Manager"),
    f"{LIST}?search=forward%20deployed&page=1": "",
    f"{JOB}{FDE}": POSTING,
    f"{JOB}{GONE}": EXPIRED,
}


@pytest.fixture
def web():
    return FakeWeb(PAGES)


def test_a_board_is_listed_page_by_page_and_wanted_roles_read(web):
    jobs = {j.id: j for j in sources.fetch("smartrecruiters", "ServiceNow", web,
                                           wanted=lambda t: "Forward Deployed" in t)}
    assert set(jobs) == {FDE, APPS, CSM, VOICE}
    assert [c for c in web.calls if c.startswith(LIST)] == [f"{LIST}?page=0", f"{LIST}?page=1", f"{LIST}?page=2"]
    fde = jobs[FDE]
    assert fde.key == f"smartrecruiters:ServiceNow:{FDE}" and fde.title == "Forward Deployed Solution Engineer – " \
        "Applied AI FDE"
    assert fde.url == f"{JOB}{FDE}-forward-deployed-solution-engineer-applied-ai-fde"
    assert (fde.company_name, fde.locations, fde.remote) == ("ServiceNow", ["Santa Clara, California, United States"],
                                                             True)
    assert fde.posted.date().isoformat() == "2026-10-07"
    assert (fde.salary_min, fde.salary_max, fde.currency) == (201_300, 352_300, "USD")
    assert "LLM-enabled applications" in fde.description and "Work Personas" in fde.description
    assert "By clicking" not in fde.description and "I'm interested" not in fde.description
    assert jobs[VOICE].title == "Staff Software Engineer_Voice Connectivity" and not jobs[VOICE].description
    assert [c for c in web.calls if c.startswith(JOB)] == [f"{JOB}{FDE}"]  # unwanted titles: listed, not read


def test_a_board_is_searched_for_the_watchlist_titles(web):
    known = {f"smartrecruiters:ServiceNow:{FDE}": Job(source="smartrecruiters", company="ServiceNow", id=FDE,
                                                      title="Forward Deployed", url=f"{JOB}{FDE}",
                                                      description="Read before.")}
    jobs = sources.fetch("smartrecruiters", "ServiceNow", web, search=["forward deployed"], known=known)
    assert sorted(j.id for j in jobs) == sorted([FDE, HRBP])
    assert f"{LIST}?page=0" not in web.calls and f"{JOB}{FDE}" not in web.calls  # read once, kept since


def test_listing_stops_at_the_cap(web):
    assert len(sources.fetch("smartrecruiters", "ServiceNow", web, wanted=lambda t: False, cap=2)) == 2
    assert web.calls == [f"{LIST}?page=0"]


@pytest.mark.parametrize("url, board, pid", [
    (f"{JOB}{FDE}-forward-deployed-solution-engineer-applied-ai-fde", "ServiceNow", FDE),
    (f"https://jobs.smartrecruiters.com/visa/{APPS}?oga=true", "visa", APPS),
    ("https://careers.smartrecruiters.com/ServiceNow", "ServiceNow", None),
    ("https://jobs.smartrecruiters.com/ServiceNow", "ServiceNow", None),
    (f"https://jobs.smartrecruiters.com/oneclick-ui/company/ServiceNow/publication/{'a' * 8}-0000?dcr_ci=x",
     "ServiceNow", None),
    (f"https://api.smartrecruiters.com/v1/companies/ServiceNow/postings/{FDE}", "ServiceNow", FDE),
])
def test_smartrecruiters_links(url, board, pid):
    assert sources.detect(url) == ("smartrecruiters", board)
    assert sources._posting_id("smartrecruiters", url) == pid


def test_not_a_board():
    assert sources.detect("https://jobs.smartrecruiters.com/") is None
    assert sources.detect("https://careers.smartrecruiters.com/api/whatever") is None
    assert sources.careers_url("smartrecruiters", "ServiceNow") == "https://careers.smartrecruiters.com/ServiceNow"


def test_a_posting_is_read_from_its_link(web):
    j = sources.posting(f"{JOB}{FDE}-forward-deployed-solution-engineer-applied-ai-fde", web)
    assert j.key == f"smartrecruiters:ServiceNow:{FDE}" and j.salary_min == 201_300
    assert j.url.endswith("-applied-ai-fde")
    assert sources.posting("https://careers.smartrecruiters.com/ServiceNow", web) is None  # the whole board
    with pytest.raises(sources.NotFound, match="expired"):
        sources.posting(f"{JOB}{GONE}-software-quality-engineer-intern-summer-2025", web)


def test_still_open_reads_the_posting_not_the_board(web):
    def job(pid):
        return Job(source="smartrecruiters", company="ServiceNow", id=pid, title="", url=f"{JOB}{pid}-x")
    assert still_open(job(FDE), web) is True
    assert still_open(job(GONE), web) is False
    assert not [c for c in web.calls if c.startswith(LIST)]


def test_find_board_by_name():
    web = FakeWeb({"https://careers.smartrecruiters.com/servicenow/api/more?page=0":
                   item(FDE, "x", "Forward Deployed Solution Engineer", board="servicenow"),
                   "https://careers.smartrecruiters.com/servicenow/api/more?page=1": ""})
    hits = [(s, b, len(jobs)) for s, b, jobs in sources.probe("ServiceNow", web)]
    assert hits == [("smartrecruiters", "servicenow", 1)]


def test_pay_with_cents_before_usd():
    assert parse_salary("The estimated salary range is 88,000 to 136,900.00 USD per year") == (88_000, 136_900)
