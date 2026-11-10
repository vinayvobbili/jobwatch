import pytest

from jobwatch.text import (
    annual,
    html_to_text,
    in_us,
    local_salary,
    names_no_place,
    parse_salary,
    pay_period,
    split_locations,
)


def test_html_to_text_handles_escaped_markup_and_lists():
    text = html_to_text("&lt;p&gt;Intro&lt;/p&gt;&lt;ul&gt;&lt;li&gt;One&lt;/li&gt;&lt;li&gt;Two&lt;/li&gt;&lt;/ul&gt;")
    assert text == "Intro\n- One\n- Two"


def test_html_to_text_empty():
    assert html_to_text("") == ""


@pytest.mark.parametrize("text, expected", [
    ("Annual Salary: $222,800 — $290,000 USD", (222_800, 290_000)),
    ("Base pay $180K - $220K plus equity", (180_000, 220_000)),
    ("$150,000 USD to $190,000", (150_000, 190_000)),
    ("between $120k–160k", (120_000, 160_000)),
    ("base salary range for this job is USD $140,400.00 - USD $372,300.00 /Yr.", (140_400, 372_300)),
    ("ranges for this position are:\n150,000 USD – 240,000 USD for Level 4; and 190,000 USD – 300,000 USD for Level 5.",
     (150_000, 240_000)),  # the currency after each amount, and no dollar sign
])
def test_parse_salary_finds_annual_ranges(text, expected):
    assert parse_salary(text) == expected


@pytest.mark.parametrize("text", [
    "Funding for compute (~$15k/month)",
    "Stipend $3,000 - $4,000 per month",
    "$500 per day travel allowance",
    "$8 - $9 per hour",  # less than a year's salary
    "Raised $100M+ to cut energy waste",
    "No pay listed here",
    "",
])
def test_parse_salary_skips_non_annual_and_missing(text):
    assert parse_salary(text) is None


TIERS = ("Base pay range (CA, WA) per year: $150,000 - 190,000\n"
         "Base pay range (all other U.S. states) per year: $120,000-160,000")


@pytest.mark.parametrize("text, state, expected", [
    (TIERS, "CO", (120_000, 160_000)),  # no tier names it: the one for the other states
    (TIERS, "WA", (150_000, 190_000)),  # a tier names it
    ("For Colorado: $130K - $170K\nFor New York and California: $160K - $190K", "CO", (130_000, 170_000)),
    ("Colorado, Utah: $130K - $170K. Rest of the US: $110K - $150K.", "UT", (130_000, 170_000)),
    ("CA or NY: $160K - $190K; any other U.S. location: $110K - $150K.", "CO", (110_000, 150_000)),
    ("Zone A (CA, NY): $160K - $190K\nZone B (TX): $110K - $150K", "CO", None),  # nothing says Colorado is B
    ("CO Level 4: $130K - $170K\nCO Level 5: $160K - $190K", "CO", None),  # two tiers name it
    ("Base pay: $120,000 - $160,000 for Initech (CO)", "CO", None),  # one range: parse_salary's job
    ("Level 4: $130K - $170K\nLevel 5: $160K - $190K", "CO", None),  # tiers by level, not place
    ("CA: $160K - $190K\nOther locations: $20 - $30 per hour", "CO", None),  # an hourly wage isn't a tier
    ("", "CO", None),
])
def test_local_salary_picks_the_tier_for_a_state(text, state, expected):
    assert local_salary(text, state) == expected


def test_parse_salary_still_reads_the_first_tier():
    assert parse_salary(TIERS) == (150_000, 190_000)


@pytest.mark.parametrize("text, expected", [
    ("$45 - $60 per hour", (93_600, 124_800)),
    ("$40–$55/hr", (83_200, 114_400)),
    ("$75–$80/hr on a W2 contract", (156_000, 166_400)),
    ("Pay: $70 an hour", (145_600, 145_600)),
    ("$45 - $50 per hour, or $150,000 - $180,000 a year", (150_000, 180_000)),  # a yearly range comes first
])
def test_parse_salary_turns_an_hourly_wage_into_a_year(text, expected):
    assert parse_salary(text) == expected


@pytest.mark.parametrize("interval, period", [
    ("per-hour-wage", "hour"), ("per-year-salary", "year"), ("1 HOUR", "hour"), ("1 MONTH", "month"),
    ("YEAR", "year"), ("one-time", None), ("", None), (None, None),
])
def test_pay_period(interval, period):
    assert pay_period(interval) == period
    if period:
        assert annual(10, period) == {"hour": 20_800, "month": 120, "year": 10}[period]


def test_parse_salary_skips_a_monthly_range_and_finds_the_salary_after_it():
    assert parse_salary("Stipend $3,000 - $4,000 per month. Salary $175,000 - $250,000.") == (175_000, 250_000)


@pytest.mark.parametrize("location, expected", [
    ("Austin, TX", True),
    ("Remote (United States)", True),
    ("US - Remote", True),
    ("Remote, USA", True),
    ("Colorado", True),
    ("Remote-Friendly, United States", True),
    ("CT - Hartford", True),  # Workday: the state's code first
    ("TX - Work from home", True),
    ("Ontario, CAN", False),
    ("CTO - Remote", False),
    ("London, UK", False),
    ("Remote - Canada", False),
    ("Join us remotely", False),
    ("Remote, or hybrid", False),
])
def test_in_us(location, expected):
    assert in_us(location) is expected


def test_names_no_place():
    assert names_no_place("Remote")
    assert names_no_place("Fully Remote")
    assert not names_no_place("Remote - Canada")


def test_split_locations_dedupes_and_splits():
    assert split_locations("London, UK; Remote | Austin, TX", "Austin, TX") == ["London, UK", "Remote", "Austin, TX"]
