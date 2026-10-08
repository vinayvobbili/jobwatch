"""Oracle Recruiting Cloud: a careers site's public REST API, searched like Workday. Trimmed from public postings."""

import os

import pytest

from jobwatch import sources

from .conftest import FakeWeb

BOARD = "eeho.fa.us2/CX_45001"
API = "https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest"
SITE = "https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_45001"


def search_url(keyword, offset=0, limit=2):
    return (f"{API}/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations"
            f"&finder=findReqs;siteNumber=CX_45001,limit={limit},offset={offset}"
            + (f",keyword={keyword}" if keyword else ""))


def detail_url(pid):
    return (f"{API}/recruitingCEJobRequisitionDetails?expand=secondaryLocations,requisitionFlexFields&onlyData=true"
            f"&finder=ById;Id=%22{pid}%22,siteNumber=CX_45001")


def req(pid, title, where, posted="2026-10-07", secondary=(), workplace=None):
    return {"Id": pid, "Title": title, "PostedDate": posted, "PrimaryLocation": where,
            "PrimaryLocationCountry": "US", "WorkplaceTypeCode": workplace, "WorkplaceType": "",
            "secondaryLocations": [{"Name": s, "CountryCode": "US"} for s in secondary]}


REQS = [
    req("342776", "Senior Platform Software Engineer (OCI - Developer Platform)", "Nashville, TN, United States",
        secondary=["United States"]),
    req("346955", "Senior Site Reliability Engineer", "United States", workplace="ORA_REMOTE"),
    req("335856", "Senior Data Center Operator I", "United States"),
]


def search_page(offset, hits=REQS):
    """One page of a search; the site counts every match on each page."""
    return {"items": [{"Keyword": "engineer", "TotalJobsCount": len(hits), "SiteNumber": "CX_45001",
                       "requisitionList": hits[offset:offset + 2]}], "count": 1, "hasMore": False}


DETAIL = {"items": [{
    "Id": "342776", "Title": "Senior Platform Software Engineer (OCI - Developer Platform)",
    "Category": "Product and Research", "JobFunction": "Software Engineering",
    "ExternalPostedStartDate": "2026-10-07T22:54:26+00:00", "PrimaryLocation": "Nashville, TN, United States",
    "PrimaryLocationCountry": "US", "WorkplaceTypeCode": None, "WorkplaceType": "",
    "ExternalDescriptionStr": "<p>Required to relocate/be onsite in Nashville, TN.&nbsp;</p><p>OCI is transforming "
                              "the developer platform experience.</p>",
    "ExternalResponsibilitiesStr": "<ul><li><p>Design, build, test, and operate core services and APIs for a "
                                   "modern application deployment platform on OCI.</p></li></ul>",
    "ExternalQualificationsStr": "Disclaimer:<br><br>US: Hiring Range in USD from: $92,500 to $209,500 per annum. "
                                 "May be eligible for bonus and equity.<br><p>Career Level - IC3</p>",
    "OrganizationDescriptionStr": "",
    "CorporateDescriptionStr": "<p>Only Oracle brings together the data, infrastructure, applications, and "
                               "expertise.</p>",
    "secondaryLocations": [{"Name": "United States", "CountryCode": "US"}],
    "requisitionFlexFields": [{"Prompt": "Years", "Value": "3 to 5+ years", "ControlType": "SingleChoiceList"},
                              {"Prompt": "Does this position require a security clearance?", "Value": "No"}],
}], "count": 1, "hasMore": False}


def remote_detail():
    d = {**DETAIL["items"][0], "Id": "346955", "Title": "Senior Site Reliability Engineer",
         "PrimaryLocation": "United States", "secondaryLocations": [], "WorkplaceTypeCode": "ORA_REMOTE",
         "ExternalQualificationsStr": "<p>Career Level - IC3</p>",
         # some sites give pay in a field of their own, not in the posting's text
         "requisitionFlexFields": [{"Prompt": "Base Pay/Salary", "Value": "New York,NY $137,750.00-$185,000.00",
                                    "ControlType": "TextArea"}, {"Prompt": "Empty", "Value": None}]}
    return {"items": [d], "count": 1, "hasMore": False}


@pytest.fixture
def oracle(monkeypatch):
    monkeypatch.setattr(sources, "ORACLE_PAGE", 2)
    fake = FakeWeb({search_url("engineer"): search_page(0), search_url("engineer", 2): search_page(2),
                    search_url(""): search_page(0), search_url("", 2): search_page(2),
                    detail_url("342776"): DETAIL, detail_url("346955"): remote_detail(),
                    detail_url("999"): {"items": [], "count": 0, "hasMore": False}})
    monkeypatch.setattr(sources, "get_json", fake)
    return fake


def test_oracle_searches_titles_and_reads_only_wanted_postings(oracle):
    jobs = sources.fetch("oracle", BOARD, search=["engineer"], wanted=lambda t: "Engineer" in t)
    by_id = {j.id: j for j in jobs}
    assert set(by_id) == {"342776", "346955", "335856"}
    assert len([c for c in oracle.calls if "JobRequisitions?" in c]) == 2  # two pages
    j = by_id["342776"]
    assert j.key == f"oracle:{BOARD}:342776" and j.url == f"{SITE}/job/342776" and j.company_name == "eeho"
    assert j.locations == ["Nashville, TN, United States", "United States"] and j.remote is None
    assert (j.salary_min, j.salary_max, j.currency) == (92_500, 209_500, "USD")
    assert "transforming the developer platform" in j.description and "core services and APIs" in j.description
    assert "Only Oracle brings together" not in j.description  # the same company blurb on every posting
    assert j.description.endswith("Years: 3 to 5+ years\nDoes this position require a security clearance?: No")
    assert j.department == "Product and Research" and j.posted.isoformat().startswith("2026-10-07T22:54")
    sre = by_id["346955"]
    assert sre.remote is True and (sre.salary_min, sre.salary_max) == (137_750, 185_000)
    assert "Base Pay/Salary: New York,NY" in sre.description and "Empty" not in sre.description
    operator = by_id["335856"]  # its title fails `wanted`: listed, not read
    assert operator.description == "" and detail_url("335856") not in oracle.calls
    assert operator.posted.date().isoformat() == "2026-10-07"


def test_oracle_known_postings_are_not_read_again(oracle):
    first = sources.fetch("oracle", BOARD, search=["engineer"], wanted=lambda t: True)
    oracle.calls.clear()
    again = sources.fetch("oracle", BOARD, search=["engineer"], wanted=lambda t: True,
                          known={j.key: j for j in first if j.description})
    assert [c for c in oracle.calls if "Details" in c] == [detail_url("335856")]  # the one it couldn't read
    assert {j.id for j in again} == {j.id for j in first}


def test_a_keyword_cant_break_the_finder(monkeypatch):
    web = FakeWeb({search_url("Staff%20Engineer%20Platform"): search_page(0, [])})
    monkeypatch.setattr(sources, "ORACLE_PAGE", 2)
    assert sources.fetch("oracle", BOARD, web, search=['Staff Engineer, "Platform";']) == []
    assert web.calls == [search_url("Staff%20Engineer%20Platform")]


@pytest.mark.parametrize("url, expected", [
    (f"{SITE}/job/342776", ("oracle", BOARD)),
    ("https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210784683/?utm_source=x",
     ("oracle", "jpmc.fa/CX_1001")),
    ("https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_45001/requisitions/preview/342776",
     ("oracle", BOARD)),
    ("https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_45001", ("oracle", BOARD)),
    ("https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites", None),
    ("https://eeho.fa.us2.oraclecloud.com/", None),
])
def test_oracle_links(url, expected):
    assert sources.detect(url) == expected


def test_oracle_careers_url_and_bad_boards():
    assert sources.careers_url("oracle", BOARD) == SITE
    assert sources.careers_url("oracle", "jpmc.fa/CX_1001") == \
        "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001"
    for bad in ("eeho.fa.us2", "eeho/CX_1", "eeho.fa.us2/CX 1,limit=1"):
        with pytest.raises(sources.SourceError):
            sources.fetch("oracle", bad, FakeWeb({}), search=["engineer"])


def test_one_oracle_posting_is_read_by_its_link(oracle):
    j = sources.posting(f"{SITE}/job/342776?utm_medium=jobshare")
    assert j.title.startswith("Senior Platform Software Engineer") and j.url == f"{SITE}/job/342776"
    assert oracle.calls == [detail_url("342776")]  # the requisition alone, no search
    assert sources.posting(f"{SITE}/requisitions/preview/346955").remote is True
    assert sources.posting(SITE) is None  # the whole site
    with pytest.raises(sources.NotFound):
        sources.posting(f"{SITE}/job/999")


def test_find_reads_an_oracle_board_from_a_link_and_never_guesses_one(oracle):
    [(source, board, jobs)] = sources.probe(f"{SITE}/job/342776")
    assert (source, board, len(jobs)) == ("oracle", BOARD, 3)
    assert not any(s == "oracle" for s, _, _ in sources.probe("Oracle", FakeWeb({})))


LIVE = [("eeho.fa.us2/CX_45001", "software engineer"),  # Oracle's own careers site
        ("jpmc.fa/CX_1001", "software engineer")]       # JPMorgan Chase


@pytest.mark.network
@pytest.mark.skipif(not os.environ.get("JOBWATCH_LIVE_TESTS"), reason="network: set JOBWATCH_LIVE_TESTS=1")
@pytest.mark.parametrize("board, term", LIVE)
def test_live_oracle_sites(board, term):
    """One search page and one posting per site: the real API still has the shape the parser reads."""
    jobs = sources.fetch("oracle", board, search=[term], wanted=lambda t: False, cap=sources.ORACLE_PAGE)
    assert jobs and all(j.title and j.url.startswith(sources.careers_url("oracle", board)) for j in jobs)
    j = sources.posting(jobs[0].url)
    assert (j.id, j.title) == (jobs[0].id, jobs[0].title) and len(j.description) > 200 and j.locations
