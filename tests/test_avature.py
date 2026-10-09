"""Avature careers portals: postings listed from the portal's sitemap (or its RSS feed), read from their pages."""

from pathlib import Path

import pytest

from jobwatch import sources
from jobwatch.models import Job
from jobwatch.watch import still_open

from .conftest import FakeWeb

FIXTURES = Path(__file__).parent / "fixtures"
# Lenovo's portal, trimmed: the sitemap index (es_ES listed first here, to show en_US is picked), the en_US
# sitemap with a few non-posting pages and five postings, the RSS feed for one search, and one posting's page.
INDEX = (FIXTURES / "avature_sitemap_index.xml").read_text(encoding="utf-8")
SITEMAP = (FIXTURES / "avature_sitemap.xml").read_text(encoding="utf-8")
FEED = (FIXTURES / "avature_feed.xml").read_text(encoding="utf-8")
PAGE = (FIXTURES / "avature_job.html").read_text(encoding="utf-8")

BOARD = "jobs.lenovo.com/careers"
FDE = "https://jobs.lenovo.com/en_US/careers/JobDetail/Forward-Deployed-Engineer/81926"
FEED_SEARCH = "https://jobs.lenovo.com/careers/SearchJobs/feed/?search=forward%20deployed"

# A posting on another company's portal, trimmed: other labels (Location, Business Area), no date, no og:url.
BLOOMBERG = "https://bloomberg.avature.net/careers/JobDetail/Buyside-Pre-Sales-Engineer-OMS-Enterprise-Sales-" \
            "Financial-Solutions/45161"
BLOOMBERG_PAGE = """<html><head>
<meta property="og:title" content="Buyside Pre Sales Engineer (OMS), Enterprise Sales - Financial Solutions" />
<meta property="og:url" content="" />
<meta name="Description" content="" />
</head><body><main>
<article class="article article--details " >
  <div class="article__content"><div class="article__content__view">
    <div class="article__content__view__field article__content__view__field__value--font">
      <div class="article__content__view__field__value">
        Buyside Pre Sales Engineer (OMS), Enterprise Sales - Financial Solutions
      </div>
    </div>
  </div></div>
</article>
<article class="article article--details regular-fields--cols-2Z regular-fields-label--inline" >
  <div class="article__content"><div class="article__content__view">
    <div class="article__content__view__field ">
      <div class="article__content__view__field__label">Location</div>
      <div class="article__content__view__field__value">London</div>
    </div>
    <div class="article__content__view__field ">
      <div class="article__content__view__field__label">Business Area</div>
      <div class="article__content__view__field__value">Sales and Client Service</div>
    </div>
    <div class="article__content__view__field ">
      <div class="article__content__view__field__label">Ref #</div>
      <div class="article__content__view__field__value">10054428</div>
    </div>
  </div></div>
</article>
<article class="article article--details " >
  <div class="article__header " ><div class="article__header__text">
    <h2 class="article__header__text__title title title--04">Description &amp; Requirements</h2>
  </div></div>
  <div class="article__content"><div class="article__content__view">
    <div class="article__content__view__field tf_replaceFieldVideoTokens field--rich-text">
      <div class="article__content__view__field__value">
        <div><strong>What's the role?&nbsp;</strong></div><div><br></div><div>We are seeking an experienced \
Pre-Sales Engineer / Solutions Architect with a deep knowledge of buyside workflows, particularly in order \
management solutions (OMS).&nbsp;</div>
      </div>
    </div>
  </div></div>
</article>
</main></body></html>"""


# A made-up portal laid out like Deloitte's: fields as field-title/field-value spans, places in the header, the
# posting's details as JobPosting markup (whose title og:title wraps in "Check out this job at ..."), and stock
# sections (accommodations, benefits) after the job's own text.
GLOBEX_BOARD = "apply.globex.example/careers"
GLOBEX = "https://apply.globex.example/en_US/careers/JobDetail/Agentic-AI-Engineer-Widgets/424242"
GLOBEX_LD = ('{"@context":"https:\\/\\/schema.org\\/","@type":"JobPosting",'
             '"title":"Agentic AI Engineer \\u2014 Widgets",'
             '"description":"Globex is building agents for widgets.\\n\\n\\tWork you\\u2019ll do\\n\\n\\t\\u2022 Build '
             'agents with LangGraph.\\n\\n\\tThe estimated base salary range is $150,000-$300,000.",'
             '"hiringOrganization":{"@type":"Organization","name":"Globex"},"datePosted":"2026-06-09",'
             '"validThrough":"2027-01-29T00:00"}')
# The first of the page's two JobPostings: named by an internal requisition title, its text the page's HTML
GLOBEX_INTERNAL_LD = ('{"@context":"http://schema.org","@type":"JobPosting","datePosted":"2026-06-09",'
                      '"title":"US Widgets Services-Agentic AI Engineer-Widgets-W&D",'
                      '"description":"<p>Globex is building agents for widgets.</p>","validThrough":"2027-01-29"}')


def globex_page(ld=True):
    return f"""<html><head>
<meta property="og:title" content="Check out this job at Globex, Agentic AI Engineer — Widgets" />
<meta property="og:url" content="{GLOBEX}" />
</head><body><main>
<article class="article article--details article--grow">
  <div class="article__header"><div class="article__header__text">
    <h2 class="article__header__text__title article__header__text__title--4">Agentic AI Engineer — Widgets</h2>
    <div class="article__header__text__subtitle"><span>Data</span> | <span>Data and Analytics</span></div>
    <div class="article__header__text__subtitle">
      <a class="link toggleLocations toggleLocations--show">Same job available in 2 locations</a>
<div class="article__header--locations article__header--locations article__header--locations-none" >
    <div class="fluid-cols fluid-cols--cols2">
        <p class="paragraph">Raleigh, North Carolina, United States</p>
        <p class="paragraph">Springfield, Illinois, United States</p>
    </div>
</div></div>
  </div></div>
</article>
<article class="article article--details"><div class="article__content"><div class="article__view">
  <div class="article__view__item view--row no-label view--rich-text">
    <span data-map="item-title" class="field-title"> </span>
    <span data-map="item-value" class="field-value"><p>Globex is building agents for widgets.</p>
      <p><span>Work you’ll do</span></p><ul><li>Build agents with LangGraph.</li></ul>
      <p>The estimated base salary range is $150,000-$300,000.</p></span>
  </div>
  <div class="article__view__item view--row view--rich-text">
    <span data-map="item-title" class="field-title"></span>
    <span data-map="item-value" class="field-value"><p>Benefits: Globex offers a stock benefits section.</p></span>
  </div>
  <div class="article__view__item ">
    <span data-map="item-title" class="field-title">Work type</span>
    <span data-map="item-value" class="field-value">Hybrid</span>
  </div>
  <div class="article__view__item visibility--hidden">
    <span data-map="item-title" class="field-title">Job ID</span>
    <span data-map="item-value" class="field-value">424242</span>
  </div>
</div></div></article>
</main>
{'<script type="application/ld+json">' + GLOBEX_INTERNAL_LD + '</script>' if ld else ''}
{'<script type="application/ld+json">' + GLOBEX_LD + '</script>' if ld else ''}
</body></html>"""


def lenovo_web(**more):
    return FakeWeb({
        f"https://{BOARD}/sitemap_index.xml": INDEX,
        "https://jobs.lenovo.com/en_US/careers/sitemap.xml": SITEMAP,
        FDE: PAGE,
        "https://jobs.lenovo.com/careers/JobDetail/Forward-Deployed-Engineer/81926": PAGE,  # redirects to en_US
        **more,
    })


def test_avature_lists_postings_from_the_sitemap_and_reads_the_wanted_ones():
    web = lenovo_web()
    jobs = {j.id: j for j in sources.fetch("avature", BOARD, web, search=["forward deployed"],
                                           wanted=lambda t: t == "Forward Deployed Engineer")}
    assert set(jobs) == {"79788", "80745", "81926"}
    fde = jobs["81926"]
    assert fde.key == f"avature:{BOARD}:81926" and fde.title == "Forward Deployed Engineer" and fde.url == FDE
    assert fde.locations == ["Morrisville, North Carolina, United States of America"] and fde.remote is None
    assert (fde.company_name, fde.department) == ("lenovo", "Artificial Intelligence")
    assert fde.posted.date().isoformat() == "2026-09-30"
    assert (fde.salary_min, fde.salary_max, fde.currency) == (152_000, 233_105, "USD")
    assert "Copilot Studio" in fde.description and "PAY TRANSPARENCY" in fde.description
    assert "WD00105712" not in fde.description  # labeled fields are the job's details, not its text
    assert fde.description.count("* United States of America") == 1  # the hidden copies are left out
    sr = jobs["79788"]  # listed, not read: its title is the one in its link
    assert sr.title == "Sr Forward Deployed Engineer REMOTE" and sr.description == "" and sr.company_name == "lenovo"
    assert web.calls == [f"https://{BOARD}/sitemap_index.xml", "https://jobs.lenovo.com/en_US/careers/sitemap.xml",
                         FDE]


def test_avature_without_search_terms_lists_every_posting():
    jobs = sources.fetch("avature", BOARD, lenovo_web(), wanted=lambda t: False)
    assert sorted(j.id for j in jobs) == ["48752", "55213", "79788", "80745", "81926"]
    assert all(not j.description for j in jobs)
    assert len(sources.fetch("avature", BOARD, lenovo_web(), wanted=lambda t: False, cap=2)) == 2


def test_avature_known_postings_are_not_read_again():
    known = Job(source="avature", company=BOARD, id="81926", title="Forward Deployed Engineer", url=FDE,
                description="read before")
    web = lenovo_web()
    jobs = sources.fetch("avature", BOARD, web, search=["forward deployed"], known={known.key: known})
    assert next(j for j in jobs if j.id == "81926") is known and FDE not in web.calls


def test_a_portal_without_postings_in_its_sitemap_is_read_from_its_feed():
    web = FakeWeb({f"https://{BOARD}/sitemap_index.xml": INDEX,
                   "https://jobs.lenovo.com/en_US/careers/sitemap.xml": "", FEED_SEARCH: FEED})
    jobs = {j.id: j for j in sources.fetch("avature", BOARD, web, search=["forward deployed"], wanted=lambda t: False)}
    assert set(jobs) == {"79788", "81926"}  # the feed's search found "AI Application Engineer" in its text only
    assert jobs["79788"].title == "Sr. Forward Deployed Engineer - REMOTE"
    assert jobs["79788"].posted.date().isoformat() == "2026-07-28"
    assert jobs["81926"].url == "https://jobs.lenovo.com/careers/JobDetail/Forward-Deployed-Engineer/81926"


@pytest.mark.parametrize("url, expected", [
    (FDE, ("avature", BOARD)),
    ("https://jobs.lenovo.com/careers/JobDetail/Forward-Deployed-Engineer/81926", ("avature", BOARD)),
    ("jobs.lenovo.com/en_US/careers/SearchJobs/?search=forward+deployed", ("avature", BOARD)),
    ("https://lenovo.avature.net/en_US/careers", ("avature", "lenovo.avature.net/careers")),
    (BLOOMBERG, ("avature", "bloomberg.avature.net/careers")),
    ("https://lenovo.avature.net/", None),
    ("https://www.lenovo.com/us/en/", None),
])
def test_avature_links(url, expected):
    assert sources.detect(url) == expected


def test_an_avature_link_is_read_from_its_page():
    web = lenovo_web()
    job = sources.posting(FDE + "?qtvc=abc123#top", web)  # robots.txt rules out qtvc=: it's dropped
    assert job.key == f"avature:{BOARD}:81926" and job.salary_max == 233_105 and job.description
    assert all("qtvc" not in u for u in web.calls)
    assert sources.posting("https://jobs.lenovo.com/careers/JobDetail/Forward-Deployed-Engineer/81926", web).id == \
        "81926"
    assert sources.posting("https://jobs.lenovo.com/en_US/careers/SearchJobs", web) is None
    assert sources._posting_id("avature", "https://jobs.lenovo.com/en_US/careers/JobDetail?jobId=81926") == "81926"
    with pytest.raises(sources.NotFound):  # a closed posting's page is Avature's 404 error page
        sources.posting("https://jobs.lenovo.com/en_US/careers/JobDetail/Forward-Deployed-Engineer/1", web)
    with pytest.raises(sources.SourceError):
        sources._avature_get("https://jobs.lenovo.com/careers/SearchJobs?qtvc=abc", web)
    assert sources.careers_url("avature", BOARD) == "https://jobs.lenovo.com/careers/SearchJobs"
    with pytest.raises(sources.SourceError):
        sources.fetch("avature", "jobs.lenovo.com", web)


def test_other_portals_name_their_fields_differently():
    job = sources.posting(BLOOMBERG, FakeWeb({BLOOMBERG: BLOOMBERG_PAGE}))
    assert job.title == "Buyside Pre Sales Engineer (OMS), Enterprise Sales - Financial Solutions"
    assert job.url == BLOOMBERG
    assert job.locations == ["London"] and job.department == "Sales and Client Service"
    assert job.company_name == "bloomberg" and job.posted is None and job.salary_min is None
    assert "order management solutions" in job.description and "10054428" not in job.description


def test_a_portal_with_field_spans_and_jobposting_markup_is_read():
    job = sources.posting(GLOBEX, FakeWeb({GLOBEX: globex_page()}))
    assert job.key == f"avature:{GLOBEX_BOARD}:424242"
    assert job.title == "Agentic AI Engineer — Widgets"  # the markup's, not og:title's "Check out this job at"
    assert job.locations == ["Raleigh, North Carolina, United States", "Springfield, Illinois, United States"]
    assert job.posted.date().isoformat() == "2026-06-09"
    assert (job.salary_min, job.salary_max) == (150_000, 300_000)
    assert job.description.startswith("Globex is building agents for widgets.")
    assert "• Build agents with LangGraph." in job.description and "\t" not in job.description
    assert "stock benefits" not in job.description and "424242" not in job.description


def test_field_spans_alone_give_the_text_and_labeled_fields():
    job = sources.posting(GLOBEX, FakeWeb({GLOBEX: globex_page(ld=False)}))
    assert "Build agents with LangGraph." in job.description and "424242" not in job.description  # hidden
    assert "Hybrid" not in job.description  # a labeled field: a detail, not the text
    assert job.locations[0] == "Raleigh, North Carolina, United States" and job.salary_max == 300_000


def test_a_page_with_no_posting_on_it_is_unreadable_not_closed():
    blank = "<html><body><main><p>Something went wrong. Try again later.</p></main></body></html>"
    web = FakeWeb({GLOBEX: blank})
    with pytest.raises(sources.SourceError) as e:
        sources.posting(GLOBEX, web)
    assert not isinstance(e.value, sources.NotFound) and "couldn't read" in str(e.value)
    job = Job(source="avature", company=GLOBEX_BOARD, id="424242", title="Agentic AI Engineer", url=GLOBEX)
    with pytest.raises(sources.SourceError):  # check_postings reports this as unknown, not closed
        still_open(job, web)


def test_a_field_span_portal_is_a_board():
    assert sources.detect(GLOBEX) == ("avature", GLOBEX_BOARD)
    index = ('<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap>'
             '<loc>https://apply.globex.example/en_US/careers/sitemap.xml</loc></sitemap></sitemapindex>')
    sitemap = ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               '<url><loc>https://apply.globex.example/en_US/careers/JobDetail</loc></url>'
               f'<url><loc>{GLOBEX}</loc></url>'
               '<url><loc>https://apply.globex.example/en_US/careers/JobDetail/Tax-Manager/424243</loc></url>'
               '</urlset>')
    web = FakeWeb({f"https://{GLOBEX_BOARD}/sitemap_index.xml": index,
                   "https://apply.globex.example/en_US/careers/sitemap.xml": sitemap, GLOBEX: globex_page()})
    jobs = {j.id: j for j in sources.fetch("avature", GLOBEX_BOARD, web, wanted=lambda t: "Agentic" in t)}
    assert set(jobs) == {"424242", "424243"} and jobs["424242"].salary_max == 300_000
    assert jobs["424243"].description == ""  # listed, not read


def test_avature_is_found_by_name_and_its_jobs_checked():
    web = lenovo_web(**{"https://lenovo.avature.net/careers/sitemap_index.xml": INDEX})
    hits = sources.probe("Lenovo", web)  # lenovo.avature.net's portal lives on jobs.lenovo.com
    assert [(s, b, sources.open_roles(j)) for s, b, j in hits] == [("avature", BOARD, "5")]
    assert not any(s == "avature" for s, _, _ in sources.probe("Globex", web))
    job = sources.posting(FDE, web)
    assert still_open(job, web) is True
    job.url = "https://jobs.lenovo.com/en_US/careers/JobDetail/Forward-Deployed-Engineer/1"
    assert still_open(job, web) is False
