import json
from datetime import UTC

import pytest

from jobwatch.models import Job
from jobwatch.store import MANUAL, Store


def job(id_: str, title: str = "Engineer") -> Job:
    return Job(source="lever", company="globex", id=id_, title=title, url=f"https://jobs.lever.co/globex/{id_}")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "sub" / "state.db")
    yield s
    s.close()


def test_a_long_read_does_not_hold_up_a_write(store, tmp_path):
    """Write-ahead logging: the page reading Today while a score or logo is saved."""
    assert store.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    store.sync("lever", "globex", [job("a"), job("b")])
    reading = store.db.execute("SELECT key FROM jobs")
    reading.fetchone()  # a read under way
    other = Store(tmp_path / "sub" / "state.db")
    other.save_logo("globex", "globex.com", "image/png", b"x")
    other.close()
    assert reading.fetchone() is not None


def test_sync_reports_only_new_roles(store):
    assert store.sync("lever", "globex", [job("a"), job("b")]) == ["lever:globex:a", "lever:globex:b"]
    assert store.sync("lever", "globex", [job("a", "Renamed"), job("c")]) == ["lever:globex:c"]
    open_jobs = {j.key: j for j, _ in store.jobs()}
    assert set(open_jobs) == {"lever:globex:a", "lever:globex:c"}
    assert open_jobs["lever:globex:a"].title == "Renamed"


def test_an_old_dated_role_new_to_a_board_read_before_counts_as_posted_today(store):
    """A reopened req can keep its first posting date; on a board's first read, old dates are kept."""
    from datetime import datetime, timedelta

    now = datetime.now(UTC)
    old = job("a")
    old.posted = now - timedelta(days=200)
    store.sync("lever", "globex", [old])
    assert store.jobs()[0][0].posted == old.posted  # the board's first read: its dates are the real ones
    repost, fresh = job("b"), job("c")
    repost.posted, fresh.posted = now - timedelta(days=200), now - timedelta(days=3)
    store.sync("lever", "globex", [old, repost, fresh])
    posted = {j.id: j.posted for j, _ in store.jobs()}
    assert posted["b"] > now - timedelta(minutes=1) and posted["c"] == fresh.posted and posted["a"] == old.posted


def test_closed_roles_reopen_when_they_come_back(store):
    store.sync("lever", "globex", [job("a"), job("b")])
    store.sync("lever", "globex", [job("b")])
    assert [j.id for j, _ in store.jobs()] == ["b"]
    assert next(r["closed"] for j, r in store.jobs(include_closed=True) if j.id == "a")
    assert store.sync("lever", "globex", [job("a"), job("b")]) == []
    assert all(r["closed"] is None for _, r in store.jobs())


def test_a_board_that_lists_nothing_closes_nothing(store):
    store.sync("lever", "globex", [job("a")])
    store.sync("lever", "globex", [])  # down or changed, not empty: the daily check of your own jobs decides
    assert [j.id for j, _ in store.jobs()] == ["a"]


def test_a_key_a_board_lists_twice_is_recorded_once(store):
    """A board listing one role twice (a role in two departments, say) fails no sync with a UNIQUE constraint."""
    assert store.sync("lever", "globex", [job("a"), job("a", "Engineer (Remote)"), job("b")]) == [
        "lever:globex:a", "lever:globex:b"]
    assert len(store.jobs()) == 2
    assert store.sync("lever", "globex", [job("a"), job("a")]) == []


def test_a_role_kept_under_another_company_is_updated_not_inserted_again(store):
    """The key is unique across the table: a board that lists a role recorded under another company (an alert's
    copy) updates it, and never fails the check with IntegrityError."""
    store.sync("lever", "initech", [job("a", "Old title")])
    store.db.execute("UPDATE jobs SET key='lever:globex:a' WHERE key='lever:initech:a'")  # kept under another board
    assert store.sync("lever", "globex", [job("a", "New title"), job("b")]) == ["lever:globex:b"]
    assert {j.title for j, _ in store.jobs()} == {"New title", "Engineer"}


def test_one_bad_role_never_fails_the_boards_other_roles(store, capsys):
    bad = job("a")
    bad.title = "x" * 10
    store.db.execute("CREATE TRIGGER refuse BEFORE INSERT ON jobs WHEN NEW.key LIKE '%:bad' "
                     "BEGIN SELECT RAISE(ABORT, 'refused'); END")
    assert store.sync("lever", "globex", [job("bad"), bad, job("c")]) == ["lever:globex:a", "lever:globex:c"]
    assert "skipped lever:globex:bad" in capsys.readouterr().err


def test_boards_are_independent(store):
    store.sync("lever", "globex", [job("a")])
    store.sync("lever", "other", [])
    assert len(store.jobs()) == 1


def test_find_by_key_or_id(store):
    store.sync("lever", "globex", [job("abc-1"), job("abc-2")])
    assert store.find("lever:globex:abc-1")[0].id == "abc-1"
    assert store.find("abc-2")[0].id == "abc-2"
    with pytest.raises(KeyError, match="no job"):
        store.find("zzz")


def test_find_reports_ambiguity(store):
    store.sync("lever", "globex", [job("x-1")])
    store.sync("lever", "other", [Job(source="lever", company="other", id="x-1", title="T", url="u")])
    with pytest.raises(KeyError, match="matches 2 jobs"):
        store.find("x-1")



def test_find_by_company_name(store):
    """`mark umbrella interviewing`: the company's name, or part of it in any case, when that names one job."""
    def umbrella(id_, title):
        return Job(source="greenhouse", company="umbrella-corp", id=id_, title=title, url="u",
                   company_name="Umbrella Corporation")

    store.sync("lever", "globex", [job("a", "Staff Engineer")])
    store.sync("greenhouse", "umbrella-corp", [umbrella("7", "Principal Engineer"), umbrella("8", "Data Engineer")])
    assert store.find("GLOBEX")[0].id == "a"  # the only job there
    with pytest.raises(KeyError) as e:
        store.find("umbrella")
    assert e.value.args[0] == ("'umbrella' matches 2 jobs; give the key of one:\n"
                               "  greenhouse:umbrella-corp:7  Umbrella Corporation: Principal Engineer (new)\n"
                               "  greenhouse:umbrella-corp:8  Umbrella Corporation: Data Engineer (new)")
    store.set_status(["greenhouse:umbrella-corp:7"], "applied")
    assert store.find("umbrella")[0].id == "7"  # the one applied to
    assert store.find("Umbrella Corp")[0].id == "7" and store.find("umbrella-c")[0].id == "7"  # name or board
    store.set_status(["greenhouse:umbrella-corp:8"], "queued")
    with pytest.raises(KeyError, match="matches 2 jobs"):
        store.find("umbrella")
    with pytest.raises(KeyError, match="no job matches 'hooli'"):
        store.find("hooli")
    assert store.find("a")[0].company == "globex"  # a posting id still comes first


def test_find_by_company_name_ignores_punctuation(store):
    """A name typed without its "&" or hyphen still finds the company, but punctuation alone finds nothing."""
    store.sync("greenhouse", "hooli-labs", [Job(source="greenhouse", company="hooli-labs", id="7", title="Engineer",
                                                url="u", company_name="Pied & Piper, Inc.")])
    assert store.find("Pied Piper")[0].id == "7"
    assert store.find("Pied and Piper")[0].id == "7"
    assert store.find("pied-piper inc")[0].id == "7"
    assert store.find("hooli labs")[0].id == "7"
    for nothing in ("!!", "Pied Pipers"):
        with pytest.raises(KeyError, match="no job matches"):
            store.find(nothing)


def test_status_and_note(store):
    store.sync("lever", "globex", [job("a"), job("b")])
    store.set_status(["lever:globex:a"], "applied", "referred by a friend")
    [(j, rec)] = store.jobs(("applied",))
    assert (j.id, rec["note"]) == ("a", "referred by a friend")
    assert [j.id for j, _ in store.jobs(("new",))] == ["b"]
    with pytest.raises(ValueError):
        store.set_status(["lever:globex:a"], "hired")


def test_a_score_made_under_another_resume_is_still_the_score_but_stale(store):
    store.save_score("k", "cv.pdf:111", {"score": 70})
    assert store.score("k", "cv.pdf:111") == {"score": 70}
    assert store.score("k", "cv.pdf:222") == {"score": 70, "stale": True, "stale_why": "older_resume",
                                              "scored_under": "cv.pdf:111"}
    assert store.score("other", "cv.pdf:222") is None


def test_stages_keep_the_day_applied(store):
    store.sync("lever", "globex", [job("a")])
    store.set_status(["lever:globex:a"], "applied", on="2026-03-02")
    store.set_status(["lever:globex:a"], "interviewing")
    rec = store.find("a")[1]
    assert (rec["status"], rec["applied_at"]) == ("interviewing", "2026-03-02")
    store.set_status(["lever:globex:a"], "queued")  # undo: not applied after all
    assert store.find("a")[1]["applied_at"] is None


def test_track_sets_and_clears_fields(store):
    store.sync("lever", "globex", [job("a")])
    store.track("lever:globex:a", next_step="call Ana", follow_up="2026-10-05", note="via Ana")
    rec = store.find("a")[1]
    assert (rec["next_step"], rec["follow_up"], rec["note"]) == ("call Ana", "2026-10-05", "via Ana")
    store.track("lever:globex:a", next_step="", follow_up="")
    rec = store.find("a")[1]
    assert (rec["next_step"], rec["follow_up"], rec["note"]) == (None, None, "via Ana")
    with pytest.raises(ValueError, match="isn't a date"):
        store.track("lever:globex:a", follow_up="next week")


def test_day():
    from datetime import date

    from jobwatch.store import day

    today = date(2026, 9, 29)
    assert day("+7", today) == "2026-10-06"
    assert day("tomorrow", today) == "2026-09-30"
    assert day(" 2026-10-01 ", today) == "2026-10-01"
    assert day("", today) is None
    assert day("none", today) is None  # `mark --follow-up none` clears it


def test_add_an_application_found_elsewhere(store):
    a = store.add("Acme, Inc.", "Staff Engineer", url="https://acme.example/jobs/1", applied="2026-09-01",
                  next_step="ask the recruiter", follow_up="2026-09-10")
    b = store.add("Acme, Inc.", "Staff Engineer", status="screening")
    assert (a.key, b.key) == ("manual:acme-inc:staff-engineer", "manual:acme-inc:staff-engineer-2")
    job_a, rec = store.find(a.key)
    assert (job_a.display_company, rec["status"], rec["applied_at"]) == ("Acme, Inc.", "applied", "2026-09-01")
    assert rec["next_step"] == "ask the recruiter"
    with pytest.raises(ValueError, match="already tracked as manual:acme-inc:staff-engineer"):
        store.add("Acme", "Other title", url="https://acme.example/jobs/1")
    with pytest.raises(ValueError, match="company and a job title"):
        store.add(" ", "Engineer")
    # A watched board never closes an application added by hand.
    store.sync(MANUAL, "other", [])
    store.sync("lever", "acme-inc", [])
    assert store.find(a.key)[1]["closed"] is None


def test_applications_follow_ups_first_ended_last(store):
    store.add("A", "Old", applied="2026-01-01")
    store.add("B", "Recent", applied="2026-09-01")
    store.add("C", "Later follow-up", follow_up="2026-12-01")
    store.add("D", "Soon follow-up", follow_up="2026-10-01")
    store.add("E", "No", status="rejected")
    store.sync("lever", "globex", [job("a")])  # not applied to: not listed
    assert [j.title for j, _ in store.applications()] == ["Soon follow-up", "Later follow-up", "Recent", "Old", "No"]


def test_an_older_state_file_gains_the_new_columns(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE jobs (key TEXT PRIMARY KEY, source TEXT NOT NULL, company TEXT NOT NULL, "
                     "data TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, closed TEXT, "
                     "status TEXT NOT NULL DEFAULT 'new', status_at TEXT, note TEXT);")
    db.execute("INSERT INTO jobs VALUES ('lever:globex:a', 'lever', 'globex', ?, 't', 't', NULL, 'applied', "
               "'2026-05-04T10:00:00+00:00', NULL)", (json.dumps(job("a").to_dict()),))
    db.commit()
    db.close()
    s = Store(path)
    [(_, rec)] = s.applications()
    assert (rec["applied_at"], rec["follow_up"]) == ("2026-05-04", None)
    s.close()
    Store(path).close()  # opening it again changes nothing
