"""The interview rounds timeline: rounds as structured records, written when the next step moves, the timeline the
Details dialog, the lists and the MCP tools show, and the backfill that proposes done rounds from the History."""

from datetime import date, datetime, timedelta

import pytest

from jobwatch import cli, rounds, timeline
from jobwatch import mcp_server as mcp
from jobwatch.models import Job
from jobwatch.store import Store
from jobwatch.web import ApiError, App

from .test_cli import run
from .test_mcp_tools import TOOLS

TODAY = date(2026, 11, 27)  # a Friday
NOW = datetime(2026, 11, 27, 9, 0)
KEY = "lever:initech:eng"


def at(days, clock="14:00"):
    """An ISO meeting time `days` from the real today (a next step the parser reads without a year)."""
    return f"{date.today() + timedelta(days=days):%Y-%m-%d}T{clock}"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state.db")
    s.sync("lever", "initech", [Job(source="lever", company="initech", id="eng", title="Field Engineer", url="",
                                    description="Our four-round interview process is short.")])
    s.set_status([KEY], "interviewing")
    return s


def rec(next_step=None, round=None, status="interviewing", note=None, length=None):
    return {"status": status, "next_step": next_step, "round": round, "length": length, "note": note,
            "follow_up": None}


def stored(**kw):
    return {"id": 1, "kind": "", "state": "done", "day": "2026-11-18", "time": "", "length": None, "who": "",
            "mode": "", "outcome": "", "note": "", "source": "you", **kw}


# -- reading words

@pytest.mark.parametrize("text, kind", [
    ("System design interview", "system_design"), ("panel interview", "panel"), ("onsite loop", "panel"),
    ("HM round", "hiring_manager"), ("call with the hiring manager", "hiring_manager"),
    ("recruiter intro call", "recruiter_screen"), ("coding interview", "technical"), ("VP chat", "executive"),
    ("HR round", "hr"), ("coffee with Sam", "informal"), ("offer call", "offer_call"),
    ("the hm said", ""), ("Interview Tuesday", ""), ("", ""), (None, ""),
])
def test_the_kind_a_text_names(text, kind):
    assert timeline.kind_from_text(text) == kind


def test_who_and_where():
    assert timeline.who_from_text("Panel with Dana Lee and Sam Ortiz on Zoom") == "Dana Lee, Sam Ortiz"
    assert timeline.who_from_text("call with the recruiter") == ""
    assert timeline.who_from_text("call with Teams link, Tue") == ""  # not a name
    assert timeline.mode_from_text("Intro call on Zoom") == "Zoom"
    assert timeline.mode_from_text("phone screen") == "Phone" and timeline.mode_from_text("Tuesday") == ""


@pytest.mark.parametrize("given, shown", [("14:30", "14:30"), ("2:30 PM", "14:30"), ("2pm", "14:00"),
                                          ("12 AM", "00:00"), ("", ""), ("none", "")])
def test_times(given, shown):
    assert timeline.clock(given) == shown


@pytest.mark.parametrize("bad", ["soon", "25:00", "13 PM", "14"])
def test_a_time_that_isnt(bad):
    with pytest.raises(ValueError, match="isn't a time"):
        timeline.clock(bad)


def test_a_posting_that_names_its_process():
    assert timeline.typical_rounds("We run a four-round interview process.") == 4
    assert timeline.typical_rounds("The interview process has 3 stages.") == 3
    assert timeline.typical_rounds("Expect 5 rounds of interviews") == 5
    assert timeline.typical_rounds("Round 2 of the contest") is None and timeline.typical_rounds(None) is None


# -- the timeline

def test_no_rounds_is_an_empty_timeline():
    tl = timeline.build(rec(), [], today=TODAY, now=NOW)
    assert tl["items"] == [] and tl["chip"] is None and tl["number"] is None and tl["next"] is None


def test_done_rounds_then_the_next_one_then_nothing_invented():
    step = "Panel with Dana Lee on Zoom 2026-11-30T12:00"
    tl = timeline.build(rec(step, "panel", length="60"), [stored(kind="recruiter_screen", who="Pat Kim"),
                                                       stored(id=2, kind="hiring_manager", day="2026-11-24")],
                        "A four-round interview process", TODAY, NOW)
    assert [(r["number"], r["state"], r["label"]) for r in tl["items"]] == [
        (1, "done", "Recruiter screen"), (2, "done", "Hiring manager"), (3, "next", "Panel / onsite loop")]
    nxt = tl["next"]
    assert (nxt["day"], nxt["time"], nxt["length"], nxt["who"], nxt["mode"]) == (
        "2026-11-30", "12:00", 60, "Dana Lee", "Zoom")
    assert tl["done"] == 2 and tl["number"] == 3 and tl["typical"] == 4
    assert tl["chip"] == "Round 3 of ~4 · next: Panel / onsite loop Mon Nov 30 12 PM"
    assert len(tl["items"]) == 3  # no fourth round is made up from the posting's four


def test_the_chip_says_of_question_mark_when_nothing_says_how_many():
    tl = timeline.build(rec("Panel 2026-11-30T12:00", "panel"), [stored()], None, TODAY, NOW)
    assert tl["chip"] == "Round 2 of ? · next: Panel / onsite loop Mon Nov 30 12 PM"


def test_a_round_whose_time_passed_is_held_until_its_outcome_is_recorded():
    tl = timeline.build(rec("Intro call 2026-11-26T14:00", "recruiter_screen"), [], None, TODAY, NOW)
    [r] = tl["items"]
    assert r["state"] == "held" and tl["next"] is None and tl["held"] == 1
    assert tl["chip"] == "Round 1 held · how did it go?"


def test_when_nothing_is_scheduled():
    tl = timeline.build(rec(), [stored(), stored(id=2, day="2026-11-20")], None, TODAY, NOW)
    assert tl["chip"] == "2 rounds done · none scheduled" and tl["next"] is None


def test_a_next_step_with_no_time_is_a_round_with_no_day():
    tl = timeline.build(rec("Panel interview, the recruiter will schedule", "panel"), [], None, TODAY, NOW)
    [r] = tl["items"]
    assert (r["state"], r["day"], r["time"]) == ("next", None, "")
    assert tl["chip"] == "Round 1 of ? · next: Panel / onsite loop, not dated yet"
    # not past applied: "wait for a recruiter screen" is a hope, not a round
    assert timeline.build(rec("wait for a recruiter screen", status="applied"), [], None, TODAY, NOW)["items"] == []


def test_two_meetings_in_one_step_are_two_rounds():
    step = "Sync with Pat Kim 2026-11-30T09:30; final round 2026-12-02T17:00"
    tl = timeline.build(rec(step), [], None, TODAY, NOW)
    assert [(r["state"], r["day"], r["kind"]) for r in tl["items"]] == [
        ("next", "2026-11-30", ""), ("scheduled", "2026-12-02", "panel")]


def test_an_ended_application_shows_only_what_was_held():
    tl = timeline.build(rec("Panel 2026-11-30T12:00", "panel", status="rejected"), [stored()], None, TODAY, NOW)
    assert [r["state"] for r in tl["items"]] == ["done"] and tl["next"] is None


def test_the_stored_round_for_the_next_step_is_not_listed_twice():
    mine = stored(id=3, state="scheduled", day="2026-11-30", time="12:00", length=60, kind="panel", source="next_step")
    tl = timeline.build(rec("Panel 2026-11-30T12:00", "panel", length="60"), [mine], None, TODAY, NOW)
    assert [r["id"] for r in tl["items"]] == [3]


# -- rounds written when the next step moves

def rows(store):
    return [(r["day"][5:], r["state"], r["kind"], r["source"]) for r in store.rounds_for([KEY]).get(KEY, [])]


def test_setting_the_next_step_records_the_round(store):
    store.track(KEY, next_step=f"Intro call with Pat Kim on Zoom {at(3)}", round="recruiter_screen", length="30m")
    [r] = store.rounds_for([KEY])[KEY]
    assert (r["kind"], r["state"], r["length"], r["who"], r["mode"], r["source"], r["time"]) == (
        "recruiter_screen", "scheduled", 30, "Pat Kim", "Zoom", "next_step", "14:00")
    store.track(KEY, next_step=f"Intro call with Pat Kim on Zoom {at(3)}")  # again: still one
    assert len(store.rounds_for([KEY])[KEY]) == 1


def test_moving_the_step_before_it_happened_moves_the_round(store):
    store.track(KEY, next_step=f"Intro call {at(3)}", round="recruiter_screen")
    store.track(KEY, next_step=f"Intro call {at(5)}")
    assert rows(store) == [((date.today() + timedelta(days=5)).strftime("%m-%d"), "scheduled",
                            "recruiter_screen", "next_step")]


def test_replacing_a_step_whose_time_passed_makes_the_round_done(store):
    store.track(KEY, next_step=f"Hiring manager call {at(-2)}", round="hiring_manager")
    assert rows(store)[0][1] == "scheduled"
    store.track(KEY, next_step=f"Technical interview {at(4)}", round="technical")
    assert [(r[1], r[2]) for r in rows(store)] == [("done", "hiring_manager"), ("scheduled", "technical")]
    store.track(KEY, next_step="wait for their decision", round="")  # one still ahead, dropped: it won't happen
    assert [(r[1], r[2]) for r in rows(store)] == [("done", "hiring_manager")]


def test_an_application_with_a_step_from_before_gets_its_round_when_the_step_changes(store):
    store.db.execute("UPDATE jobs SET next_step=?, round='panel' WHERE key=?", (f"Panel {at(-1)}", KEY))
    assert rows(store) == []  # nothing recorded yet: the timeline reads the step itself
    store.track(KEY, next_step="check in with the recruiter", round="")
    assert [(r[1], r[2]) for r in rows(store)] == [("done", "panel")]


def test_a_rejection_drops_the_rounds_still_ahead(store):
    store.track(KEY, next_step=f"Panel {at(4)}", round="panel")
    store.set_status([KEY], "rejected")
    store.track(KEY, next_step=f"Panel {at(4)}")
    assert rows(store) == []


# -- by hand

def test_add_edit_done_delete(store):
    first = store.add_round(KEY, kind="recruiter_screen", day="2026-11-10", who="Pat Kim", length="30m")
    [r] = store.rounds_for([KEY])[KEY]
    assert (r["state"], r["source"], r["length"]) == ("done", "you", 30)  # a day that has passed: done
    soon = store.add_round(KEY, kind="panel", day=at(4)[:10], time="2:30 PM")
    assert store.get_round(KEY, soon)["state"] == "scheduled" and store.get_round(KEY, soon)["time"] == "14:30"
    store.finish_round(KEY, soon, "Went well", "Asked about on-call")
    assert (store.get_round(KEY, soon)["state"], store.get_round(KEY, soon)["outcome"]) == ("done", "Went well")
    store.edit_round(KEY, first, who="Pat Kim, Lee Cho", mode="Phone")
    assert store.get_round(KEY, first)["who"] == "Pat Kim, Lee Cho"
    store.delete_round(KEY, first)
    assert [r["id"] for r in store.rounds_for([KEY])[KEY]] == [soon]
    with pytest.raises(ValueError, match="no round"):
        store.get_round(KEY, first)


@pytest.mark.parametrize("fields, message", [
    ({"kind": "chat"}, "round must be one of"), ({"day": "soonish"}, "isn't a date"),
    ({"time": "later"}, "isn't a time"), ({"state": "done"}, "needs the day"), ({"length": "x"}, "length must be"),
    ({"mood": "x"}, "unknown round field"),
])
def test_a_round_that_isnt_valid(store, fields, message):
    with pytest.raises(ValueError, match=message):
        store.add_round(KEY, **fields)


def test_a_round_from_the_next_step_keeps_its_day_but_takes_its_kind_and_length(store):
    store.track(KEY, next_step=f"Call {at(3)}", round="panel")
    [r] = store.rounds_for([KEY])[KEY]
    with pytest.raises(ValueError, match="change the step"):
        timeline.change(store, KEY, "edit", r["id"], day="2030-01-01")
    timeline.change(store, KEY, "edit", r["id"], kind="executive", length="45m", who="Sam Ortiz")
    assert store.find(KEY)[1]["round"] == "executive" and store.find(KEY)[1]["length"] == "45"
    assert [(x["kind"], x["length"], x["who"], x["source"]) for x in store.rounds_for([KEY])[KEY]] == [
        ("executive", 45, "Sam Ortiz", "next_step")]


def test_editing_an_inferred_round_makes_it_yours(store):
    rid = store.add_round(KEY, source="inferred", kind="", day="2026-11-10")
    assert store.get_round(KEY, rid)["source"] == "inferred"
    store.edit_round(KEY, rid, kind="technical")
    assert store.get_round(KEY, rid)["source"] == "you"


# -- the backfill

HISTORY = ("2026-11-10: Applied online. "
           "2026-11-12: Recruiter screen with Dana Lee done, went well. Moved to the hiring manager. "
           "2026-11-16: Hiring manager round scheduled for Thu 11/19, invite sent. "
           "2026-11-19: 11/19 HM round: Sam Ortiz asked about on-call. "
           "2026-11-20: Waiting to hear. Reply drafted to the recruiter. "
           "2026-11-24: System design interview with Pat Kim and Lee Cho done, did well on it. "
           "2026-11-25: Thank-you note sent after the loop.")


def test_infer_reads_done_rounds_from_the_history_and_skips_scheduling_lines():
    found = timeline.infer(rec(note=HISTORY), TODAY)
    assert [(r["day"], r["kind"], r["who"], r["outcome"]) for r in found] == [
        ("2026-11-12", "recruiter_screen", "Dana Lee", "Went well"),
        ("2026-11-19", "hiring_manager", "", ""),
        ("2026-11-24", "system_design", "Pat Kim, Lee Cho", "Went well"),
        ("2026-11-25", "panel", "", ""),  # "the loop"
    ]
    assert all(r["state"] == "done" and r["source"] == "inferred" for r in found)
    assert "scheduled" not in found[1]["note"] and found[0]["note"].startswith("Recruiter screen with Dana Lee")


@pytest.mark.parametrize("note", [
    "2026-11-12: The form had no pay question; say it in the recruiter screen.",
    "2026-11-12: The 11/12 call did not happen, he cited technical issues.",
    "2026-11-12: Next if passed: technical round with two engineers.",
    "2026-11-12: Asked for availability for the system design interview.",
    "2026-11-12: Intro call went well. 2026-11-30: Intro call done.",  # the second is in the future
    "Intro call done.",  # no day anywhere
])
def test_infer_leaves_out_what_isnt_a_held_round(note):
    found = timeline.infer(rec(note=note), date(2026, 11, 20))
    assert [r["day"] for r in found] in ([], ["2026-11-12"])
    assert not any(r["day"] > "2026-11-20" for r in found)


def test_an_undated_first_line_can_start_with_its_day():
    [r] = timeline.infer(rec(note="11/13 HM round: Sam asked about caching. 2026-11-16: Waiting."), TODAY)
    assert (r["day"], r["kind"]) == ("2026-11-13", "hiring_manager")


def test_new_proposals_leave_out_rounds_you_already_have(store):
    r = rec(note=HISTORY)
    have = [stored(day="2026-11-12", kind="recruiter_screen")]
    assert [p["day"] for p in timeline.new_proposals(r, have, TODAY)] == ["2026-11-19", "2026-11-24", "2026-11-25"]


def test_the_backfill_proposes_and_applies_only_for_the_keys_named(store, watchlist, capsys):
    store.add_note(KEY, "Recruiter screen with Dana Lee done, went well.")  # dated today
    other = Job(source="lever", company="initech", id="two", title="Analyst", url="")
    store.sync("lever", "initech", [store.job(KEY), other])
    store.set_status(["lever:initech:two"], "applied", "2026-11-01: Call with Pat Kim done.")
    found = timeline.proposals(store)
    assert {k: [p["kind"] for p in props] for k, _, props in found} == {
        KEY: ["recruiter_screen"], "lever:initech:two": [""]}
    assert store.rounds_for() == {}  # proposing writes nothing
    timeline.apply(store, timeline.proposals(store, [KEY]))
    assert list(store.rounds_for()) == [KEY]
    assert store.rounds_for([KEY])[KEY][0]["source"] == "inferred"
    assert timeline.proposals(store, [KEY])[0][2] == []  # a second time adds nothing


# -- the command

def test_the_command_lists_adds_finishes_and_deletes(watchlist, capsys):
    c = ("-c", str(watchlist))
    run(capsys, *c, "add", "Initech", "Field Engineer", "--status", "interviewing")
    out = run(capsys, *c, "rounds", "field-engineer").out
    assert "No rounds yet" in out
    out = run(capsys, *c, "rounds", "field-engineer", "--add", "recruiter_screen", "--date", "2026-11-10", "--done",
              "--with", "Pat Kim", "--length", "30m", "--outcome", "Went well").out
    assert "added round #1" in out and "done" in out and "with Pat Kim" in out and "30 min" in out
    assert "Later rounds: not scheduled yet" in out
    out = run(capsys, *c, "rounds", "field-engineer", "--add", "panel", "--date", "+4", "--time", "2pm").out
    assert "scheduled" in out and "2 PM" in out
    out = run(capsys, *c, "rounds", "field-engineer", "--done", "2", "--outcome", "Passed").out
    assert "round #2: done" in out and "Passed" in out
    out = run(capsys, *c, "rounds", "field-engineer", "--edit", "1", "--kind", "technical", "--mode", "Zoom").out
    assert "Tech interview" in out and "Zoom" in out
    assert "deleted round #1" in run(capsys, *c, "rounds", "field-engineer", "--delete", "1").out
    with pytest.raises(SystemExit, match="--done ID"):
        cli.main([*c, "rounds", "field-engineer", "--done"])


def test_the_command_records_a_round_when_the_next_step_is_set(watchlist, capsys):
    c = ("-c", str(watchlist))
    run(capsys, *c, "add", "Initech", "Field Engineer", "--status", "interviewing", "--next",
        f"Panel with Dana Lee {at(4)}", "--round", "panel")
    out = run(capsys, *c, "rounds", "field-engineer").out
    assert "Panel / onsite loop" in out and "with Dana Lee" in out and "next" in out


def test_the_backfill_command_is_a_dry_run_until_apply_with_only(watchlist, capsys):
    c = ("-c", str(watchlist))
    run(capsys, *c, "add", "Initech", "Field Engineer", "--status", "interviewing",
        "--note", "2026-11-12: Recruiter screen with Dana Lee done, went well.")
    out = run(capsys, *c, "rounds", "--backfill").out
    assert "inferred from your notes" in out and "1 round(s) in 1 of 1 application(s) proposed" in out
    assert Store(watchlist.parent / "state.db").rounds_for() == {}
    with pytest.raises(SystemExit, match="--apply --only"):
        cli.main([*c, "rounds", "--backfill", "--apply"])
    out = run(capsys, *c, "rounds", "--backfill", "--apply", "--dry-run", "--only", "field-engineer").out
    assert "proposed" in out and Store(watchlist.parent / "state.db").rounds_for() == {}
    out = run(capsys, *c, "rounds", "--backfill", "--apply", "--only", "field-engineer").out
    assert "written" in out
    assert [r["source"] for r in Store(watchlist.parent / "state.db").rounds_for()["manual:initech:field-engineer"]
            ] == ["inferred"]
    with pytest.raises(SystemExit, match="not keys"):
        cli.main([*c, "rounds", "--backfill", "field-engineer"])


# -- the page's data

def test_the_details_rounds_and_the_lists_chip(watchlist, server):
    app = App(watchlist)
    key = app.post_add({"company": "Initech", "title": "Field Engineer", "status": "interviewing",
                        "next_step": f"Panel with Dana Lee {at(4)}", "round": "panel",
                        "note": "2026-11-12: Recruiter screen with Pat Kim done, went well."})["key"]
    r = app.get_job({"key": [key]})["rounds"]
    assert r["next"] == 1 and [i["state"] for i in r["items"]] == ["next"]
    assert r["items"][0]["id"] and r["items"][0]["who"] == "Dana Lee"  # the step's meeting has a row to edit
    assert [k["id"] for k in r["kinds"]][:2] == ["recruiter_screen", "hiring_manager"] and r["kinds"][-1]["id"] == ""
    assert all(k["help"] for k in r["kinds"])
    assert [p["kind"] for p in r["proposed"]] == ["recruiter_screen"]
    [row] = [a for a in app.get_applications({})["applications"] if a["key"] == key]
    assert row["rounds"]["chip"].startswith("Round 1 of ? · next: Panel / onsite loop") and row["rounds"]["dots"] == [
        "next"]


def test_the_page_adds_and_changes_rounds_and_offers_the_backfill(watchlist, server):
    app = App(watchlist)
    key = app.post_add({"company": "Initech", "title": "Field Engineer", "status": "applied",
                        "note": "2026-11-12: Recruiter screen with Pat Kim done."})["key"]
    assert app.get_job({"key": [key]})["rounds"]["items"] == []  # a new application starts with none
    assert [a["key"] for a in app.get_rounds_found({})["applications"]] == [key]
    got = app.post_rounds({"key": key, "action": "add", "fields": {"kind": "other", "day": "2026-11-12",
                                                                     "who": "Pat Kim"}})
    [item] = got["items"]
    assert (item["label"], item["state"], item["who"]) == ("Interview", "done", "Pat Kim")
    assert got["proposed"] == []  # it is there now
    got = app.post_rounds({"key": key, "action": "edit", "id": item["id"], "fields": {"kind": "technical"}})
    assert got["items"][0]["label"] == "Tech interview"
    with pytest.raises(ApiError, match="needs the round's id"):
        app.post_rounds({"key": key, "action": "delete"})
    with pytest.raises(ApiError, match="no round"):
        app.post_rounds({"key": key, "action": "delete", "id": 99})
    assert app.post_rounds({"key": key, "action": "delete", "id": item["id"]})["items"] == []
    assert app.post_rounds_found({"keys": [key]}) == {"added": 1}
    assert app.get_job({"key": [key]})["rounds"]["items"][0]["inferred"] is True
    with pytest.raises(ApiError, match="send the keys"):
        app.post_rounds_found({})


def test_the_company_view_carries_each_jobs_summary(watchlist, server):
    app = App(watchlist)
    app.post_add({"company": "Initech", "title": "Field Engineer", "status": "interviewing",
                  "next_step": f"Panel {at(4)}", "round": "panel"})
    app.post_add({"company": "Initech", "title": "Analyst", "status": "applied"})
    jobs = {j["title"]: j for j in app.get_company({"q": ["Initech"]})["jobs"]}
    assert jobs["Field Engineer"]["rounds"]["chip"].startswith("Round 1 of ?")
    assert jobs["Analyst"]["rounds"] is None


# -- the MCP tools

def test_the_tools_describe_themselves():
    assert {"get_rounds", "set_round"} <= TOOLS.keys() and "set_round" in TOOLS["get_rounds"].description
    assert "get_rounds" in TOOLS["list_applications"].description and "rounds" in TOOLS["mark_job"].description


def test_get_and_set_round(watchlist, monkeypatch):
    monkeypatch.setattr(mcp, "_changed_since_start", lambda: None)
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    mcp.add_application("Initech", "Field Engineer", status="interviewing")
    assert mcp.get_rounds("initech")["items"] == []
    mcp.mark_job("initech", next_step=f"Intro call {at(3)}", round="recruiter_screen")
    got = mcp.get_rounds("initech")
    assert [i["state"] for i in got["items"]] == ["next"] and got["chip"].startswith("Round 1 of ?")
    done = mcp.set_round("initech", "add", kind="technical", day="2026-11-01", who="Sam Ortiz", outcome="Went well")
    assert [i["state"] for i in done["items"]] == ["done", "next"]
    assert done["items"][0]["who"] == "Sam Ortiz" and done["chip"].startswith("Round 2 of ?")
    [listed] = [a for a in mcp.list_applications() if a["key"].endswith("field-engineer")]
    assert listed["rounds"]["dots"] == ["done", "next"]
    with pytest.raises(mcp.ToolError, match="needs the round's id"):
        mcp.set_round("initech", "delete")
    with pytest.raises(mcp.ToolError, match="round must be"):
        mcp.set_round("initech", "add", kind="chat")  # type: ignore[arg-type]
    assert "kind" in TOOLS["set_round"].input_schema["properties"] and rounds.ROUNDS


def test_every_kind_has_its_help():
    assert set(timeline.KIND_HELP) == {*rounds.ROUNDS, ""}
