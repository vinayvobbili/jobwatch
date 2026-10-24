"""The Activity tab: what jobwatch did (checked the boards, read job-alert emails, scored jobs, looked up pay),
newest first, kept in the store, and what it's doing now."""

import functools

import yaml

from jobwatch import alerts, config, watch
from jobwatch import store as store_mod
from jobwatch.store import Store
from jobwatch.web import App

from .test_alerts import IMAP_WATCHLIST, FakeIMAP
from .test_background_scoring import resume_watchlist, scored  # noqa: F401 (fixtures)


def test_entries_are_newest_first_by_kind_and_only_the_last_of_each_kind_are_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "ACTIVITY_KEPT", 3)
    store = Store(tmp_path / "s.db")
    store.log("boards", "one")
    store.log("score", "two", ok=False, detail=["why"], by="background")
    store.log("boards", "three")
    store.log("pay", "four")
    for i in range(4):
        store.log("pay", f"pay {i}")
    # each kind keeps its own last few, so many of one kind don't push another out
    assert [e["text"] for e in store.activity()] == ["pay 3", "pay 2", "pay 1", "three", "two", "one"]
    assert [e["text"] for e in store.activity(kind="boards")] == ["three", "one"]
    assert [e["text"] for e in store.activity(kind="score,boards")] == ["three", "two", "one"]
    two = store.activity(kind="score")[0]
    assert (two["ok"], two["detail"], two["by"]) == (False, ["why"], "background")
    store.close()


def test_a_check_says_what_it_found_for_you_and_what_failed(watchlist, web):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store, by="schedule")
    e = store.activity()[0]
    # what Today shows leads; the new postings the filters hide are a detail
    assert (e["kind"], e["text"], e["ok"], e["by"]) == ("boards", "Checked 3 boards: 3 new jobs for you", True,
                                                        "schedule")
    assert len([d for d in e["detail"] if d.startswith("New: ")]) == 3
    assert e["detail"][-1] == "5 open jobs, 5 new, 2 hidden by your filters"
    watch.fetch_all(cfg, store)  # the same jobs again
    assert store.activity()[0]["text"] == "Checked 3 boards: nothing new for you"
    web.responses.clear()  # no network: every board fails
    watch.fetch_all(cfg, store)
    e = store.activity()[0]
    assert e["text"] == "Couldn't check the boards, 3 failed" and not e["ok"]
    assert len([d for d in e["detail"] if d.startswith("Failed: ")]) == 3
    store.close()


def test_reading_the_mailbox_is_its_own_entry(tmp_path, watchlist, web, monkeypatch):
    path = tmp_path / "w.yaml"
    path.write_text(watchlist.read_text() + IMAP_WATCHLIST + "    password_env: JOBWATCH_IMAP_PASSWORD\n")
    monkeypatch.setenv("JOBWATCH_IMAP_PASSWORD", "not-a-real-password")
    monkeypatch.setattr(alerts, "intake", functools.partial(alerts.intake, follow=False))
    cfg = config.load(path)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store, mail=FakeIMAP)
    mail = store.activity(kind="mail")[0]
    assert mail["ok"] and mail["text"] == "Read 2 job-alert emails: 1 new job for you"
    assert mail["detail"][-1].startswith("From imap.example.com: ")
    monkeypatch.delenv("JOBWATCH_IMAP_PASSWORD")
    watch.fetch_all(cfg, store, mail=FakeIMAP)
    mail = store.activity(kind="mail")[0]
    assert not mail["ok"] and mail["text"] == "Couldn't read job-alert emails from imap.example.com"
    assert "not-a-real-password" not in str(store.activity())
    store.close()


def test_scoring_says_which_jobs_and_their_scores(resume_watchlist, scored):  # noqa: F811
    _, fail = scored
    cfg = config.load(resume_watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    todo = watch.unscored(cfg, store)
    watch.score_entries(cfg, store, todo[:1], progress=lambda m: None, by="background")
    one = store.activity(kind="score")[0]
    assert one["text"].startswith("Scored 70/100 ") and one["by"] == "background" and one["detail"] == []
    fail.add(todo[2].job.key)
    watch.score_entries(cfg, store, todo[1:], progress=lambda m: None, batch=True)
    many = store.activity(kind="score")[0]
    assert many["text"] == "Scored 1 job through the Batches API, 1 failed" and many["ok"]
    assert [d.split(" ")[0] for d in many["detail"]] == ["70/100", "Failed:"]
    store.close()


def test_the_page_shows_the_log_and_whats_running(watchlist, web):
    app = App(watchlist)
    app.post_fetch({})
    got = app.get_activity({})
    assert got["events"][0]["kind"] == "boards" and got["events"][0]["by"] == "page"
    assert got["now"] == {"boards": False, "score": app.scorer.status(), "pay": False}
    assert app.get_activity({"kind": ["pay"]})["events"] == []  # as the server reads a query: lists


def test_only_what_is_worth_a_look_is_notable(tmp_path, watchlist, web, monkeypatch):
    """A strong fit, a mailbox that can't be read and a check that read no board are notable (the page tells
    you); a check that worked, or a so-so fit, isn't."""
    (watchlist.parent / "cv.md").write_text("Python, LLMs, RAG")
    path = tmp_path / "w.yaml"
    raw = yaml.safe_load(watchlist.read_text() + IMAP_WATCHLIST + "    password_env: JOBWATCH_IMAP_PASSWORD\n")
    path.write_text(yaml.safe_dump({**raw, "resume": "cv.md"}))
    cfg = config.load(path)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store, mail=FakeIMAP)  # no password: the mailbox can't be read
    assert [(e["kind"], e["notable"]) for e in store.activity()] == [("boards", False), ("mail", True)]
    scores = iter([80, 60, 60])
    monkeypatch.setattr(watch, "score_jobs", lambda jobs, *a, **kw: (
        {j.key: {"score": next(scores), "must_haves_met": 1, "must_haves_total": 1, "gaps": [], "summary": ""}
         for j in jobs}, {}))
    todo = watch.unscored(cfg, store)
    watch.score_entries(cfg, store, todo[:2], progress=lambda m: None)
    assert store.activity()[0]["text"] == "Scored 2 jobs: 1 strong fit" and store.activity()[0]["notable"]
    watch.score_entries(cfg, store, todo[2:], progress=lambda m: None)  # 60: not one
    assert not store.activity()[0]["notable"]
    web.responses.clear()
    watch.fetch_all(cfg, store)
    assert store.activity(kind="boards")[0]["notable"]  # no board read
    marks = [e["at"] for e in store.activity(notable=True)]
    assert len(marks) == 4  # the mailbox failed again with the boards
    assert store.activity(notable=True, since=marks[1]) == store.activity(notable=True)[:1]
    store.close()


def test_a_strong_fit_is_news_only_once_and_only_for_a_job_you_would_see(tmp_path, watchlist, web, monkeypatch):
    """A re-score of a job that was already strong, a strong fit for a job your filters hide, and one you've
    acted on aren't news: they don't count on the Activity tab."""
    (watchlist.parent / "cv.md").write_text("Python, LLMs, RAG")
    path = tmp_path / "w.yaml"
    path.write_text(yaml.safe_dump({**yaml.safe_load(watchlist.read_text()), "resume": "cv.md"}))
    cfg = config.load(path)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    scores = iter([80, 85, 90, 90])
    monkeypatch.setattr(watch, "score_jobs", lambda jobs, *a, **kw: (
        {j.key: {"score": next(scores), "must_haves_met": 1, "must_haves_total": 1, "gaps": [], "summary": ""}
         for j in jobs}, {}))
    first, other, *_ = watch.unscored(cfg, store)
    watch.score_entries(cfg, store, [first], progress=lambda m: None)
    assert store.activity()[0]["notable"]  # 80, first time strong
    watch.score_entries(cfg, store, [first], progress=lambda m: None)
    assert not store.activity()[0]["notable"]  # 85: it was strong already
    with monkeypatch.context() as m:
        m.setattr(watch, "rejection", lambda job, f, fit=None: ("place", "location"))
        watch.score_entries(cfg, store, [other], progress=lambda m: None)
    assert not store.activity()[0]["notable"]  # 90, but Today doesn't show it
    store.save_score(other.job.key, watch.resume_id(cfg.resume, cfg.prompts), {"score": 10})
    other.record["status"] = "applied"
    watch.score_entries(cfg, store, [other], progress=lambda m: None)
    assert not store.activity()[0]["notable"]  # 90 after 10, but applied to already
    store.close()


def test_an_older_activity_table_gains_notable(tmp_path):
    import sqlite3
    db = sqlite3.connect(tmp_path / "s.db")
    db.execute("CREATE TABLE activity (at TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, ok INTEGER NOT "
               "NULL, detail TEXT NOT NULL, by TEXT NOT NULL)")
    db.execute("INSERT INTO activity VALUES ('2026-01-01T00:00:00+00:00', 'pay', 'old', 1, '[]', '')")
    db.commit()
    db.close()
    store = Store(tmp_path / "s.db")
    store.log("boards", "new", notable=True)
    assert [(e["text"], e["notable"]) for e in store.activity()] == [("new", True), ("old", False)]
    store.close()
