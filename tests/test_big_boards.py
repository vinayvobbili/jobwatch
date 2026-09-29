"""Workday and Eightfold: boards too big to list whole, so they're searched and read in full only when needed."""

import pytest

from jobwatch import config, sources, text
from jobwatch.filters import Filters, search_terms, title_ok
from jobwatch.store import Store
from jobwatch.watch import fetch_all

from .conftest import FakeWeb

WD = "https://initech.wd5.myworkdayjobs.com/wday/cxs/initech/External"


def wd_posting(n, title, where="2 Locations", posted="Posted Today"):
    return {"title": title, "externalPath": f"/job/{where.replace(' ', '-')}/{title.replace(' ', '-')}_R{n}",
            "locationsText": where, "postedOn": posted, "bulletFields": [f"R{n}"]}


# 25 engineer postings (two pages of 20), one architect; the search answers by term and offset.
ENGINEERS = [wd_posting(100 + n, f"Staff Security Engineer {n}") for n in range(24)] + \
    [wd_posting(200, "Pharmacy Engineer Intern")]
ARCHITECTS = [wd_posting(300, "Principal Architect", "TX - Work from home", "Posted 30+ Days Ago")]


def wd_search(body):
    hits = {"engineer": ENGINEERS, "architect": ARCHITECTS}.get(body["searchText"], ENGINEERS + ARCHITECTS)
    page = hits[body["offset"]:body["offset"] + body["limit"]]
    return {"total": len(hits) if body["offset"] == 0 else 0, "jobPostings": page}  # Workday counts once


def wd_detail(p):
    return {"jobPostingInfo": {
        "title": p["title"], "location": "Work At Home-Texas", "additionalLocations": ["MN - Minneapolis"],
        "remoteType": "Remote", "startDate": "2026-09-01",
        "externalUrl": "https://initech.wd5.myworkdayjobs.com/External" + p["externalPath"],
        "jobDescription": "<p>Detection engineering in <b>Python</b>.</p><p>Pay range: $180,000 - $250,000</p>"}}


def workday_web():
    responses = {f"{WD}/jobs": wd_search}
    for p in ENGINEERS + ARCHITECTS:
        responses[WD + p["externalPath"]] = wd_detail(p)
    return FakeWeb(responses)


def test_workday_searches_titles_and_reads_only_wanted_postings():
    web = workday_web()
    f = Filters(titles=["engineer", "architect"], exclude_titles=["intern"])
    jobs = sources.fetch("workday", "initech.wd5/External", web, search=search_terms(f),
                         wanted=lambda t: title_ok(t, f))
    by_id = {j.id: j for j in jobs}
    assert len(jobs) == 26 and set(by_id) == {f"R{100 + n}" for n in range(24)} | {"R200", "R300"}
    staff = by_id["R100"]
    assert staff.key == "workday:initech.wd5/External:R100" and staff.remote is True
    assert staff.locations == ["Work At Home-Texas", "MN - Minneapolis"]
    assert (staff.salary_min, staff.salary_max) == (180_000, 250_000) and "Python" in staff.description
    assert staff.posted.date().isoformat() == "2026-09-01"
    assert staff.url.startswith("https://initech.wd5.myworkdayjobs.com/External/job/")
    # The intern is listed from the search alone; its posting isn't read.
    intern = by_id["R200"]
    assert intern.description == "" and not any(c.endswith("_R200") for c in web.calls)
    assert by_id["R300"].age_days() is not None  # read: the detail's start date
    detail_calls = [c for c in web.calls if "/job/" in c]
    assert len(detail_calls) == 25


def test_workday_known_postings_are_not_read_again():
    web = workday_web()
    wanted = lambda t: True  # noqa: E731
    first = sources.fetch("workday", "initech.wd5/External", web, search=["architect"], wanted=wanted)
    web.calls.clear()
    again = sources.fetch("workday", "initech.wd5/External", web, search=["architect"], wanted=wanted,
                          known={j.key: j for j in first})
    assert again[0].description == first[0].description and web.calls == [f"{WD}/jobs"]


def test_workday_listed_ages():
    assert sources._workday_posted("Posted Today").date() == sources.datetime.now(sources.timezone.utc).date()
    def days(text):
        age = sources.datetime.now(sources.timezone.utc) - sources._workday_posted(text)
        return round(age.total_seconds() / 86400)
    assert (days("Posted 30+ Days Ago"), days("Posted 3 Days Ago"), days("Posted Yesterday")) == (30, 3, 1)
    assert sources._workday_posted("") is None


def test_a_search_stops_at_the_cap(monkeypatch):
    web = workday_web()
    jobs = sources.fetch("workday", "initech.wd5/External", web, wanted=lambda t: False, cap=20)
    assert len(jobs) == 20 and len(web.calls) == 1


EF = "https://globex.eightfold.ai/api/pcsx"


def ef_position(n, name, locations, where):
    return {"id": n, "name": name, "locations": locations, "workLocationOption": where, "department": "Security",
            "postedTs": "1790000000"}


EF_POSITIONS = [ef_position(1, "Principal Platform Engineer", "['Denver, CO, United States', 'Remote, United States']",
                            "remote_local"),
                ef_position(2, "Field Service Engineer", "['Hsinchu County, Taiwan']", "onsite"),
                *[ef_position(10 + n, f"Security Engineer {n}", ["United States"], "remote") for n in range(9)]]


def eightfold_web():
    responses = {}
    for start in (0, 10):
        responses[f"{EF}/search?domain=globex.com&query=engineer&start={start}"] = {
            "data": {"count": len(EF_POSITIONS), "positions": EF_POSITIONS[start:start + 10]}}
    for p in EF_POSITIONS:
        responses[f"{EF}/position_details?position_id={p['id']}&domain=globex.com"] = {"data": {
            "jobDescription": "<p>Salary: $200,000 - $260,000 per year</p>",
            "publicUrl": f"https://globex.eightfold.ai/careers/job/{p['id']}"}}
    return FakeWeb(responses)


def test_eightfold():
    web = eightfold_web()
    jobs = sources.fetch("eightfold", "globex", web, search=["engineer"], wanted=lambda t: "Field" not in t)
    by_id = {j.id: j for j in jobs}
    assert len(jobs) == 11
    lead = by_id["1"]
    assert lead.key == "eightfold:globex:1"
    assert lead.locations == ["Denver, CO, United States", "Remote, United States"]
    assert lead.remote is None  # remote_local names its places; they decide
    assert by_id["10"].remote is True and by_id["10"].locations == ["United States"]
    assert (lead.salary_min, lead.url) == (200_000, "https://globex.eightfold.ai/careers/job/1")
    assert by_id["2"].description == "" and lead.posted.year == 2026


@pytest.mark.parametrize("url, expected", [
    ("https://acme.wd1.myworkdayjobs.com/en-US/Acme_Careers/job/AZ---Phoenix/Staff_R1",
     ("workday", "acme.wd1/Acme_Careers")),
    ("https://initech.wd5.myworkdayjobs.com/External", ("workday", "initech.wd5/External")),
    ("https://wd5.myworkdaysite.com/recruiting/acme/Careers/job/x", ("workday", "acme.wd5/Careers")),
    ("https://initech.wd1.myworkdayjobs.com/", None),
    ("https://globex.eightfold.ai/careers?domain=globex.com", ("eightfold", "globex")),
    ("https://acme.eightfold.ai/careers/job/12?domain=acme-careers.com", ("eightfold", "acme/acme-careers.com")),
])
def test_detect_big_boards(url, expected):
    assert sources.detect(url) == expected


def test_careers_urls():
    assert sources.careers_url("workday", "initech.wd5/External") == "https://initech.wd5.myworkdayjobs.com/External"
    assert sources.careers_url("eightfold", "globex") == "https://globex.eightfold.ai/careers?domain=globex.com"
    assert sources.careers_url("lever", "globex") == "https://jobs.lever.co/globex"


def test_probe_finds_the_workday_data_center_and_site():
    """422: not in this data center; 404: here, but the site has another name; 200: found."""
    def site(board_site):
        def answer(body):
            return {"total": 1, "jobPostings": [wd_posting(1, "Staff Engineer")]}
        return answer
    responses = {}
    for pod in sources.WORKDAY_PODS:
        if pod != "wd12":
            for s in sources._workday_sites("initech"):
                responses[f"https://initech.{pod}.myworkdayjobs.com/wday/cxs/initech/{s}/jobs"] = \
                    sources.SourceError("HTTP 422")
    responses["https://initech.wd12.myworkdayjobs.com/wday/cxs/initech/Initech_Careers/jobs"] = site("Initech_Careers")
    hits = sources.probe("Initech", FakeWeb(responses))
    assert [(s, b, sources.open_roles(j)) for s, b, j in hits] == [("workday", "initech.wd12/Initech_Careers", "1")]
    assert sources.open_roles([None] * sources.PROBE_CAP) == f"{sources.PROBE_CAP}+"


def test_titles_to_search_and_to_read():
    f = Filters(titles=["engineer", "forward deployed", r"\bSRE\b"], exclude_titles=["intern"])
    assert search_terms(f) == ["engineer", "forward deployed"]
    assert title_ok("Staff Engineer", f) and not title_ok("Engineer Intern", f) and not title_ok("Designer", f)
    assert title_ok("Anything", Filters())


def test_work_from_home_is_remote():
    for place in ("Work At Home-Texas", "TX - Work from home", "NY - Work from hom", "Telecommute"):
        assert text.is_remote(place), place
    assert not text.is_remote("Homestead, FL")


def test_fetch_all_reads_a_posting_once(tmp_path):
    path = tmp_path / "jobwatch.yaml"
    path.write_text("companies:\n  - {source: workday, board: initech.wd5/External, name: Initech}\n"
                    "filters:\n  titles: [architect]\nstate: state.db\n")
    cfg, web = config.load(path), workday_web()
    store = Store(cfg.state)
    report = fetch_all(cfg, store, get=web)
    assert (report.boards, report.jobs, len(report.new)) == (1, 1, 1) and not report.errors
    assert sum("/job/" in c for c in web.calls) == 1
    web.calls.clear()
    fetch_all(cfg, store, get=web)
    assert web.calls == [f"{WD}/jobs"]  # the search only: the posting is in the store
    [(job, _)] = store.jobs()
    assert job.display_company == "Initech" and job.remote is True
