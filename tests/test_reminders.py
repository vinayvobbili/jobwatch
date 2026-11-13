"""Follow-up days in Apple Reminders: what is asked of osascript (stubbed), when it is and isn't, and that a failure
never gets in the way."""

import json
import subprocess
from datetime import datetime

import pytest

from jobwatch import cli, config, reminders
from jobwatch.store import Store
from jobwatch.web import ApiError, App

from .conftest import TOKEN  # noqa: F401  (keeps the shared fixtures importable)


class Osascript:
    """Stands in for osascript: records each script's ARGS and answers like the JXA would."""

    def __init__(self):
        self.calls = []
        self.reply = {"created": 0, "moved": 0, "deleted": 0, "kept": 0}
        self.fail = None

    def __call__(self, cmd, **kw):
        assert cmd[:3] == ["osascript", "-l", "JavaScript"]
        script = cmd[-1]
        line = next(x for x in script.splitlines() if x.startswith("const ARGS = "))
        self.calls.append(json.loads(line[len("const ARGS = "):].rstrip(";")))
        if self.fail:
            return self.fail
        return subprocess.CompletedProcess(cmd, 0, json.dumps(self.reply), "")


@pytest.fixture
def osa(monkeypatch):
    fake = Osascript()
    monkeypatch.setattr(reminders.subprocess, "run", fake)
    monkeypatch.setattr(reminders.sys, "platform", "darwin")
    monkeypatch.setattr(reminders, "_warned", False)
    return fake


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state.db")
    yield s
    s.close()


def cfg_with(follow_ups="reminders"):
    return config.Config(path=None, boards=[], follow_ups=follow_ups)


def add(store, company="Initech", title="Platform Engineer", follow_up="2026-11-20", **kw):
    """An applied job with a day and a next step, so it qualifies; next_step="" makes it a plain applied one."""
    url = f"https://jobs.{company.lower()}.example/1"
    kw.setdefault("next_step", "check for a reply")
    return store.add(company, title, url=url, follow_up=follow_up, **kw).key


def test_a_follow_up_makes_one_reminder_with_its_marker(store, osa):
    key = add(store, next_step="ask about the panel")
    reminders.refresh(cfg_with(), store, [key])
    (call,) = osa.calls
    (it,) = call["items"]
    assert it["key"] == key and it["title"] == "Follow up: Initech — Platform Engineer"
    assert it["due"] == int(datetime(2026, 11, 20, 9, 0).timestamp())
    assert it["notes"].splitlines() == ["ask about the panel", "https://jobs.initech.example/1", f"jobwatch:{key}"]
    assert call["drop"] == [] and call["prune"] is False


def test_moving_the_day_sends_the_new_due_time_for_the_same_key(store, osa):
    key = add(store)
    reminders.refresh(cfg_with(), store, [key])
    store.track(key, follow_up="2026-11-25")
    reminders.refresh(cfg_with(), store, [key])
    first, second = (c["items"][0] for c in osa.calls)
    assert first["key"] == second["key"] and second["due"] > first["due"]


def test_clearing_the_day_drops_the_reminder(store, osa):
    key = add(store)
    store.track(key, follow_up="")
    reminders.refresh(cfg_with(), store, [key])
    assert osa.calls[0]["items"] == [] and osa.calls[0]["drop"] == [key]


@pytest.mark.parametrize("status", ["rejected", "withdrawn"])
def test_closing_an_application_drops_its_reminder(store, osa, status):
    key = add(store)
    store.set_status([key], status)
    reminders.refresh(cfg_with(), store, [key])
    assert osa.calls[0]["items"] == [] and osa.calls[0]["drop"] == [key]


@pytest.mark.parametrize("status", ["screening", "interviewing", "offer"])
def test_a_stage_that_keeps_its_day_keeps_its_reminder(store, osa, status):
    key = add(store)
    store.set_status([key], status)
    reminders.refresh(cfg_with(), store, [key])
    assert [i["key"] for i in osa.calls[0]["items"]] == [key]


def test_a_live_stage_with_a_day_qualifies_without_a_next_step(store, osa):
    key = add(store, next_step="")
    store.set_status([key], "interviewing")
    reminders.refresh(cfg_with(), store, [key])
    assert [i["key"] for i in osa.calls[0]["items"]] == [key]


def test_a_next_step_with_a_day_qualifies_at_applied(store, osa):
    key = add(store, next_step="nudge")
    reminders.refresh(cfg_with(), store, [key])
    assert [i["key"] for i in osa.calls[0]["items"]] == [key]


def test_a_plain_applied_one_with_only_a_day_has_none(store, osa):
    key = add(store, next_step="")
    reminders.refresh(cfg_with(), store, [key])
    assert osa.calls[0]["items"] == [] and osa.calls[0]["drop"] == [key]


def test_a_next_step_without_a_day_has_none(store, osa):
    key = add(store, follow_up="")
    reminders.refresh(cfg_with(), store, [key])
    assert osa.calls[0]["items"] == [] and osa.calls[0]["drop"] == [key]


def test_a_snoozed_applied_one_has_none_and_loses_its_reminder(store, osa):
    key = add(store)
    store.snooze(key, 7)
    reminders.refresh(cfg_with(), store, [key])
    assert osa.calls[0]["items"] == [] and osa.calls[0]["drop"] == [key]


@pytest.mark.parametrize("status", ["screening", "interviewing", "offer"])
def test_a_snoozed_live_one_keeps_its_reminder(store, osa, status):
    key = add(store, next_step="Wait for the recruiter")
    store.set_status([key], status)
    until = store.snooze(key, 7)
    reminders.refresh(cfg_with(), store, [key])
    assert osa.calls[0]["items"][0]["due"] == reminders.due_epoch(until)


@pytest.mark.parametrize("text", [
    "Wait for recruiter; if they ask about the COI, answer", "waiting on Varun", "  Await the screen", "Awaiting word",
    "Passive: nothing to do", "No action", "no action until they write", "Expect to hear back by Friday",
    "None; let it go unless they reach out", "", None])
def test_a_waiting_next_step_is_not_something_to_do(text):
    assert reminders.waiting(text)


@pytest.mark.parametrize("text", [
    "Follow up if no reply", "check for a reply", "nudge", "Recruiter screen; ask about pay early",
    "Follow up with Dana if no word", "check for a reply; follow up through Pooja if none",
    "Email the recruiter, then wait a day", "Prepare for the waitlist call"])
def test_an_action_next_step_is_something_to_do(text):
    assert not reminders.waiting(text)


def test_an_applied_one_waiting_has_no_reminder_but_an_action_has(store, osa):
    waits = add(store, next_step="Wait for the recruiter")
    acts = add(store, "Globex", "Data Engineer", next_step="Follow up if no reply")
    reminders.sync(cfg_with(), store)
    assert [i["key"] for i in osa.calls[0]["items"]] == [acts] and waits != acts


def test_reminders_all_keeps_the_old_rule(store, osa):
    plain = add(store, next_step="")
    asleep = add(store, "Globex", "Data Engineer")
    until = store.snooze(asleep, 7)
    reminders.refresh(cfg_with("reminders-all"), store, [plain, asleep])
    items = {i["key"]: i for i in osa.calls[0]["items"]}
    assert set(items) == {plain, asleep} and items[asleep]["due"] == reminders.due_epoch(until)
    assert reminders.sync(cfg_with("reminders-all"), store) is not None


def test_a_queued_job_has_no_reminder(store, osa):
    key = add(store, status="queued")
    reminders.refresh(cfg_with(), store, [key])
    assert osa.calls[0]["items"] == [] and osa.calls[0]["drop"] == [key]


def test_sync_sends_every_open_follow_up_and_prunes_the_rest(store, osa):
    a, b = add(store), add(store, "Globex", "Data Engineer", "2026-11-22")
    add(store, "Umbrella", "SRE", "")
    add(store, "Soylent", "DBA", "2026-11-23", next_step="")
    ended = add(store, "Hooli", "QA", "2026-11-21")
    store.set_status([ended], "rejected")
    osa.reply = {"created": 2, "moved": 0, "deleted": 1, "kept": 0}
    assert reminders.sync(cfg_with(), store) == osa.reply
    (call,) = osa.calls
    assert sorted(i["key"] for i in call["items"]) == sorted([a, b]) and call["prune"] is True


def test_sync_twice_asks_for_the_same_thing(store, osa):
    add(store), add(store, "Globex", "Data Engineer", "2026-11-22")
    reminders.sync(cfg_with(), store)
    reminders.sync(cfg_with(), store)
    assert osa.calls[0] == osa.calls[1]


def test_the_script_finds_reminders_by_the_marker_and_only_those(store, osa):
    script = reminders.build_script(reminders.SYNC_BODY, {"items": [], "drop": [], "prune": True})
    assert "_contains: 'jobwatch:'" in script and r"/^jobwatch:(\S+)$/m" in script
    # nothing outside `found` is ever deleted, moved or created over: no unmarked reminder is reachable
    assert script.count("app.delete(") == 2 and "found[" in script and "app.delete(h.r)" in script


def test_sync_deletes_by_marker_what_no_longer_qualifies(store, osa):
    key = add(store)
    store.track(key, next_step="")  # no longer has a next step
    reminders.sync(cfg_with(), store)
    reminders.refresh(cfg_with(), store, [key])
    assert osa.calls[0]["items"] == [] and osa.calls[0]["prune"] is True  # prune deletes every marked key not wanted
    assert osa.calls[1]["drop"] == [key]
    body = reminders.SYNC_BODY
    assert "app.delete(h.r)" in body and "found[key]" in body and "completed = true" not in body


def test_the_script_holds_reminders_by_id_not_by_position():
    # a whose-query's q[i] is re-evaluated at each use, so deleting one shifts the rest onto the wrong reminders
    assert "q[i]" not in reminders.SYNC_BODY and "byId(ids[i])" in reminders.SYNC_BODY


def test_one_a_person_finished_for_the_same_day_is_not_made_again():
    assert "finished by hand for this day" in reminders.SYNC_BODY


@pytest.mark.parametrize("setting", ["off", "no", None, False])
def test_off_does_nothing(store, osa, setting):
    cfg = config.Config(path=None, boards=[], follow_ups=config._follow_ups(setting, "x"))
    key = add(store)
    reminders.refresh(cfg, store, [key])
    assert reminders.sync(cfg, store)["created"] == 0
    assert osa.calls == []


def test_not_a_mac_does_nothing(store, osa, monkeypatch):
    monkeypatch.setattr(reminders.sys, "platform", "linux")
    reminders.refresh(cfg_with(), store, [add(store)])
    assert reminders.sync(cfg_with(), store)["kept"] == 0
    assert osa.calls == []


def test_the_setting_is_read_and_checked():
    assert config._follow_ups("Reminders", "x") == "reminders"
    assert config._follow_ups("reminders-all", "x") == "reminders-all"
    with pytest.raises(config.ConfigError, match="follow_ups must be one of"):
        config._follow_ups("calendar", "x")


def test_a_refused_permission_warns_once_in_one_line_and_never_raises(store, osa, capsys):
    osa.fail = subprocess.CompletedProcess([], 1, "", "execution error: Not authorized to send Apple events (-1743)")
    key = add(store)
    reminders.refresh(cfg_with(), store, [key])
    reminders.refresh(cfg_with(), store, [key])
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and "Privacy & Security > Automation" in err[0]


def test_a_missing_osascript_warns_and_the_mark_still_happens(store, monkeypatch, capsys):
    def gone(*a, **k):
        raise FileNotFoundError
    monkeypatch.setattr(reminders.subprocess, "run", gone)
    monkeypatch.setattr(reminders.sys, "platform", "darwin")
    monkeypatch.setattr(reminders, "_warned", False)
    key = add(store)
    reminders.refresh(cfg_with(), store, [key])
    assert "osascript" in capsys.readouterr().err and store.find(key)[1]["follow_up"] == "2026-11-20"


def test_sync_reports_a_failure_for_the_command(store, osa):
    osa.fail = subprocess.CompletedProcess([], 1, "", "execution error: Not authorized (-1743)")
    with pytest.raises(reminders.RemindersError, match="Automation"):
        reminders.sync(cfg_with(), store)


def test_the_command_says_what_it_did(store, osa, capsys):
    add(store)
    osa.reply = {"created": 1, "moved": 0, "deleted": 0, "kept": 0}
    cli.cmd_reminders(None, cfg_with(), store)
    assert "1 created, 0 moved, 0 deleted, 0 already right" in capsys.readouterr().out
    with pytest.raises(ValueError, match="follow_ups: reminders"):
        cli.cmd_reminders(None, cfg_with("off"), store)


def test_marking_with_a_follow_up_makes_the_reminder(store, osa, tmp_path):
    key = add(store, follow_up="")
    args = cli.build_parser().parse_args(["mark", "screening", key, "--follow-up", "2026-12-01"])
    cli.cmd_mark(args, cfg_with(), store)
    assert [i["key"] for i in osa.calls[-1]["items"]] == [key]


@pytest.fixture
def app(watchlist, store, osa):
    text = watchlist.read_text() + "follow_ups: reminders\n"
    watchlist.write_text(text)
    return App(watchlist)


def test_the_page_track_and_snooze_keep_reminders_in_step(app, osa):
    store = Store(config.load(app.path).state)
    key = add(store, follow_up="2026-12-01")
    store.close()
    osa.calls.clear()
    app.post_track({"key": key, "follow_up": "2026-12-05"})
    app.post_snooze({"key": key, "days": 3})
    track, snooze = osa.calls
    assert track["items"][0]["key"] == key and snooze["items"] == [] and snooze["drop"] == [key]  # snoozed: none
    assert app.get_applications({})["reminders"] is True


def test_the_bell_makes_a_one_off_with_the_link_and_no_marker(app, osa):
    store = Store(config.load(app.path).state)
    key = add(store)
    store.close()
    osa.reply = {"title": "Initech: call", "due": 0}
    app.post_remind({"key": key, "title": "Initech: call", "due": "2026-11-20T14:30", "note": "ask about pay"})
    (call,) = osa.calls
    assert call["title"] == "Initech: call" and call["due"] == int(datetime(2026, 11, 20, 14, 30).timestamp())
    assert call["notes"] == "ask about pay\nhttps://jobs.initech.example/1" and "jobwatch:" not in call["notes"]
    with pytest.raises(ApiError, match="YYYY-MM-DDTHH:MM"):
        app.post_remind({"key": key, "title": "x", "due": "tomorrow"})
    with pytest.raises(ApiError, match="needs a title"):
        app.post_remind({"key": key, "title": " ", "due": "2026-11-20T14:30"})


def test_the_bell_is_refused_when_reminders_are_off(watchlist, osa):
    page = App(watchlist)
    store = Store(config.load(watchlist).state)
    key = add(store)
    store.close()
    with pytest.raises(ApiError, match="Reminders are off"):
        page.post_remind({"key": key, "title": "x", "due": "2026-11-20T14:30"})
    assert page.get_applications({})["reminders"] is False and osa.calls == []
