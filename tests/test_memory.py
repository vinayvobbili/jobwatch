"""The UI server's memory stays small however many jobs the store holds: the pages go through every job (a hundred
thousand, each with the posting's text), so what they read is streamed or read when asked for, never all held.
scripts/ui_memory.py measures a real server."""

import tracemalloc
import types

import pytest

from jobwatch import alerts
from jobwatch.models import Job
from jobwatch.store import Scores, Store

POSTING = "Build and run Initech's platform. " * 300  # about 10 KB of text a job


def job(i: int) -> Job:
    return Job(source="lever", company="globex", id=str(i), title=f"Engineer {i}", description=POSTING,
               url=f"https://jobs.lever.co/globex/{i}")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state.db")
    s.sync("lever", "globex", [job(i) for i in range(300)])
    yield s
    s.close()


def peak(fn) -> int:
    tracemalloc.start()
    try:
        fn()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_iter_jobs_holds_one_job_at_a_time(store):
    assert isinstance(store.iter_jobs(), types.GeneratorType)
    everything = peak(lambda: store.jobs())  # 300 jobs x 10 KB, and more parsed
    streamed = peak(lambda: sum(1 for _ in store.iter_jobs()))
    assert sum(1 for _ in store.iter_jobs()) == 300 and everything > 3_000_000
    assert streamed < everything / 10


def test_tracked_indexes_the_store_without_holding_its_jobs(store):
    held = peak(lambda: alerts._Tracked(store))
    assert held < 1_000_000  # the 3 MB of postings aren't kept
    tracked = alerts._Tracked(store)
    assert tracked.match("Globex", "Engineer 7") == "lever:globex:7"
    assert tracked.get("lever:globex:7").title == "Engineer 7" and tracked.get("lever:globex:none") is None
    new = job(900)
    tracked.add(new)
    assert tracked.get(new.key) is new  # one taken in since is known before it's read back


def test_scores_are_parsed_when_asked_for(store):
    store.save_score("lever:globex:1", "resume-a", {"score": 80, "reasoning": "x" * 1000})
    scores = store.scores("resume-a")
    assert isinstance(scores, Scores) and len(scores) == 1 and list(scores) == ["lever:globex:1"]
    assert scores["lever:globex:1"]["score"] == 80 and scores.get("lever:globex:2") is None
    store.save_score("lever:globex:2", "resume-a", {"score": 70})
    other = Scores({"lever:globex:1": ('{"score": 10}', True)})
    merged = store.scores("resume-a").over(other)
    assert merged["lever:globex:1"] == {"score": 10, "stale": True} and merged["lever:globex:2"]["score"] == 70
