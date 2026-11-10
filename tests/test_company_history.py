"""What earlier applications at a company came to, and filters.company_notes, as warnings on its other jobs."""

import pytest

from jobwatch.filters import Filters, company_note
from jobwatch.models import Job
from jobwatch.watch import company_history, warnings


def job(company: str = "Initech", n: int = 1) -> Job:
    return Job(source="manual", company=company.lower(), id=str(n), title="Security Engineer",
               url=f"https://example.com/{company}/{n}", company_name=company)


def app(company: str, n: int, status: str, applied: str, ended: str | None = None):
    return job(company, n), {"status": status, "applied_at": applied, "status_at": ended or f"{applied}T12:00:00+00:00"}


def test_other_applications_at_the_company_are_summed_up():
    apps = [app("Initech", 1, "rejected", "2026-09-10", "2026-09-16T15:00:00+00:00"),
            app("Initech, Inc.", 2, "rejected", "2026-10-20", "2026-10-29T15:00:00+00:00"),
            app("Initech", 3, "applied", "2026-10-30"),
            app("Globex", 4, "rejected", "2026-10-01")]
    said = company_history(job("Initech", 9), apps)
    assert said == "at Initech before: 2 rejected (9/16, 10/29), 1 open (applied 10/30)"


def test_a_job_is_not_its_own_history_and_no_history_says_nothing():
    apps = [app("Initech", 1, "applied", "2026-10-30")]
    assert company_history(job("Initech", 1), apps) is None
    assert company_history(job("Umbrella"), apps) is None
    assert company_history(job("Umbrella"), []) is None


def test_a_company_note_is_its_own_warning():
    f = Filters(company_notes={"Initech": "no new applications"})
    assert company_note(job("Initech"), f) == "Initech: no new applications"
    assert company_note(job("Initech, Inc."), f) == "Initech: no new applications"
    assert company_note(job("Globex"), f) is None
    assert "Initech: no new applications" in warnings(job("Initech"), f)
    assert warnings(job("Globex"), f) == []


def test_company_notes_must_be_a_mapping():
    with pytest.raises(ValueError, match="company_notes"):
        Filters.from_dict({"company_notes": ["Initech"]})
    assert Filters.from_dict({"company_notes": {"Initech": "x"}}).company_notes == {"Initech": "x"}


def test_exclude_companies_still_rejects():
    from jobwatch.filters import rejection
    assert rejection(job("Initech"), Filters(exclude_companies=["Initech"])) == ("company", "company 'Initech'")
