import json
from datetime import date, datetime, timedelta, timezone

import pytest
import yaml

from jobwatch import config, watch
from jobwatch.score import resume_id
from jobwatch.store import Store
from jobwatch.web import ApiError, App

from .conftest import TOKEN, request


@pytest.fixture
def app(watchlist):
    return App(watchlist)


def test_first_run_has_no_watchlist_until_saved(tmp_path, web):
    app = App(tmp_path / "new" / "config.yaml")
    assert app.get_settings({})["exists"] is False
    with pytest.raises(ApiError, match="No watchlist yet"):
        app.get_digest({})
    hits = app.post_find({"company": "Initech"})
    assert hits[0]["source"] == "ashby" and hits[0]["sample_titles"] == ["Staff Data Engineer"]
    app.post_settings({"companies": [{"source": "ashby", "board": "initech", "name": "Initech"}],
                       "filters": {"locations": ["remote", "Denver"]}, "keywords": {"RAG": 3}})
    s = app.get_settings({})
    assert s["exists"] and s["companies"] == [{"source": "ashby", "board": "initech", "name": "Initech"}]
    assert app.post_fetch({})["new"] == 1  # the unlisted role is skipped


def test_save_keeps_other_keys_and_a_backup(app, watchlist):
    before = watchlist.read_text()
    app.post_settings({"filters": {"titles": ["engineer"]}})
    raw = yaml.safe_load(watchlist.read_text())
    assert raw["filters"] == {"titles": ["engineer"]} and raw["state"] == "state.db" and len(raw["companies"]) == 3
    assert (watchlist.parent / "jobwatch.yaml.bak").read_text() == before


def test_a_bad_setting_leaves_the_file_alone(app, watchlist):
    before = watchlist.read_text()
    with pytest.raises(config.ConfigError, match="min_pay"):
        app.post_settings({"filters": {"min_pay": 1}})
    assert watchlist.read_text() == before
    assert not list(watchlist.parent.glob("*.new"))


def test_display_settings(app, watchlist):
    cfg = config.load(watchlist)
    assert (cfg.theme, cfg.width) == ("system", "standard") and app.get_settings({})["display"] == {}
    app.post_settings({"display": {"theme": "dark", "width": "wide"}})
    cfg = config.load(watchlist)
    assert (cfg.theme, cfg.width) == ("dark", "wide")
    assert app.get_settings({})["display"] == {"theme": "dark", "width": "wide"}
    assert yaml.safe_load(watchlist.read_text())["filters"]  # the rest of the watchlist is kept
    for bad, key in (({"theme": "sepia"}, "theme"), ({"width": "huge"}, "width")):
        with pytest.raises(config.ConfigError, match=rf"display\.{key}"):
            app.post_settings({"display": bad})
    assert config.load(watchlist).theme == "dark"


def test_digest_marks_new_jobs_seen_and_queue_flow(app, web):
    app.post_fetch({})
    first = app.get_digest({})
    assert [j["status"] for j in first["jobs"]] == ["new"] * 3
    # Today's "Where" control reads this
    assert all(j["where"] in (["remote"], ["onsite"], ["remote", "onsite"], []) for j in first["jobs"])
    assert {j["status"] for j in app.get_digest({})["jobs"]} == {"shown"}
    app.post_mark({"keys": ["c1"], "status": "queued", "note": "referral first"})
    queued = app.get_queue({})
    assert [(j["key"], j["note"]) for j in queued] == [("ashby:initech:c1", "referral first")]
    assert "ashby:initech:c1" not in [j["key"] for j in app.get_digest({})["jobs"]]
    app.post_mark({"keys": ["c1"], "status": "applied"})
    assert [j["title"] for j in app.get_jobs({"status": ["applied"]})] == ["Staff Data Engineer"]
    assert app.get_job({"key": ["c1"]})["text"].startswith("# Staff Data Engineer")
    assert app.get_job({"key": ["c1"]})["candidate_home"] is None  # only Workday has one
    with pytest.raises(ApiError):
        app.post_mark({"keys": ["c1"], "status": "bogus"})


def test_score_needs_a_resume(app, web):
    app.post_fetch({})
    with pytest.raises(ApiError, match="Add your resume"):
        app.post_score({"key": "c1"})


def test_details_show_the_fit_score(app, watchlist, web):
    app.post_fetch({})
    got = app.get_job({"key": ["c1"]})
    assert got["fit"] is None and not got["can_score"]  # no resume yet
    app.upload("resume", "cv.md", b"# Jane Doe")
    assert app.get_job({"key": ["c1"]})["can_score"]
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    store.save_score("ashby:initech:c1", resume_id(cfg.resume), {"score": 81, "must_haves_met": 4})
    store.close()
    assert app.get_job({"key": ["c1"]})["fit"]["score"] == 81


def test_uploads(app, watchlist, web):
    csv = ("Notes:\n\nFirst Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
           "Ana,Li,,,Initech,Engineer,x\n")
    assert app.upload("connections", "Connections.csv", csv.encode()) == {"connections": "Connections.csv",
                                                                          "people": 1}
    assert app.upload("resume", "My CV.PDF", b"%PDF-1.4") == {"resume": "resume.pdf"}
    cfg = config.load(watchlist)
    assert cfg.resume == watchlist.parent / "resume.pdf" and cfg.connections.is_file()
    app.post_fetch({})
    assert app.get_digest({})["jobs"][0]["contacts"][0]["name"] == "Ana Li"
    with pytest.raises(ApiError, match=r"\.csv"):
        app.upload("connections", "c.xlsx", b"x")
    with pytest.raises(ApiError, match=r"Connections\.csv"):
        app.upload("connections", "c.csv", b"a,b\n")
    with pytest.raises(ApiError):
        app.upload("state", "state.db", b"x")


def test_page_carries_the_token(server):
    status, html = request(server, "GET", "/")
    assert status == 200 and f'const TOKEN = "{TOKEN}"' in html.decode()


def test_page_has_a_skills_tab(server):
    """Skills to build, with where to learn them, is a tab of its own, and a job's gap chips link to it."""
    page = request(server, "GET", "/")[1].decode()
    assert '<button data-tab="skills">Skills</button>' in page
    assert '"skills", "activity", "settings"]' in page and "skills: renderSkills" in page
    assert 'api("/api/skills"' in page and 'go("skills")' in page


def test_page_has_an_activity_tab(server):
    """What jobwatch did in the background is a tab of its own, read from /api/activity."""
    page = request(server, "GET", "/")[1].decode()
    assert '<button data-tab="activity">Activity<span id="actcount"></span></button>' in page
    assert "activity: renderActivity" in page and "watchNotices();" in page
    # one list at a time: the boards, the emails, then scoring (with pay and logos), which there's most of
    assert '[["boards", "Job Boards"], ["mail", "Gmail"], ["score,pay,logos", "Scored"]]' in page
    status, body = request(server, "GET", "/api/activity?kind=boards&notable=1&since=0",
                           headers={"X-Jobwatch-Token": TOKEN})
    assert status == 200 and json.loads(body)["events"] == [] and set(json.loads(body)) == {"events", "now"}


def test_api_requires_the_token_and_a_local_host(server):
    ok = {"X-Jobwatch-Token": TOKEN}
    assert request(server, "GET", "/api/settings")[0] == 403
    assert request(server, "GET", "/api/settings", headers={"X-Jobwatch-Token": "wrong"})[0] == 403
    # DNS rebinding: right port, someone else's name.
    assert request(server, "GET", "/api/settings", headers=ok, host=f"evil.example:{server}")[0] == 403
    assert request(server, "GET", "/", host=f"evil.example:{server}")[0] == 403
    # The page's own name works; another *.localhost name doesn't.
    assert request(server, "GET", "/api/settings", headers=ok, host=f"jobwatch.localhost:{server}")[0] == 200
    assert request(server, "GET", "/api/settings", headers=ok, host=f"other.localhost:{server}")[0] == 403
    status, data = request(server, "GET", "/api/settings", headers=ok)
    assert status == 200 and len(json.loads(data)["companies"]) == 3
    status, data = request(server, "POST", "/api/fetch", {}, headers=ok, host=f"localhost:{server}")
    assert status == 200 and json.loads(data)["new"] == 5


def test_api_errors_are_json(server):
    ok = {"X-Jobwatch-Token": TOKEN}
    status, data = request(server, "GET", "/api/job?key=nope", headers=ok)
    assert status == 404 and "no job matches" in json.loads(data)["error"]
    assert request(server, "GET", "/api/nothing", headers=ok)[0] == 404
    assert request(server, "POST", "/api/mark", [], headers=ok)[0] == 400


def test_track_applications(app, web):
    app.post_fetch({})
    app.post_mark({"keys": ["c1"], "status": "applied"})
    applied = (date.today() - timedelta(days=10)).isoformat()  # recent: not gone quiet yet
    added = app.post_add({"company": "Umbrella", "title": "Principal Engineer", "applied_at": applied,
                          "next_step": "check in with the recruiter", "follow_up": "2000-01-01"})
    assert added == {"key": "manual:umbrella:principal-engineer", "company": "Umbrella",
                     "title": "Principal Engineer", "read": False}
    app.post_track({"key": "c1", "status": "interviewing", "note": "panel next week", "follow_up": ""})
    d = app.get_applications({})
    rows = {a["key"]: a for a in d["applications"]}
    assert list(rows) == ["manual:umbrella:principal-engineer", "ashby:initech:c1"]  # the due one first
    assert rows["manual:umbrella:principal-engineer"]["due"] and rows["manual:umbrella:principal-engineer"]["manual"]
    assert (rows["ashby:initech:c1"]["status"], rows["ashby:initech:c1"]["note"]) == ("interviewing", "panel next week")
    assert rows["ashby:initech:c1"]["applied_at"] == d["today"]
    with pytest.raises(ApiError, match="status must be"):
        app.post_add({"company": "X", "title": "Y", "status": "skipped"})
    with pytest.raises(ValueError, match="isn't a date"):
        app.post_track({"key": "c1", "follow_up": "soon"})


def test_hidden_counts_what_each_filter_hides(app, web):
    """Today says how many roles the filters hide, by which filter, and lists them on request."""
    app.post_fetch({})
    got = app.get_hidden({})
    assert (got["total"], got["by"], got["jobs"]) == (2, {"excluded": 1, "place": 1}, [])
    assert got["total"] == sum(app.get_digest({})["rejected"].values())  # the same jobs Today leaves out
    place = app.get_hidden({"kind": ["place"]})
    assert [(j["title"], j["company"], j["why"]) for j in place["jobs"]] == [("Account Executive", "Acme", "location")]
    assert place["more"] == 0 and app.get_hidden({"kind": ["excluded"], "limit": ["0"]})["more"] == 1
    with pytest.raises(ApiError, match="kind must be one of"):
        app.get_hidden({"kind": ["salary"]})


def test_hidden_since_lists_what_just_came_in_from_every_filter(app, web):
    """`hidden --since 6h`: what a fetch or an alert email just brought in that the filters keep off Today."""
    app.post_fetch({})
    now = datetime.now(timezone.utc)
    got = app._with_store(lambda cfg, store: watch.hidden(cfg, store, since=now - timedelta(hours=1)))
    assert sorted((j["kind"], j["company"]) for j in got["jobs"]) == [("excluded", "globex"), ("place", "Acme")]
    assert app._with_store(lambda cfg, store: watch.hidden(cfg, store, since=now + timedelta(minutes=1)))["total"] == 0
    assert app._with_store(lambda cfg, store: watch.hidden(cfg, store, "place", since=now - timedelta(hours=1)))[
        "by"] == {"excluded": 1, "place": 1}
    assert app._with_store(lambda cfg, store: watch.hidden(cfg, store, source="lever"))["by"] == {"excluded": 1}
    assert app._with_store(lambda cfg, store: watch.hidden(cfg, store, source="greenhouse"))["by"] == {"place": 1}


def test_a_filter_change_shows_at_once(app, watchlist, web):
    """The filter bar saves through the settings API: the next digest uses the new filters."""
    app.post_fetch({})
    before = {j["title"] for j in app.get_digest({})["jobs"]}
    filters = {**app.get_settings({})["filters"], "min_salary": 250_000}
    app.post_settings({"filters": filters})
    after = {j["title"] for j in app.get_digest({})["jobs"]}
    assert before - after == {"Senior Software Engineer, Platform", "Machine Learning Engineer"}
    assert app.get_hidden({})["by"] == {"excluded": 1, "place": 1, "pay": 2}
    assert yaml.safe_load(watchlist.read_text())["filters"]["exclude_titles"] == ["contract"]  # the rest is kept


def test_exclude_text_is_saved_checked_and_reported_like_excluded_titles(app, web):
    """filters.exclude_text hides a job by its description, counted and listed with the excluded titles."""
    app.post_fetch({})
    before = app.get_hidden({"kind": ["excluded"], "limit": ["50"]})
    with pytest.raises(ValueError, match=r"filters\.exclude_text: '\(red' isn't a valid pattern"):
        app.post_settings({"filters": {**app.get_settings({})["filters"], "exclude_text": ["(red"]}})
    app.post_settings({"filters": {**app.get_settings({})["filters"], "exclude_text": ["python"]}})
    after = app.get_hidden({"kind": ["excluded"], "limit": ["50"]})
    assert after["total"] > before["total"]
    assert {j["why"] for j in after["jobs"]} - {j["why"] for j in before["jobs"]} == {"text matches 'python'"}
    assert app.get_settings({})["filters"]["exclude_text"] == ["python"]
    assert after["total"] == sum(app.get_digest({})["rejected"].values())


def test_an_unknown_source_breaks_only_its_board(app, watchlist, web):
    """A board from a source this version doesn't know (a newer jobwatch's) doesn't take every page down:
    Settings shows it as an error so it can be removed, and checking for jobs skips it."""
    watchlist.write_text(watchlist.read_text().replace("companies:\n", "companies:\n  - nosuch:acme\n"))
    s = app.get_settings({})
    assert s["companies"][0] == {"source": "nosuch", "board": "acme", "name": "", "error": config.UNKNOWN_SOURCE}
    assert all("error" not in c for c in s["companies"][1:])
    r = app.post_fetch({})
    assert r["new"] == 5 and r["errors"] == {"nosuch:acme": config.UNKNOWN_SOURCE}
    assert len(app.get_digest({})["jobs"]) == 3 and app.get_queue({}) == [] and app.get_hidden({})["total"] == 2
    app.post_settings({"filters": {"titles": ["engineer"]}})  # saving something else keeps it
    assert "nosuch:acme" in yaml.safe_load(watchlist.read_text())["companies"]
    app.post_settings({"companies": [c for c in s["companies"] if "error" not in c]})  # Settings' ✕
    assert len(app.get_settings({})["companies"]) == 3 and config.load(watchlist).unknown == []


def test_an_unknown_source_can_be_removed_by_name(watchlist):
    watchlist.write_text(watchlist.read_text().replace("companies:\n", "companies:\n  - nosuch:acme\n"))
    assert [b.board for b in config.load(watchlist).unknown] == ["acme"]
    assert config.remove_board(watchlist, "nosuch:acme").unknown == []
    assert len(config.add_board(watchlist, "workable:hooli").boards) == 4
    with pytest.raises(config.ConfigError, match="unknown source"):
        config.add_board(watchlist, "nosuch:acme")  # a new board still has to be one jobwatch can read


def test_links_without_a_url_are_plain_text(server):
    """A job added by hand with no posting link: its title isn't a link to "" (which reopened jobwatch)."""
    page = request(server, "GET", "/")[1].decode()
    assert 'if (!url || url === "#") return h("span"' in page


def test_page_has_the_filter_bar(server):
    """Today shows the filters in force, edits them in place, and says what they hide."""
    page = request(server, "GET", "/")[1].decode()
    assert "function filterBar(" in page and "function hiddenLine(" in page
    assert 'api("/api/hidden' in page and 'api("/api/settings", { filters' in page
    assert "c.error" in page  # an unknown source shows on its board in Settings
    ok = {"X-Jobwatch-Token": TOKEN}
    status, data = request(server, "GET", "/api/hidden?kind=place", headers=ok)
    assert status == 200 and json.loads(data)["kind"] == "place"
    assert request(server, "GET", "/api/hidden?kind=bogus", headers=ok)[0] == 400
