"""import-list: the jobs on a LinkedIn or Indeed list page (read in the person's browser) counted against what's
tracked, the rest tracked from the company's own board, coverage kept per site. No network: boards are canned (the
`web` fixture), and linkedin.com and indeed.com are never asked for anything."""

import json

import pytest

from jobwatch import cli, config, joblist, suggest
from jobwatch.store import Store
from jobwatch.watch import fetch_all

from .conftest import TOKEN, request


def hooli_board(web, *titles):
    web.responses["https://boards-api.greenhouse.io/v1/boards/hooli/jobs?content=true"] = {"jobs": [
        {"id": 500 + i, "title": t, "company_name": "Hooli", "content": "&lt;p&gt;Build things.&lt;/p&gt;",
         "absolute_url": f"https://job-boards.greenhouse.io/hooli/jobs/{500 + i}",
         "location": {"name": "Remote, United States"}, "offices": [], "metadata": [], "departments": []}
        for i, t in enumerate(titles)]}


def rec(title, company, location="United States (Remote)", id="", source="linkedin", **kw):
    return {"source": source, "id": id, "title": title, "company": company, "location": location, **kw}


@pytest.fixture
def setup(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    fetch_all(cfg, store)  # the watched boards first: Acme's roles are tracked
    hooli_board(web, "Platform Engineer")
    yield cfg, store
    store.close()


LIST = [
    rec("Sr. Software Engineer - Platform (Verified job)", "Acme, Inc.", id="4100000001"),  # Acme's, as it names it
    rec("Platform Engineer", "Hooli", id="4100000002", pay="$120K/yr - $180K/yr"),
    rec("Detection Engineer", "Vandelay Industries", id="4100000003"),                     # no board anywhere
    rec("Data Analyst", "Hooli", "London, UK", id="4100000004"),                            # not on Hooli's board
]


def test_tracked_added_and_unplaced(setup):
    cfg, store = setup
    r = joblist.take(cfg, store, joblist.records(LIST))
    got = {s.record.id: s for s in r.seen}
    assert got["4100000001"].outcome == "tracked" and got["4100000001"].key == "greenhouse:acme:101"
    added = got["4100000002"]
    assert added.outcome == "added" and added.key == "greenhouse:hooli:500" and added.board == "greenhouse:hooli"
    _, record = store.find(added.key)
    assert record["status"] == "new" and record["via"] == "linkedin-list"
    assert "From a LinkedIn job list: https://www.linkedin.com/jobs/view/4100000002/" in record["note"]
    assert got["4100000003"].outcome == "unplaced" and got["4100000003"].why == "no board found under its name"
    assert got["4100000004"].outcome == "unplaced" and got["4100000004"].why == "not on its board"
    assert got["4100000004"].board == "greenhouse:hooli"
    # Unplaced jobs are tracked from the list, with their link on the site, for the backfill to find later
    kept, rec_ = store.find(got["4100000003"].key)
    assert kept.url == "https://www.linkedin.com/jobs/view/4100000003/" and rec_["via"] == "linkedin-list"
    assert got["4100000003"].key in {j.key for j, _ in store.textless_alert_jobs()}
    c = r.counts("linkedin")
    assert (c["seen"], c["tracked"], c["added"], c["unplaced"], c["coverage"]) == (4, 1, 1, 2, 0.25)
    text = joblist.summary(r)
    assert "LinkedIn: seen 4 job(s), 1 already tracked, 1 added" in text and "Coverage: 25%" in text
    assert "Vandelay Industries: Detection Engineer (United States (Remote))  no board found" in text


def test_with_two_boards_under_the_name_the_job_goes_on_the_one_that_lists_it(setup, web):
    """"Hooli" finds greenhouse:hooli and greenhouse:hoolisecurity: each job is placed on the board with its title,
    never on the first one found."""
    cfg, store = setup
    web.responses["https://boards-api.greenhouse.io/v1/boards/hoolisecurity/jobs?content=true"] = {"jobs": [
        {"id": 900, "title": "Security Engineer", "company_name": "Hooli Security", "content": "&lt;p&gt;x&lt;/p&gt;",
         "absolute_url": "https://job-boards.greenhouse.io/hoolisecurity/jobs/900", "location": {"name": "Remote"},
         "offices": [], "metadata": [], "departments": []}]}
    r = joblist.take(cfg, store, joblist.records([rec("Security Engineer", "Hooli", id="4100000011"),
                                                  rec("Platform Engineer", "Hooli", id="4100000012")]))
    assert [(s.outcome, s.key) for s in r.seen] == [("added", "greenhouse:hoolisecurity:900"),
                                                    ("added", "greenhouse:hooli:500")]


def test_the_filters_decide_the_digest_not_what_is_tracked(setup, web):
    cfg, store = setup
    hooli_board(web, "Contract Platform Engineer")  # the watchlist leaves contract roles out
    r = joblist.take(cfg, store, joblist.records([rec("Contract Platform Engineer", "Hooli", id="4100000009")]))
    assert r.seen[0].outcome == "added" and r.seen[0].filtered
    assert store.find(r.seen[0].key)[1]["status"] == "new"


def test_companies_seen_count_toward_watching_their_boards(setup):
    cfg, store = setup
    joblist.take(cfg, store, joblist.records(LIST))
    names = {row["company"] for row in store.unwatched()}
    assert {"hooli", "vandelayindustries"} <= names and "acme" not in names  # Acme's board is watched
    hooli = next(s for s in suggest.suggestions(cfg, store, limit=0) if s.company == "hooli")
    assert hooli.entry == "greenhouse:hooli" and hooli.found_by == "posting"


def test_a_list_seen_again_counts_earlier_imports_apart(setup):
    cfg, store = setup
    joblist.take(cfg, store, joblist.records(LIST))
    r = joblist.take(cfg, store, joblist.records(LIST))
    assert [s.outcome for s in r.seen] == ["tracked", "earlier", "earlier", "earlier"]
    assert r.counts()["coverage"] == 1.0  # of the jobs it hadn't been handed before
    runs = joblist.history(cfg)
    assert [h["coverage"] for h in runs] == [0.25, 1.0] and runs[0]["unplaced_jobs"][0]["company"] == \
        "Vandelay Industries"


def test_a_job_kept_as_listed_moves_onto_its_board_when_a_later_import_finds_it(setup, web):
    """"Data Analyst" isn't on Hooli's board the first time; once it is (or the matching is looser), importing the
    list again gives the tracked entry the board's posting, without a second entry."""
    cfg, store = setup
    first = joblist.take(cfg, store, joblist.records(LIST))
    key = next(s.key for s in first.seen if s.record.id == "4100000004")
    assert not store.find(key)[0].description
    hooli_board(web, "Platform Engineer", "Data Analyst")
    dry = joblist.take(cfg, store, joblist.records(LIST), dry_run=True)
    assert dry.counts()["upgraded"] == 1 and not store.find(key)[0].description
    assert "1 job(s) an earlier import kept as listed would be moved" in joblist.summary(dry)
    before = len(list(store.jobs(include_closed=True)))
    r = joblist.take(cfg, store, joblist.records(LIST))
    mine = next(s for s in r.seen if s.record.id == "4100000004")
    assert mine.outcome == "earlier" and mine.upgraded and mine.board == "greenhouse:hooli"
    kept, record = store.find(key)
    assert kept.description == "Build things." and "greenhouse" in kept.url and record["via"] == "linkedin-list"
    assert len(list(store.jobs(include_closed=True))) == before
    # the one with no board anywhere is still said to be unplaced
    assert "Vandelay Industries: Detection Engineer  no board found" in joblist.summary(r)


def test_a_dry_run_records_nothing(setup):
    cfg, store = setup
    r = joblist.take(cfg, store, joblist.records(LIST), dry_run=True)
    assert r.counts()["added"] == 1 and "would be added" in joblist.summary(r)
    assert not store.has("greenhouse:hooli:500") and joblist.history(cfg) == []


def test_coverage_is_per_site(setup):
    cfg, store = setup
    r = joblist.take(cfg, store, joblist.records([
        LIST[0], rec("Platform Engineer", "Hooli", "Remote", id="a1b2c3d4e5f60001", source="indeed")]))
    assert r.counts("linkedin")["coverage"] == 1.0 and r.counts("indeed")["coverage"] == 0.0
    assert set(r.to_dict()["by_source"]) == {"linkedin", "indeed"}
    assert store.find("greenhouse:hooli:500")[1]["via"] == "indeed-list"
    assert [h["source"] for h in joblist.history(cfg)] == ["linkedin", "indeed"]
    assert [h["source"] for h in joblist.history(cfg, "indeed")] == ["indeed"]
    text = joblist.history_text(joblist.history(cfg))
    assert "LinkedIn, all runs: 100% of 1 job(s)" in text and "Indeed, all runs: 0% of 1 job(s)" in text


def test_an_indeed_job_is_never_read_from_indeed(setup, web):
    cfg, store = setup
    r = joblist.take(cfg, store, joblist.records([rec("Detection Engineer", "Vandelay", id="a1b2c3d4e5f60002",
                                                      source="indeed")]))
    assert r.seen[0].outcome == "unplaced"
    assert store.find(r.seen[0].key)[0].url == "https://www.indeed.com/viewjob?jk=a1b2c3d4e5f60002"
    assert not [u for u in web.calls if "indeed.com" in u or "linkedin.com" in u]


def test_records_from_the_extractor():
    got = joblist.records(json.dumps({"records": [
        {"linkedin_id": "4100000001", "title": "Platform Engineer  (Verified job)", "company": " Initech "},
        {"linkedin_id": "4100000001", "title": "Platform Engineer", "company": "Initech"},  # twice on the page
        {"source": "indeed", "id": "a1b2c3", "title": "Analyst", "company": "Globex", "pay": "$60 an hour"},
        {"title": "No company"}, "not a record"]}))
    assert [(r.source, r.id, r.title, r.company) for r in got] == [
        ("linkedin", "4100000001", "Platform Engineer", "Initech"), ("indeed", "a1b2c3", "Analyst", "Globex")]
    assert got[1].url == "https://www.indeed.com/viewjob?jk=a1b2c3"
    with pytest.raises(ValueError, match="list of job records"):
        joblist.records('{"x": 1}')
    with pytest.raises(ValueError, match="source"):
        joblist.records([{"source": "https://evil", "title": "A", "company": "B"}])


def test_the_cli(setup, watchlist, tmp_path, capsys):
    cli.main(["import-list", "--script"])
    assert "JWList" in capsys.readouterr().out
    path = tmp_path / "list.json"
    path.write_text(json.dumps(LIST))
    cli.main(["-c", str(watchlist), "import-list", str(path)])
    assert "Coverage: 25%" in capsys.readouterr().out
    cli.main(["-c", str(watchlist), "import-list", "--history"])
    assert "LinkedIn, last 7 days: 25% of 4 job(s)" in capsys.readouterr().out


def test_the_extension_imports_a_list_with_its_token(server, web):
    hooli_board(web, "Platform Engineer")
    token = json.loads(request(server, "GET", "/api/extension", headers={"X-Jobwatch-Token": TOKEN})[1])["token"]
    ok = {"X-Jobwatch-Extension": token}
    assert "import-list" in json.loads(request(server, "GET", "/ext/ping", headers=ok)[1])["features"]
    body = {"records": LIST[1:3]}
    assert request(server, "POST", "/ext/import-list", body)[0] == 403
    status, data = request(server, "POST", "/ext/import-list", body, headers=ok)
    got = json.loads(data)
    assert status == 200 and got["by_source"]["linkedin"]["added"] == 1
    assert [j["company"] for j in got["unplaced"]] == ["Vandelay Industries"] and "Coverage: 0%" in got["summary"]
    status, data = request(server, "POST", "/ext/import-list", {"records": "nope"}, headers=ok)
    assert status == 400
