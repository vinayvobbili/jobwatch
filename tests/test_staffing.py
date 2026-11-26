"""A staffing or recruiting agency's posting gets a warning line: a label, never a filter."""

import pytest

from jobwatch.filters import (
    CLIENT_NOT_NAMED,
    KINDS,
    STAFFING_WARNING,
    Filters,
    reject_reason,
    rejection,
    staffing_firm,
    unnamed_client,
)
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
    "For our client, we are seeking a Staff Security Engineer to lead detections.",
    "for our client we are hiring a principal engineer.",
    "For our client, a leader in the enterprise technology space, we need an engineer.",
    "For our client in Boulder, a global leader in the consumer technology space, we are growing.",
])
def test_agency_phrases_are_flagged(text):
    assert staffing_firm(job("Globex", text)) == STAFFING_WARNING


@pytest.mark.parametrize("name", ["Globex Staffing", "Umbrella Recruiting", "Hooli Staffing Solutions", "Ladders",
                                  "ladders", "Ladders, Inc."])
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
    ("Initech", "We are a leader in the fintech space. For our clients' data we use envelope encryption."),
    ("Initech", "You will build dashboards for our client success team, a leader in the support space."),
    ("Initech", "We are seeking a detection engineer. Ladders of seniority are clear here."),
    ("Ladders Holdings", "Build a platform for our customers."),
    ("Stepladders", "Build a platform for our customers."),
])
def test_ordinary_postings_are_not_flagged(company, text):
    assert staffing_firm(job(company, text)) is None


def test_it_is_a_warning_beside_the_others_and_never_a_filter():
    j = job("Globex Staffing", "On behalf of our client, hiring now.")
    assert rejection(j, Filters()) is None  # on the agency's own board: its own jobs, shown with the warning
    assert STAFFING_WARNING in warnings(j, Filters())
    assert STAFFING_WARNING not in warnings(job(), Filters())


# -- Demotion: a row from a source that doesn't name its client is hidden from Today

def row(company="Ladders", text="For our client, we are seeking a security engineer.", source="manual", **kw):
    return Job(source=source, company=company.lower(), id="1", title="Security Engineer", url="https://example.com/1",
               company_name=company, description=text, **kw)


@pytest.mark.parametrize("name", ["Ladders", "Ladders, Inc.", "Globex Staffing", "Umbrella Recruiting"])
def test_a_row_that_does_not_name_its_client_is_hidden_from_today(name):
    assert unnamed_client(row(name))
    assert rejection(row(name), Filters()) == ("client", CLIENT_NOT_NAMED)
    assert reject_reason(row(name), Filters()) == "client not named"
    assert "client" in KINDS


def test_naming_the_client_lifts_the_demotion():
    assert rejection(row("Initech"), Filters()) is None  # the company renamed to the client's
    assert rejection(row(text="Client: Initech Corporation. Build detections."), Filters()) is None
    assert rejection(row(text="client name: Initech\nBuild detections."), Filters()) is None
    for hint in ("Client: confidential", "Client: Undisclosed", "Client: N/A", "Client:"):
        assert unnamed_client(row(text=f"{hint}. Build detections.")), hint


def test_an_agency_own_board_and_ordinary_companies_are_not_demoted():
    assert rejection(row("Globex Staffing", source="greenhouse"), Filters()) is None  # its board: its own jobs
    assert rejection(row("Initech"), Filters()) is None
    assert rejection(row("Globex Talent"), Filters()) is None  # a name any company might have
    assert rejection(row("Stepladders"), Filters()) is None


def test_the_rule_can_be_left_out_for_the_suggestions_that_explain_an_agency():
    assert rejection(row(), Filters(), client=False) is None
    assert reject_reason(row(), Filters(), client=False) is None
    assert reject_reason(row(), Filters(titles=["manager"]), client=False) == "title"


def test_the_demoted_row_still_carries_the_staffing_warning():
    assert STAFFING_WARNING in warnings(row(), Filters())
