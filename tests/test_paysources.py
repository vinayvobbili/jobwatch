"""One job's pay as labelled sources (paysources.py). Every figure here is made up."""

import pytest

from jobwatch import cli, config, lca, levels, paysources
from jobwatch.models import Job
from jobwatch.store import Store
from jobwatch.web import App

EST = levels.Estimate(company="Initech", family="Software Engineer", level="L5", total=300_000, base=170_000,
                      ask=180_000, where="US-wide", url="https://example.com/levels", why=[])
FILINGS = lca.Estimate(company="Initech", title="Senior Software Engineer", where="Boulder, CO", count=14,
                       median=165_000, p25=150_000, p75=180_000, levels={}, examples=[], why=[])


def job(low=150_000, high=196_000):
    return Job(source="greenhouse", company="initech", id="1", title="Senior Software Engineer", url="u",
               company_name="Initech", locations=["Boulder, CO"], salary_min=low, salary_max=high, currency="USD")


def by_key(items):
    return {s["key"]: s for s in items}


def test_sources_come_in_one_fixed_order_each_with_a_label():
    got = paysources.sources(job(), result=EST, levels_on=True, est=FILINGS, lca_cached=True)
    assert [(s["key"], s["label"]) for s in got] == [
        ("posted", "Posted"), ("levels", "Levels"), ("lca", "LCA"), ("recruiter", "Recruiter"),
        ("glassdoor", "Glassdoor"), ("ask", "Ask")]
    s = by_key(got)
    assert s["posted"]["value"] == "$150K–$196K"
    assert s["levels"]["value"] == "$170K base" and s["levels"]["amount"] == 170_000
    assert s["lca"]["value"] == "$165K median (14 filings)"
    assert s["ask"]["value"] == "$180K"
    assert all(s[k]["reason"] is None for k in ("posted", "levels", "lca", "ask"))


def test_other_employers_filings_say_they_are_not_this_employers_pay():
    market = lca.Estimate(**{**FILINGS.__dict__, "where": f"CO, {lca.MARKET}", "count": 40})
    s = by_key(paysources.sources(job(), est=market, lca_cached=True))["lca"]
    assert s["value"] == "$165K median (40 filings, CO, all employers; not this employer's)"
    assert s["short"] == "$165K mkt"
    assert s["market"] is True  # the page's pay filter doesn't take it as this job's pay
    assert "market" not in by_key(paysources.sources(job(), est=FILINGS, lca_cached=True))["lca"]


def test_levels_without_a_base_shows_the_total():
    s = by_key(paysources.sources(job(), result=levels.Estimate(**{**EST.__dict__, "base": None, "ask": None}),
                                  levels_on=True))
    assert s["levels"]["value"] == "$300K total"
    assert (s["ask"]["value"], s["ask"]["reason"]) == (None, "Levels.fyi gives no base for this level")


@pytest.mark.parametrize("result, on, blank, reason", [
    (levels.REFUSED, True, "TBD", "refused today, asks again tomorrow"),
    (levels.PENDING, True, "TBD", "looking it up on Levels.fyi, a few pages at a time"),
    (paysources.LATER, True, "TBD", "not looked up in this list yet; open the job to look it up"),
    (None, True, "none", "no data for this title"),
    (None, False, "off", "turn on with pay.levels: true in the watchlist"),
])
def test_an_empty_levels_says_why(result, on, blank, reason):
    s = by_key(paysources.sources(job(), result=result, levels_on=on))["levels"]
    assert (s["value"], s["blank"]) == (None, blank) and s["reason"].startswith(reason)


def test_every_empty_source_has_a_reason():
    got = paysources.sources(job(None, None), levels_on=True)
    s = by_key(got)
    assert s["posted"]["reason"] == "the posting lists no pay"
    assert "jobwatch lca update" in s["lca"]["reason"]
    assert "jobwatch comp" in s["recruiter"]["reason"]
    assert "never fetches Glassdoor" in s["glassdoor"]["reason"]
    assert s["ask"]["reason"] == "no Levels.fyi figure to work from"
    assert all(x["value"] or x["reason"] for x in got)
    cached = by_key(paysources.sources(job(), lca_cached=True))["lca"]
    assert cached["reason"].startswith("fewer than 3 matching H-1B filings")


def test_recruiter_and_glassdoor_are_only_what_was_entered():
    comp = {"base": "165-195K", "bonus": "10% target", "equity": "", "offered": "180K", "asked": "210K",
            "glassdoor": "170-210K"}
    s = by_key(paysources.sources(job(), comp=comp))
    assert s["recruiter"]["value"] == "base 165-195K, bonus 10% target, offered 180K"
    assert s["glassdoor"]["value"] == "170-210K"


def test_the_json_has_a_key_per_source_and_the_line_reads_in_one_go():
    items = paysources.sources(job(), result=levels.REFUSED, levels_on=True, est=FILINGS, lca_cached=True)
    assert list(paysources.as_dict(items)) == ["posted", "levels", "lca", "recruiter", "glassdoor", "ask"]
    assert paysources.as_dict(items)["levels"] == {
        "label": "Levels", "value": None, "reason": "refused today, asks again tomorrow", "blank": "TBD"}
    text = paysources.line(items)
    assert " ".join(text.split()).startswith("Pay: Posted $150K–$196K · Levels TBD (refused today, asks again "
                                             "tomorrow) · LCA $165K median (14 filings)")
    assert "· Recruiter none · Glassdoor none ·" in " ".join(text.split())  # hints stay on the page's hover
    assert all(len(row) <= 100 for row in text.splitlines()) and text.splitlines()[1].startswith("     ")


def test_glassdoor_is_kept_next_to_the_recruiters_figures(web, watchlist, capsys):
    cli.main(["-c", str(watchlist), "fetch"])
    cli.main(["-c", str(watchlist), "comp", "101", "--glassdoor", "170-210K", "--base", "165-195K"])
    assert "base 165-195K; glassdoor 170-210K" in capsys.readouterr().out
    store = Store(config.load(watchlist).state)
    key = store.find("101")[0].key
    store.set_comp(key, glassdoor="")  # an empty one clears it, the rest stays
    assert store.comp(key)["glassdoor"] is None and store.comp(key)["base"] == "165-195K"
    with pytest.raises(ValueError, match="unknown compensation field"):
        store.set_comp(key, indeed="1")
    store.close()


def test_show_prints_the_pay_sources_on_one_line(web, watchlist, capsys):
    cli.main(["-c", str(watchlist), "fetch"])
    cli.main(["-c", str(watchlist), "comp", "101", "--glassdoor", "170-210K", "--base", "165-195K"])
    capsys.readouterr()
    cli.main(["-c", str(watchlist), "show", "101"])
    out = capsys.readouterr().out
    assert sum(row.startswith("Pay:") for row in out.splitlines()) == 1  # not also the posting's own header
    line = " ".join(out[out.index("Pay: "):].split("\n\n")[0].split())
    assert "Recruiter base 165-195K" in line and "Glassdoor 170-210K" in line
    assert "Levels off (turn on with pay.levels: true in the watchlist) · LCA" in line
    assert "Recruiter base 165-195K" in line and line.endswith("Ask off (needs pay.levels on)")


def test_the_posted_source_carries_the_posted_top_so_the_page_needs_no_other_field():
    posted = by_key(paysources.sources(job(120_000, 190_000)))["posted"]
    assert (posted["value"], posted["amount"]) == ("$120K–$190K", 190_000)
    assert by_key(paysources.sources(job(120_000, None)))["posted"]["amount"] == 120_000
    assert by_key(paysources.sources(job(None, None)))["posted"]["amount"] is None


def test_what_you_asked_a_recruiter_for_is_the_ask_chip():
    comp = {"base": "210K", "bonus": "20% target", "equity": "40K (vesting not yet asked)", "asked": "240K"}
    s = by_key(paysources.sources(job(), comp=comp, result=EST, levels_on=True))
    assert s["recruiter"]["value"] == "base 210K, bonus 20% target, equity 40K (vesting not yet asked)"
    assert s["ask"]["value"] == "240K"  # not Levels.fyi's $180K suggestion
    assert "You asked for 240K" in s["ask"]["detail"]
    s = by_key(paysources.sources(job(), comp={"base": "210K"}, result=EST, levels_on=True))
    assert s["ask"]["value"] == "$180K"  # nothing asked: the suggestion stays


def test_the_job_dialog_has_the_posted_top_and_what_a_recruiter_said(watchlist, web, capsys):
    cli.main(["-c", str(watchlist), "fetch"])
    cli.main(["-c", str(watchlist), "comp", "aaaa-1111", "--base", "210K", "--asked", "240K"])
    capsys.readouterr()
    got = App(watchlist).get_job({"key": ["lever:globex:aaaa-1111"]})  # the Details dialog's payload
    assert got["salary_max"] == 210_000 and got["pay_per"] is None
    s = by_key(got["pay_sources"])
    assert s["posted"]["amount"] == 210_000
    assert s["recruiter"]["value"] == "base 210K" and s["ask"]["value"] == "240K"


# -- links: each source points to where its figure can be checked (or nowhere), see paysources.py

def linked_job(**kw):
    return Job(source="greenhouse", company="initech", id="1", title="Senior Software Engineer",
               url=kw.pop("url", "https://boards.example.com/initech/jobs/1"), company_name="Initech",
               locations=["Boulder, CO"], salary_min=150_000, salary_max=196_000, currency="USD")


def test_each_source_links_to_where_its_figure_can_be_checked():
    comp = {"base": "165-195K", "asked": "210K", "glassdoor": "170-210K"}
    s = by_key(paysources.sources(linked_job(), comp=comp, result=EST, levels_on=True, est=FILINGS, lca_cached=True))
    assert s["posted"]["href"] == "https://boards.example.com/initech/jobs/1"
    assert s["posted"]["tip"] == "Open the posting to verify: the posting's own range"
    assert s["levels"]["href"] == "https://example.com/levels"  # the page the estimate was read from
    assert s["levels"]["tip"].startswith("Open Levels.fyi to verify: L5 median $170K base for Software Engineer")
    assert s["lca"]["href"] == lca.PAGE
    assert s["lca"]["tip"] == ("Open the U.S. Department of Labor's H-1B (LCA) disclosure data to verify: 14 certified "
                               "filings for Initech (Boulder, CO); base pay only, not total compensation")
    assert s["glassdoor"]["href"] == ("https://www.glassdoor.com/Search/results.htm"
                                      "?keyword=Initech%20Senior%20Software%20Engineer%20salary")
    assert "Glassdoor salary search for Initech, Senior Software Engineer" in s["glassdoor"]["tip"]
    assert "170-210K" in s["glassdoor"]["tip"]


def test_what_comes_from_your_notes_is_never_a_link():
    comp = {"base": "165-195K", "offered": "180K", "asked": "210K"}
    s = by_key(paysources.sources(linked_job(), comp=comp, result=EST, levels_on=True))
    for key in ("recruiter", "ask"):
        assert "href" not in s[key]
    assert s["recruiter"]["tip"] == "From your notes: base 165-195K, offered 180K"
    assert s["ask"]["tip"].startswith("From your notes: you asked for 210K")
    suggested = by_key(paysources.sources(linked_job(), result=EST, levels_on=True))["ask"]
    assert "href" not in suggested  # Levels.fyi's suggestion is jobwatch's arithmetic, not a page to open


def test_the_lca_tip_names_the_filing_count_and_years_and_says_when_it_is_other_employers():
    years = lca.Estimate(**{**FILINGS.__dict__, "count": 1, "years": (2025, 2026)})
    tip = by_key(paysources.sources(linked_job(), est=years, lca_cached=True))["lca"]["tip"]
    assert "1 certified filing, starting 2025–2026 for Initech" in tip
    one_year = lca.Estimate(**{**FILINGS.__dict__, "years": (2025, 2025)})
    assert "14 certified filings, starting 2025 for" in by_key(
        paysources.sources(linked_job(), est=one_year, lca_cached=True))["lca"]["tip"]
    market = lca.Estimate(**{**FILINGS.__dict__, "where": f"CO, {lca.MARKET}", "count": 40})
    s = by_key(paysources.sources(linked_job(), est=market, lca_cached=True))["lca"]
    assert "40 certified filings by other employers in CO, not this employer's" in s["tip"]
    assert s["href"] == lca.PAGE


@pytest.mark.parametrize("url", ["", "u", "#", "javascript:alert(1)", "/relative/path", "https://", "manual:1"])
def test_a_job_with_no_usable_address_has_a_posted_chip_with_no_link(url):
    posted = by_key(paysources.sources(linked_job(url=url)))["posted"]
    assert posted["value"] == "$150K–$196K" and "href" not in posted
    assert posted["tip"] == "the posting's own range"


def test_an_empty_source_has_no_link_and_no_tip():
    s = by_key(paysources.sources(linked_job(), comp={"glassdoor": "170K"}, levels_on=True, result=levels.REFUSED))
    assert "href" not in s["levels"] and "tip" not in s["levels"]
    assert "href" not in s["lca"] and "tip" not in s["recruiter"]
    blank = by_key(paysources.sources(linked_job(url="https://x.example/1"), levels_on=True))
    assert "href" not in blank["glassdoor"]  # nothing typed in: nothing to check
    nopay = by_key(paysources.sources(Job(source="a", company="b", id="1", title="t", url="https://x.example/1")))
    assert "href" not in nopay["posted"]  # the posting lists no pay: no figure to verify


def test_a_rate_links_to_the_posting_and_says_it_is_a_rate():
    rate = Job(source="a", company="initech", id="1", title="Consultant", url="https://x.example/1", salary_min=40,
               salary_max=80, pay_per="hour", currency="USD")
    posted = by_key(paysources.sources(rate))["posted"]
    assert posted["href"] == "https://x.example/1" and "rate" in posted["tip"]


@pytest.mark.parametrize("company, title, want", [
    ("Initech", "Senior Engineer", "Initech%20Senior%20Engineer%20salary"),
    ("Globex & Sons", "C++ Dev / Ops", "Globex%20%26%20Sons%20C%2B%2B%20Dev%20%2F%20Ops%20salary"),
    ("  Umbrella   Corp ", "", "Umbrella%20Corp%20salary"),
    ("Initech", None, "Initech%20salary"),
    ("Café Ünïcode", "Ingénieur", "Caf%C3%A9%20%C3%9Cn%C3%AFcode%20Ing%C3%A9nieur%20salary"),
])
def test_the_glassdoor_search_is_built_from_the_company_and_title_and_url_encoded(company, title, want):
    assert paysources.glassdoor_url(company, title) == f"{paysources.GLASSDOOR_SEARCH}?keyword={want}"


@pytest.mark.parametrize("company", ["", "   ", None])
def test_no_company_means_no_glassdoor_link(company):
    assert paysources.glassdoor_url(company, "Engineer") is None


def test_only_full_web_addresses_count_as_links():
    assert paysources.web_url(" https://a.example/x?y=1 ") == "https://a.example/x?y=1"
    assert paysources.web_url("http://a.example") == "http://a.example"
    for bad in (None, "", "ftp://a.example", "//a.example", "a.example/x", "mailto:a@b.example", "javascript:1"):
        assert paysources.web_url(bad) is None
