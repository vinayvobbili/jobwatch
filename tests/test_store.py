import pytest

from jobwatch.models import Job
from jobwatch.store import Store


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
