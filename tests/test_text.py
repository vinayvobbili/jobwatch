import pytest

from jobwatch.text import html_to_text, in_us, names_no_place, parse_salary, split_locations


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
])
def test_parse_salary_finds_annual_ranges(text, expected):
    assert parse_salary(text) == expected


@pytest.mark.parametrize("text", [
    "Funding for compute (~$15k/month)",
    "$45 - $60 per hour",
    "$40–$55/hr",
    "No pay listed here",
    "",
])
def test_parse_salary_skips_non_annual_and_missing(text):
    assert parse_salary(text) is None


def test_parse_salary_skips_a_monthly_range_and_finds_the_salary_after_it():
    assert parse_salary("Stipend $3,000 - $4,000 per month. Salary $200,000 - $250,000.") == (200_000, 250_000)


@pytest.mark.parametrize("location, expected", [
    ("Austin, TX", True),
    ("Remote (United States)", True),
    ("US - Remote", True),
    ("Remote, USA", True),
    ("Colorado", True),
    ("Remote-Friendly, United States", True),
    ("Ontario, CAN", False),
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
