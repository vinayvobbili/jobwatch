"""The same opening tracked twice: matched by a shared req or posting id (the same opening) or by title alone
(possibly the same), and flagged everywhere it shows, never hidden."""

import asyncio
import hashlib
import json
import sqlite3

import pytest

from jobwatch import alerts, cli, config, dupes
from jobwatch.dupes import Signature, company_key, same_opening, title_key
from jobwatch.models import Job
from jobwatch.store import Store
from jobwatch.watch import build_digest, fetch_all, queue, save_job

from .conftest import TOKEN, request

AVATURE = "jobs.initech.com/careers"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state.db")
    yield s
    s.close()


def board_job(id_, title="Solutions Engineer", source="avature", board=AVATURE, company="Initech", **kw):
    url = kw.pop("url", f"https://{board}/JobDetail/{title.replace(' ', '-')}/{id_}")
    return Job(source=source, company=board, id=id_, title=title, url=url, company_name=company, **kw)


def sig(job, note=""):
    return Signature.of(job, note)


def manual(company, title, url="", description=""):
    return Job(source="manual", company=company.lower(), id=title.lower().replace(" ", "-"), title=title, url=url,
               company_name=company, description=description)


# -- Names and titles

def test_company_names_set_aside_case_punctuation_and_suffixes():
    assert company_key("Hooli Investments") == company_key("hooli") == company_key("HOOLI, Inc.") == "hooli"
    assert company_key("Initech Holdings, LLC") == company_key("The Initech Group") == "initech"
    assert company_key("Pied Piper Technologies") == "piedpiper"
    assert company_key("Hewlett Packard Enterprise") != company_key("hpe")  # a different name stays different
    assert company_key("Group") == "group"  # a suffix alone is the name


def test_titles_set_aside_dashes_reqs_workplace_and_seniority():
    a = title_key("Senior Data Platform Engineer — Payments")
    b = title_key("Data Platform Engineer - Payments (482913)")
    assert a[0] == b[0] == "data platform engineer payments"
    assert a[1] == {"senior"} and b[1] == set()
    assert title_key("Solutions Engineer (Remote)")[0] == title_key("Solutions Engineer")[0]
    assert title_key("Data Engineer (Hybrid - Austin)")[0] == "data engineer"
    assert title_key("Data Engineer, Remote US")[0] == "data engineer"
    assert title_key("Sr. Data Engineer II [R-0123456]") == ("data engineer", frozenset({"senior", "ii"}))
    assert title_key("Platform Engineer (Python)")[0] == "platform engineer python"  # not a req, not a place


# -- Ids

def test_reqs_from_titles_notes_and_posting_text():
    assert sig(manual("Acme", "Engineer (482913)")).reqs == {"482913"}
    assert sig(manual("Acme", "Engineer", description="Job ID: 20769. Requisition ID: R0123456")).reqs == {
        "20769", "123456"}
    assert sig(manual("Acme", "Engineer"), "req 4711; also JR12345 and REQ-88123").reqs == {"4711", "12345",
                                                                                         "88123"}
    # Dates, years and plain numbers aren't reqs.
    assert sig(manual("Acme", "Summer Intern (2026)"), "2026-04-01: called; 12 offices; $98,500").reqs == set()


def test_ids_from_known_links():
    def ids(url):
        return sig(manual("Acme", "Engineer", url=url)).ids

    assert ids("https://acme.wd5.myworkdayjobs.com/External/job/Austin/Engineer_R0123456") == {"123456"}
    assert ids("https://acme.wd5.myworkdayjobs.com/External/job/Austin/Engineer_R0123456-1") == {"123456"}
    assert ids(f"https://{AVATURE}/JobDetail/Solutions-Engineer/61542") == {"61542"}
    assert ids("https://job-boards.greenhouse.io/acme/jobs/4012345") == {"4012345"}
    assert ids("https://jobs.lever.co/acme/AAAA-1111-bbbb") == {"aaaa-1111-bbbb"}
    assert ids("https://jobs.ashbyhq.com/acme/c1d2e3f4-0000") == {"c1d2e3f4-0000"}
    assert ids("https://jobs.smartrecruiters.com/Acme/744000012345678-engineer") == {"744000012345678"}
    assert ids("https://www.linkedin.com/jobs/view/4100000001/") == {"linkedin:4100000001"}
    assert ids("https://acme.example.com/careers/engineer") == set()


def test_ids_in_a_note_count_even_without_their_https():
    note = ("Applied to WD00200431. Reposted 2026-03-20 as WD00207765 "
            "(jobs.initech.com JobDetail/Solutions-Engineer/61542), pay now lower; old req gone.")
    s = sig(manual("Initech", "Solutions Engineer (Remote)"), note)
    assert s.ids == s.note_ids == {"200431", "207765", "61542"}
    assert s.reposted_as == {"207765", "61542"}  # what "reposted" names, to the end of its sentence
    linked = sig(manual("Acme", "Engineer"), "the real posting: jobs.lever.co/acme/0c1d2e3f-aaaa-1111")
    assert "0c1d2e3f-aaaa-1111" in linked.ids


# -- Matching

def test_the_same_req_under_two_titles_is_the_same_opening():
    applied = sig(manual("Umbrella", "Data Platform Engineer - Payments (482913)"))
    later = sig(manual("Umbrella", "Senior Data Platform Engineer — Payments"), "Official posting: req 482913")
    assert same_opening(later, applied) == "same req 482913"
    assert same_opening(sig(manual("Umbrella", "Senior Data Platform Engineer — Payments")), applied) == "same title"


def test_a_note_about_a_second_opening_is_not_a_match():
    """Two jobs, each posted under its own req: a note on one naming the other's req is a cross-reference."""
    principal = sig(manual("Umbrella", "Principal Architect (R0811234)"),
                    "Recruiter suggests this one instead of the Staff role (R0822345)")
    staff = sig(manual("Umbrella", "Staff Software Engineer (R0822345)"))
    assert same_opening(principal, staff) is None
    asked = sig(manual("Umbrella", "Advisory Engineer (WD00203344)"),
                "Asked whether the other application carries over to WD00207765")
    noted = sig(manual("Umbrella", "Field Engineer"), "posting: req WD00207765")
    assert same_opening(asked, noted) == "same req 207765"  # the other shows no req of its own: it may be this one
    shown = sig(manual("Umbrella", "Field Engineer (WD00207765)"))
    assert same_opening(asked, shown) is None
    # but a note that says it was reposted as the other's req is the same opening, whatever reqs both show
    old = sig(manual("Umbrella", "Field Engineer (R200431)"), "Reposted as R207765.")
    new = sig(manual("Umbrella", "Field Engineer (R207765)"))
    assert same_opening(new, old) == "reposted as req 207765"
    # and a note about the repost on a second opening isn't
    assert same_opening(sig(manual("Umbrella", "Advisory Engineer (R203344)"), "carries over to R207765?"),
                        old) is None


def test_a_title_alone_is_conservative():
    def match(a, b):
        return same_opening(sig(a), sig(b))

    assert match(manual("Acme", "Senior Data Engineer"), manual("Acme", "Staff Data Engineer")) is None
    assert match(manual("Acme", "Data Engineer"), manual("Globex", "Data Engineer")) is None
    assert match(manual("Acme", "Engineer"), manual("Acme", "Senior Engineer")) is None  # one word: too generic
    assert match(manual("Acme", "Data Engineer (R11111)"), manual("Acme", "Data Engineer (R22222)")) is None
    # two postings on one board are two postings, whatever their titles
    assert match(board_job("61535"), board_job("61536")) is None
    assert match(manual("Acme Inc.", "Data Engineer"), manual("acme", "Senior Data Engineer")) == "same title"


def test_a_postings_copy_is_the_same_req():
    a = board_job("R0123456", "Data Engineer", source="workday", board="acme.wd5/External", company="Acme",
                  url="https://acme.wd5.myworkdayjobs.com/External/job/Austin/Data-Engineer_R0123456")
    b = board_job("R0123456-1", "Data Engineer", source="workday", board="acme.wd5/External", company="Acme",
                  url="https://acme.wd5.myworkdayjobs.com/External/job/Denver/Data-Engineer_R0123456-1")
    assert same_opening(sig(a), sig(b)) == "same req 123456"


# -- In the store

def test_an_alert_import_of_a_job_applied_to_is_flagged(store):
    applied = store.add("Umbrella", "Data Platform Engineer - Payments (482913)", applied="2026-02-11")
    again = store.add("Umbrella", "Senior Data Platform Engineer — Payments", status="queued")
    m = dupes.check(store, again.key)
    assert m.other.key == applied.key and not m.strong
    assert m.label == "Possible duplicate of your 2026-02-11 application: check it's a different opening"
    assert applied.key in m.line and "same title" in m.line
    store.add_note(again.key, "2026-04-01: Official posting: req 482913")  # found later: now it's sure
    m = dupes.check(store, again.key)
    assert m.strong and m.why == "same req 482913" and m.label == "Already applied 2026-02-11"
    assert m.line == (f"Already applied 2026-02-11: same opening as Data Platform Engineer - Payments (482913) "
                      f"({applied.key}; same req 482913). Don't apply or ask for a referral again")
    # and the other way around: the application knows about the queued one
    assert dupes.check(store, applied.key).label == f"Already queued {store.find(again.key)[1]['status_at'][:10]}"


def test_of_many_postings_with_one_title_only_the_reposted_one_is_the_same_opening(store):
    """A board posting one title per opening: the posting a note names is the repost, the rest only might be."""
    app = store.add("Initech", "Solutions Engineer (Remote)", applied="2026-03-02",
                    note="Applied to WD00200431. Reposted 2026-03-20 as WD00207765 "
                         "(jobs.initech.com JobDetail/Solutions-Engineer/61542)")
    postings = [board_job(i) for i in ("61535", "61536", "61539", "61542", "61560")]
    store.sync("avature", AVATURE, postings)
    found = dupes.record(store, postings)
    assert set(found) == {p.key for p in postings}  # all of them match
    strong = {k for k, m in found.items() if m.strong}
    assert strong == {f"avature:{AVATURE}:61542"}
    rows = {j.key: r for j, r in store.jobs()}
    assert {k for k, r in rows.items() if r["duplicate_of"]} == strong  # only the strong one is recorded
    assert rows[f"avature:{AVATURE}:61542"]["duplicate_of"] == app.key
    repost = found[f"avature:{AVATURE}:61542"]
    assert repost.reposted and repost.why == "reposted as req 61542"
    assert repost.label == "Reposted: you applied 2026-03-02 (old req 200431)"  # not one it was reposted as
    assert "carries over" in repost.line
    maybe = found[f"avature:{AVATURE}:61535"]
    assert maybe.label.startswith("Possible duplicate of your 2026-03-02 application")


def test_a_repost_names_the_old_req_when_the_application_has_one(store):
    store.add("Initech", "Solutions Engineer (R200431)", applied="2026-03-02",
              note="Reposted as jobs.initech.com/careers/JobDetail/Solutions-Engineer/61542")
    store.sync("avature", AVATURE, [new := board_job("61542")])
    assert dupes.check(store, new.key).label == "Reposted: you applied 2026-03-02 (old req 200431)"


def test_queued_and_skipped_matches_say_so(store):
    store.add("Acme", "Data Engineer (R-55501)", status="queued")
    store.sync("lever", "acme", [twin := Job("lever", "acme", "x1", "Data Engineer", "https://jobs.lever.co/acme/x1",
                                             company_name="Acme", description="Requisition ID: R-55501")])
    m = dupes.record(store, [twin])[twin.key]
    assert m.strong and m.label.startswith("Already queued ") and m.line.endswith("Don't queue it twice")
    store.add("Globex", "ML Platform Engineer", status="skipped")
    m = dupes.check(store, store.add("Globex", "Senior ML Platform Engineer", status="queued").key)
    assert m.label.startswith("Possible duplicate of a job you skipped ")


def test_an_application_beats_a_queued_or_skipped_match_and_an_id_beats_a_title(store):
    store.add("Acme", "Data Engineer", status="skipped")
    store.add("Acme", "Senior Data Engineer", applied="2026-08-01")
    by_id = store.add("Acme", "Analytics Engineer (R-77001)", status="queued")
    new = store.add("Acme", "Data Engineer, Analytics", status="queued", note="req R-77001")
    assert dupes.check(store, new.key).other.key == by_id.key  # an id over the application's title
    m = dupes.check(store, store.add("Acme", "Staff Data Engineer", status="queued").key)
    assert m.status == "skipped" and not m.strong  # Staff isn't Senior; the skipped one has no level: maybe
    m = dupes.check(store, store.add("Acme", "Data Engineer (Remote)", status="queued").key)
    assert m.status == "applied"  # both match by title: the application first


def test_nothing_is_hidden_from_the_digest(watchlist, web):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    store.add("Initech", "Staff AI Engineer", applied="2026-09-20", note="posting: jobs.ashbyhq.com/initech/c1")
    fetch_all(cfg, store)
    d = build_digest(cfg, store, score_top=0)
    entry = next(e for e in d.entries if e.job.key == "ashby:initech:c1")
    assert entry.duplicate.strong and entry.duplicate.label == "Already applied 2026-09-20"
    assert entry.warnings[0] == entry.duplicate.line
    assert "duplicate" not in d.rejected
    assert store.find("c1")[1]["duplicate_of"] == "manual:initech:staff-ai-engineer"  # recorded by the fetch


def test_the_queue_warns_first(watchlist, web):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    fetch_all(cfg, store)
    store.add("Acme", "Senior Software Engineer, Platform (Remote)", applied="2026-09-01")
    store.set_status(["greenhouse:acme:101"], "queued")
    (e,) = queue(cfg, store)
    assert e.duplicate and not e.duplicate.strong
    assert e.warnings[0].startswith("Possible duplicate of your 2026-09-01 application")


def test_adding_a_job_records_its_duplicate(store):
    applied = store.add("Umbrella", "Field Engineer (R-31337)", applied="2026-09-02")
    job, _ = save_job(store, company="Umbrella", title="Senior Field Engineer", text="Req ID: R-31337")
    assert store.find(job.key)[1]["duplicate_of"] == applied.key


def test_alert_imports_flag_what_was_applied_to(watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    # Not the alert's titles (those would be tracked already): one by its LinkedIn link, one by title.
    app = store.add("Acme", "Software Engineer III, Platform Team", applied="2026-09-03",
                    note="Found on LinkedIn: https://www.linkedin.com/jobs/view/4100000001/")
    umbrella = store.add("Umbrella", "Senior Field Engineer", status="skipped")
    r = alerts.intake(cfg, store, alerts.read([str(alerts_fixture("linkedin.eml"))]), follow=False)
    out = {f.alert.title: f for f in r.found}
    same = out["Senior Software Engineer, Platform"]
    assert same.result == "new" and same.same.strong and same.same.other.key == app.key
    assert store.find(same.key)[1]["duplicate_of"] == app.key
    assert out["Field Engineer"].same.other.key == umbrella.key
    d = alerts.to_dict(r)
    flagged = {f["title"]: f["duplicate_of"] for f in d["found"]}
    assert flagged["Senior Software Engineer, Platform"]["label"] == "Already applied 2026-09-03"
    assert flagged["Account Executive"] is None
    assert "Already applied 2026-09-03" in alerts.summary(r, every=True)
    assert same.key in {e.job.key for e in build_digest(cfg, store, score_top=0).entries}  # still on Today


def alerts_fixture(name):
    from .test_alerts import FIXTURES

    return FIXTURES / name


def test_pairs_list_whats_in_the_store(store):
    app = store.add("Umbrella", "Data Platform Engineer - Payments (482913)", applied="2026-02-11")
    later = store.add("Umbrella", "Senior Data Platform Engineer — Payments", status="skipped",
                      note="req 482913")
    store.sync("avature", AVATURE, [board_job("61535")])
    store.add("Initech", "Solutions Engineer (Remote)", applied="2026-03-02")
    found = dupes.pairs(store)
    assert [(p.a.key, p.b.key, p.why) for p in found] == [
        (app.key, later.key, "same req 482913"),
        ("manual:initech:solutions-engineer-remote", f"avature:{AVATURE}:61535", "same title")]
    assert [p.why for p in dupes.pairs(store, strong_only=True)] == ["same req 482913"]
    text = dupes.pairs_text(found)
    assert "Umbrella: same opening (same req 482913)" in text and "possibly the same opening" in text
    assert "1 the same opening, 1 possibly" in text
    assert dupes.pair_dict(found[0])["jobs"][0] == {
        "key": app.key, "company": "Umbrella", "title": app.title, "status": "applied", "date": "2026-02-11",
        "closed": False}


# -- Where it shows

@pytest.fixture
def twice(watchlist):
    """The test watchlist's store with one application and a later job for the same req."""
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    app = store.add("Umbrella", "Data Platform Engineer - Payments (482913)", applied="2026-02-11")
    later = store.add("Umbrella", "Senior Data Platform Engineer — Payments", status="skipped", note="req 482913")
    store.close()
    return app.key, later.key


def run(capsys, *argv):
    cli.main(list(argv))
    return capsys.readouterr().out


def test_cli_show_mark_add_and_dupes(watchlist, twice, capsys):
    app, later = twice
    c = ["-c", str(watchlist)]
    assert "Check: Already applied 2026-02-11: same opening as" in run(capsys, *c, "show", later)
    out = run(capsys, *c, "mark", "queued", later)
    assert f"{later}: queued" in out and "Check: Already applied 2026-02-11" in out  # queued all the same
    assert "Check: Already applied" not in run(capsys, *c, "mark", "skipped", later)
    out = run(capsys, *c, "add", "Umbrella", "Data Platform Engineer, Payments", "--status", "queued")
    assert "Check: Possible duplicate of your 2026-02-11 application" in out
    out = run(capsys, *c, "dupes")
    assert "Umbrella: same opening (same req 482913)" in out and app in out and later in out
    assert "possibly the same opening" in out
    out = run(capsys, *c, "dupes", "--strong")
    assert "same req 482913" in out and "possibly the same opening" not in out
    assert "**Check:** Possible duplicate of your 2026-02-11 application" in run(capsys, *c, "queue")


def test_dupes_changes_nothing_not_even_an_older_state_file(tmp_path, capsys):
    """An older version's file (no duplicate_of column) is read as it is: `dupes` never writes."""
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE jobs (key TEXT PRIMARY KEY, source TEXT NOT NULL, company TEXT NOT NULL, data TEXT "
               "NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, closed TEXT, status TEXT NOT NULL "
               "DEFAULT 'new', status_at TEXT, note TEXT, applied_at TEXT, next_step TEXT, follow_up TEXT, via TEXT)")
    for job, status, applied, note in ((manual("Umbrella", "Data Engineer (R-12345)"), "applied", "2026-02-11", ""),
                                       (manual("Umbrella", "Sr Data Engineer"), "new", None, "req 12345")):
        db.execute("INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, NULL, NULL, NULL)",
                   (job.key, job.source, job.company, json.dumps(job.to_dict()), "2026-02-11",
                    "2026-02-11", status, "2026-02-11T00:00:00", note, applied))
    db.commit()
    db.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path / "w.yaml").write_text(f"companies: [greenhouse:acme]\nstate: {path}\n")
    out = run(capsys, "-c", str(tmp_path / "w.yaml"), "dupes")
    assert "same req 12345" in out
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    # and with no state file yet, it says so rather than making one
    (tmp_path / "none.yaml").write_text(f"companies: [greenhouse:acme]\nstate: {tmp_path / 'missing.db'}\n")
    with pytest.raises(SystemExit, match="no jobs tracked yet"):
        cli.main(["-c", str(tmp_path / "none.yaml"), "dupes"])
    assert not (tmp_path / "missing.db").exists()


def test_mcp_tools_flag_duplicates(watchlist, twice, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    app, later = twice
    d = mcp.get_job(later)["duplicate_of"]
    assert d["key"] == app and d["status"] == "applied" and d["date"] == "2026-02-11" and d["strong"]
    assert mcp.get_job(app)["duplicate_of"]["key"] == later  # skipped later: "skipped before"
    said = mcp.mark_job(later, "queued")
    assert said.startswith(f"{later}: queued. Check: Already applied 2026-02-11")
    (q,) = mcp.list_queued_jobs()
    assert q["duplicate_of"]["key"] == app and q["warnings"][0].startswith("Already applied")
    pairs = mcp.find_duplicates()
    assert [p["why"] for p in pairs] == ["same req 482913"] and pairs[0]["strong"]
    assert "Possible duplicate" in mcp.add_application("Umbrella", "Data Platform Engineer: Payments",
                                                       status="queued")
    tools = {t.name: t for t in asyncio.run(mcp.server.list_tools())}
    assert tools["find_duplicates"].annotations.read_only_hint
    assert "find_duplicates" in mcp.server.instructions and "duplicate_of" in mcp.server.instructions


def test_the_page_shows_and_warns(twice, server):
    app, later = twice
    ok = {"X-Jobwatch-Token": TOKEN}
    status, data = request(server, "GET", f"/api/job?key={later}", headers=ok)
    assert status == 200 and json.loads(data)["duplicate_of"]["label"] == "Already applied 2026-02-11"
    status, data = request(server, "POST", "/api/mark", {"keys": [later], "status": "queued"}, headers=ok)
    assert json.loads(data)["warning"].startswith("Already applied 2026-02-11")  # and it's queued
    status, data = request(server, "GET", "/api/queue", headers=ok)
    (q,) = json.loads(data)
    assert q["duplicate_of"]["key"] == app and q["warnings"][0].startswith("Already applied")
