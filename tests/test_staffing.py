"""A staffing or recruiting agency's posting gets a warning line: a label, never a filter."""

import pytest

from jobwatch.filters import STAFFING_WARNING, Filters, rejection, staffing_firm
from jobwatch.models import Job
from jobwatch.watch import warnings


def job(company: str = "Initech", text: str = "Build detection pipelines.", title: str = "Security Engineer") -> Job:
    return Job(source="greenhouse", company=company.lower().replace(" ", ""), id="1", title=title,
               url="https://example.com/1", company_name=company, description=text)


@pytest.mark.parametrize("text", [
    "We are hiring on behalf of our client, a retailer.",
    "Our client is seeking a security engineer.",
    "Our client, a fintech in Boulder, needs an engineer.",
    "Open to C2C or W2.",
    "Corp-to-corp only.",
    "W2 contract, 12 months.",
    "This is a contract-to-hire role.",
    "Globex is a staffing firm placing engineers.",
    "Globex Talent Solutions connects engineers with employers.",
])
def test_agency_phrases_are_flagged(text):
    assert staffing_firm(job("Globex", text)) == STAFFING_WARNING


@pytest.mark.parametrize("name", ["Globex Staffing", "Umbrella Recruiting", "Hooli Staffing Solutions"])
def test_agency_names_are_flagged(name):
    assert staffing_firm(job(name)) == STAFFING_WARNING


@pytest.mark.parametrize("name", ["Globex Talent", "Umbrella Consulting Group", "Hooli Solutions"])
def test_ambiguous_names_need_a_contract_word_in_the_text(name):
    assert staffing_firm(job(name)) is None
    assert staffing_firm(job(name, "Placing consultants with each client on a contract basis.")) == STAFFING_WARNING


@pytest.mark.parametrize("company,text", [
    ("Initech", "Join our Talent Acquisition team to hire engineers."),
    ("Initech", "This is a one-year contract position working on detections."),
    ("Initech", "Our client success team uses the product daily."),
    ("Initech", "Our platform has solutions for every team; we track staffing levels weekly."),
    ("Initech", "Recruiting is handled by our in-house talent partners."),
    ("Umbrella", "Experience with hiring and recruiting security staff is a plus."),
])
def test_ordinary_postings_are_not_flagged(company, text):
    assert staffing_firm(job(company, text)) is None


def test_it_is_a_warning_beside_the_others_and_never_a_filter():
    j = job("Globex Staffing", "On behalf of our client, hiring now.")
    assert rejection(j, Filters()) is None
    assert STAFFING_WARNING in warnings(j, Filters())
    assert STAFFING_WARNING not in warnings(job(), Filters())
