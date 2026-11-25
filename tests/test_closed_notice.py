"""Closed-posting notices: which closed postings become one, the daily popup's text, the command, the launchd job and
the page's endpoints. The popup and launchctl are faked: these tests never show a notification or touch launchd."""

import plistlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from jobwatch import closed_notice, config, watch
from jobwatch.cli import main
from jobwatch.web import ApiError, App


@pytest.fixture
def cfg(watchlist):
    return config.load(watchlist)


@pytest.fixture
def store(cfg):
    from jobwatch.store import Store
    s = Store(cfg.state)
    yield s
    s.close()


def close(store, job, days_ago: float = 0, confirmed: bool = True):
    """Mark a job's posting closed, `days_ago` days back, and (unless `confirmed` is off) seen closed again."""
    store.set_closed(job.key, True)
    stamp = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat(timespec="microseconds")
    store.db.execute("UPDATE jobs SET closed=? WHERE key=?", (stamp, job.key))
    store.db.commit()
    if confirmed:
        store.confirm_closed([job.key])


@pytest.fixture(autouse=True)
def postings_still_closed(monkeypatch):
    """The popup looks at each posting once more before telling (verify); here, with no network, every one is still
    closed. tests/test_closed_evidence.py covers the real look."""
    monkeypatch.setattr(closed_notice, "verify", lambda store, keys, *a, **k: [
        SimpleNamespace(job=store.find(k)[0], result="closed", detail="") for k in keys])


@pytest.fixture
def shown():
    """A popup that records what it was asked to show."""
    out = []
    out_fn = lambda title, body: out.append((title, body))  # noqa: E731
    out_fn.calls = out
    return out_fn


def test_applications_and_queued_jobs_get_a_notice_and_nothing_else_does(store):
    applied = store.add("Initech", "Principal Architect", status="applied")
    queued = store.add("Globex", "Staff Engineer", status="queued")
    shown_job = store.add("Umbrella", "Data Engineer", status="shown")
    new_job = store.add("Acme", "SRE", status="new")
    skipped = store.add("Hooli", "PM", status="skipped")
    rejected = store.add("Pied Piper", "Compression Engineer", status="rejected")
    for j in (applied, queued, shown_job, new_job, skipped, rejected):
        close(store, j)
    assert set(closed_notice.collect(store)) == {applied.key, queued.key}
    assert {n["key"] for n in closed_notice.unseen(store)} == {applied.key, queued.key}


def test_a_notice_says_company_title_status_and_the_day_it_closed(store):
    j = store.add("Initech", "Principal Architect", status="interviewing")
    close(store, j, days_ago=2)
    closed_notice.collect(store)
    [n] = closed_notice.unseen(store)
    assert (n["company"], n["title"], n["status"], n["application"]) == ("Initech", "Principal Architect",
                                                                           "interviewing", True)
    assert n["day"] == (date.today() - timedelta(days=2)).isoformat()


def test_a_posting_closed_long_ago_is_old_news(store):
    j = store.add("Initech", "Principal Architect", status="applied")
    close(store, j, days_ago=closed_notice.WINDOW_DAYS + 3)
    assert closed_notice.collect(store) == [] and closed_notice.unseen(store) == []


def test_collecting_twice_makes_one_notice_and_a_dismissed_one_stays_dismissed(store):
    j = store.add("Initech", "Principal Architect", status="applied")
    close(store, j)
    assert closed_notice.collect(store) == [j.key] and closed_notice.collect(store) == []
    assert store.dismiss_closed_notices([j.key]) == 1 and store.dismiss_closed_notices([j.key]) == 0
    closed_notice.collect(store)
    assert closed_notice.unseen(store) == []


def test_a_posting_that_reopens_loses_its_notice_and_one_that_closes_again_is_new(store):
    j = store.add("Initech", "Principal Architect", status="applied")
    close(store, j)
    closed_notice.collect(store)
    store.dismiss_closed_notices()
    store.set_closed(j.key, False)
    closed_notice.collect(store)
    assert store.closed_notices() == []
    close(store, j)
    assert closed_notice.collect(store) == [j.key] and len(closed_notice.unseen(store)) == 1


def test_a_notice_goes_when_the_application_ends(store):
    j = store.add("Initech", "Principal Architect", status="applied")
    close(store, j)
    closed_notice.collect(store)
    store.set_status([j.key], "rejected")
    closed_notice.collect(store)
    assert closed_notice.unseen(store) == []


def test_applications_come_before_queued_jobs_then_newest_first(store):
    jobs = [("Globex", "Queued, newest", "queued", 0), ("Initech", "Applied, older", "applied", 3),
            ("Umbrella", "Applied, newer", "screening", 1), ("Acme", "Queued, older", "queued", 5)]
    for company, title, status, days in jobs:
        close(store, store.add(company, title, status=status), days_ago=days)
    closed_notice.collect(store)
    assert [n["title"] for n in closed_notice.unseen(store)] == [
        "Applied, newer", "Applied, older", "Queued, newest", "Queued, older"]


def test_the_summary_lists_three_and_counts_the_rest():
    many = [{"company": c, "title": "Engineer"} for c in ("Initech", "Globex", "Umbrella", "Acme", "Hooli")]
    assert closed_notice.summary(many) == ("jobwatch: 5 postings closed",
                                          "Initech: Engineer\nGlobex: Engineer\nUmbrella: Engineer\n+2 more")
    assert closed_notice.summary(many[:3])[1].count("\n") == 2 and "more" not in closed_notice.summary(many[:3])[1]
    assert closed_notice.summary(many[:1]) == ("jobwatch: 1 posting closed", "Initech: Engineer")


def test_the_popup_tells_each_notice_once(cfg, store, shown, monkeypatch):
    monkeypatch.setattr(watch, "check_daily", lambda *a, **k: [])
    close(store, store.add("Initech", "Principal Architect", status="applied"))
    close(store, store.add("Globex", "Staff Engineer", status="queued"))
    said = closed_notice.run(cfg, store, show=shown)
    assert shown.calls == [("jobwatch: 2 postings closed", "Initech: Principal Architect\nGlobex: Staff Engineer")]
    assert said.startswith("jobwatch: 2 postings closed")
    assert closed_notice.run(cfg, store, show=shown) == "No newly closed postings." and len(shown.calls) == 1
    assert len(closed_notice.unseen(store)) == 2  # told, but still on the page until dismissed
    close(store, store.add("Umbrella", "Data Engineer", status="applied"))
    closed_notice.run(cfg, store, show=shown)
    assert shown.calls[1] == ("jobwatch: 1 posting closed", "Umbrella: Data Engineer")


def test_the_popup_checks_the_postings_first_but_not_ones_checked_in_the_last_12_hours(cfg, store, shown, monkeypatch):
    seen = {}

    def fake(store_, get, page, watched, **kwargs):
        seen.update(kwargs)
        close(store_, store_.find("initech")[0])  # the check finds this one closed
        return []
    monkeypatch.setattr(watch, "check_daily", fake)
    store.add("Initech", "Principal Architect", status="applied")
    closed_notice.run(cfg, store, show=shown)
    assert seen == {"every": timedelta(hours=12)}
    assert shown.calls == [("jobwatch: 1 posting closed", "Initech: Principal Architect")]


def test_a_check_that_fails_still_pops_what_is_known(cfg, store, shown, monkeypatch):
    def broken(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(watch, "check_daily", broken)
    close(store, store.add("Initech", "Principal Architect", status="applied"))
    said = closed_notice.run(cfg, store, show=shown)
    assert "could not be checked (offline)" in said and len(shown.calls) == 1


def test_a_dry_run_says_what_it_would_and_checks_and_marks_nothing(cfg, store, shown, monkeypatch):
    monkeypatch.setattr(watch, "check_daily", lambda *a, **k: pytest.fail("a dry run reads no board"))
    close(store, store.add("Initech", "Principal Architect", status="applied"))
    said = closed_notice.run(cfg, store, dry_run=True, show=shown)
    assert said == "Would say:\njobwatch: 1 posting closed\nInitech: Principal Architect" and shown.calls == []
    assert len(store.closed_notices(untold=True)) == 1  # still untold


def test_the_test_popup_shows_a_sample(cfg, store, shown):
    closed_notice.run(cfg, store, test=True, show=shown)
    assert shown.calls[0][0] == "jobwatch: 2 postings closed" and "Initech" in shown.calls[0][1]


def test_a_popup_that_fails_is_not_marked_told(cfg, store, monkeypatch):
    monkeypatch.setattr(watch, "check_daily", lambda *a, **k: [])
    close(store, store.add("Initech", "Principal Architect", status="applied"))

    def refuse(title, body):
        raise closed_notice.NoticeError("osascript failed")
    with pytest.raises(closed_notice.NoticeError):
        closed_notice.run(cfg, store, show=refuse)
    assert len(store.closed_notices(untold=True)) == 1


def test_osascript_gets_the_text_as_arguments_never_inside_the_script(monkeypatch):
    seen = []
    monkeypatch.setattr(closed_notice.sys, "platform", "darwin")
    monkeypatch.setattr(closed_notice.subprocess, "run",
                        lambda cmd, **kw: seen.append(cmd) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    closed_notice.popup('jobwatch: 1 posting closed', 'Initech: The "Quote" \\ and a newline\n')
    cmd = seen[0]
    assert cmd[0] == "osascript" and cmd[-2:] == ['Initech: The "Quote" \\ and a newline\n',
                                                 'jobwatch: 1 posting closed']
    assert not any("Initech" in a for a in cmd[:-2])  # the script itself holds none of it


def test_a_failing_osascript_and_a_non_mac_say_so(monkeypatch):
    monkeypatch.setattr(closed_notice.sys, "platform", "darwin")
    monkeypatch.setattr(closed_notice.subprocess, "run",
                        lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="not allowed"))
    with pytest.raises(closed_notice.NoticeError, match="not allowed"):
        closed_notice.popup("t", "b")
    monkeypatch.setattr(closed_notice.sys, "platform", "linux")
    with pytest.raises(closed_notice.NoticeError, match="macOS only"):
        closed_notice.popup("t", "b")


def test_the_launchd_job_runs_notify_closed_daily_at_nine(tmp_path, monkeypatch):
    job = closed_notice.definition(tmp_path / "jobwatch.yaml")
    assert job["Label"] == "io.github.jobwatch.notify-closed"
    assert job["StartCalendarInterval"] == {"Hour": 9, "Minute": 0}
    assert job["ProgramArguments"][-1] == "notify-closed" and "-c" in job["ProgramArguments"]
    calls = []
    monkeypatch.setattr(closed_notice, "plist_path", lambda: tmp_path / "job.plist")
    monkeypatch.setattr(closed_notice, "log_path", lambda: tmp_path / "logs" / "job.log")
    monkeypatch.setattr(closed_notice, "_mac", lambda: None)
    monkeypatch.setattr(closed_notice, "_launchctl", lambda *a, **k: calls.append(a))
    assert closed_notice.install(tmp_path / "jobwatch.yaml") == "daily at 9:00"
    assert plistlib.loads((tmp_path / "job.plist").read_bytes())["Label"] == closed_notice.LABEL
    assert [c[0] for c in calls] == ["bootout", "bootstrap"]
    assert closed_notice.uninstall() is True and not (tmp_path / "job.plist").exists()
    assert closed_notice.uninstall() is False


def test_the_command_dry_run_and_clear_which_leaves_the_applications_alone(cfg, store, capsys):
    j = store.add("Initech", "Principal Architect", status="applied")
    close(store, j)
    main(["-c", str(cfg.path), "notify-closed", "--dry-run"])
    assert "Would say:\njobwatch: 1 posting closed\nInitech: Principal Architect" in capsys.readouterr().out
    main(["-c", str(cfg.path), "notify-closed", "--clear"])
    assert "Cleared 1 closed-posting notices (your applications are unchanged)" in capsys.readouterr().out
    assert store.find(j.key)[1]["status"] == "applied"  # still tracked, as it was
    main(["-c", str(cfg.path), "notify-closed", "--dry-run"])
    assert "No newly closed postings." in capsys.readouterr().out


def test_dismiss_still_works_as_another_name_for_clear(cfg, store, capsys):
    close(store, store.add("Initech", "Principal Architect", status="applied"))
    main(["-c", str(cfg.path), "notify-closed", "--dismiss"])
    assert "Cleared 1 closed-posting notices" in capsys.readouterr().out


def test_the_strip_says_got_it_explains_itself_and_marks_live_applications():
    page = (Path(closed_notice.__file__).parent / "static" / "index.html").read_text()
    strip = page[page.index("function closedStrip"):page.index("const LIVE_STAGES")]
    assert '"Got it, all"' in strip and '"Got it"' in strip and "Dismiss" not in strip
    assert "Clearing a notice only hides it here. Nothing is removed or changed in your applications." in strip
    assert "Clears this notice. The application stays tracked." in strip
    assert 'LIVE_STAGES.includes(n.status)' in strip and '["screening", "interviewing"]' in page


def test_the_command_install_only_sets_the_daily_job_up_and_tells_nothing(cfg, store, capsys, monkeypatch):
    close(store, store.add("Initech", "Principal Architect", status="applied"))
    monkeypatch.setattr(closed_notice, "install", lambda config: "daily at 9:00")
    monkeypatch.setattr(closed_notice, "popup", lambda *a: pytest.fail("installing pops nothing up"))
    main(["-c", str(cfg.path), "notify-closed", "--install"])
    assert "daily at 9:00 (io.github.jobwatch.notify-closed)" in capsys.readouterr().out
    assert closed_notice.collect(store) == [store.find("initech")[0].key]  # nothing was collected or told yet


def test_the_page_lists_the_notices_marks_the_cards_and_dismisses(cfg, store):
    a = store.add("Initech", "Principal Architect", status="applied")
    q = store.add("Globex", "Staff Engineer", status="queued")
    old = store.add("Acme", "SRE", status="applied")
    close(store, a, days_ago=2)
    close(store, q)
    close(store, old, days_ago=40)
    app = App(cfg.path)
    got = app.get_applications({})
    assert [(n["company"], n["application"]) for n in got["closed_notices"]] == [("Initech", True), ("Globex", False)]
    cards = {c["company"]: c for c in got["applications"]}
    assert cards["Initech"]["closed_new"] and cards["Initech"]["closed_day"] == \
        (date.today() - timedelta(days=2)).isoformat()
    assert not cards["Acme"]["closed_new"] and cards["Acme"]["closed_day"]  # closed, but long ago: the date only
    assert app.post_closed_dismiss({"key": a.key}) == {"dismissed": 1}
    assert [n["company"] for n in app.get_applications({})["closed_notices"]] == ["Globex"]
    assert app.post_closed_dismiss({"all": True}) == {"dismissed": 1}
    assert app.get_applications({})["closed_notices"] == []
    with pytest.raises(ApiError):
        app.post_closed_dismiss({})


# -- Closed by company: a real, ended status, and the strip's buttons that set it (or skip a queued job)

def test_closed_is_a_real_ended_status_that_every_list_knows():
    from jobwatch import store as store_module
    assert "closed" in store_module.STATUSES and "closed" in store_module.STAGES and "closed" in store_module.ENDED
    assert "closed" not in store_module.IN_PROGRESS and "closed" not in store_module.OPEN
    page = (Path(closed_notice.__file__).parent / "static" / "index.html").read_text()
    assert 'closed: "Closed by company"' in page and "--s-closed" in page
    assert 's === "closed"' in page  # isEndedStatus: it leaves the live lists with rejected and withdrawn


def test_mark_closed_works_from_the_command_and_validates_the_status(cfg, store, capsys):
    j = store.add("Initech", "Principal Architect", status="applied")
    main(["-c", str(cfg.path), "mark", "closed", j.key])
    assert store.find(j.key)[1]["status"] == "closed"
    with pytest.raises(SystemExit):
        main(["-c", str(cfg.path), "mark", "gone", j.key])
    with pytest.raises(ValueError, match="status must be one of"):
        store.add("Globex", "Staff Engineer", status="gone")
    with pytest.raises(ApiError, match="status must be one of"):
        App(cfg.path).post_track({"key": j.key, "status": "gone"})


def test_a_closed_application_leaves_the_live_lists_and_the_page_counts_it(cfg, store):
    live = store.add("Globex", "Staff Engineer", status="interviewing", follow_up="2026-03-18")
    ended = store.add("Initech", "Principal Architect", status="applied", follow_up="2026-03-18")
    store.set_status([ended.key], "closed")
    got = App(cfg.path).get_applications({})
    assert "closed" in got["stages"]
    by_status = {}
    for a in got["applications"]:
        by_status[a["status"]] = by_status.get(a["status"], 0) + 1
    assert by_status == {"interviewing": 1, "closed": 1}  # the chip counts the page draws
    assert next(a["key"] for a in got["applications"]) == live.key  # open ones first, the ended one last
    from jobwatch import quiet, report
    assert not report.due(store.find(ended.key)[1]) and not quiet.find([store.find(ended.key)], cfg.quiet)


def test_only_applied_and_queued_rows_have_an_action_live_ones_have_none(store):
    for company, status in (("Initech", "applied"), ("Globex", "queued"), ("Umbrella", "screening"),
                            ("Acme", "interviewing"), ("Hooli", "offer")):
        close(store, store.add(company, "Engineer", status=status))
    closed_notice.collect(store)
    assert {n["company"]: n["action"] for n in closed_notice.unseen(store)} == {
        "Initech": "close", "Globex": "skip", "Umbrella": None, "Acme": None, "Hooli": None}


def test_closed_by_company_sets_the_status_adds_the_dated_note_and_clears_the_notice(store):
    j = store.add("Initech", "Principal Architect", status="applied", note="2026-03-01: Applied on the site")
    close(store, j, days_ago=2)
    closed_notice.collect(store)
    [undo] = closed_notice.act(store, "close", [j.key])
    rec = store.find(j.key)[1]
    day = (date.today() - timedelta(days=2)).isoformat()
    assert rec["status"] == "closed"
    assert rec["note"] == f"2026-03-01: Applied on the site {date.today().isoformat()}: Posting closed {day}: " \
                          "closed by company"
    assert closed_notice.unseen(store) == [] and undo["status"] == "applied"


def test_skip_sets_a_queued_job_to_skipped_with_its_note(store):
    j = store.add("Globex", "Staff Engineer", status="queued")
    close(store, j)
    closed_notice.collect(store)
    closed_notice.act(store, "skip", [j.key])
    rec = store.find(j.key)[1]
    assert rec["status"] == "skipped" and f"Posting closed {date.today().isoformat()}: skipped" in rec["note"]
    assert closed_notice.unseen(store) == []


def test_a_live_application_cant_be_closed_or_skipped_through_the_strip(store):
    live = store.add("Umbrella", "Engineer", status="screening")
    close(store, live)
    closed_notice.collect(store)
    for action in ("close", "skip"):
        with pytest.raises(ValueError, match="only applies to"):
            closed_notice.act(store, action, [live.key])
    assert closed_notice.act(store, "close") == []  # in bulk, live rows are simply not touched
    assert store.find(live.key)[1]["status"] == "screening" and len(closed_notice.unseen(store)) == 1
    with pytest.raises(ValueError, match="no closed-posting notice"):
        closed_notice.act(store, "close", ["manual:nobody:nothing"])
    with pytest.raises(ValueError, match="action must be one of"):
        closed_notice.act(store, "withdraw", [live.key])


def test_closed_by_company_for_all_applied_leaves_live_and_queued_rows_alone(store):
    jobs = {c: store.add(c, "Engineer", status=s) for c, s in (
        ("Initech", "applied"), ("Globex", "applied"), ("Umbrella", "interviewing"), ("Acme", "queued"))}
    for j in jobs.values():
        close(store, j)
    closed_notice.collect(store)
    undo = closed_notice.act(store, "close")
    assert {u["key"] for u in undo} == {jobs["Initech"].key, jobs["Globex"].key}
    assert {c: store.find(j.key)[1]["status"] for c, j in jobs.items()} == {
        "Initech": "closed", "Globex": "closed", "Umbrella": "interviewing", "Acme": "queued"}
    assert {n["company"] for n in closed_notice.unseen(store)} == {"Umbrella", "Acme"}


def test_undo_puts_back_the_status_the_note_and_the_notice(store):
    j = store.add("Initech", "Principal Architect", status="applied", note="2026-03-01: Applied on the site")
    close(store, j)
    closed_notice.collect(store)
    undo = closed_notice.act(store, "close", [j.key])
    assert closed_notice.undo(store, undo) == 1
    rec = store.find(j.key)[1]
    assert rec["status"] == "applied" and rec["note"] == "2026-03-01: Applied on the site"
    assert [n["key"] for n in closed_notice.unseen(store)] == [j.key]  # showing again
    q = store.add("Globex", "Staff Engineer", status="queued")  # a queued job had no note at all
    close(store, q)
    closed_notice.collect(store)
    closed_notice.undo(store, closed_notice.act(store, "skip", [q.key]))
    assert store.find(q.key)[1]["status"] == "queued" and not store.find(q.key)[1]["note"]
    with pytest.raises(ValueError, match="undo needs"):
        closed_notice.undo(store, [{"key": q.key, "status": "gone", "note": ""}])


def test_the_page_endpoints_act_and_undo(cfg, store):
    a = store.add("Initech", "Principal Architect", status="applied")
    q = store.add("Globex", "Staff Engineer", status="queued")
    s = store.add("Umbrella", "Engineer", status="screening")
    for j in (a, q, s):
        close(store, j)
    app = App(cfg.path)
    notices = {n["company"]: n["action"] for n in app.get_applications({})["closed_notices"]}
    assert notices == {"Initech": "close", "Globex": "skip", "Umbrella": None}
    done = app.post_closed_act({"action": "close", "key": a.key})
    assert done["done"] == 1 and store.find(a.key)[1]["status"] == "closed"
    with pytest.raises(ApiError, match="only applies to"):
        app.post_closed_act({"action": "close", "key": s.key})
    with pytest.raises(ApiError):
        app.post_closed_act({"action": "close"})
    assert app.post_closed_undo({"undo": done["undo"]}) == {"restored": 1}
    assert store.find(a.key)[1]["status"] == "applied"
    assert app.post_closed_act({"action": "close", "all": True})["done"] == 1  # Initech only: not Globex, not Umbrella
    with pytest.raises(ApiError, match="undo needs"):
        app.post_closed_undo({"undo": [{"key": a.key, "status": "nope"}]})


def test_the_strip_asks_inline_offers_undo_for_eight_seconds_and_has_no_button_for_live_rows():
    page = (Path(closed_notice.__file__).parent / "static" / "index.html").read_text()
    strip = page[page.index("function closedStrip"):page.index("const LIVE_STAGES")]
    for text in ("Closed by company, all applied", "Skip this job? You can change the status back.", "n.action ?",
                 "Mark this application Closed by company? You can change the status back.", '"Undo", 8000',
                 "/api/closed/undo"):
        assert text in strip, text
    assert "confirm(" in strip and "window.confirm" not in strip  # an inline question, not a browser dialog
    assert "ms = 6000" in page  # toast's new length argument
