"""The Interviews tab: which next steps are interviews coming up, the prep sheets linked to them, the page."""

import os
from datetime import date

import pytest

from jobwatch import config, interviews
from jobwatch.models import Job
from jobwatch.store import Store
from jobwatch.web import ApiError, App

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


def test_a_sheet_opens_with_its_styles_and_no_scripts(tmp_path):
    folder = sheet_dir(tmp_path)
    page = interviews.sheet(folder, "acme-onsite.html")
    assert "<style>\nbody { color: red }\n</style>" in page and "prep.css" not in page
    assert page.index("script-src 'none'") < page.index("<style>")  # in the head, before anything else
    (folder / "inside").mkdir()
    (folder / "inside" / "x.html").write_text("x")
    (tmp_path / "outside.html").write_text("x")
    for bad in ("../outside.html", "inside/x.html", "prep.css", "acme-notes.txt", "nope.html",
                str(tmp_path / "outside.html")):
        with pytest.raises(FileNotFoundError):
            interviews.sheet(folder, bad)
    with pytest.raises(FileNotFoundError, match=r"prep\.sheets"):
        interviews.sheet(None, "acme-onsite.html")


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
    assert "script-src 'none'" in app.get_prep_sheet({"name": ["acme-onsite.html"]})["html"]
    with pytest.raises(ApiError, match="no prep sheet"):
        app.get_prep_sheet({"name": ["../jobwatch.yaml"]})
    Store(tmp_path / "state.db").set_status([key], "rejected")
    assert app.get_interviews({})["interviews"] == [] and app.get_job({"key": [key]})["meeting"] is None


def test_page_has_an_interviews_tab(server):
    """Interviews coming up are a tab of their own, a card opens the job's details, and sheets open in a new tab."""
    page = request(server, "GET", "/")[1].decode()
    assert '<button data-tab="interviews">Interviews<span id="ivcount"></span></button>' in page
    assert '"today", "interviews", "queue"' in page and "interviews: renderInterviews" in page
    assert 'api("/api/interviews")' in page and "openDetails(iv.key)" in page
    assert 'api("/api/prep/sheet?name="' in page and "sheetButtons(j.sheets)" in page
