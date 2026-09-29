from datetime import datetime, timedelta, timezone

import pytest

from jobwatch.filters import Filters, reject_reason, relevance
from jobwatch.models import Job


def job(**kw) -> Job:
    base = dict(source="greenhouse", company="acme", id="1", title="Senior Software Engineer", url="u",
                locations=["Austin, TX"], description="Python and C++ services")
    return Job(**{**base, **kw})


def test_no_filters_pass_everything():
    assert reject_reason(job(), Filters()) is None


def test_titles_and_exclusions():
    f = Filters(titles=["engineer"], exclude_titles=["manager", r"\bintern"])
    assert reject_reason(job(), f) is None
    assert reject_reason(job(title="Recruiter"), f) == "title"
    assert reject_reason(job(title="Engineering Manager"), f) == "title matches 'manager'"


def test_exclude_departments():
    assert reject_reason(job(department="Sales"), Filters(exclude_departments=["sales"])) is not None


@pytest.mark.parametrize("locations, remote, ok", [
    (["Remote (United States)"], None, True),
    (["Remote"], None, True),
    (["Remote - Canada"], None, False),
    (["London, UK"], None, False),
    (["Austin, TX"], True, True),            # the posting's remote flag, in a US location
    (["London, UK"], True, False),
    (["Austin, TX"], None, False),           # on-site in Austin is not remote
    (["India", "Remote"], None, False),      # a bare "Remote" is remote where the posting's other places are
    (["Austin, TX", "Remote"], None, True),
    # Remote in one state or city is remote for people there, not anywhere in the US.
    (["Maryland", "Virginia", "Remote - Washington D.C."], None, False),
    (["United States", "Remote - California"], None, False),
    (["Work At Home-Texas", "Work At Home-Florida"], None, False),
    (["Remote-Minnesota-Minneapolis Metro"], None, False),
    (["Seattle, SF, NYC, Remote in the US", "US"], None, True),
    (["San Francisco, New York City, Chicago, US-Remote", "US"], None, True),
    (["NY, SF, Chicago, Remote", "US"], None, True),
    (["Remote-Friendly US (Travel Required)"], None, True),
    (["Remote - United States of America"], None, True),
])
def test_remote_in_us(locations, remote, ok):
    f = Filters(locations=["remote"])
    assert (reject_reason(job(locations=locations, remote=remote), f) is None) is ok


def test_remote_in_a_wanted_state():
    f = Filters(locations=["remote", "North Carolina"])
    assert reject_reason(job(locations=["Remote - North Carolina"]), f) is None
    assert reject_reason(job(locations=["Remote - Virginia"]), f) == "location"


def test_remote_anywhere():
    f = Filters(locations=["remote"], remote_country="any")
    assert reject_reason(job(locations=["Remote - Canada"]), f) is None


def test_named_places_match_as_text():
    f = Filters(locations=["remote", "Denver", "Boulder, CO"])
    assert reject_reason(job(locations=["Denver, CO"]), f) is None
    assert reject_reason(job(locations=["Boulder, CO, United States"]), f) is None
    assert reject_reason(job(locations=["Charlotte, CO"]), f) == "location"


def test_pay_floor_uses_the_top_of_the_range():
    f = Filters(min_salary=200_000)
    assert reject_reason(job(salary_min=174_000, salary_max=237_000), f) is None
    assert reject_reason(job(salary_min=120_000, salary_max=160_000), f) == "pay $120K–$160K"
    assert reject_reason(job(), f) is None  # pay not listed passes...
    assert reject_reason(job(), Filters(require_salary=True)) == "pay not listed"  # ...unless required


def test_age():
    old = job(posted=datetime.now(timezone.utc) - timedelta(days=45))
    assert reject_reason(old, Filters(max_age_days=30)) == "posted 45 days ago"
    assert reject_reason(job(), Filters(max_age_days=30)) is None  # unknown date passes


def test_unknown_filter_setting_is_an_error():
    with pytest.raises(ValueError, match="min_pay"):
        Filters.from_dict({"min_pay": 1})


def test_relevance_weights_title_hits_double_and_handles_symbols():
    score, hits = relevance(job(title="Python Engineer"), {"Python": 2, "C++": 1, "Go": 5, "re:servic(e|es)": 1})
    assert hits == ["Python", "C++", "re:servic(e|es)"]
    assert score == 2 * 2 + 1 + 1


def test_relevance_matches_whole_words_only():
    assert relevance(job(description="Django and Golang"), {"Go": 1})[0] == 0


def test_relevance_counts_plurals():
    assert relevance(job(description="Build AI agents and LLMs"), {"agent": 1, "LLM": 1, "agentic": 1})[1] == [
        "agent", "LLM"]
