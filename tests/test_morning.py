"""The morning digest: which new matches it names, the notification's text and how it is shown, the once-a-day rule,
the setting, the saved page. The notification is faked: these tests never show one or run osascript."""

import subprocess
from datetime import UTC, datetime, timedelta

import pytest
import yaml

from jobwatch import cli, closed_notice, config, morning
from jobwatch.models import Job
from jobwatch.score import resume_id
from jobwatch.store import Store
from jobwatch.web import App

from .conftest import request

NOW = datetime(2026, 3, 16, 13, 0, tzinfo=UTC)   # 8 AM in New York
FIT = {"must_haves_met": 4, "must_haves_total": 5, "gaps": [], "summary": "", "scored_by": "local:test"}


def write(tmp_path, **extra) -> config.Config:
    (tmp_path / "resume.txt").write_text("Jordan Rivera, platform engineer")
    path = tmp_path / "jobwatch.yaml"
    path.write_text(yaml.safe_dump({
        "companies": ["greenhouse:acme"], "state": "state.db", "resume": "resume.txt",
        "filters": {"locations": ["remote", "Denver"], "min_salary": 150000, "exclude_titles": ["contract"]},
        **extra}))
    return config.load(path)


@pytest.fixture
def cfg(tmp_path):
    return write(tmp_path)


@pytest.fixture
def store(cfg):
    s = Store(cfg.state)
    yield s
    s.close()


def job(id_, title="Platform Engineer", company="initech", where="Remote", pay=(150000, 190000), **kw):
    j = Job(source="greenhouse", company=company, id=id_, title=title, url=f"https://boards.example/{id_}",
            locations=[where], description="Build things. Python and AWS.", **kw)
    if pay:
        j.set_pay(*pay, "USD")
    return j


def land(store, jobs, at=NOW - timedelta(hours=3)):
    """Jobs the boards just listed, first seen at `at`."""
    for j in jobs:
        store.sync("greenhouse", j.company, [j], close_missing=False)
        store.db.execute("UPDATE jobs SET first_seen=? WHERE key=?", (at.isoformat(), j.key))
    store.db.commit()


def score(cfg, store, j, value):
    store.save_score(j.key, resume_id(cfg.resume, cfg.prompts), {"score": value, **FIT})


@pytest.fixture
def shown():
    """A notification that records what it was asked to show."""
    calls = []

    def show(title, body, url):
        calls.append((title, body, url))
    show.calls = calls
    return show


def test_the_setting_is_on_by_default_and_checked(tmp_path):
    assert write(tmp_path).morning == config.Morning(True, 3)
    assert write(tmp_path, morning={"notify": False, "top": 5}).morning == config.Morning(False, 5)
    with pytest.raises(config.ConfigError, match=r"morning\.notify must be on or off"):
        write(tmp_path, morning={"notify": "maybe"})
    with pytest.raises(config.ConfigError, match=r"morning\.top must be a whole number from 1 to 10"):
        write(tmp_path, morning={"top": 0})
    with pytest.raises(config.ConfigError, match="unknown morning setting"):
        write(tmp_path, morning={"loud": True})


def test_the_matches_pass_the_filters_and_are_not_acted_on_or_old(cfg, store):
    ok = job("1")
    low = job("2", pay=(90000, 100000))                        # under the pay floor
    far = job("3", where="Berlin")                             # not remote, not Denver
    contract = job("4", title="Platform Engineer (Contract)")  # an excluded title
    applied, skipped = job("5", title="SRE"), job("6", title="Data Engineer")
    land(store, [ok, low, far, contract, applied, skipped])
    store.set_status([applied.key], "applied")
    store.set_status([skipped.key], "skipped")
    old = job("7", company="umbrella", title="Old Role")
    land(store, [old], at=NOW - timedelta(days=5))
    items, total = morning.pick(cfg, store, NOW - timedelta(days=1))
    assert [i["key"] for i in items] == [ok.key] and total == 1
    assert items[0] == {"key": ok.key, "title": "Platform Engineer", "company": "initech",
                        "url": "https://boards.example/1", "fit": None, "pay": "$150K–$190K", "place": "Remote"}


def test_a_copy_of_a_job_you_already_applied_to_is_left_out(cfg, store):
    store.add("Globex", "Staff Platform Engineer", status="applied", applied="2026-03-09")  # found elsewhere
    again = job("2", title="Staff Platform Engineer", company="globex")
    land(store, [again, job("3", title="Staff Data Engineer", company="globex")])
    items, total = morning.pick(cfg, store, NOW - timedelta(days=1))
    assert [i["title"] for i in items] == ["Staff Data Engineer"] and total == 1


def test_the_best_fit_comes_first_and_shows_its_score(cfg, store):
    a, b, c = job("1", title="Platform Engineer"), job("2", title="Staff Platform Engineer"), job("3", title="SRE")
    land(store, [a, b, c])
    score(cfg, store, a, 62)
    score(cfg, store, b, 91)
    items, total = morning.pick(cfg, store, NOW - timedelta(days=1))
    assert [(i["key"], i["fit"]) for i in items[:2]] == [(b.key, 91), (a.key, 62)] and total == 3
    assert [i["fit"] for i in items] == [91, 62, None]
    assert morning.pick(cfg, store, NOW - timedelta(days=1), limit=2)[1] == 3


def test_the_notification_names_the_top_matches_with_fit_or_pay():
    items = [{"title": "Staff Platform Engineer", "company": "Globex", "fit": 91, "pay": "", "place": "Remote"},
             {"title": "Platform Engineer", "company": "Initech", "fit": None, "pay": "$150K–$190K", "place": ""},
             {"title": "SRE", "company": "Umbrella", "fit": None, "pay": "", "place": "Denver, CO"},
             {"title": "Analyst", "company": "Hooli", "fit": None, "pay": "", "place": ""}]
    assert morning.summary(items, 4, 3) == ("jobwatch: 4 new matches", "\n".join([
        "Staff Platform Engineer, Globex (91/100 fit)", "Platform Engineer, Initech ($150K–$190K)",
        "SRE, Umbrella (Denver, CO)", "+1 more"]))
    assert morning.summary(items[:1], 1, 3) == ("jobwatch: 1 new match", "Staff Platform Engineer, Globex (91/100 fit)")


def test_a_run_shows_one_notification_and_saves_the_digest(cfg, store, shown):
    land(store, [job("1"), job("2", title="SRE")])
    out = morning.run(cfg, store, now=NOW, port=9000, show=shown)
    (title, body, url), = shown.calls
    assert title == "jobwatch: 2 new matches" and "Platform Engineer, initech ($150K–$190K)" in body
    assert url == f"http://jobwatch.localhost:9000/digest/{store.secret('digest')}" and out.startswith(title)
    saved = store.morning_digest()
    assert saved["day"] == "2026-03-16" and saved["at"] == NOW and len(saved["items"]) == 2
    log = store.activity(kind="boards")[0]
    assert log["text"] == "Morning digest: 2 new matches" and log["by"] == "cli"


def test_a_quiet_morning_shows_nothing_and_a_second_run_counts_from_the_first(cfg, store, shown):
    assert morning.run(cfg, store, now=NOW, show=shown) == "No new matches since the last digest."
    assert shown.calls == [] and store.morning_digest()["items"] == []
    land(store, [job("1")], at=NOW + timedelta(hours=1))
    later = NOW + timedelta(hours=6)
    assert morning.run(cfg, store, now=later, show=shown).startswith("jobwatch: 1 new match")
    assert morning.run(cfg, store, now=later + timedelta(hours=1), show=shown) == \
        "No new matches since the last digest."
    assert len(shown.calls) == 1


def test_the_first_digest_looks_back_a_day_and_none_looks_back_more_than_three(cfg, store, shown):
    land(store, [job("1")], at=NOW - timedelta(hours=30))
    assert morning.run(cfg, store, now=NOW, dry_run=True).startswith("No new")
    store.save_morning_digest("2026-03-01", [], at=NOW - timedelta(days=15))
    land(store, [job("2", title="SRE")], at=NOW - timedelta(days=4))
    land(store, [job("3", title="Data Engineer")], at=NOW - timedelta(days=2))
    out = morning.run(cfg, store, now=NOW, show=shown)
    assert "Data Engineer" in out and "SRE" not in out


def test_the_scheduled_digest_runs_once_a_day_and_not_when_off(tmp_path, shown):
    cfg = write(tmp_path)
    store = Store(cfg.state)
    land(store, [job("1")])
    assert morning.run(cfg, store, scheduled=True, now=NOW, show=shown).startswith("jobwatch: 1 new match")
    assert store.activity(kind="boards")[0]["by"] == "schedule"
    land(store, [job("2", title="SRE")], at=NOW + timedelta(hours=1))
    assert morning.run(cfg, store, scheduled=True, now=NOW + timedelta(hours=6), show=shown) == \
        "Today's digest was already made."
    assert len(shown.calls) == 1
    off = write(tmp_path, morning={"notify": False})
    assert morning.run(off, store, scheduled=True, now=NOW + timedelta(days=1), show=shown) == \
        "The morning digest is off."
    assert morning.run(off, store, now=NOW + timedelta(days=1), show=shown).startswith("jobwatch: 1 new match")
    store.close()


def test_a_notification_that_fails_is_tried_again_by_the_next_check(cfg, store):
    land(store, [job("1")])

    def broken(title, body, url):
        raise closed_notice.NoticeError("osascript failed: not allowed")

    with pytest.raises(closed_notice.NoticeError, match="not allowed"):
        morning.run(cfg, store, scheduled=True, now=NOW, show=broken)
    assert store.morning_digest() is None


def test_a_dry_run_prints_and_saves_nothing_and_does_not_wait(cfg, store, shown):
    land(store, [job("1")])
    waited = []
    out = morning.run(cfg, store, now=NOW, dry_run=True, show=shown, wait=lambda: waited.append(1))
    assert out.startswith("Would say:\njobwatch: 1 new match") and shown.calls == [] and waited == []
    assert store.morning_digest() is None


def test_the_scorer_is_waited_for_so_the_scores_are_in(cfg, store, shown):
    j = job("1")
    land(store, [j])
    morning.run(cfg, store, now=NOW, show=shown, wait=lambda: score(cfg, store, j, 88))
    assert "(88/100 fit)" in shown.calls[0][1]


def test_terminal_notifier_opens_the_page_on_a_click(monkeypatch):
    ran = []
    monkeypatch.setattr(morning.sys, "platform", "darwin")
    monkeypatch.setattr(morning.shutil, "which", lambda name: "/opt/homebrew/bin/terminal-notifier")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: ran.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    morning.notify("jobwatch: 1 new match", "SRE, Umbrella", "http://jobwatch.localhost:8765/digest/abc")
    cmd, = ran
    assert cmd[0].endswith("terminal-notifier") and cmd[cmd.index("-open") + 1].endswith("/digest/abc")
    assert cmd[cmd.index("-title") + 1] == "jobwatch: 1 new match" and cmd[cmd.index("-message") + 1] == "SRE, Umbrella"


def test_without_terminal_notifier_osascript_shows_the_text(monkeypatch):
    ran = []
    monkeypatch.setattr(morning.sys, "platform", "darwin")
    monkeypatch.setattr(closed_notice.sys, "platform", "darwin")
    monkeypatch.setattr(morning.shutil, "which", lambda name: None)
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: ran.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    morning.notify('jobwatch: "1" new match', "SRE, Umbrella", "http://x/digest/abc")
    cmd, = ran
    assert cmd[0] == "osascript" and cmd[-2:] == ["SRE, Umbrella", 'jobwatch: "1" new match']
    assert "http://x/digest/abc" not in " ".join(cmd)   # the text goes in as arguments, never into the script


def test_a_failing_tool_and_a_computer_that_isnt_a_mac_are_notice_errors(monkeypatch):
    monkeypatch.setattr(morning.sys, "platform", "linux")
    with pytest.raises(closed_notice.NoticeError, match="macOS only"):
        morning.notify("t", "b")
    monkeypatch.setattr(morning.sys, "platform", "darwin")
    monkeypatch.setattr(morning.shutil, "which", lambda name: "/bin/tn")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "denied"))
    with pytest.raises(closed_notice.NoticeError, match="terminal-notifier failed: denied"):
        morning.notify("t", "b")


def test_the_page_lists_the_matches_with_links_and_escapes_everything(store):
    items = [{"key": "k1", "title": "Staff <b>Engineer</b>", "company": "Glo&bex",
              "url": "https://x.example/1?a=1&b=2", "fit": 91, "pay": "", "place": "Remote"},
             {"key": "k2", "title": "SRE", "company": "Umbrella", "url": "javascript:alert(1)", "fit": None,
              "pay": "$150K", "place": ""},
             {"key": "k3", "title": "Analyst", "company": "Hooli", "url": "https://x.example/3", "fit": 40,
              "pay": "", "place": ""}]
    store.save_morning_digest("2026-03-16", items, 5, NOW)
    html = morning.page(store.morning_digest())
    assert "<h1>5 new matches</h1>" in html and "+2 more on Today" in html and "2026-03-16" in html
    assert 'href="https://x.example/1?a=1&amp;b=2"' in html and "Staff &lt;b&gt;Engineer&lt;/b&gt;" in html
    assert "Glo&amp;bex" in html and "javascript:" not in html and "<b>Engineer" not in html
    assert '<span class="fit">91/100 fit</span>' in html and '<span class="fit lo">40/100 fit</span>' in html
    assert 'id="theme-system"' in html and 'id="width-wide"' in html and "<script" not in html


def test_the_page_before_any_digest_says_so():
    html = morning.page(None)
    assert "<h1>0 new matches</h1>" in html and "No new matches yet" in html


@pytest.fixture
def popped(monkeypatch):
    """`morning.notify` faked, wherever it is called from: what it was asked to show."""
    calls = []
    monkeypatch.setattr(morning, "notify", lambda title, body, url="": calls.append((title, body, url)))
    return calls


def test_the_command_tells_you_the_new_matches_and_writes_the_page(tmp_path, popped, capsys):
    cfg = write(tmp_path)
    store = Store(cfg.state)
    land(store, [job("1"), job("2", title="SRE")], at=datetime.now(UTC) - timedelta(hours=2))
    cli.main(["-c", str(cfg.path), "digest", "--notify", "--dry-run"])
    assert capsys.readouterr().out.startswith("Would say:\njobwatch: 2 new matches") and popped == []
    page = tmp_path / "digest.html"
    cli.main(["-c", str(cfg.path), "digest", "--notify", "-o", str(page)])
    out = capsys.readouterr()
    assert out.out.startswith("jobwatch: 2 new matches") and len(popped) == 1 and "Wrote" in out.err
    assert "<h1>2 new matches</h1>" in page.read_text() and "Platform Engineer" in page.read_text()
    cli.main(["-c", str(cfg.path), "digest", "--notify"])
    assert capsys.readouterr().out == "No new matches since the last digest.\n" and len(popped) == 1
    assert store.find(job("1").key)[1]["status"] == "new"   # nothing was marked shown
    store.close()


def test_the_command_says_plainly_when_no_notification_can_be_shown(tmp_path, monkeypatch):
    cfg = write(tmp_path)
    store = Store(cfg.state)
    land(store, [job("1")], at=datetime.now(UTC) - timedelta(hours=2))
    store.close()
    monkeypatch.setattr(morning.sys, "platform", "linux")
    with pytest.raises(SystemExit, match="macOS only"):
        cli.main(["-c", str(cfg.path), "digest", "--notify"])


def test_a_scheduled_check_that_read_a_board_runs_the_digest_once_a_day(tmp_path, popped):
    cfg = write(tmp_path)
    store = Store(cfg.state)
    land(store, [job("1")], at=datetime.now(UTC) - timedelta(hours=2))
    store.close()
    app = App(cfg.path, background=False)
    assert app.refresher.after_scheduled({"boards": 0}) is None
    app.refresher.after_scheduled({"boards": 3}).join(10)
    assert [t for t, *_ in popped] == ["jobwatch: 1 new match"]
    app.refresher.after_scheduled({"boards": 3}).join(10)   # the afternoon's check: nothing more to say today
    assert len(popped) == 1


def test_a_digest_that_cant_be_shown_never_takes_the_page_down(tmp_path, monkeypatch, capsys):
    cfg = write(tmp_path)
    store = Store(cfg.state)
    land(store, [job("1")], at=datetime.now(UTC) - timedelta(hours=2))
    store.close()

    def refuse(title, body, url=""):
        raise closed_notice.NoticeError("osascript failed: not allowed")

    monkeypatch.setattr(morning, "notify", refuse)
    assert App(cfg.path, background=False).morning_digest() is None
    assert "the morning digest failed: NoticeError: osascript failed: not allowed" in capsys.readouterr().err


def test_the_digest_page_is_served_at_a_secret_address(server, watchlist):
    store = Store(config.load(watchlist).state)
    store.save_morning_digest("2026-03-16", [{"key": "k", "title": "SRE <i>", "company": "Umbrella",
                                              "url": "https://x.example/1", "fit": 77, "pay": "", "place": ""}], 1, NOW)
    secret = store.secret("digest")
    store.close()
    status, body, headers = request(server, "GET", f"/digest/{secret}", with_headers=True)
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert b"<h1>1 new match</h1>" in body and b"77/100 fit" in body and b"SRE &lt;i&gt;" in body
    for bad in ("/digest/wrong", "/digest/", f"/digest/{secret}x", f"/digest/{secret[:-1]}"):
        assert request(server, "GET", bad)[0] == 404
    assert request(server, "GET", f"/digest/{secret}", host="evil.example")[0] == 403
