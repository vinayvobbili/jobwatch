"""Amazon: amazon.jobs's own search, in JSON with each role's full text, searched for the watchlist's titles."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from jobwatch import sources
from jobwatch.filters import Filters, reject_reason
from jobwatch.watch import still_open

# Four public postings from amazon.jobs's search, their text trimmed: a forward deployed engineer role in three
# US cities with a pay line for each, one virtual anywhere in the US, one virtual in Texas only, and one in London.
POSTINGS = json.loads((Path(__file__).parent / "fixtures" / "amazon_search.json").read_text(encoding="utf-8"))
FDE, PENTEST, TEXAS, LONDON = "10517491", "10541168", "10482387", "10571963"


class AmazonSearch:
    """Stands in for get_json on amazon.jobs's search: base_query finds a posting by id or by all its words,
    normalized_country_code[] keeps one country, offset and result_limit page. Records each URL asked for."""

    def __init__(self, postings=None, error=None):
        self.postings = POSTINGS if postings is None else postings
        self.error = error
        self.calls: list[str] = []

    def __call__(self, url, timeout=30, body=None):
        self.calls.append(url)
        parsed = urlparse(url)
        if not url.startswith(sources.AMAZON_SEARCH):
            raise sources.NotFound(url)
        q = {k: v[0] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
        term, country = q.get("base_query", "").lower(), q.get("normalized_country_code[]")

        def hit(p):
            text = " ".join(str(p.get(k) or "") for k in ("title", "description", "basic_qualifications")).lower()
            return term == p["id_icims"] or all(w in text for w in term.split())
        hits = [p for p in self.postings if hit(p) and (not country or p["country_code"] == country)]
        offset, size = int(q.get("offset", 0)), int(q.get("result_limit", 10))
        return {"error": self.error, "hits": len(hits), "facets": {}, "content": {},
                "jobs": hits[offset:offset + size]}


def test_amazon_lists_its_us_roles():
    web = AmazonSearch()
    jobs = {j.id: j for j in sources.fetch("amazon", "amazon", web, search=["engineer"])}
    assert set(jobs) == {FDE, PENTEST, TEXAS}  # not the London one
    assert len(web.calls) == 1 and "sort=recent" in web.calls[0] and "normalized_country_code%5B%5D=USA" in web.calls[0]
    fde = jobs[FDE]
    assert fde.key == f"amazon:amazon:{FDE}" and fde.title.startswith("Sr Forward Deployed Engineer")
    assert fde.url == sources.AMAZON_JOBS + POSTINGS[0]["job_path"]
    assert fde.locations == ["Seattle, Washington, USA", "New York, New York, USA", "Mountain View, California, USA"]
    assert (fde.company_name, fde.department, fde.remote) == ("Amazon", "Software Development", None)
    assert fde.posted.date().isoformat() == "2026-08-27"
    assert "Basic qualifications\n- 5+ years" in fde.description and "AD&D insurance" in fde.description


def test_amazon_pay_spans_its_places():
    jobs = {j.id: j for j in sources.fetch("amazon", "amazon", AmazonSearch(), search=["engineer"])}
    # Seattle's floor to Mountain View's top, not just the first line
    assert (jobs[FDE].salary_min, jobs[FDE].salary_max, jobs[FDE].currency) == (168_100, 261_500, "USD")
    assert (jobs[PENTEST].salary_min, jobs[PENTEST].salary_max) == (159_300, 202_400)


def test_amazon_virtual_roles_are_remote_where_they_say():
    jobs = {j.id: j for j in sources.fetch("amazon", "amazon", AmazonSearch(), search=["security"])}
    anywhere, texas = jobs[PENTEST], jobs[TEXAS]
    assert anywhere.locations == ["Remote - USA"] and anywhere.remote is True
    assert texas.locations == ["Remote - Texas, USA"] and texas.remote is None
    remote = Filters(locations=["remote"])
    assert reject_reason(anywhere, remote) is None
    assert reject_reason(texas, remote) == "location"  # remote only for people in Texas
    assert reject_reason(texas, Filters(locations=["remote", "Texas"])) is None


def test_amazon_titles_not_wanted_are_kept_without_their_text():
    jobs = {j.id: j for j in sources.fetch("amazon", "amazon", AmazonSearch(), search=["security"],
                                           wanted=lambda t: "Manager" not in t)}
    assert jobs[PENTEST].description and jobs[PENTEST].salary_min == 159_300
    assert jobs[TEXAS].description == "" and jobs[TEXAS].salary_min is None and jobs[TEXAS].title


def test_amazon_any_is_everywhere():
    jobs = {j.id: j for j in sources.fetch("amazon", "amazon/any", AmazonSearch(), search=["forward deployed"])}
    assert set(jobs) == {FDE, LONDON}
    london = jobs[LONDON]
    assert london.key == f"amazon:amazon/any:{LONDON}" and london.locations == ["London, England, GBR"]
    assert london.salary_min is None and london.posted.date().isoformat() == "2026-10-07"  # "October  7, 2026"
    with pytest.raises(sources.SourceError):
        sources.fetch("amazon", "aws", AmazonSearch())


def test_amazon_is_searched_a_page_at_a_time_up_to_the_cap():
    many = [dict(POSTINGS[1], id_icims=str(20000000 + n)) for n in range(250)]
    web = AmazonSearch(many)
    assert len(sources.fetch("amazon", "amazon", web, search=["security"])) == 250
    assert [parse_qs(urlparse(u).query)["offset"] for u in web.calls] == [["0"], ["100"], ["200"]]
    web = AmazonSearch(many)
    assert len(sources.fetch("amazon", "amazon", web, search=["security"], cap=150)) == 150
    assert len(web.calls) == 2
    web = AmazonSearch(many)
    assert len(sources.fetch("amazon", "amazon", web, search=["security", "penetration"])) == 250  # once each


def test_an_amazon_error_is_a_source_error():
    with pytest.raises(sources.SourceError):
        sources.fetch("amazon", "amazon", AmazonSearch(error="Invalid search"), search=["engineer"])


@pytest.mark.parametrize("url, expected", [
    (f"https://www.amazon.jobs/en/jobs/{FDE}/sr-forward-deployed-engineer-aws", ("amazon", "amazon")),
    (f"https://amazon.jobs/en-gb/jobs/{LONDON}", ("amazon", "amazon")),
    (f"https://account.amazon.jobs/jobs/{FDE}/apply", ("amazon", "amazon")),
    ("https://www.amazon.jobs/en/search?base_query=engineer", ("amazon", "amazon")),
    ("https://www.amazon.com/jobs", None),
])
def test_amazon_links(url, expected):
    assert sources.detect(url) == expected


def test_an_amazon_link_is_read_by_its_id():
    web = AmazonSearch()
    job = sources.posting(f"https://www.amazon.jobs/en/jobs/{FDE}/sr-forward-deployed-engineer", web)
    assert job.key == f"amazon:amazon:{FDE}" and job.salary_max == 261_500 and job.description
    assert parse_qs(urlparse(web.calls[-1]).query)["base_query"] == [FDE]
    assert sources.posting(f"https://account.amazon.jobs/jobs/{LONDON}/apply", web).id == LONDON  # outside the US
    assert sources.posting("https://www.amazon.jobs/en/search?base_query=engineer", web) is None
    assert sources.posting("https://www.amazon.jobs/en/jobs/", web) is None
    with pytest.raises(sources.NotFound):
        sources.posting("https://www.amazon.jobs/en/jobs/10000001/gone", web)
    assert sources.careers_url("amazon", "amazon") == "https://www.amazon.jobs/en/search"


def test_amazon_is_found_by_name_and_its_jobs_checked():
    for name in ("Amazon Web Services", "AWS"):
        hits = sources.probe(name, AmazonSearch())
        assert [(s, b, sources.open_roles(j)) for s, b, j in hits] == [("amazon", "amazon", "3")]
    assert not any(s == "amazon" for s, _, _ in sources.probe("Globex", AmazonSearch()))
    job = sources.posting(f"https://www.amazon.jobs/en/jobs/{TEXAS}", AmazonSearch())
    assert still_open(job, AmazonSearch()) is True
    job.url = "https://www.amazon.jobs/en/jobs/10000001/gone"
    assert still_open(job, AmazonSearch()) is False
