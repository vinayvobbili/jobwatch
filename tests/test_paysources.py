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
    posted = by_key(paysources.sources(job(120_000, 240_000)))["posted"]
    assert (posted["value"], posted["amount"]) == ("$120K–$240K", 240_000)
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
