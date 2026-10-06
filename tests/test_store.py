import json

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


def test_sync_reports_only_new_roles(store):
    assert store.sync("lever", "globex", [job("a"), job("b")]) == ["lever:globex:a", "lever:globex:b"]
    assert store.sync("lever", "globex", [job("a", "Renamed"), job("c")]) == ["lever:globex:c"]
    open_jobs = {j.key: j for j, _ in store.jobs()}
    assert set(open_jobs) == {"lever:globex:a", "lever:globex:c"}
    assert open_jobs["lever:globex:a"].title == "Renamed"


def test_closed_roles_reopen_when_they_come_back(store):
    store.sync("lever", "globex", [job("a")])
    store.sync("lever", "globex", [])
    assert store.jobs() == []
    assert store.jobs(include_closed=True)[0][1]["closed"]
    assert store.sync("lever", "globex", [job("a")]) == []
    assert store.jobs()[0][1]["closed"] is None


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

def test_status_and_note(store):
    store.sync("lever", "globex", [job("a"), job("b")])
    store.set_status(["lever:globex:a"], "applied", "referred by a friend")
    [(j, rec)] = store.jobs(("applied",))
    assert (j.id, rec["note"]) == ("a", "referred by a friend")
    assert [j.id for j, _ in store.jobs(("new",))] == ["b"]
    with pytest.raises(ValueError):
        store.set_status(["lever:globex:a"], "hired")


def test_scores_are_per_resume(store):
    store.save_score("k", "cv.pdf:111", {"score": 70})
    assert store.score("k", "cv.pdf:111") == {"score": 70}
    assert store.score("k", "cv.pdf:222") is None


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
