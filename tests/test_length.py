"""How long an interview lasts: read from the next step's words, carried with the application (`mark --length`, the
MCP tool's length), and used by the Interviews card, the details view and the calendar feed."""

from datetime import UTC, date, datetime, timedelta

import pytest

from jobwatch import cli, ics, interviews, rounds
from jobwatch import mcp_server as mcp
from jobwatch.models import Job
from jobwatch.store import Store
from jobwatch.web import App

from .test_cli import run
from .test_mcp_tools import TOOLS

TODAY = date(2026, 10, 12)  # a Monday
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
INTRO = "Intro call with Pat, Fri 10/16 2:15 PM ET"  # 18:15 UTC, no length in its words


def job(company="Acme", title="Staff Engineer", id_="1"):
    return Job(source="manual", company=company.lower(), id=id_, title=title, url="", company_name=company)


def rec(next_step=INTRO, length=None, round="recruiter_screen"):
    return {"status": "interviewing", "next_step": next_step, "follow_up": None, "note": None, "round": round,
            "length": length}


def minutes(m):
    return (m.end - m.start) / timedelta(minutes=1)


@pytest.mark.parametrize("text, expected", [
    ("15-minute recruiter intro call", 15), ("intro call, 15 min", 15), ("15 mins with Pat", 15),
    ("30 minutes with the director", 30), ("1 hour panel", 60), ("1.5 hours onsite", 90), ("2 hrs", 120),
    ("45-MIN screen", 45),
    ("call Fri 10/16 2:15 PM ET", None), ("", None), (None, None),
    ("15 minutes or 30 minutes, to be settled", None),  # two different ones: not sure
    ("15 min call, 15 minutes", 15),  # the same one twice
    ("3m", None), ("2h", None),  # a bare letter after a number isn't a length in a step
    ("call 0 minutes", None), ("a 20 hour day", None),  # out of range
])
def test_a_length_stated_in_the_next_step(text, expected):
    assert rounds.stated_length(text) == expected


@pytest.mark.parametrize("given, stored", [
    ("15m", "15"), ("15", "15"), (15, "15"), (" 45 min ", "45"), ("30 minutes", "30"), ("1h", "60"),
    ("1 hour", "60"), ("1.5h", "90"), ("1h30m", "90"), ("1h 30m", "90"), ("1h30", "90"),
    ("90", "90"), ("", ""), ("  ", ""),
])
def test_a_length_as_given(given, stored):
    assert rounds.check_length(given) == stored


@pytest.mark.parametrize("bad", ["soon", "h", "0", "0m", "13h", "-5", "15x", "1h30x"])
def test_a_bad_length_is_refused(bad):
    with pytest.raises(ValueError, match="length must be"):
        rounds.check_length(bad)


def test_the_length_a_record_carries():
    assert rounds.length_of({"length": "15"}) == 15 and rounds.length_of({"length": 45}) == 45
    assert rounds.length_of({"length": None}) is None and rounds.length_of({}) is None
    assert rounds.length_of({"length": ""}) is None and rounds.length_of({"length": "x"}) is None


def test_a_meeting_with_no_length_still_lasts_an_hour():
    m = ics.meeting(INTRO, TODAY, "recruiter_screen")
    assert minutes(m) == 60 and m.start == datetime(2026, 10, 16, 18, 15, tzinfo=UTC)


def test_the_words_length_ends_the_meeting():
    m = ics.meeting("15-minute intro call with Pat, Fri 10/16 2:15 PM ET", TODAY)
    assert (minutes(m), m.end) == (15, datetime(2026, 10, 16, 18, 30, tzinfo=UTC))
    assert minutes(ics.meeting("Panel interview 1 hour, Fri 10/16 2:15 PM ET", TODAY)) == 60
    assert minutes(ics.meeting("Call 30 min 2026-10-16 14:15 ET", TODAY)) == 30  # an ISO time reads it too


def test_the_stored_length_wins_over_the_words_and_an_end_time_wins_over_both():
    assert minutes(ics.meeting(INTRO, TODAY, "recruiter_screen", 15)) == 15
    assert minutes(ics.meeting("30 minute chat, Fri 10/16 2:15 PM ET", TODAY, None, 15)) == 15
    assert minutes(ics.meeting("call Fri 10/16 2:15-3:00 PM ET", TODAY, None, 15)) == 45
    assert minutes(ics.meeting("call 2026-10-16 14:15 ET", TODAY, None, 20)) == 20


def test_a_step_with_two_meetings_gives_each_the_length():
    step = "Sync Fri 10/16 9:30 AM ET; final round Sun 10/18 5:00 PM ET"
    assert [minutes(m) for m in ics.meetings(step, TODAY, None, 25)] == [25, 25]
    step = "Sync 15 min Fri 10/16 9:30 AM ET; final round 2 hours Sun 10/18 5:00 PM ET"
    assert [minutes(m) for m in ics.meetings(step, TODAY)] == [15, 120]


def test_the_calendar_feed_ends_the_event_at_the_length():
    feed = ics.calendar([(job(), rec(length="15"))], today=TODAY, now=NOW).replace("\r\n ", "").split("\r\n")
    assert "DTSTART:20261016T181500Z" in feed and "DTEND:20261016T183000Z" in feed
    feed = ics.calendar([(job(), rec())], today=TODAY, now=NOW).replace("\r\n ", "").split("\r\n")
    assert "DTEND:20261016T191500Z" in feed
    feed = ics.calendar([(job(), rec("20-minute screen Fri 10/16 2:15 PM ET"))], today=TODAY, now=NOW)
    assert "DTEND:20261016T183500Z" in feed.replace("\r\n ", "").split("\r\n")


def test_the_card_and_the_details_view_end_at_the_length():
    [found] = interviews.upcoming([(job(), rec(length="15"))], TODAY)
    card = interviews.to_dict(found, None)
    assert (card["start"], card["end"], card["length"]) == ("2026-10-16T18:15:00+00:00",
                                                            "2026-10-16T18:30:00+00:00", 15)
    [plain] = interviews.upcoming([(job(), rec())], TODAY)
    plain = interviews.to_dict(plain, None)
    assert (plain["end"], plain["length"]) == ("2026-10-16T19:15:00+00:00", None)
    assert interviews.meeting_dict(INTRO, TODAY, "recruiter_screen", 15)["end"] == "2026-10-16T18:30:00+00:00"
    assert interviews.meeting_dict(INTRO, TODAY, "recruiter_screen")["end"] == "2026-10-16T19:15:00+00:00"


def test_the_store_keeps_and_clears_the_length(tmp_path):
    store = Store(tmp_path / "state.db")
    store.sync("lever", "globex", [Job(source="lever", company="globex", id="a", title="Engineer", url="")])
    assert store.find("a")[1]["length"] is None
    store.track("lever:globex:a", length="15m", next_step="call Pat")
    assert store.find("a")[1]["length"] == "15" and rounds.length_of(store.find("a")[1]) == 15
    store.track("lever:globex:a", next_step="call Pat Friday")  # None leaves it
    assert store.find("a")[1]["length"] == "15"
    with pytest.raises(ValueError, match="length must be"):
        store.track("lever:globex:a", length="soon")
    assert store.find("a")[1]["length"] == "15"
    store.track("lever:globex:a", length="")
    assert store.find("a")[1]["length"] is None


def test_an_older_state_file_gets_the_column(tmp_path):
    path = tmp_path / "state.db"
    store = Store(path)
    store.db.execute("ALTER TABLE jobs DROP COLUMN length")
    store.db.commit()
    store.close()
    assert "length" in {r["name"] for r in Store(path).db.execute("PRAGMA table_info(jobs)")}


def test_the_command_sets_the_length(watchlist, capsys):
    c = ("-c", str(watchlist))
    run(capsys, *c, "add", "Umbrella", "Principal Engineer", "--next", INTRO, "--round", "recruiter_screen",
        "--length", "15m")
    store = Store(watchlist.parent / "state.db")
    assert store.find("principal-engineer")[1]["length"] == "15"
    run(capsys, *c, "mark", "principal-engineer", "--length", "1h")
    assert store.find("principal-engineer")[1]["length"] == "60"
    with pytest.raises(SystemExit, match="length must be"):
        cli.main([*c, "mark", "principal-engineer", "--length", "soon"])
    assert store.find("principal-engineer")[1]["length"] == "60"
    run(capsys, *c, "mark", "principal-engineer", "--length", "")
    assert store.find("principal-engineer")[1]["length"] is None


def test_mark_job_takes_a_length(watchlist, monkeypatch):
    monkeypatch.setattr(mcp, "_changed_since_start", lambda: None)
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    mcp.add_application("Initech", "Field Engineer", status="interviewing")
    mcp.mark_job("initech", next_step=INTRO, round="recruiter_screen", length="15m")
    store = Store(watchlist.parent / "state.db")
    assert store.find("initech")[1]["length"] == "15"
    mcp.mark_job("initech", length="")
    assert store.find("initech")[1]["length"] is None
    assert "length" in TOOLS["mark_job"].input_schema["properties"]


def test_the_page_shows_the_length(watchlist, server):
    app = App(watchlist)
    soon = date.today() + timedelta(days=3)
    key = app.post_add({"company": "Acme", "title": "Staff Engineer", "status": "interviewing",
                        "next_step": f"Intro call {soon:%m/%d/%Y} 2:15 PM ET", "round": "recruiter_screen"})["key"]

    def shown():
        [card] = [i for i in app.get_interviews({})["interviews"] if i["key"] == key]
        end = app.get_job({"key": [key]})["meeting"]["end"]
        assert card["end"] == end
        return minutes_between(card["start"], card["end"]), card["length"]

    assert shown() == (60, None)  # nothing says: an hour, as before
    app.post_track({"key": key, "length": "15m"})
    assert shown() == (15, 15) and app.get_job({"key": [key]})["length"] == 15
    app.post_track({"key": key, "length": ""})
    assert shown() == (60, None)


def minutes_between(start, end):
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)) / timedelta(minutes=1)
