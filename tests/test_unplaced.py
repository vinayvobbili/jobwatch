"""`import-list --unplaced`: the jobs the list imports tracked from the list's text alone, with why they weren't found
on the company's board (recorded going forward, worked out for older rows)."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from jobwatch import cli, config, joblist
from jobwatch.store import Store
from jobwatch.watch import fetch_all

NO_BOARD, NOT_ON_BOARD = "no board found under its name", "not on its board"


def hooli_board(web, *titles):
    web.responses["https://boards-api.greenhouse.io/v1/boards/hooli/jobs?content=true"] = {"jobs": [
        {"id": 500 + i, "title": t, "company_name": "Hooli", "content": "&lt;p&gt;Build things.&lt;/p&gt;",
         "absolute_url": f"https://job-boards.greenhouse.io/hooli/jobs/{500 + i}",
         "location": {"name": "Remote, United States"}, "offices": [], "metadata": [], "departments": []}
        for i, t in enumerate(titles)]}


def rec(title, company, location="United States (Remote)", id="", source="linkedin"):
    return {"source": source, "id": id, "title": title, "company": company, "location": location}


LIST = [
    rec("Platform Engineer", "Hooli", id="4100000002"),                        # on Hooli's board
    rec("Detection Engineer", "Vandelay Industries", id="4100000003"),         # no board anywhere
    rec("Data Analyst", "Hooli", "London, UK", id="4100000004"),               # not on Hooli's board
    rec("Account Manager", "Pendant Publishing", "Denver, CO", id="9f8e7d", source="indeed"),
]


@pytest.fixture
def imported(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    fetch_all(cfg, store)
    hooli_board(web, "Platform Engineer")
    joblist.take(cfg, store, joblist.records(LIST))
    yield cfg, store
    store.close()


def keys(rows):
    return [r["title"] for r in rows]


def test_each_unplaced_job_has_its_reason_recorded_by_the_import(imported):
    cfg, store = imported
    rows = joblist.unplaced(cfg, store)
    assert sorted(keys(rows)) == ["Account Manager", "Data Analyst", "Detection Engineer"]  # not the one on a board
    by = {r["title"]: r for r in rows}
    assert by["Detection Engineer"]["why"] == NO_BOARD and by["Data Analyst"]["why"] == NOT_ON_BOARD
    assert {r["why_source"] for r in rows} == {"recorded"}
    d = by["Data Analyst"]
    assert (d["company"], d["location"], d["source"], d["status"]) == ("Hooli", "London, UK", "linkedin", "new")
    assert d["key"] == "manual:hooli:data-analyst" and d["url"] == "https://www.linkedin.com/jobs/view/4100000004/"
    assert d["first_seen"] == date.today().isoformat() and d["closed"] is False


def test_newest_first_and_by_site_or_day(imported):
    cfg, store = imported
    old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    store.db.execute("UPDATE jobs SET first_seen=? WHERE key=?", (old, "manual:vandelay-industries:detection-engineer"))
    store.db.commit()
    assert keys(joblist.unplaced(cfg, store))[-1] == "Detection Engineer"  # the oldest last
    assert sorted(keys(joblist.unplaced(cfg, store, since="-3"))) == ["Account Manager", "Data Analyst"]
    assert keys(joblist.unplaced(cfg, store, source="Indeed")) == ["Account Manager"]
    assert joblist.unplaced(cfg, store, source="ladders") == []
    with pytest.raises(ValueError, match="isn't a date"):
        joblist.unplaced(cfg, store, since="last week")


def test_an_older_row_gets_its_reason_from_the_runs_kept_or_a_guess(imported):
    cfg, store = imported
    store.db.execute("DELETE FROM list_unplaced")  # imported before the reason was kept in the store
    store.db.commit()
    rows = joblist.unplaced(cfg, store)
    assert {r["why_source"] for r in rows} == {"history"}  # import-list.jsonl has it
    assert {r["title"]: r["why"] for r in rows}["Detection Engineer"] == NO_BOARD
    joblist.history_path(cfg).unlink()
    rows = {r["title"]: r for r in joblist.unplaced(cfg, store)}
    assert {r["why_source"] for r in rows.values()} == {"inferred"}
    assert rows["Detection Engineer"]["why"] == NO_BOARD  # its company was looked for, none found
    assert rows["Data Analyst"]["why"] == NOT_ON_BOARD    # a board was found for Hooli
    assert "(guessed)" in joblist.unplaced_text(list(rows.values()))


def test_a_job_found_on_its_board_later_is_no_longer_unplaced(imported, web):
    cfg, store = imported
    hooli_board(web, "Platform Engineer", "Data Analyst")
    joblist.take(cfg, store, joblist.records(LIST))  # read again: the job is on the board now
    assert "Data Analyst" not in keys(joblist.unplaced(cfg, store))


def test_a_dry_run_records_no_reason(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    try:
        hooli_board(web, "Platform Engineer")
        joblist.take(cfg, store, joblist.records(LIST), dry_run=True)
        assert joblist.unplaced(cfg, store) == []
        assert store.db.execute("SELECT COUNT(*) FROM list_unplaced").fetchone()[0] == 0
    finally:
        store.close()


def test_the_text(imported):
    cfg, store = imported
    text = joblist.unplaced_text(joblist.unplaced(cfg, store))
    assert text.startswith("3 jobs tracked from a list's text alone, not found on the company's board, newest first:")
    assert ("  Hooli: Data Analyst (London, UK)\n    LinkedIn · first seen " in text
            and f" · {NOT_ON_BOARD}\n    `manual:hooli:data-analyst`" in text)
    assert "Indeed · first seen" in text and "(guessed)" not in text
    assert joblist.unplaced_text([]) == "No job tracked from a list's text alone."
    assert joblist.unplaced_text([], "indeed", "2026-11-01") == \
        "No job tracked from Indeed list's text alone since 2026-11-01."


def test_the_cli(imported, watchlist, capsys):
    c = ("-c", str(watchlist))
    cli.main([*c, "import-list", "--unplaced"])
    out = capsys.readouterr().out
    assert "3 jobs tracked from a list's text alone" in out and "Vandelay Industries: Detection Engineer" in out
    cli.main([*c, "import-list", "--unplaced", "--source", "indeed", "--format", "json"])
    [row] = json.loads(capsys.readouterr().out)
    assert row["title"] == "Account Manager" and row["why"] == NO_BOARD and row["why_source"] == "recorded"
    cli.main([*c, "import-list", "--unplaced", "--since", "tomorrow"])
    assert capsys.readouterr().out.startswith("No job tracked from a list's text alone since ")
    with pytest.raises(SystemExit, match="--since is for --unplaced"):
        cli.main([*c, "import-list", "--history", "--since", "today"])


def test_the_mcp_tool(imported, watchlist, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    monkeypatch.setattr(mcp, "_changed_since_start", lambda: None)
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    assert sorted(keys(mcp.list_unplaced_jobs())) == ["Account Manager", "Data Analyst", "Detection Engineer"]
    assert keys(mcp.list_unplaced_jobs(source="indeed", since="today")) == ["Account Manager"]
    with pytest.raises(mcp.ToolError, match="isn't a date"):
        mcp.list_unplaced_jobs(since="soon")
