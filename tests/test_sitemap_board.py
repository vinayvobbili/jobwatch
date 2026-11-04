"""A careers site that lists its job pages in a sitemap, each page carrying schema.org JobPosting markup."""

from pathlib import Path

import pytest

from jobwatch import cli, config, sources, watch
from jobwatch.models import Job
from jobwatch.watch import still_open

from .conftest import FakeWeb

FIXTURES = Path(__file__).parent / "fixtures"
# Made-up pages in a common layout: a sitemap of four postings (and pages that aren't postings, a French copy of
# one, and a link on another host), the page of the first posting, with every place, its career area and its pay,
# and the page a closed posting shows in place of its own.
SITEMAP = (FIXTURES / "sitemap_urls.xml").read_text(encoding="utf-8")
POSTING = (FIXTURES / "sitemap_job.html").read_text(encoding="utf-8")
CLOSED = (FIXTURES / "sitemap_closed.html").read_text(encoding="utf-8")

HOST = "careers.example.com"
SITE = f"https://{HOST}/en/jobs"
MAP = f"https://{HOST}/sitemap.xml"
ROBOTS = f"https://{HOST}/robots.txt"
PLATFORM = f"{SITE}/r-100001/senior-platform-engineer/"
RETIRED = f"{SITE}/r-100004/retired-role/"


def site_web(**more) -> FakeWeb:
    return FakeWeb({MAP: SITEMAP, PLATFORM: POSTING, RETIRED: CLOSED, **more})


def listed(web, **kw):
    return {j.id: j for j in sources.fetch("sitemap", HOST, web, **kw)}


def test_the_sitemap_is_listed_and_wanted_roles_read():
    web = site_web()
    jobs = listed(web, wanted=lambda t: "Platform" in t)
    assert set(jobs) == {"R-100001", "R-100002", "R-100003", "R-100004"}  # not the French copy, not other pages
    eng = jobs["R-100001"]
    assert eng.key == f"sitemap:{HOST}:R-100001" and eng.title == "Senior Platform Engineer"
    assert eng.url == PLATFORM and (eng.company_name, eng.department) == ("Initech", "Technology")
    assert eng.locations == ["Boulder, Colorado", "Pune, Maharashtra, India"] and eng.remote is None
    assert eng.posted.date().isoformat() == "2026-01-02"
    assert (eng.salary_min, eng.salary_max, eng.currency) == (150_000, 190_000, "USD")
    assert "Terraform" in eng.description and "Build and run the widget platform & its tooling." in eng.description
    da = jobs["R-100002"]  # listed, not read: the title is the link's, in words; the company, the host's
    assert da.description == "" and da.title == "Data Analyst Reporting" and da.company_name == "Example"
    assert web.calls == [ROBOTS, MAP, PLATFORM]


def test_robots_txt_names_the_sitemaps_and_closes_pages_to_robots():
    index = ('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap>'
             f'<loc>https://{HOST}/sitemap-pages.xml</loc></sitemap><sitemap><loc>https://{HOST}/sitemap-jobs.xml'
             '</loc></sitemap></sitemapindex>')
    pages = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>'
             f'{SITE}/r-100009/not-a-posting-sitemap/</loc></url></urlset>')
    robots = f"User-agent: *\nDisallow: /en/jobs/r-100003/\nSitemap: https://{HOST}/index.xml\n"
    web = site_web(**{ROBOTS: robots, f"https://{HOST}/index.xml": index, f"https://{HOST}/sitemap-jobs.xml": SITEMAP,
                      f"https://{HOST}/sitemap-pages.xml": pages})
    assert set(listed(web, wanted=lambda t: False)) == {"R-100001", "R-100002", "R-100004"}  # R-100003: disallowed
    assert f"https://{HOST}/sitemap-pages.xml" not in web.calls  # an index is followed to the sitemaps for jobs
    assert MAP not in web.calls
    with pytest.raises(sources.SourceError, match="HTTP 403"):  # a robots.txt that can't be read allows nothing
        sources.fetch("sitemap", HOST, site_web(**{ROBOTS: sources.SourceError("HTTP 403")}))


def test_a_site_with_no_job_pages_in_its_sitemap_is_an_error():
    with pytest.raises(sources.SourceError, match="no job pages"):
        sources.fetch("sitemap", HOST, FakeWeb({}))
    with pytest.raises(sources.SourceError):
        sources.fetch("sitemap", HOST, FakeWeb({MAP: "<html>not a sitemap"}))


def test_a_search_lists_only_roles_with_its_words_and_the_cap_ends_the_list():
    web = site_web()
    titles = [j.title for j in sources.fetch("sitemap", HOST, web, search=("platform engineer",),
                                             wanted=lambda t: False)]
    assert titles == ["Senior Platform Engineer"] and PLATFORM not in web.calls
    assert len(sources.fetch("sitemap", HOST, site_web(), wanted=lambda t: False, cap=2)) == 2


def test_known_postings_are_not_read_again():
    known = Job(source="sitemap", company=HOST, id="R-100001", title="Senior Platform Engineer", url=PLATFORM,
                description="read before")
    web = site_web()
    jobs = listed(web, known={known.key: known})
    assert jobs["R-100001"] is known and PLATFORM not in web.calls


def test_a_posting_that_cant_be_read_stays_listed():
    web = site_web(**{PLATFORM: sources.SourceError("HTTP 500")})
    eng = listed(web)["R-100001"]
    assert eng.description == "" and eng.title == "Senior Platform Engineer"


@pytest.mark.parametrize("url, expected", [
    (PLATFORM, ("R-100001", "Senior Platform Engineer")),
    (PLATFORM + "?src=mail#top", ("R-100001", "Senior Platform Engineer")),
    (f"{SITE}/r-100001/", ("R-100001", "")),
    ("careers.example.com/en/jobs/r-584380/branch-manager", ("R-584380", "Branch Manager")),
    ("https://jobs.example.com/job/JR0012/data-analyst_reporting", ("JR0012", "Data Analyst Reporting")),
    ("https://example.com/careers/jobs/12345-staff-engineer", ("12345", "Staff Engineer")),
    ("https://example.com/job/4821", ("4821", "")),
    (f"{SITE}/", None),
    (f"{SITE}/?search=security", None),
    (f"{SITE}/search", None),
    ("https://careers.example.com/en/", None),
    ("https://careers.example.com/blog/jobs-report-2026", None),
])
def test_a_job_page_is_a_job_segment_then_an_id(url, expected):
    assert sources._sitemap_job(url) == expected


@pytest.mark.parametrize("host, company", [
    ("careers.initech.com", "Initech"), ("www.globex.com", "Globex"), ("initechjobs.com", "Initech"),
    ("jobs.umbrella-corp.com", "Umbrella Corp"), ("jobs.com", "Jobs")])
def test_the_company_is_named_by_the_host(host, company):
    assert sources._sitemap_company(host) == company


def test_a_link_is_read_from_its_page_and_a_closed_posting_is_not_found():
    web = site_web()
    job = sources.posting(PLATFORM + "?src=mail", web)  # a host that isn't watched: its page is read all the same
    assert job.key == f"sitemap:{HOST}:R-100001" and job.salary_max == 190_000 and job.description
    assert job.company_name == "Initech" and job.url == PLATFORM
    assert web.calls == [ROBOTS, PLATFORM]
    assert sources.posting(f"{SITE}/?search=security", web) is None
    with pytest.raises(sources.NotFound):  # the page titled "Sorry, this job posting is now closed"
        sources.posting(RETIRED, site_web(), hosts=(HOST,))
    with pytest.raises(sources.NotFound):  # or no page at all (HTTP 404)
        sources.posting(f"{SITE}/r-100005/", FakeWeb({}), hosts=(HOST,))
    empty = f"{SITE}/r-100006/"
    with pytest.raises(sources.SourceError) as e:  # a page with no posting on it is unreadable, not closed
        sources.posting(empty, FakeWeb({empty: "<html><title>Initech</title></html>"}), hosts=(HOST,))
    assert not isinstance(e.value, sources.NotFound)


def test_a_page_on_a_host_nobody_watches_is_read_only_when_it_is_a_posting_robots_txt_allows():
    assert sources.posting(RETIRED, site_web()) is None  # closed, or any page that isn't a posting: not for us to say
    empty = f"{SITE}/r-100006/"
    assert sources.posting(empty, FakeWeb({empty: "<html><title>Initech</title></html>"})) is None
    shut = site_web(**{ROBOTS: "User-agent: *\nDisallow: /en/jobs/\n"})
    assert sources.posting(PLATFORM, shut) is None and PLATFORM not in shut.calls
    with pytest.raises(sources.SourceError, match=r"robots\.txt"):  # but a watched host is told
        sources.posting(PLATFORM, shut, hosts=(HOST,))


def test_the_board_is_a_host():
    assert sources.careers_url("sitemap", HOST) == f"https://{HOST}/"
    for board in ("initech", "https://careers.example.com", "careers.example.com/jobs"):
        with pytest.raises(sources.SourceError):
            sources.fetch("sitemap", board, site_web())


def test_a_sitemap_board_is_found_from_a_careers_page_or_job_link_and_its_jobs_checked():
    web = site_web(**{f"{SITE}/": "<html><a href='/en/jobs/r-100001/x/'>Jobs</a></html>"})
    for link in (f"{SITE}/", f"{HOST}/en/jobs/", PLATFORM):
        hits = sources.probe(link, web, web)
        assert [(s, b, sources.open_roles(j)) for s, b, j in hits] == [("sitemap", HOST, "4")], link
    assert sources.probe("Initech", web, web) == []  # no name guess
    job = sources.posting(PLATFORM, web, hosts=(HOST,))
    assert still_open(job, web) is True
    job.url = RETIRED
    assert still_open(job, web) is False


def test_finding_a_sitemap_board_is_the_last_thing_tried_and_needs_job_markup():
    page = "<html><a href='https://boards.greenhouse.io/initech'>Open roles</a></html>"
    web = site_web(**{f"{SITE}/": page, "https://boards-api.greenhouse.io/v1/boards/initech/jobs?content=true":
                      {"jobs": []}})
    assert [(s, b) for s, b, _ in sources.probe(f"{SITE}/", web, web)] == [("greenhouse", "initech")]
    assert MAP not in web.calls and ROBOTS not in web.calls  # a page that links to a board never reaches the sitemap
    assert sources.probe("https://boards.greenhouse.io/initech", web, web)[0][0] == "greenhouse"
    plain = site_web(**{PLATFORM: "<html><title>Senior Platform Engineer</title></html>", RETIRED: CLOSED,
                        f"{SITE}/": "<html>Jobs</html>"})
    assert sources.probe(f"{SITE}/", plain, plain) == []  # job links, but pages without JobPosting markup
    gone = FakeWeb({MAP: SITEMAP, PLATFORM: POSTING})  # its careers page 404s (a closed job's link): still found
    assert [(s, b) for s, b, _ in sources.probe(RETIRED, gone, gone)] == [("sitemap", HOST)]
    with pytest.raises(sources.NotFound):  # nothing found, and the page was unreadable: say so
        sources.probe("https://careers.initech.example/en/jobs/", FakeWeb({}), FakeWeb({}))


def test_find_names_the_board_and_fetch_watches_it(web, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sources, "get_text", site_web(**{f"{SITE}/": "<html>Jobs</html>"}))
    cli.main(["find", f"{SITE}/"])
    out = capsys.readouterr().out
    assert (f"{SITE}/: sitemap:{HOST}  (4 open roles, Example)  https://{HOST}/\n"
            "    e.g. Senior Platform Engineer") in out
    path = tmp_path / "jobwatch.yaml"
    path.write_text(f"companies:\n  - sitemap:{HOST}\nfilters:\n  titles: [engineer]\n", encoding="utf-8")
    assert config.load(path).boards[0].entry == f"sitemap:{HOST}"
    cli.main(["-c", str(path), "fetch"])
    assert "Checked 1 board(s): 1 open roles, 1 new." in capsys.readouterr().out
    cli.main(["-c", str(path), "digest"])
    out = capsys.readouterr().out
    assert "Senior Platform Engineer" in out and "Branch Manager" not in out
    assert "Initech's careers site" in out


def test_adding_a_link_on_a_watched_host_reads_its_page_and_a_closed_one_is_an_error(tmp_path):
    from jobwatch.config import Board
    from jobwatch.store import Store
    store = Store(tmp_path / "state.db")
    job, read = watch.save_job(store, PLATFORM, get=site_web(), boards=[Board("sitemap", HOST)])
    assert read and job.key == f"sitemap:{HOST}:R-100001" and job.description
    with pytest.raises(sources.NotFound):
        watch.save_job(store, RETIRED, get=site_web(), boards=[Board("sitemap", HOST)])
    job, read = watch.save_job(store, PLATFORM, get=site_web())  # not watched: the same
    assert read and job.company_name == "Initech"
