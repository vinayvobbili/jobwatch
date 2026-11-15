"""`jobwatch prune`: old jobs nobody acted on shrink, and nothing a person touched changes."""

from datetime import datetime, timedelta, timezone

import pytest

from jobwatch import prune
from jobwatch.models import Job
from jobwatch.store import Store

LONG_AGO = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()


def job(id_: str, title: str = "Engineer") -> Job:
    return Job(source="lever", company="globex", id=id_, title=title, url=f"https://jobs.lever.co/globex/{id_}",
               description="A long posting. " * 200)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state.db")
    yield s
    s.close()


def age(store, key, closed=False):
    """Make a job look first seen 90 days ago (closed then too, when asked)."""
    with store.db:
        store.db.execute("UPDATE jobs SET first_seen=?, last_seen=?, closed=? WHERE key=?",
                         (LONG_AGO, LONG_AGO, LONG_AGO if closed else None, key))


def rows(store):
    return {r["key"]: r for r in store.db.execute("SELECT * FROM jobs")}


def test_a_closed_old_job_is_deleted_and_an_open_old_one_is_slimmed(store):
    store.sync("lever", "globex", [job("1"), job("2")])
    store.sync("lever", "globex", [job("2")])  # 1 left the board
    for k in ("lever:globex:1", "lever:globex:2"):
        age(store, k, closed=k.endswith("1"))
    p = prune.plan(store)
    assert p.delete == ["lever:globex:1"] and p.slim == ["lever:globex:2"] and p.bytes > 0
    prune.apply(store, p)
    left = rows(store)
    assert list(left) == ["lever:globex:2"] and left["lever:globex:2"]["slim"] == "1"
    kept = store.job("lever:globex:2")
    assert kept.title == "Engineer" and kept.description == "" and kept.url.endswith("/2")


def test_a_job_closed_only_lately_is_slimmed_not_deleted_and_old_dated_jobs_count_by_posting_date(store):
    old_posted = job("1")
    old_posted.posted = datetime.now(timezone.utc) - timedelta(days=90)
    store.sync("lever", "globex", [old_posted, job("2")])
    store.sync("lever", "globex", [job("2")])  # 1 closed just now; first seen just now, but posted 90 days ago
    p = prune.plan(store)
    assert p.delete == [] and p.slim == ["lever:globex:1"]  # 2 has no posting date and was first seen today
    prune.apply(store, p)
    assert store.sync("lever", "globex", [old_posted, job("2")]) == []  # it came back: not new


def test_a_slimmed_job_is_not_reported_new_again_and_stays_slim(store):
    store.sync("lever", "globex", [job("1")])
    age(store, "lever:globex:1")
    prune.apply(store, prune.plan(store))
    assert store.sync("lever", "globex", [job("1")]) == []
    assert store.job("lever:globex:1").description == ""
    assert rows(store)["lever:globex:1"]["slim"] == "1"


def test_a_slimmed_job_you_then_queue_gets_its_text_back_on_the_next_check(store):
    store.sync("lever", "globex", [job("1")])
    age(store, "lever:globex:1")
    prune.apply(store, prune.plan(store))
    store.set_status(["lever:globex:1"], "queued")
    store.sync("lever", "globex", [job("1")])
    assert store.job("lever:globex:1").description.startswith("A long posting")
    assert rows(store)["lever:globex:1"]["slim"] is None


def test_jobs_somebody_acted_on_or_kept_something_about_are_untouched(store, tmp_path):
    keys = [f"lever:globex:{i}" for i in range(1, 12)]
    store.sync("lever", "globex", [job(str(i)) for i in range(1, 12)])
    store.sync("lever", "globex", [])  # all closed
    for k in keys:
        age(store, k, closed=True)
    store.set_status(keys[0:1], "queued")
    store.set_status(keys[1:2], "applied")
    store.set_status(keys[2:3], "skipped")
    store.set_status(keys[3:4], "shown")
    store.add_note(keys[4], "ask Dana")
    store.save_score(keys[5], "resume", {"fit": 80})
    store.set_comp(keys[6], base="170K")
    store.save_draft(keys[7], "inputs", "reply")
    store.package(keys[8]).attach("resume.txt", b"mine")
    store.set_duplicate(keys[9], keys[10])  # the pair: one points at the other
    age(store, keys[0], closed=True)  # the status changes above don't touch first_seen, but make it plain
    before = {k: dict(r) for k, r in rows(store).items()}
    prune.apply(store, prune.plan(store))
    after = rows(store)
    assert set(after) == set(keys)
    assert {k: dict(r) for k, r in after.items()} == before


def test_a_recent_job_and_a_job_from_an_alert_are_left_alone(store):
    store.sync("lever", "globex", [job("1"), job("2")])
    store.sync("lever", "globex", [job("2")])  # 1 closed, but only just
    store.add("Initech", "Staff Engineer", status="new")
    manual = next(k for k, r in rows(store).items() if r["source"] == "manual")
    age(store, manual)
    p = prune.plan(store)
    assert p.delete == [] and p.slim == []


def test_the_dry_run_changes_nothing(store, capsys, tmp_path):
    from jobwatch import cli
    store.sync("lever", "globex", [job("1"), job("2")])
    store.sync("lever", "globex", [job("2")])
    for k in ("lever:globex:1", "lever:globex:2"):
        age(store, k, closed=k.endswith("1"))
    before = {k: dict(r) for k, r in rows(store).items()}
    args = cli.build_parser().parse_args(["prune"])
    cli.cmd_prune(args, None, store)
    out = capsys.readouterr().out
    assert "delete (off their board for over 30 days): 1" in out and "Nothing changed" in out
    assert {k: dict(r) for k, r in rows(store).items()} == before
    assert not store.path.with_name("state.db.before-prune").exists()


def test_apply_copies_the_database_first(store, capsys):
    from jobwatch import cli
    store.sync("lever", "globex", [job("1")])
    store.sync("lever", "globex", [])
    age(store, "lever:globex:1", closed=True)
    cli.cmd_prune(cli.build_parser().parse_args(["prune", "--apply"]), None, store)
    copy = Store(store.path.with_name("state.db.before-prune"))
    assert copy.has("lever:globex:1") and not store.has("lever:globex:1")
    copy.close()
