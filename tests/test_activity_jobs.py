"""Activity rows that are about a job carry its key, so the page links each to the job's card: stored with the row,
resolved to {key, company, title, status}, matched by name for rows written before (only when one job fits), and a
prep sheet's row linked to its application."""

import json
import sqlite3

import pytest

from jobwatch import actjobs, config, filltext, watch
from jobwatch.store import Store
from jobwatch.web import App

from .test_background_scoring import resume_watchlist, scored  # noqa: F401 (fixtures)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "s.db")
    yield s
    s.close()


def test_a_row_keeps_its_jobs_and_names_them(store):
    job = store.add("Initech", "Principal Architect", status="queued")
    store.log("score", "Scored 88/100 Initech: Principal Architect (model-x)", jobs=[job.key, "gone:key:1", job.key])
    store.log("boards", "Checked 3 boards: nothing new for you")
    plain, scored_row = store.activity()
    assert plain["jobs"] == []
    assert scored_row["jobs"] == [{"key": job.key, "company": "Initech", "title": "Principal Architect",
                                   "status": "queued"}]  # the one that's gone is left out, a repeat said once


def test_a_row_about_many_jobs_lists_each(store):
    jobs = [store.add("Globex", f"Role {i}", status="applied") for i in range(3)]
    store.log("boards", "Found 3 postings taken down", jobs=[j.key for j in jobs])
    assert [j["title"] for j in store.activity()[0]["jobs"]] == ["Role 0", "Role 1", "Role 2"]


def test_the_names_a_line_may_hold():
    got = list(actjobs.name_candidates("88/100 Optum: Senior AI/ML Engineer (claude-sonnet-5-5)"))
    assert ("optum", "senior ai/ml engineer") in got
    failed = list(actjobs.name_candidates("Failed: Initech: Staff Engineer: model said no"))
    assert ("initech", "staff engineer") in failed
    assert ("globex", "lead: platform") in list(actjobs.name_candidates("New: Globex: Lead: Platform"))
    assert next(iter(actjobs.name_candidates("From imap.example.com: 3 jobs")))[0] == "from imap.example.com"


def test_a_model_with_its_own_parentheses_is_dropped_from_the_name():
    got = list(actjobs.name_candidates("Scored 46/100 Globex: Staff Engineer (Remote) (local-model (fallback))"))
    assert ("globex", "staff engineer (remote)") in got and ("globex", "staff engineer") in got


def test_link_activity_links_the_rows_still_naming_no_job(watchlist, capsys):
    from jobwatch import cli
    store = Store(config.load(watchlist).state)
    job = store.add("Globex", "Staff Engineer", status="queued")
    store.log("score", "Scored 46/100 Globex: Staff Engineer (local-model (fallback))")  # as before the fix: no keys
    store.close()
    cli.main(["-c", str(watchlist), "link-activity"])
    assert capsys.readouterr().out.strip() == "1 Activity rows linked to their jobs"
    store = Store(config.load(watchlist).state)
    assert [j["key"] for j in store.activity()[0]["jobs"]] == [job.key]
    store.close()


def _old_file(path):
    """A state file from before rows kept their jobs: the activity table with the older columns only."""
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE activity (at TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, ok INTEGER NOT NULL, "
               "detail TEXT NOT NULL, by TEXT NOT NULL, notable INTEGER NOT NULL DEFAULT 0)")
    rows = [("2026-01-01T00:00:01+00:00", "score", "Scored 88/100 Initech: Principal Architect (model-x)", "[]"),
            ("2026-01-01T00:00:02+00:00", "score", "Scored 2 jobs", json.dumps(
                ["70/100 Globex: Staff Engineer (model-x)", "Failed: Umbrella: Data Lead: model said no"])),
            ("2026-01-01T00:00:03+00:00", "score", "Scored 55/100 Hooli: Engineer (model-x)", "[]"),
            ("2026-01-01T00:00:04+00:00", "boards", "Found 1 posting taken down",
             json.dumps(["Globex: Staff Engineer"])),
            ("2026-01-01T00:00:05+00:00", "pay", "Looked up pay", json.dumps(["Nobody: No Such Role"])),
            ("2026-01-01T00:00:06+00:00", "prep", "Rendered the drill video for initech-dana.html in 9 s", "[]")]
    db.executemany("INSERT INTO activity VALUES (?, ?, ?, 1, ?, '', 0)", rows)
    db.commit()
    db.close()


def test_an_older_activity_table_gains_jobs_matched_by_name_when_one_job_fits(tmp_path):
    path = tmp_path / "s.db"
    db = Store(path)
    initech = db.add("Initech", "Principal Architect", status="queued")
    globex = db.add("Globex", "Staff Engineer", status="applied")
    globex_again = db.add("Globex", "Staff Engineer", status="applied")  # the same role twice: ambiguous
    db.add("Hooli", "Engineer", status="new")
    db.add("Hooli", "Engineer", status="new")  # two: no link
    umbrella = db.add("Umbrella", "Data Lead", status="queued")
    db.db.execute("DROP TABLE activity")
    db.close()
    _old_file(path)
    db = Store(path)  # opens the old table: adds the columns and links what it can
    got = {e["text"]: [j["key"] for j in e["jobs"]] for e in db.activity()}
    assert got["Scored 88/100 Initech: Principal Architect (model-x)"] == [initech.key]
    assert got["Scored 2 jobs"] == [umbrella.key]  # Globex has two: only the Umbrella line is one job
    assert got["Scored 55/100 Hooli: Engineer (model-x)"] == []
    assert got["Found 1 posting taken down"] == []
    assert got["Looked up pay"] == []
    assert globex.key != globex_again.key
    db.close()


def test_a_prep_sheets_row_is_about_the_application_it_belongs_to(store):
    initech = store.add("Initech", "Principal Architect", status="screening")
    store.add("Globex", "Staff Engineer", status="applied")
    store.log("prep", "Rendered the drill video for initech-dana.html in 9 s")
    store.log("prep", "Saved 2 edits to globex-staff.html", jobs=[])  # said none: left none
    store.log("prep", "Saved 1 edit to unknown-co.html")
    stored = {e["text"]: [j["key"] for j in e["jobs"]] for e in store.activity()}
    assert stored["Rendered the drill video for initech-dana.html in 9 s"] == [initech.key]
    assert stored["Saved 2 edits to globex-staff.html"] == []
    assert stored["Saved 1 edit to unknown-co.html"] == []


def test_a_sheet_the_note_names_wins_and_a_req_number_picks_the_opening(store):
    a = store.add("Initech", "Architect 40125", status="applied", url="https://example.com/jobs/40125")
    b = store.add("Initech", "Architect 51234", status="applied", url="https://example.com/jobs/51234")
    rows = [(a, {"status": "applied"}), (b, {"status": "applied"})]
    assert actjobs.sheet_jobs(rows, "initech-51234-dana.html") == [b.key]
    assert actjobs.sheet_jobs(rows, "initech-dana.html") == []  # two openings, nothing to tell them by
    assert actjobs.sheet_jobs([(a, {"status": "applied", "note": "Prep sheet: dana-loop.html"}),
                               (b, {"status": "applied"})], "dana-loop.html") == [a.key]


def test_log_lines_naming_a_job_key_link_to_it():
    assert actjobs.line_keys("saw greenhouse:acme:101 and lever:globex:aaaa-1111; texts: 0 new at 10:30:05") == [
        "greenhouse:acme:101", "lever:globex:aaaa-1111"]


def test_scoring_passes_the_jobs_scored_and_the_ones_that_failed(resume_watchlist, scored):  # noqa: F811
    _, fail = scored
    cfg = config.load(resume_watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    todo = watch.unscored(cfg, store)
    watch.score_entries(cfg, store, todo[:1], progress=lambda m: None)
    one = store.activity(kind="score")[0]
    assert [j["key"] for j in one["jobs"]] == [todo[0].job.key]
    assert f"{one['jobs'][0]['company']}: {one['jobs'][0]['title']}" in one["text"]
    fail.add(todo[2].job.key)
    watch.score_entries(cfg, store, todo[1:], progress=lambda m: None, batch=True)
    many = store.activity(kind="score")[0]
    assert [j["key"] for j in many["jobs"]] == [e.job.key for e in todo[1:]]
    store.close()


def test_a_check_links_the_jobs_it_found_and_the_postings_it_found_closed(watchlist, web):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store, by="schedule")
    found = store.activity(kind="boards")[0]
    assert len(found["jobs"]) == 3 and all(j["status"] == "new" for j in found["jobs"])
    assert {d.removeprefix("New: ") for d in found["detail"] if d.startswith("New: ")} == \
        {f"{j['company']}: {j['title']}" for j in found["jobs"]}
    store.close()


def test_filling_in_a_posting_text_is_a_row_about_that_job(tmp_path, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    job = store.add("Initech", "Staff Engineer", url="https://www.linkedin.com/jobs/view/123456/", status="queued")
    page = "About the job\n" + "Build things. " * 30 + "\nShow more\n"
    filltext.save_page_posting(store, job.key, filltext.posting_from_page("linkedin", page))
    row = store.activity(kind="mail")[0]
    assert row["text"].startswith("Read the posting text of Initech: Staff Engineer")
    assert [j["key"] for j in row["jobs"]] == [job.key]
    store.close()


def test_the_page_gets_the_jobs_in_the_api(watchlist, web):
    app = App(watchlist)
    app.post_fetch({})
    events = app.get_activity({"kind": ["boards"]})["events"]
    assert events[0]["jobs"] and set(events[0]["jobs"][0]) == {"key", "company", "title", "status"}
    # the logs other programs write: a line that names a job by its key links to it
    log = watchlist.parent / "other.log"
    log.write_text(f"2026-01-02 03:04:05 queued {events[0]['jobs'][0]['key']}\n2026-01-02 03:04:06 texts: 0 new\n")
    watchlist.write_text(watchlist.read_text() + f"ui:\n  activity_logs:\n    - {{name: Other, path: {log}}}\n")
    lines = App(watchlist).get_activity_logs({})["logs"][0]["lines"]
    assert [bool(x["jobs"]) for x in lines] == [False, True]
    assert lines[1]["jobs"][0]["key"] == events[0]["jobs"][0]["key"]
