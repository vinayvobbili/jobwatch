"""Jobs found somewhere else: read from their link on a board jobwatch reads, or added with pasted text."""

import pytest

from jobwatch import cli, sources
from jobwatch.store import Store
from jobwatch.watch import save_job
from jobwatch.web import App

from .conftest import FakeWeb

WORKABLE = "https://apply.workable.com/api/v1/widget/accounts/initech?details=true"
WORKABLE_DATA = {"name": "Initech Systems", "jobs": [
    {"title": "Staff Platform Engineer", "shortcode": "A1B2C3D4E5", "telecommuting": True,
     "department": "Security", "published_on": "2026-07-01", "city": "Denver", "state": "Colorado",
     "country": "United States",
     "locations": [{"country": "United States", "city": "Denver", "region": "Colorado", "hidden": False}],
     "description": "<p>Build platform automation in <b>Python</b>.</p><p>Requirements</p><ul><li>6+ years</li></ul>"},
    {"title": "Office Coordinator", "shortcode": "B2C3D4E5F6", "telecommuting": "False", "city": "Denver",
     "state": "Colorado", "country": "United States", "description": "<p>Pay: $50,000 - $60,000</p>"},
]}


def test_workable():
    jobs = sources.fetch("workable", "initech", FakeWeb({WORKABLE: WORKABLE_DATA}))
    eng, admin = jobs
    assert eng.key == "workable:initech:A1B2C3D4E5" and eng.display_company == "Initech Systems"
    assert eng.url == "https://apply.workable.com/initech/j/A1B2C3D4E5/" and eng.remote is True
    assert eng.locations == ["Denver, Colorado, United States"] and "Python" in eng.description
    assert eng.posted.date().isoformat() == "2026-07-01"
    assert admin.remote is None and admin.salary_min == 50_000
    assert sources.careers_url("workable", "initech") == "https://apply.workable.com/initech/"


@pytest.mark.parametrize("url, expected", [
    ("https://apply.workable.com/initech/j/A1B2C3D4E5/", ("workable", "initech")),
    ("https://apply.workable.com/initech/jobs/view/A1B2C3D4E5.md", ("workable", "initech")),
    ("https://initech.workable.com/", ("workable", "initech")),
    ("https://apply.workable.com/j/A1B2C3D4E5", None),
    ("https://www.linkedin.com/jobs/view/4000000001/", None),
])
def test_detect_workable(url, expected):
    assert sources.detect(url) == expected


@pytest.mark.parametrize("url, pid", [
    ("https://job-boards.greenhouse.io/acme/jobs/101", "101"),
    ("https://boards.greenhouse.io/embed/job_app?for=acme&gh_jid=101", "101"),
    ("https://jobs.lever.co/globex/aaaa-1111/apply", "aaaa-1111"),
    ("https://jobs.ashbyhq.com/initech/c1", "c1"),
    ("https://apply.workable.com/initech/jobs/view/A1B2C3D4E5.md", "A1B2C3D4E5"),
    ("https://jobs.lever.co/globex", None),
])
def test_posting_ids(url, pid):
    assert sources._posting_id(sources.detect(url)[0], url) == pid


def test_a_posting_read_from_its_link(web):
    job = sources.posting("https://job-boards.greenhouse.io/acme/jobs/101", web)
    assert job.key == "greenhouse:acme:101" and "Python" in job.description
    assert sources.posting("https://www.linkedin.com/jobs/view/1/", web) is None
    with pytest.raises(sources.NotFound):
        sources.posting("https://job-boards.greenhouse.io/acme/jobs/999", web)


def test_a_workday_posting_is_read_directly():
    api = "https://initech.wd5.myworkdayjobs.com/wday/cxs/initech/External"
    path = "/job/Denver/Staff-Engineer_R42"
    web = FakeWeb({api + path: {"jobPostingInfo": {"title": "Staff Engineer", "location": "Denver, CO",
                                                   "jobDescription": "<p>Python.</p>"}}})
    job = sources.posting(f"https://initech.wd5.myworkdayjobs.com/en-US/External{path}", web)
    assert job.key == "workday:initech.wd5/External:R42" and job.title == "Staff Engineer"
    assert web.calls == [api + path]


def test_save_job_from_a_link_leaves_its_board_alone(tmp_path, web):
    store = Store(tmp_path / "state.db")
    other = sources.fetch("greenhouse", "acme", web)[1]
    store.sync("greenhouse", "acme", [other])  # the board is watched and has another job
    job, read = save_job(store, "https://job-boards.greenhouse.io/acme/jobs/101", get=web)
    assert read and store.find(job.key)[1]["status"] == "queued"
    assert store.find(other.key)[1]["closed"] is None  # one posting added; nothing else marked closed
    store.set_status([job.key], "screening")
    save_job(store, "https://job-boards.greenhouse.io/acme/jobs/101", note="saw it again", get=web)
    rec = store.find(job.key)[1]
    assert rec["status"] == "screening" and "saw it again" in rec["note"]  # further along: stage kept


def test_save_job_with_pasted_text(tmp_path, web):
    store = Store(tmp_path / "state.db")
    link = "https://www.linkedin.com/jobs/view/4000000001/"
    with pytest.raises(ValueError, match="can't read that link"):
        save_job(store, link, get=web)
    job, read = save_job(store, link, "Initech", "Staff Engineer", "Build things.\nPay: $200,000 - $240,000",
                         get=web)
    assert not read and job.key == "manual:initech:staff-engineer" and job.url == link
    stored, rec = store.find(job.key)
    assert rec["status"] == "queued" and stored.description.startswith("Build things")
    assert (stored.salary_min, stored.salary_max) == (200_000, 240_000)


def test_cli_add(watchlist, web, capsys):
    cli.main(["--config", str(watchlist), "add", "https://job-boards.greenhouse.io/acme/jobs/101", "--status",
              "queued"])
    assert "greenhouse:acme:101: queued" in capsys.readouterr().out
    cli.main(["--config", str(watchlist), "add", "Initech", "Staff Engineer", "--on", "2026-09-01"])
    assert "manual:initech:staff-engineer: applied" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="link to the posting, or the company"):
        cli.main(["--config", str(watchlist), "add", "Initech"])


def test_web_add(watchlist, web):
    app = App(watchlist)
    got = app.post_add({"url": "https://job-boards.greenhouse.io/acme/jobs/101", "status": "queued"})
    assert got["read"] and got["key"] == "greenhouse:acme:101"
    assert [j["key"] for j in app.get_queue({})] == ["greenhouse:acme:101"]
