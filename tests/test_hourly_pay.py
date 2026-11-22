"""An hourly wage worked out as a year's pay is shown as the rate it is, never as a salary. Every figure is made up."""

import json

import pytest

from jobwatch import config, paysources
from jobwatch.advice import History, advise
from jobwatch.alerts import Alert, email_job
from jobwatch.models import Job
from jobwatch.store import MANUAL, Store
from jobwatch.text import parse_pay, parse_salary, pay_label
from jobwatch.watch import Entry

HOURLY = "Job Types: Part-time, Contract\n\nPay: $40.00 - $80.00 per hour\n\nWork Location: Remote\n"
LABEL = "$40–$80/hr, about $83K–$166K a year"


@pytest.mark.parametrize("text", [
    "$40 - $80 per hour", "$40 - $80/hr", "Pay: $40.00 - $80.00 per hour", "$40–$80 an hour", "$40 - $80/hour",
])
def test_an_hourly_range_is_a_year_worked_out_once_and_says_it_was_hourly(text):
    assert parse_pay(text) == (83_200, 166_400, "hour")  # x 2,080 hours, once
    assert parse_salary(text) == (83_200, 166_400)


@pytest.mark.parametrize("text", ["$45 an hour", "$70/hr", "USD 45/hour", "$45 - $50 hourly"])
def test_other_hourly_wordings_are_never_taken_for_a_yearly_pay(text):
    found = parse_pay(text)
    assert found is None or found[2] == "hour"


def test_a_stated_yearly_pay_is_not_a_rate():
    assert parse_pay("$150,000 - $190,000 a year") == (150_000, 190_000, "")
    assert parse_pay("$45 - $50 per hour, or $150,000 - $180,000 a year") == (150_000, 180_000, "")
    assert parse_pay("167,000 - 230,000 USD per year") == (167_000, 230_000, "")


def test_the_label_says_the_rate_and_the_year_it_comes_to():
    assert pay_label(83_200, 166_400, "hour") == LABEL
    assert pay_label(145_600, 145_600, "hour") == "$70/hr, about $146K a year"
    assert pay_label(150_000, 196_000) == "$150K–$196K"
    assert pay_label(150_000, 196_000, "", "CAD") == "$150K–$196K CAD"


def test_a_job_remembers_its_rate_and_pay_shows_it_everywhere():
    j = Job("manual", "initech", "1", "Engineer", "https://example.com/1")
    j.set_pay(83_200, 166_400, "USD", "hour")
    assert j.is_rate and j.pay_per == "hour"
    assert j.pay() == LABEL
    assert f"Pay: {LABEL}" in j.to_text()
    assert Job.from_dict(j.to_dict()).pay() == j.pay()
    j.set_pay(150_000, 196_000, "USD")  # a yearly pay later replaces it
    assert not j.is_rate and j.pay() == "$150K–$196K"
    j.set_pay(150_000, 196_000, "USD", "year")  # "year" is no rate
    assert not j.is_rate


def test_a_job_saved_before_it_kept_its_rate_reads_as_a_yearly_pay():
    j = Job.from_dict({"source": "manual", "company": "initech", "id": "1", "title": "Engineer", "url": "u",
                       "salary_min": 83_200, "salary_max": 166_400})
    assert j.pay_per == "" and j.pay() == "$83K–$166K"


def test_an_alert_email_job_keeps_the_rate_its_pay_line_gave():
    j = email_job(Alert(title="Security Engineer", company="Initech", url="https://example.com/j", location="Remote",
                        pay="$40 - $80 an hour"))
    assert j.pay_per == "hour" and j.pay() == LABEL


def test_the_postings_text_gives_a_manual_job_its_rate(tmp_path):
    store = Store(tmp_path / "state.db")
    added = store.add("Initech", "Security Engineer", description=HOURLY, status="queued")
    assert added.pay() == LABEL
    assert store.find(added.key)[0].pay() == LABEL
    store.close()


def test_older_jobs_whose_text_gives_an_hourly_wage_are_marked_once_at_open(tmp_path):
    path = tmp_path / "state.db"
    store = Store(path)
    old = Job(MANUAL, "initech", "old", "Engineer", "u", company_name="Initech", description=HOURLY,
              salary_min=83_200, salary_max=166_400, currency="USD")
    salary = Job(MANUAL, "initech", "salary", "Engineer", "u", company_name="Initech",
                 description="Salary: $83,200 - $166,400", salary_min=83_200, salary_max=166_400, currency="USD")
    with store.db:
        for j in (old, salary):
            store.db.execute("INSERT INTO jobs (key, source, company, data, first_seen, last_seen) VALUES "
                             "(?, ?, ?, ?, 'x', 'x')", (j.key, MANUAL, "initech", json.dumps(j.to_dict())))
        store.db.execute("PRAGMA user_version=0")
    store.close()
    store = Store(path)  # opening runs the backfill
    got = {k: store.find(f"{MANUAL}:initech:{k}")[0] for k in ("old", "salary")}
    assert got["old"].pay() == LABEL
    assert got["salary"].pay() == "$83K–$166K"  # a stated salary stays one
    assert store.backfill_pay_per() == 0
    store.close()


def rated(per="hour"):
    j = Job("manual", "initech", "1", "Security Engineer", "https://example.com/1", company_name="Initech")
    j.set_pay(83_200, 166_400, "USD", per)
    return j


def test_posted_pay_source_marks_a_rate_and_a_salary_stays_plain():
    posted = paysources.sources(rated())[0]
    assert posted["rate"] is True and posted["short"] == "$40–$80/hr"
    assert posted["value"] == LABEL and "not a salary" in posted["detail"]
    salary = paysources.sources(rated(""))[0]
    assert "rate" not in salary and salary["value"] == "$83K–$166K"


def test_an_hourly_wage_does_not_earn_the_meets_your_target_reason(watchlist):
    watchlist.write_text(watchlist.read_text() + "pay: {target: 70000-150000, floor: 50000}\n")
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    for per, queued in (("hour", False), ("", True)):
        said = advise(cfg, Entry(rated(per), {"status": "new"}, 0, [], fit=None, contacts=[]), History(store))
        assert ("pay" in said.codes if said else False) is queued, per
    store.close()
