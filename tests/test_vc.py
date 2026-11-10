"""VC portfolio job boards: one board for a fund's whole portfolio, read newest first as a feeder (Consider, Getro, or
the fund's own Next.js page), each job under its own company with the board its link is on noted."""

import json
from datetime import timedelta

import pytest

from jobwatch import config, report, sources, suggest, watch
from jobwatch.models import Job
from jobwatch.store import Store

from .conftest import NOW, FakeWeb


def iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


# -- Consider: the page hands out a session and a CSRF token; the search API answers 100 roles a page, newest first

CONSIDER = "jobs.example-ventures.vc"
CONSIDER_PAGE = ('<html><script>window.serverInitialData = {"user":{},"csrfToken":"tok-123",'
                 '"board":{"id":"example-ventures","isParent":true},"clientConfig":{}};</script></html>')
CONSIDER_API = f"https://{CONSIDER}/api-boards/search-jobs"


def consider_job(slug: str, name: str, title: str, link: str, days_ago: float, **extra) -> dict:
    return {"jobId": str(len(title)), "companySlug": slug, "companyName": name, "title": title,
            "applyUrl": link, "url": link.split("?")[0], "locations": ["Remote USA"], "remote": True,
            "departments": ["Engineering"], "timeStamp": iso(days_ago), **extra}


INITECH = consider_job("initech", "Initech", "Senior Security Engineer",
                       "https://job-boards.greenhouse.io/initech/jobs/4001?utm_source=jobs.example-ventures.vc", 1,
                       salary={"minValue": 180000, "maxValue": 220000, "currency": {"value": "USD"},
                               "period": {"value": "year"}})
GLOBEX = consider_job("globex", "Globex", "Platform Engineer, Data Infrastructure",
                      "https://jobs.lever.co/globex/aaaa-1111?lever-source%5B%5D=jobs.example-ventures.vc", 2)
UMBRELLA = consider_job("umbrella", "Umbrella", "Security Engineer", "https://umbrella.example/careers/77", 3)
HOOLI = consider_job("hooli", "Hooli", "Account Executive", "https://jobs.ashbyhq.com/hooli/bbbb-2222", 2)
OLD = consider_job("vandelay", "Vandelay", "Security Engineer", "https://jobs.lever.co/vandelay/cccc-3333", 40)


def consider_api(pages: list[list[dict]]):
    """The search API: page one without a sequence, each later one with the sequence the one before handed out."""
    def answer(body):
        assert body["board"] == {"id": "example-ventures", "isParent": True} and body["meta"]["size"] == 100
        n = int(body["meta"].get("sequence", "0"))
        return {"jobs": pages[n] if n < len(pages) else [], "total": sum(map(len, pages)),
                "meta": {"size": 100, "sequence": str(n + 1) if n + 1 < len(pages) else None}}
    return answer


GREENHOUSE_INITECH = "https://boards-api.greenhouse.io/v1/boards/initech/jobs?content=true"


@pytest.fixture
def web():
    return FakeWeb({
        f"https://{CONSIDER}/jobs": CONSIDER_PAGE,
        CONSIDER_API: consider_api([[INITECH, GLOBEX, HOOLI], [UMBRELLA, OLD]]),
        GREENHOUSE_INITECH: {"jobs": [{"id": 4001, "title": "Senior Security Engineer",
                                       "absolute_url": "https://job-boards.greenhouse.io/initech/jobs/4001",
                                       "location": {"name": "Remote (US)"}, "content": "&lt;p&gt;Guard the TPS "
                                       "reports.&lt;/p&gt;", "first_published": iso(1)}]},
        "https://api.lever.co/v0/postings/globex?mode=json": [
            {"id": "aaaa-1111", "text": "Platform Engineer, Data Infrastructure",
             "hostedUrl": "https://jobs.lever.co/globex/aaaa-1111", "categories": {"location": "Remote"},
             "descriptionPlain": "Pipelines for the billing platform."}],
    })


def by_company(jobs) -> dict[str, Job]:
    return {j.company_name: j for j in jobs}


def test_a_consider_board_each_job_under_its_own_company(web):
    jobs = by_company(sources.fetch("vc", CONSIDER, web))
    assert sorted(jobs) == ["Globex", "Hooli", "Initech", "Umbrella"]  # not one posted 40 days ago
    initech = jobs["Initech"]
    assert initech.key == "vc:jobs.example-ventures.vc:initech-24"
    assert initech.url == "https://job-boards.greenhouse.io/initech/jobs/4001"  # where it was seen, dropped
    assert initech.boards == ["greenhouse:initech"]  # the company's own board, noted (not read: nothing wanted)
    assert (initech.salary_min, initech.salary_max, initech.currency) == (180000, 220000, "USD")
    assert initech.locations == ["Remote USA"] and initech.remote and initech.department == "Engineering"
    assert initech.age_days() == 1 and initech.description == ""
    assert jobs["Globex"].url == "https://jobs.lever.co/globex/aaaa-1111" and jobs["Globex"].boards == ["lever:globex"]
    assert jobs["Umbrella"].boards == []  # its own careers site: no board jobwatch reads
    # the page first (its session and token), then the API a page at a time; no posting read
    assert web.calls == [f"https://{CONSIDER}/robots.txt", f"https://{CONSIDER}/jobs", CONSIDER_API, CONSIDER_API]


def test_only_titles_with_a_search_terms_words(web):
    jobs = sources.fetch("vc", CONSIDER, web, search=["security engineer"])
    assert sorted(j.company_name for j in jobs) == ["Initech", "Umbrella"]


def test_wanted_jobs_are_read_from_their_own_posting(web):
    jobs = by_company(sources.fetch("vc", CONSIDER, web, wanted=lambda t: "Security" in t))
    initech = jobs["Initech"]
    assert initech.description == "Guard the TPS reports."
    assert initech.key == "vc:jobs.example-ventures.vc:initech-24"  # still the portfolio board's job
    assert jobs["Umbrella"].description == ""  # its own site: kept as listed
    assert GREENHOUSE_INITECH in web.calls and not [u for u in web.calls if "lever" in u or "ashby" in u]


def test_a_posting_its_board_no_longer_lists_is_left_out(web):
    web.responses[GREENHOUSE_INITECH] = {"jobs": []}
    jobs = by_company(sources.fetch("vc", CONSIDER, web, wanted=lambda t: "Security" in t))
    assert "Initech" not in jobs and "Umbrella" in jobs


def test_a_board_that_says_slow_down_is_not_asked_again(web):
    second = consider_job("initrode", "Initrode", "Security Engineer II",
                          "https://job-boards.greenhouse.io/initrode/jobs/5001", 1)
    web.responses[CONSIDER_API] = consider_api([[INITECH, second]])
    web.responses[GREENHOUSE_INITECH] = sources.SourceError(f"{GREENHOUSE_INITECH}: HTTP 429")
    jobs = sources.fetch("vc", CONSIDER, web, wanted=lambda t: True)
    assert len(jobs) == 2 and all(not j.description for j in jobs)  # both kept as listed
    assert [u for u in web.calls if "greenhouse" in u] == [GREENHOUSE_INITECH]  # Initrode's wasn't asked for


def test_a_job_read_before_is_kept_as_it_was(web):
    first = by_company(sources.fetch("vc", CONSIDER, web, wanted=lambda t: "Security" in t))
    known = {j.key: j for j in first.values()}
    web.calls.clear()
    again = by_company(sources.fetch("vc", CONSIDER, web, wanted=lambda t: "Security" in t, known=known))
    assert again["Initech"].description == "Guard the TPS reports."
    assert GREENHOUSE_INITECH not in web.calls  # read once


def test_reading_stops_at_jobs_older_than_the_newest_kept(web):
    pages = [[INITECH, GLOBEX], [consider_job("acme", "Acme", "Security Engineer", "https://acme.example/1", 9)],
             [UMBRELLA]]
    web.responses[CONSIDER_API] = consider_api(pages)
    kept = Job("vc", CONSIDER, "kept-1", "Engineer", "https://acme.example/0", company_name="Acme",
               posted=NOW - timedelta(days=5))
    jobs = sources.fetch("vc", CONSIDER, web, known={kept.key: kept})
    # page two is all older than the newest kept (less two days' slack): page three isn't asked for
    assert web.calls.count(CONSIDER_API) == 2
    assert sorted(j.company_name for j in jobs) == ["Acme", "Globex", "Initech"]


def test_a_board_that_stops_answering_partway(web):
    calls = []

    def answer(body):
        calls.append(body)
        if len(calls) > 1:
            raise sources.SourceError(f"{CONSIDER_API}: HTTP 429")
        return {"jobs": [INITECH], "meta": {"sequence": "1"}}
    web.responses[CONSIDER_API] = answer
    with pytest.raises(sources.Partial) as e:
        sources.fetch("vc", CONSIDER, web)
    assert [j.company_name for j in e.value.jobs] == ["Initech"]


def test_robots_txt_is_obeyed(web):
    web.responses[f"https://{CONSIDER}/robots.txt"] = "User-agent: *\nDisallow: /api-boards/\n"
    with pytest.raises(sources.SourceError, match="doesn't allow"):
        sources.fetch("vc", CONSIDER, web)
    assert CONSIDER_API not in web.calls


@pytest.mark.parametrize("board", ["", "not a host", "jobs"])
def test_board_names(web, board):
    with pytest.raises(sources.SourceError, match="host of its jobs page"):
        sources.fetch("vc", board, web)


def test_a_page_with_no_jobs_jobwatch_can_read(web):
    web.responses[f"https://{CONSIDER}/jobs"] = "<html><body>Our portfolio is hiring!</body></html>"
    with pytest.raises(sources.SourceError, match="no jobs found"):
        sources.fetch("vc", CONSIDER, web)


# -- Getro: the list page carries the newest matches for a search (?q=) as Next.js data

GETRO = "jobs.globex-capital.vc"


def getro_page(*jobs: dict) -> str:
    data = {"props": {"pageProps": {"initialState": {"jobs": {"found": list(jobs), "total": len(jobs)}}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


def getro_job(id_: int, name: str, title: str, url: str, days_ago: float, **extra) -> dict:
    return {"id": id_, "title": title, "url": url, "organization": {"name": name, "slug": name.lower()},
            "locations": ["Boulder, CO"], "workMode": "on_site",
            "createdAt": int((NOW - timedelta(days=days_ago)).timestamp()), **extra}


def test_a_getro_board_is_searched_for_each_title_term():
    pay = {"compensationAmountMinCents": 15000000, "compensationAmountMaxCents": 19000000,
           "compensationCurrency": "USD", "compensationPeriod": "year"}
    web = FakeWeb({
        f"https://{GETRO}/jobs": getro_page(getro_job(1, "Hooli", "Account Executive", "https://hooli.example/1", 1)),
        f"https://{GETRO}/jobs?q=security%20engineer": getro_page(
            getro_job(2, "Initech", "Security Engineer", "https://jobs.ashbyhq.com/initech/dddd-4444", 1, **pay)),
        f"https://{GETRO}/jobs?q=platform": getro_page(
            getro_job(3, "Globex", "Platform Engineer", "https://jobs.lever.co/globex/eeee-5555", 2)),
    })
    jobs = by_company(sources.fetch("vc", GETRO, web, search=["security engineer", "platform"]))
    assert sorted(jobs) == ["Globex", "Initech"]  # the newest overall don't match
    initech = jobs["Initech"]
    assert initech.key == f"vc:{GETRO}:2" and initech.boards == ["ashby:initech"]
    assert (initech.salary_min, initech.salary_max) == (150000, 190000) and initech.age_days() == 1
    assert initech.locations == ["Boulder, CO"] and initech.remote is None


# -- A fund's own Next.js page: the roles come in its React data, searched (?q=) or a page at a time

NEXT = "jobs.umbrella-partners.vc"


def flight_page(*jobs: dict, paged: bool = False) -> str:
    """A Next.js page: its React data pushed as strings, the roles inside."""
    data = '0:["$","div",null,{"children":["$","$L18",null,{"initialData":{"jobs":' + json.dumps(list(jobs)) + \
           ',"total":' + str(len(jobs)) + (',"pageCount":3' if paged else '') + '}}]}]\n'
    pushes = "".join(f"<script>self.__next_f.push([1,{json.dumps(part)}])</script>"
                     for part in (data[:40], data[40:]))  # one string can end inside a role
    return f"<html><body>{pushes}</body></html>"


def next_job(id_: str, name: str, title: str, link: str, days_ago: float) -> dict:
    return {"id": id_, "title": title, "apply_url": link, "company_name": name, "locations": ["Remote"],
            "remote": True, "salary_min": 160000, "salary_max": 190000, "salary_currency": "USD",
            "posted_at": iso(days_ago), "job_types": [{"label": "Engineering", "value": "engineering"}]}


def test_a_next_page_searched_for_each_title_term():
    web = FakeWeb({
        f"https://{NEXT}/jobs": flight_page(next_job("ats:1", "Hooli", "Designer", "https://hooli.example/1", 1)),
        f"https://{NEXT}/jobs?q=security": flight_page(
            next_job("ats:2", "Initech", "Security Engineer", "https://job-boards.greenhouse.io/initech/jobs/4001",
                     1)),
    })
    jobs = sources.fetch("vc", NEXT, web, search=["security"])
    assert [(j.company_name, j.id, j.boards) for j in jobs] == [("Initech", "ats-2", ["greenhouse:initech"])]
    assert jobs[0].salary_min == 160000 and jobs[0].remote


def test_a_numbered_next_page_is_read_a_page_at_a_time():
    board = f"{NEXT}/portfolio/jobs/"
    web = FakeWeb({
        f"https://{NEXT}/portfolio/jobs/": flight_page(
            next_job("a1", "Initech", "Security Engineer", "https://jobs.ashbyhq.com/initech/1", 1), paged=True),
        f"https://{NEXT}/portfolio/jobs/?page=2": flight_page(
            next_job("a2", "Globex", "Security Engineer", "https://jobs.lever.co/globex/2", 3), paged=True),
        f"https://{NEXT}/portfolio/jobs/?page=3": flight_page(
            next_job("a3", "Umbrella", "Security Engineer", "https://jobs.lever.co/umbrella/3", 30), paged=True),
    })
    jobs = sources.fetch("vc", board, web, search=["security"])
    assert [j.company_name for j in jobs] == ["Initech", "Globex"]  # page three's is too old to be new
    assert f"https://{NEXT}/portfolio/jobs/?q=security" not in web.calls  # a numbered list isn't searched
    assert f"https://{NEXT}/portfolio/jobs/?page=4" not in web.calls  # page three was all old: done
    assert sources.careers_url("vc", board) == f"https://{NEXT}/portfolio/jobs/"
    assert sources.careers_url("vc", CONSIDER) == f"https://{CONSIDER}/jobs"


# -- Watching a portfolio board

@pytest.fixture
def watched(tmp_path, web):
    path = tmp_path / "jobwatch.yaml"
    path.write_text(f"companies:\n  - vc:{CONSIDER}\n"
                    "filters:\n  titles: [engineer]\n  locations: [remote]\n  max_age_days: 30\n"
                    "state: state.db\ncache: cache\n")
    cfg = config.load(path)
    store = Store(cfg.state)
    yield cfg, store
    store.close()


def test_watching_a_portfolio_board(watched, web):
    cfg, store = watched
    r = watch.fetch_all(cfg, store, get=web)
    assert (r.boards, len(r.new), r.errors) == (1, 3, {})  # its engineering roles; not Hooli's sales one
    names = {j.key: j.display_company for j, _ in store.jobs()}
    assert sorted(names.values()) == ["Globex", "Initech", "Umbrella"]  # each job's own company
    initech, _ = store.find("vc:jobs.example-ventures.vc:initech-24")
    assert initech.description == "Guard the TPS reports."  # it passes the filters: read from its posting
    assert watch.scorable(initech)
    # their companies are ones to watch, with the board each job's link is on
    got = {s.name: s for s in suggest.suggestions(cfg, store)}
    assert (got["Initech"].entry, got["Initech"].found_by) == ("greenhouse:initech", "posting")
    assert got["Globex"].entry == "lever:globex"
    # the board lists only its newest roles: one missing from a later read hasn't closed
    web.responses[CONSIDER_API] = consider_api([[GLOBEX]])
    watch.fetch_all(cfg, store, get=web, every_board=True)
    assert initech.key in {j.key for j, _ in store.jobs()}
    # whether it's still posted is asked of its own posting
    assert watch.still_open(initech, get=web) is True
    web.responses[GREENHOUSE_INITECH] = {"jobs": []}
    assert watch.still_open(initech, get=web) is False
    umbrella = next(j for j, _ in store.jobs() if j.company_name == "Umbrella")
    assert watch.still_open(umbrella, get=web) is None  # its own careers site: jobwatch can't tell


def test_where_a_job_came_from():
    job = Job("vc", CONSIDER, "1", "Engineer", "https://x", company_name="Initech")
    assert report.found_on(job) == f"the {CONSIDER} VC portfolio board"
    assert report.found_on(Job("vc", f"{NEXT}/portfolio/jobs/", "1", "Engineer", "https://x")) == \
        f"the {NEXT} VC portfolio board"


def test_a_portfolio_board_isnt_guessed_from_a_name(web):
    assert not [s for s, _, _ in sources.probe("Example Ventures", web) if s == "vc"]
