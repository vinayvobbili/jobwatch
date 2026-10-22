"""The follow-up and interview calendar feed: the file, the times read from next steps, the command, the page."""

import json
from datetime import date, datetime, timezone

import pytest

from jobwatch import cli, config, ics
from jobwatch.models import Job
from jobwatch.store import Store

from .conftest import TOKEN, request

TODAY = date(2026, 10, 12)  # a Monday
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


def meet(text):
    return ics.meeting(text, TODAY)


def span(text):
    m = meet(text)
    return m and (m.start.replace(tzinfo=None).isoformat(), m.end.replace(tzinfo=None).isoformat(), m.zoned, m.label)


@pytest.mark.parametrize("text, expected", [
    # Thursday 10/15 is in EDT (UTC-4)
    ("Panel interview Thursday 10/15 10:00 AM ET", ("2026-10-15T14:00:00", "2026-10-15T15:00:00", True, "Interview")),
    ("call Thu 10/15 2:15-3:00 PM ET", ("2026-10-15T18:15:00", "2026-10-15T19:00:00", True, "Call")),
    ("Recruiter call Thursday, Oct 15th at 3pm PT", ("2026-10-15T22:00:00", "2026-10-15T23:00:00", True, "Call")),
    ("interview 15 October 11:30-12:30 PM UTC", ("2026-10-15T11:30:00", "2026-10-15T12:30:00", True, "Interview")),
    ("onsite 10/15 10-11am CT", ("2026-10-15T15:00:00", "2026-10-15T16:00:00", True, "Interview")),
    ("interview 10/15 14:30 EST", ("2026-10-15T19:30:00", "2026-10-15T20:30:00", True, "Interview")),
    ("interview 2026-10-16 10:00 ET", ("2026-10-16T14:00:00", "2026-10-16T15:00:00", True, "Interview")),
    ("intro call 2026-10-16T09:30:00-07:00", ("2026-10-16T16:30:00", "2026-10-16T17:30:00", True, "Call")),
    ("call 2026-10-16T09:30Z", ("2026-10-16T09:30:00", "2026-10-16T10:30:00", True, "Call")),
    # no zone: the same clock time wherever it is read
    ("Screen on 10/15 at 2:15 PM", ("2026-10-15T14:15:00", "2026-10-15T15:15:00", False, "Call")),
    # no year and the date is behind us: next year (EST, UTC-5)
    ("interview 1/8 9am ET", ("2027-01-08T14:00:00", "2027-01-08T15:00:00", True, "Interview")),
])
def test_times_read_from_a_next_step(text, expected):
    assert span(text) == expected


@pytest.mark.parametrize("text", [
    None, "", "Send thank-you note",
    "Interview on 10/15",                       # no time
    "Interview Thursday 10:00 AM ET",           # no date
    "Interview 10/15 10:00",                    # 10:00 with no am/pm: maybe 10 at night
    "Interview next week, 10 AM",
    "Interview Friday 10/15 10:00 AM ET",       # 10/15/2026 is a Thursday
    "Interview 10/15 or 10/16 at 10 AM ET",     # two days
    "Interview 10/15 at 10 AM or 2 PM ET",      # two times
    "Interview 10/15 10 AM ET / 7 AM PT",       # two zones
    "Send availability for 10/15 at 10 AM",     # not a meeting
    "call 13/45 at 10 AM",                      # not a date
])
def test_text_that_isnt_confident_gives_no_time(text):
    assert meet(text) is None


def job(company, title, url="", id_="1"):
    return Job(source="manual", company=company.lower().replace(" ", ""), id=id_, title=title, url=url,
               company_name=company)


def rec(status="applied", next_step=None, follow_up=None):
    return {"status": status, "next_step": next_step, "follow_up": follow_up}


def unfold(text):
    return text.replace("\r\n ", "").split("\r\n")


def test_feed_is_valid_ics():
    rows = [(job("Acme Robotics", "Staff Engineer", "https://acme.example/jobs/1"),
             rec("interviewing", "Panel interview Thu 10/15 10:00 AM ET; bring portfolio, slides", "2026-10-14"))]
    text = ics.calendar(rows, today=TODAY, now=NOW)
    assert text.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert "\n" not in text.replace("\r\n", "")
    lines = unfold(text)
    assert lines.count("BEGIN:VEVENT") == lines.count("END:VEVENT") == 2
    assert "DTSTART;VALUE=DATE:20261014" in lines and "DTEND;VALUE=DATE:20261015" in lines
    assert "DTSTART:20261015T140000Z" in lines and "DTEND:20261015T150000Z" in lines
    assert "SUMMARY:Follow up: Acme Robotics — Staff Engineer" in lines
    assert "SUMMARY:Interview: Acme Robotics — Staff Engineer" in lines
    assert "DTSTAMP:20261012T090000Z" in lines and "URL:https://acme.example/jobs/1" in lines
    desc = next(x for x in lines if x.startswith("DESCRIPTION:Next step"))
    assert desc == ("DESCRIPTION:Next step: Panel interview Thu 10/15 10:00 AM ET\\; bring portfolio\\, slides\\n"
                    "Posting: https://acme.example/jobs/1\\njobwatch key: manual:acmerobotics:1")
    assert not any(x.startswith("BEGIN:VALARM") for x in lines)


def test_lines_fold_at_75_octets_without_splitting_characters():
    rows = [(job("Globex", "Ingénieur · " + "é" * 120), rec(follow_up="2026-10-14"))]
    text = ics.calendar(rows, today=TODAY, now=NOW)
    physical = text.split("\r\n")[:-1]
    assert max(len(x.encode()) for x in physical) <= 75
    assert any(x.startswith(" ") for x in physical)
    assert "SUMMARY:Follow up: Globex — Ingénieur · " + "é" * 120 in unfold(text)


def test_escaping():
    assert ics._escape("a,b;c\\d\ne\r\nf") == "a\\,b\\;c\\\\d\\ne\\nf"


def test_uids_are_stable_and_distinct():
    a = (job("Initech", "Engineer"), rec(next_step="call 10/15 3pm ET", follow_up="2026-10-14"))
    b = (job("Initech", "Engineer", id_="2"), rec(next_step="call 10/15 3pm ET", follow_up="2026-10-14"))

    def uids(rows, today, now):
        return [x for x in unfold(ics.calendar(rows, today=today, now=now)) if x.startswith("UID:")]
    first = uids([a, b], TODAY, NOW)
    assert first == uids([a, b], date(2026, 10, 13), datetime(2026, 10, 13, tzinfo=timezone.utc))
    assert len(first) == len(set(first)) == 4
    # the date moving updates the same events
    moved = (a[0], rec(next_step="call 10/16 3pm ET", follow_up="2026-10-15"))
    assert uids([moved], TODAY, NOW) == first[:2]


TWO = "Pat sync Fri 10/23 9:30 AM ET (prep for Sam, comp and timing); Sam Recruiter final round Sun 10/25 5:00 PM ET"


def test_a_next_step_naming_two_meetings_reads_as_two():
    assert meet(TWO) is None  # as one text it has two dates
    found = ics.meetings(TWO, TODAY)
    assert [(m.start.isoformat(), m.label) for m in found] == [("2026-10-23T13:30:00+00:00", "Call"),
                                                              ("2026-10-25T21:00:00+00:00", "Interview")]
    # one meeting reads as before, a clause with no time is dropped, line breaks split too
    assert ics.meetings("call 10/15 3pm ET", TODAY) == [meet("call 10/15 3pm ET")]
    assert len(ics.meetings("call 10/15 3pm ET; final round, time to be set", TODAY)) == 1
    assert len(ics.meetings("call 10/15 3pm ET\nonsite 10/16 1pm ET", TODAY)) == 2
    assert ics.meetings("send references; wait", TODAY) == [] and ics.meetings(None, TODAY) == []


def test_each_meeting_is_an_event_and_the_first_keeps_its_uid():
    one = (job("Initech", "Engineer"), rec(next_step="Pat sync Fri 10/23 9:30 AM ET"))
    two = (one[0], rec(next_step=TWO))

    def uids(row):
        return [x for x in unfold(ics.calendar([row], today=TODAY, now=NOW)) if x.startswith("UID:")]
    before, after = uids(one), uids(two)
    assert len(before) == 1 and len(after) == 2
    assert after[0] == before[0] and after[1] == before[0].replace("-meeting@", "-meeting-2@")


def test_ended_applications_are_left_out_and_unreadable_times_keep_the_follow_up():
    rows = [(job("Acme Robotics", "A", id_="1"), rec("rejected", "call 10/15 3pm ET", "2026-10-14")),
            (job("Acme Robotics", "B", id_="2"), rec("withdrawn", None, "2026-10-14")),
            (job("Globex", "C", id_="3"), rec("screening", "call sometime Thursday", "2026-10-16")),
            (job("Initech", "D", id_="4"), rec("offer", "decide by Friday", None))]
    lines = unfold(ics.calendar(rows, today=TODAY, now=NOW))
    assert [x for x in lines if x.startswith("SUMMARY:")] == ["SUMMARY:Follow up: Globex — C"]


def test_reminders_only_on_timed_events():
    rows = [(job("Acme Robotics", "A"), rec("interviewing", "call 10/15 3pm ET", "2026-10-14"))]
    lines = unfold(ics.calendar(rows, today=TODAY, now=NOW, remind=30))
    assert lines.count("BEGIN:VALARM") == 1 and "TRIGGER:-PT30M" in lines
    assert lines.index("BEGIN:VALARM") > lines.index("SUMMARY:Call: Acme Robotics — A")
    assert "BEGIN:VALARM" not in ics.calendar(rows, today=TODAY, now=NOW)


def test_remind_setting(tmp_path):
    p = tmp_path / "w.yaml"
    p.write_text("companies: [lever:globex]\n")
    assert config.load(p).calendar.remind == 0
    p.write_text("companies: [lever:globex]\ncalendar: {remind: 30}\n")
    assert config.load(p).calendar.remind == 30
    for bad in ("calendar: {remind: -5}", "calendar: {remind: soon}", "calendar: {minutes: 5}", "calendar: 5"):
        p.write_text(f"companies: [lever:globex]\n{bad}\n")
        with pytest.raises(config.ConfigError, match="calendar"):
            config.load(p)


@pytest.fixture
def tracked(watchlist):
    store = Store(config.load(watchlist).state)
    store.add("Acme Robotics", "Staff Engineer", url="https://acme.example/jobs/1", status="interviewing",
              next_step="Panel interview Thu 10/15 10:00 AM ET", follow_up="2026-10-14")
    store.add("Globex", "Engineer", status="rejected", follow_up="2026-10-14")
    store.close()
    return watchlist


def test_calendar_command(tracked, capsys, tmp_path):
    cli.main(["-c", str(tracked), "calendar"])
    out = capsys.readouterr().out
    assert out.startswith("BEGIN:VCALENDAR\r\n") and "Follow up: Acme Robotics" in out and "Globex" not in out
    target = tmp_path / "jobwatch.ics"
    cli.main(["-c", str(tracked), "calendar", "-o", str(target)])
    assert target.read_bytes().decode() == out and "Wrote" in capsys.readouterr().err


def test_calendar_command_uses_the_reminder_setting(tracked, capsys):
    tracked.write_text(tracked.read_text() + "calendar: {remind: 15}\n")
    cli.main(["-c", str(tracked), "calendar"])
    assert "TRIGGER:-PT15M" in capsys.readouterr().out


def test_feed_is_served_at_a_secret_address(server, tracked):
    status, body = request(server, "GET", "/api/calendar", headers={"X-Jobwatch-Token": TOKEN})
    path = json.loads(body)["path"]
    assert status == 200 and path.startswith("/calendar/") and path.endswith(".ics")
    assert request(server, "GET", "/api/calendar")[0] == 403  # the address is only given to the page
    # a calendar app sends no token header: the secret in the address is the credential
    status, body, headers = request(server, "GET", path, with_headers=True)
    assert status == 200 and headers["Content-Type"].startswith("text/calendar")
    assert b"SUMMARY:Follow up: Acme Robotics" in body and b"Globex" not in body
    # the same address next time, so a subscription keeps working
    assert json.loads(request(server, "GET", "/api/calendar", headers={"X-Jobwatch-Token": TOKEN})[1])["path"] == path
    secret = path[len("/calendar/"):-len(".ics")]
    for bad in ("/calendar/wrong.ics", "/calendar/.ics", f"/calendar/{secret}x.ics", f"/calendar/{secret[:-1]}.ics",
                f"/calendar/{secret}"):
        assert request(server, "GET", bad)[0] == 404
    # and only under this machine's own name
    assert request(server, "GET", path, host="evil.example")[0] == 403
