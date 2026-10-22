"""The Interviews tab: which next steps are interviews coming up, the prep sheets linked to them, the page."""

import os
from datetime import date

import pytest

from jobwatch import config, interviews
from jobwatch.models import Job
from jobwatch.store import Store
from jobwatch.web import App

from .conftest import request

TODAY = date(2026, 10, 12)  # a Monday


def job(company, title, id_="1"):
    return Job(source="manual", company=company.lower().replace(" ", ""), id=id_, title=title, url="",
               company_name=company)


def rec(status="interviewing", next_step=None, follow_up=None):
    return {"status": status, "next_step": next_step, "follow_up": follow_up, "note": None}


def test_interviews_today_first_then_the_next_two_weeks_then_the_unscheduled():
    rows = [(job("Globex", "Later", "1"), rec(next_step="Panel interview Thu 10/15 10:00 AM ET")),
            (job("Acme", "Today", "2"), rec(next_step="call 10/12 2:00 PM")),
            (job("Initech", "Unset", "3"), rec(next_step="onsite loop, recruiter to schedule", follow_up="2026-10-13")),
            (job("Hooli", "Past", "4"), rec(next_step="interview Fri 10/9 1:00 PM")),
            (job("Umbrella", "Too far", "5"), rec(next_step="interview 11/20 1:00 PM")),
            (job("Stark", "Ended", "6"), rec("rejected", "interview 10/13 1:00 PM")),
            (job("Wayne", "Not a meeting", "7"), rec(next_step="send references", follow_up="2026-10-12")),
            (job("Cyberdyne", "Stale unscheduled", "8"), rec(next_step="final round", follow_up="2026-10-01")),
            (job("Soylent", "Still hoping", "9"), rec("applied", "wait for a recruiter screen", "2026-10-12")),
            (job("Tyrell", "Applied, timed", "10"), rec("applied", "recruiter screen 10/13 9:00 AM"))]
    found = interviews.upcoming(rows, today=TODAY)
    assert [i.job.title for i in found] == ["Today", "Applied, timed", "Later", "Unset"]
    assert [i.day.isoformat() for i in found] == ["2026-10-12", "2026-10-13", "2026-10-15", "2026-10-13"]
    assert found[3].meeting is None
    d = interviews.to_dict(found[0], None)
    assert (d["scheduled"], d["label"], d["start"], d["zoned"]) == (True, "Call", "2026-10-12T14:00:00", False)
    assert interviews.to_dict(found[3], None)["scheduled"] is False


def test_a_next_step_with_two_meetings_is_listed_twice():
    step = "Pat sync Wed 10/14 9:30 AM ET (prep, comp and timing); final round Sun 10/25 5:00 PM ET"
    rows = [(job("Acme", "Two", "1"), rec(next_step=step, follow_up="2026-10-14")),
            (job("Globex", "Half", "2"), rec(next_step="sync Thu 10/15 1:00 PM ET; final round, time to be set"))]
    found = interviews.upcoming(rows, today=TODAY, ahead=30)
    assert [(i.job.title, i.day.isoformat()) for i in found] == [("Two", "2026-10-14"), ("Half", "2026-10-15"),
                                                                 ("Two", "2026-10-25")]
    assert not any(i.meeting is None for i in found)  # it has times, so not "not scheduled yet"
    assert [interviews.to_dict(i, None)["start"][:10] for i in found if i.job.title == "Two"] == [
        "2026-10-14", "2026-10-25"]
    assert [i.day.isoformat() for i in interviews.upcoming(rows[:1], today=TODAY, ahead=5)] == ["2026-10-14"]  # window
    # the details chip shows the one still to come: the first until it has ended, then the last
    future = "sync 10/14/2099 9:30 AM ET; final round 10/25/2099 5:00 PM ET"
    assert interviews.meeting_dict(future, TODAY)["start"].startswith("2099-10-14")
    past = "sync 10/9/2020 9:30 AM ET; final round 10/10/2020 5:00 PM ET"
    assert interviews.meeting_dict(past, TODAY)["start"].startswith("2020-10-10")
    half = "sync 10/9/2020 9:30 AM ET; final round 10/10/2099 5:00 PM ET"
    assert interviews.meeting_dict(half, TODAY)["start"].startswith("2099-10-10")


def sheet_dir(tmp_path):
    folder = tmp_path / "prep"
    folder.mkdir()
    for name, age in (("acme-screen.html", 200), ("acme-onsite.html", 100), ("acme.htm", 300),
                      ("acmecorp-panel.html", 0), ("acme-notes.txt", 0), ("globex-call.html", 0)):
        (folder / name).write_text("<html><head><link rel='stylesheet' href='prep.css'></head><body>hi</body></html>")
        t = 1_800_000_000 - age
        os.utime(folder / name, (t, t))
    (folder / "prep.css").write_text("body { color: red }")
    return folder


def test_prep_sheets_are_matched_by_the_start_of_their_name(tmp_path):
    folder = sheet_dir(tmp_path)
    assert interviews.sheets(folder, "Acme") == ["acme-onsite.html", "acme-screen.html", "acme.htm"]  # newest first
    assert interviews.sheets(folder, "Initech", "globex") == ["globex-call.html"]  # either of a company's names
    assert interviews.sheets(folder, "") == [] and interviews.sheets(None, "Acme") == []
    assert interviews.sheets(tmp_path / "missing", "Acme") == []


def test_only_files_directly_in_the_sheets_folder_are_served(tmp_path):
    folder = sheet_dir(tmp_path)
    assert interviews.sheet_file(folder, "acme-onsite.html") == ((folder / "acme-onsite.html").resolve(),
                                                                "text/html; charset=utf-8")
    assert interviews.sheet_file(folder, "prep.css")[1] == "text/css"  # what a sheet links to, next to it
    (folder / "inside").mkdir()
    (folder / "inside" / "x.html").write_text("x")
    (tmp_path / "outside.html").write_text("x")
    (folder / "link.html").symlink_to(tmp_path / "outside.html")
    for bad in ("../outside.html", "inside/x.html", "acme-notes.txt", "nope.html", "link.html",
                str(tmp_path / "outside.html")):
        with pytest.raises(FileNotFoundError):
            interviews.sheet_file(folder, bad)
    with pytest.raises(FileNotFoundError, match=r"prep\.sheets"):
        interviews.sheet_file(None, "acme-onsite.html")


def test_the_sheets_folder_is_read_next_to_the_watchlist(watchlist):
    watchlist.write_text(watchlist.read_text() + "prep:\n  sheets: prep\n")
    assert config.load(watchlist).prep.sheets == watchlist.parent / "prep"
    watchlist.write_text(watchlist.read_text().replace("sheets: prep", "sheets: [prep]"))
    with pytest.raises(config.ConfigError, match=r"prep\.sheets is a folder"):
        config.load(watchlist)


def test_the_page_lists_interviews_with_their_sheets(watchlist, tmp_path, web):
    sheet_dir(tmp_path)
    watchlist.write_text(watchlist.read_text() + "prep:\n  sheets: prep\n")
    app = App(watchlist)
    key = app.post_add({"company": "Acme", "title": "Staff Engineer", "status": "interviewing",
                        "next_step": f"Interview with Sam {date.today():%m/%d} 11:59 PM",
                        "follow_up": date.today().isoformat()})["key"]
    d = app.get_interviews({})
    assert d["sheets_folder"] == str(tmp_path / "prep")
    [iv] = d["interviews"]
    assert (iv["key"], iv["day"], iv["scheduled"]) == (key, d["today"], True)
    assert iv["sheets"] == ["acme-onsite.html", "acme-screen.html", "acme.htm"]
    def slow(*a):
        raise AssertionError("an application isn't in the scorer's line: its details don't work that out")
    app.scorer.reasons = slow
    j = app.get_job({"key": [key]})
    assert j["unscored"]["code"] in ("no_text", "no_resume", "manual")
    assert j["sheets"] == iv["sheets"] and j["meeting"]["day"] == d["today"] and j["next_step"].startswith("Interview")
    base = d["sheets_base"]
    assert j["sheets_base"] == base and base.startswith("/prep/") and base.endswith("/")
    secret = base.split("/")[2]
    assert app.prep_file(secret, "acme-onsite.html")[1].startswith("text/html")
    assert app.prep_file("wrong", "acme-onsite.html") is None and app.prep_file(secret, "../jobwatch.yaml") is None
    Store(tmp_path / "state.db").set_status([key], "rejected")
    assert app.get_interviews({})["interviews"] == [] and app.get_job({"key": [key]})["meeting"] is None


def test_page_has_an_interviews_tab(server):
    """Interviews coming up are a tab of their own, a card opens the job's details, and sheets open in a new tab."""
    page = request(server, "GET", "/")[1].decode()
    assert '<button data-tab="interviews">Interviews<span id="ivcount"></span></button>' in page
    assert '"today", "interviews", "queue"' in page and "interviews: renderInterviews" in page
    assert 'api("/api/interviews")' in page and "openDetails(iv.key)" in page
    assert "sheetButtons(j.sheets, j.sheets_base)" in page and "sheetButtons(iv.sheets, d.sheets_base)" in page


def test_the_sheets_folder_is_served_sandboxed_with_byte_ranges(server, watchlist, tmp_path):
    folder = sheet_dir(tmp_path)
    (folder / "acme-drill.mp4").write_bytes(bytes(range(100)))
    watchlist.write_text(watchlist.read_text() + "prep:\n  sheets: prep\n")
    base = App(watchlist).get_interviews({})["sheets_base"]
    status, body, headers = request(server, "GET", base + "acme-onsite.html", with_headers=True)
    assert status == 200 and b"hi" in body and headers["Content-Security-Policy"] == "sandbox"
    assert request(server, "GET", base + "prep.css")[1] == b"body { color: red }"
    status, body, headers = request(server, "GET", base + "acme-drill.mp4", headers={"Range": "bytes=10-19"},
                                    with_headers=True)
    assert (status, body, headers["Content-Range"]) == (206, bytes(range(10, 20)), "bytes 10-19/100")
    assert request(server, "GET", base + "acme-drill.mp4", headers={"Range": "bytes=-5"})[1] == bytes(range(95, 100))
    assert request(server, "GET", base + "acme-drill.mp4", headers={"Range": "bytes=200-"})[0] == 416
    assert request(server, "GET", "/prep/wrong/acme-onsite.html")[0] == 404
    assert request(server, "GET", base + "..%2Fjobwatch.yaml")[0] == 404
