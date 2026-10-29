"""The interview round on an application: the list, what it decides on the Interviews tab and in the calendar feed,
how it is stored and set (store, command, MCP tool, page)."""

import re
from datetime import date, datetime, timezone
from typing import get_args

import pytest

from jobwatch import cli, ics, interviews, rounds
from jobwatch import mcp_server as mcp
from jobwatch.models import Job
from jobwatch.store import Store
from jobwatch.web import App

from .conftest import request
from .test_cli import run
from .test_mcp_tools import TOOLS

TODAY = date(2026, 10, 12)  # a Monday
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
STEP = "Fri 10/16 3:30-3:45 PM ET"  # no word that says it is a meeting


def job(company="Acme", title="Staff Engineer", id_="1"):
    return Job(source="manual", company=company.lower(), id=id_, title=title, url="", company_name=company)


def rec(round=None, next_step=STEP, status="interviewing", follow_up=None):
    return {"status": status, "next_step": next_step, "follow_up": follow_up, "note": None, "round": round}


def test_the_rounds_are_a_small_fixed_list():
    assert list(rounds.ROUNDS) == ["recruiter_screen", "hiring_manager", "technical", "system_design", "panel",
                                   "executive", "hr", "informal", "offer_call"]
    assert rounds.label("executive") == "VP / exec round" and rounds.kind("executive") == "Interview"
    assert rounds.kind("informal") == "Call" and rounds.kind("recruiter_screen") == "Call"
    assert rounds.label("") is None and rounds.label(None) is None and rounds.kind("nope") is None
    assert rounds.check(" hr ") == "hr" and rounds.check("") == ""
    with pytest.raises(ValueError, match="round must be one of"):
        rounds.check("coffee")


def test_a_round_makes_any_next_step_a_meeting():
    assert ics.meeting(STEP, TODAY) is None and not ics.names_meeting(STEP)
    m = ics.meeting(STEP, TODAY, "informal")
    assert (m.label, m.round, m.zoned) == ("Call", "Informal chat", True)
    assert m.start == datetime(2026, 10, 16, 19, 30, tzinfo=timezone.utc)
    assert ics.names_meeting("recruiter to schedule", "panel")
    assert ics.meeting(STEP, TODAY, "technical").label == "Interview"
    assert [m.round for m in ics.meetings(f"{STEP}; Mon 10/19 1:00 PM", TODAY, "hr")] == ["HR round"] * 2


def test_without_a_round_the_words_still_decide():
    m = ics.meeting("Interview Fri 10/16 3:30 PM", TODAY, None)
    assert (m.label, m.round) == ("Interview", None) and ics.meeting("Interview Fri 10/16 3:30 PM", TODAY, "") == m


def test_the_round_names_the_calendar_event():
    rows = [(job(), rec("executive"))]
    lines = ics.calendar(rows, today=TODAY, now=NOW).replace("\r\n ", "").split("\r\n")
    assert "SUMMARY:VP / exec round: Acme — Staff Engineer" in lines
    assert "SUMMARY:Interview: Acme — Staff Engineer" in ics.calendar(
        [(job(), rec(None, "Interview " + STEP))], today=TODAY, now=NOW).replace("\r\n ", "").split("\r\n")
    assert "SUMMARY:Interview: Acme — Staff Engineer" not in lines


def test_the_interviews_tab_lists_a_step_by_its_round():
    rows = [(job("Acme"), rec("informal")), (job("Globex", id_="2"), rec(None))]
    [found] = interviews.upcoming(rows, TODAY)
    assert found.job.company == "acme" and found.meeting.round == "Informal chat"
    d = interviews.to_dict(found, None)
    assert (d["label"], d["round"], d["round_label"]) == ("Call", "informal", "Informal chat")
    # not scheduled yet: still a meeting, with the round's kind
    [waiting] = interviews.upcoming([(job(), rec("panel", "recruiter to schedule", follow_up="2026-10-14"))], TODAY)
    assert waiting.meeting is None and interviews.to_dict(waiting, None)["label"] == "Interview"
    assert interviews.meeting_dict(STEP, TODAY, "hr")["round_label"] == "HR round"
    assert interviews.meeting_dict(STEP, TODAY) is None


def test_the_store_keeps_and_clears_the_round(tmp_path):
    store = Store(tmp_path / "state.db")
    store.sync("lever", "globex", [Job(source="lever", company="globex", id="a", title="Engineer", url="")])
    assert store.find("a")[1]["round"] is None
    store.track("lever:globex:a", round="hiring_manager", next_step="call Pat")
    assert store.find("a")[1]["round"] == "hiring_manager"
    store.track("lever:globex:a", next_step="call Pat Friday")  # None leaves it
    assert store.find("a")[1]["round"] == "hiring_manager"
    with pytest.raises(ValueError, match="round must be one of"):
        store.track("lever:globex:a", round="coffee")
    store.track("lever:globex:a", round="")
    assert store.find("a")[1]["round"] is None


def test_an_older_state_file_gets_the_column(tmp_path):
    path = tmp_path / "state.db"
    store = Store(path)
    store.db.execute("ALTER TABLE jobs DROP COLUMN round")
    store.db.commit()
    store.close()
    assert "round" in {r["name"] for r in Store(path).db.execute("PRAGMA table_info(jobs)")}


def test_the_command_sets_the_round(watchlist, capsys):
    c = ("-c", str(watchlist))
    run(capsys, *c, "add", "Umbrella", "Principal Engineer", "--next", STEP, "--round", "informal")
    store = Store(watchlist.parent / "state.db")
    assert store.find("principal-engineer")[1]["round"] == "informal"
    run(capsys, *c, "mark", "principal-engineer", "--round", "executive")
    assert store.find("principal-engineer")[1]["round"] == "executive"
    with pytest.raises(SystemExit):
        cli.main([*c, "mark", "principal-engineer", "--round", "coffee"])
    run(capsys, *c, "mark", "principal-engineer", "--round", "")
    assert store.find("principal-engineer")[1]["round"] is None


def test_mark_job_takes_a_round(watchlist):
    schema = TOOLS["mark_job"].input_schema["properties"]["round"]
    values = {v for option in schema.get("anyOf", [schema]) for v in option.get("enum", [])}
    assert values == {*rounds.ROUNDS, ""} and schema["description"]
    assert [v for v in get_args(mcp.Round) if v] == list(rounds.ROUNDS) and get_args(mcp.Round)[-1] == ""


def test_the_page_sets_and_shows_the_round(watchlist, server):
    app = App(watchlist)
    key = app.post_add({"company": "Acme", "title": "Staff Engineer", "status": "interviewing", "next_step": STEP,
                        "round": "informal"})["key"]
    [row] = app.get_applications({})["applications"]
    assert (row["key"], row["round"]) == (key, "informal")
    assert app.get_job({"key": [key]})["round"] == "informal"
    app.post_track({"key": key, "round": ""})
    assert app.get_applications({})["applications"][0]["round"] is None
    from jobwatch.web import ApiError
    with pytest.raises(ApiError, match="round must be one of"):
        app.post_track({"key": key, "round": "coffee"})
    page = request(server, "GET", "/")[1].decode()
    names = dict(re.findall(r'(\w+): "([^"]+)"', re.search(r"const ROUND_NAMES = \{(.*?)\};", page, re.S).group(1)))
    assert names == {k: v[0] for k, v in rounds.ROUNDS.items()}
    assert "round: round.value" in page and 'class: "badge round"' in page
