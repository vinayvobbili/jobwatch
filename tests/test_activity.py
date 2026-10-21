"""The Activity tab: what jobwatch did (checked the boards, read job-alert emails, scored jobs, looked up pay),
newest first, kept in the store, and what it's doing now."""

import functools

from jobwatch import alerts, config, watch
from jobwatch import store as store_mod
from jobwatch.store import Store
from jobwatch.web import App

from .test_alerts import IMAP_WATCHLIST, FakeIMAP
from .test_background_scoring import resume_watchlist, scored  # noqa: F401 (fixtures)


def test_entries_are_newest_first_by_kind_and_only_the_last_are_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "ACTIVITY_KEPT", 3)
    store = Store(tmp_path / "s.db")
    store.log("boards", "one")
    store.log("score", "two", ok=False, detail=["why"], by="background")
    store.log("boards", "three")
    store.log("pay", "four")
    assert [e["text"] for e in store.activity()] == ["four", "three", "two"]
    assert [e["text"] for e in store.activity(kind="boards")] == ["three"]
    two = store.activity(kind="score")[0]
    assert (two["ok"], two["detail"], two["by"]) == (False, ["why"], "background")
    store.close()


def test_a_check_says_what_it_found_and_what_failed(watchlist, web):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store, by="schedule")
    e = store.activity()[0]
    assert (e["kind"], e["text"], e["ok"], e["by"]) == ("boards", "Checked 3 boards: 5 open jobs, 5 new", True,
                                                        "schedule")
    assert len([d for d in e["detail"] if d.startswith("New: ")]) == 5
    web.responses.clear()  # no network: every board fails
    watch.fetch_all(cfg, store)
    e = store.activity()[0]
    assert e["text"] == "Checked 0 boards: 0 open jobs, 0 new, 3 failed" and not e["ok"]
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
    assert mail["ok"] and mail["text"].startswith("Read 2 job-alert emails from imap.example.com: ")
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
    assert app.get_activity({"kind": "pay"})["events"] == []
