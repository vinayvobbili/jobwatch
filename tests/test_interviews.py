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


def test_an_application_gets_its_own_sheets_among_its_companys(tmp_path):
    folder = tmp_path / "prep"
    folder.mkdir()
    for name in ("globex-31245-pat.html", "globex-40769-technical.html", "globex-platform-engineer.html",
                 "globex-tips.html"):
        (folder / name).write_text("<h1>prep</h1>")
    job = Job(source="manual", company="globex", id="architect-job-31245", title="Architect (Job 31245)", url="",
              company_name="Globex")
    named = {"note": "Booked Fri. Prep sheet: prep/globex-31245-pat.html", "next_step": "Talk with Pat Fri"}
    assert interviews.job_sheets(folder, job, named) == ["globex-31245-pat.html"]  # the one its note names
    # none named: the newest, less the sheet for another opening's number
    for name, age in (("globex-31245-pat.html", 30), ("globex-platform-engineer.html", 20), ("globex-tips.html", 10)):
        os.utime(folder / name, (1_800_000_000 - age,) * 2)
    assert interviews.job_sheets(folder, job, {"note": None}) == ["globex-tips.html"]
    assert interviews.job_sheet(None, job, named) is None and interviews.job_sheets(folder, job, {}) == [
        "globex-tips.html"]


def _page(folder, name, role=None, title=None, extra=""):
    marker = f'<meta name="jobwatch-prep-role" content="{role}">' if role else ""
    (folder / name).write_text(f"<html><head><meta charset='utf-8'><title>{title or name}</title>{marker}{extra}"
                               "</head><body>hi</body></html>")


def test_a_pages_role_is_read_from_its_marker_with_fallbacks_for_older_pages(tmp_path):
    _page(tmp_path, "acme-role.html", "module")
    _page(tmp_path, "acme-loop-playlist.html", "playlist")
    _page(tmp_path, "acme-loop.html")
    _page(tmp_path, "acme-loop-rehearse.html", "rehearse")
    _page(tmp_path, "acme-old-rehearse.html", title="Rehearse: Acme")  # written before the marker existed
    _page(tmp_path, "acme-old-playlist.html")
    _page(tmp_path, "acme-run-sheet.html", extra='<meta name="prep-sheet" content="companion">')
    _page(tmp_path, "acme-odd.html", "nonsense")
    got = {p.name: interviews.sheet_role(p) for p in tmp_path.iterdir()}
    assert got == {"acme-role.html": "module", "acme-loop-playlist.html": "playlist", "acme-loop.html": "sheet",
                   "acme-loop-rehearse.html": "rehearse", "acme-old-rehearse.html": "rehearse",
                   "acme-old-playlist.html": "playlist", "acme-run-sheet.html": "companion", "acme-odd.html": "sheet"}
    assert interviews.sheet_info(tmp_path / "acme-loop.html") == ("sheet", "acme-loop.html")
    assert interviews.sheet_info(tmp_path / "gone.html") == ("sheet", "gone")  # unreadable: a sheet by its file name
    # only the first ROLE_BYTES are read: a marker far down the page is not found, so it's cheap on a long sheet
    _page(tmp_path, "acme-long.html", extra="<style>" + "x" * interviews.ROLE_BYTES + "</style>"
          '<meta name="jobwatch-prep-role" content="module">')
    assert interviews.sheet_role(tmp_path / "acme-long.html") == "sheet"


def test_a_card_links_one_sheet_never_a_module_playlist_or_rehearse_page(tmp_path):
    folder = tmp_path / "prep"
    folder.mkdir()
    pages = {"acme-12345-hm.html": None, "acme-12345-hm-playlist.html": "playlist",
             "acme-12345-hm-rehearse.html": "rehearse", "acme-teams.html": "module", "acme-roles.html": "module",
             "acme-67890-screen.html": None, "acme-old.html": None}
    for age, (name, role) in enumerate(pages.items()):
        _page(folder, name, role, title=f"Title of {name}")
        os.utime(folder / name, (1_800_000_000 - age * 10,) * 2)  # in the order given, newest first
    os.utime(folder / "acme-teams.html", (1_800_000_100,) * 2)  # a module is the very newest file
    job = Job(source="manual", company="acme", id="lead-67890", title="Lead", url="", company_name="Acme")

    def pick(note=None, step=None):
        return interviews.job_sheets(folder, job, {"note": note, "next_step": step})

    assert pick() == ["acme-67890-screen.html"]  # not the newest page, not another posting's, not a module
    # the sheet the note names, whatever it is: the last one labelled "Prep sheet:", else the first named
    assert pick("Prep sheet: prep/acme-old.html") == ["acme-old.html"]
    assert pick("Prep sheet: prep/acme-old.html", "then prep/acme-12345-hm.html") == ["acme-old.html"]
    assert pick("2026-11-01: Prep sheet: prep/acme-old.html. 2026-11-02: Prep sheet: acme-12345-hm.html") == [
        "acme-12345-hm.html"]  # a note's newest line comes last
    assert pick("see acme-old.html and acme-12345-hm.html") == ["acme-old.html"]  # first by position, not by age
    assert pick(None, "prep sheet acme-12345-hm.html") == ["acme-12345-hm.html"]  # the colon is optional
    # naming a rehearse page, a playlist or a module only: they are never the chip, so the default applies
    assert pick("prep for the call: prep/acme-12345-hm-rehearse.html, drill clips acme-12345-hm-playlist.html "
                "and acme-teams.html") == ["acme-67890-screen.html"]
    # ...but a sheet named after them still is the one
    assert pick("practice acme-12345-hm-rehearse.html, sheet acme-12345-hm.html") == ["acme-12345-hm.html"]
    assert pick("see xacme-old.html") == ["acme-67890-screen.html"]  # a name inside another name isn't a mention
    _page(folder, "sam-screen.html")  # not named for the company: only a note can link it
    assert pick("Prep sheet: prep/sam-screen.html") == ["sam-screen.html"] and "sam-screen.html" not in pick()
    assert interviews.job_sheets(tmp_path / "missing", job, {}) == []


def test_only_files_directly_in_the_sheets_folder_are_served(tmp_path):
    folder = sheet_dir(tmp_path)
    assert interviews.sheet_file(folder, "acme-onsite.html") == ((folder / "acme-onsite.html").resolve(),
                                                                "text/html; charset=utf-8")
    assert interviews.sheet_file(folder, "prep.css")[1] == "text/css"  # what a sheet links to, next to it
    (folder / "player.js").write_text("// the sheet's script")
    assert interviews.sheet_file(folder, "player.js")[1].startswith("text/javascript")
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
    assert iv["sheets"] == ["acme-onsite.html"] and iv["sheet"] == "acme-onsite.html"  # the newest, one
    assert iv["sheet_title"] == "acme onsite"  # no <title> in the page: its name as words
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
    assert '"/api/interviews"' in page and "openDetails(iv.key)" in page
    assert "sheetChip(j, j.sheets_base)" in page and "sheetChip(iv, d.sheets_base)" in page


def test_a_sheets_web_links_open_in_new_tabs(server, watchlist, tmp_path):
    folder = sheet_dir(tmp_path)
    (folder / "acme-links.html").write_text(
        "<a href='https://example.com/a'>a</a> <a class=x href=http://example.com/b>b</a> "
        "<a href='#notes'>c</a> <a href='prep.css'>d</a> <a target=_self href='https://example.com/e'>e</a>")
    watchlist.write_text(watchlist.read_text() + "prep:\n  sheets: prep\n")
    base = App(watchlist).get_interviews({})["sheets_base"]
    status, body, headers = request(server, "GET", base + "acme-links.html", with_headers=True)
    new_tab = '<a target="_blank" rel="noopener"'
    assert status == 200 and body.decode() == (
        f"{new_tab} href='https://example.com/a'>a</a> {new_tab} class=x href=http://example.com/b>b</a> "
        "<a href='#notes'>c</a> <a href='prep.css'>d</a> <a target=_self href='https://example.com/e'>e</a>")
    assert int(headers["Content-Length"]) == len(body)


def test_the_sheets_folder_is_served_sandboxed_with_byte_ranges(server, watchlist, tmp_path):
    folder = sheet_dir(tmp_path)
    (folder / "acme-drill.mp4").write_bytes(bytes(range(100)))
    watchlist.write_text(watchlist.read_text() + "prep:\n  sheets: prep\n")
    base = App(watchlist).get_interviews({})["sheets_base"]
    status, body, headers = request(server, "GET", base + "acme-onsite.html", with_headers=True)
    assert status == 200 and b"hi" in body and headers["Content-Security-Policy"] == interviews.SHEET_POLICY
    assert "allow-scripts" in interviews.SHEET_POLICY and "allow-same-origin" not in interviews.SHEET_POLICY
    status, body, headers = request(server, "GET", base + "prep.css", with_headers=True)
    assert body == b"body { color: red }" and headers["Content-Security-Policy"] == "sandbox"
    status, body, headers = request(server, "GET", base + "acme-drill.mp4", headers={"Range": "bytes=10-19"},
                                    with_headers=True)
    assert (status, body, headers["Content-Range"]) == (206, bytes(range(10, 20)), "bytes 10-19/100")
    assert request(server, "GET", base + "acme-drill.mp4", headers={"Range": "bytes=-5"})[1] == bytes(range(95, 100))
    assert request(server, "GET", base + "acme-drill.mp4", headers={"Range": "bytes=200-"})[0] == 416
    assert request(server, "GET", "/prep/wrong/acme-onsite.html")[0] == 404
    assert request(server, "GET", base + "..%2Fjobwatch.yaml")[0] == 404
