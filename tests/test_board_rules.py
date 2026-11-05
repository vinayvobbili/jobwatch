"""Boards watched by rule, not by hand: suggestions.auto_watch adds a board when one of the company's jobs is on it and
the company is worth watching; slow boards are read less often; a board that stops answering is said once. No
network: the boards are canned (the `web` fixture)."""

from datetime import datetime, timedelta, timezone

import pytest
import yaml

from jobwatch import cli, config, report, sources, suggest, watch
from jobwatch.store import Store
from jobwatch.watch import save_job

from .conftest import FakeWeb, iso

HOOLI = "https://api.lever.co/v0/postings/hooli?mode=json"
UMBRELLA = "https://boards-api.greenhouse.io/v1/boards/umbrella/jobs?content=true"
JIBE = "https://careers.wayne.example/api/jobs?page=1&limit=100"
ACME = "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
NOW = datetime.now(timezone.utc)


def lever_job(title):
    return {"id": title.lower().replace(" ", "-"), "text": title,
            "hostedUrl": f"https://jobs.lever.co/hooli/{title.lower().replace(' ', '-')}",
            "categories": {"location": "Remote (United States)", "allLocations": ["Remote (United States)"]},
            "workplaceType": "remote", "descriptionPlain": "Python services.", "lists": []}


def jibe_page(*titles, **fields):
    return {"totalCount": len(titles), "jobs": [
        {"data": {"req_id": str(100 + i), "slug": str(100 + i), "title": t, "location_name": "Remote",
                  "posted_date": iso(1), "description": "Python.", **fields}} for i, t in enumerate(titles)]}


@pytest.fixture
def rules(watchlist):
    """The test watchlist with auto_watch on."""
    watchlist.write_text(watchlist.read_text() + "suggestions: {auto_watch: true}\n")
    return watchlist


def added(cfg, store, company, title, link="", status="queued", location="Remote"):
    return save_job(store, company=company, title=title, status=status, location=location, boards=cfg.boards,
                    link=link)[0]


def watching(path):
    return {b.entry for b in config.load(path).boards}


# -- The rules

def test_off_unless_asked(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    added(cfg, store, "Hooli", "Platform Engineer")
    added(cfg, store, "Hooli", "Data Platform Engineer")
    web.calls.clear()
    assert suggest.auto_watch(cfg, store) == (cfg, [])
    assert web.calls == []
    with pytest.raises(config.ConfigError, match=r"suggestions\.auto_watch is true or false"):
        config.save(watchlist, {"suggestions": {"auto_watch": "yes please"}})


def test_two_matching_jobs_on_the_board_add_it(web, rules):
    web.responses[HOOLI] = [lever_job("Senior Data Platform Engineer")]
    cfg = config.load(rules)
    store = Store(cfg.state)
    added(cfg, store, "Hooli", "Senior Data Platform Engineer")
    added(cfg, store, "Hooli", "Principal Data Platform Engineer")
    _, got = suggest.auto_watch(cfg, store)
    assert [s.entry for s in got] == ["lever:hooli"] and "lever:hooli" in watching(rules)
    assert suggest.why_watched(cfg, got[0]) == "2 matching jobs"
    assert rules.with_name("jobwatch.yaml.bak").exists()  # rewritten the way add_board does


def test_one_job_alone_is_only_a_suggestion(web, rules):
    web.responses[HOOLI] = [lever_job("Senior Data Platform Engineer")]
    cfg = config.load(rules)
    store = Store(cfg.state)
    added(cfg, store, "Hooli", "Senior Data Platform Engineer")
    web.calls.clear()
    assert suggest.auto_watch(cfg, store)[1] == []
    assert web.calls == []  # nothing looked up for a company the rules don't take


def test_an_application_or_a_nearby_office_is_enough(web, rules):
    web.responses[HOOLI] = [lever_job("Senior Data Platform Engineer")]
    cfg = config.load(rules)
    store = Store(cfg.state)
    added(cfg, store, "Hooli", "Senior Data Platform Engineer", status="applied")
    _, got = suggest.auto_watch(cfg, store)
    assert [s.name for s in got] == ["Hooli"] and suggest.why_watched(cfg, got[0]) == "you applied there"

    rules.write_text(rules.read_text().replace("filters:\n", "filters:\n  nearby_offices: [Umbrella]\n"))
    web.responses[UMBRELLA] = {"jobs": [{
        "id": 501, "title": "Staff Field Service Engineer", "company_name": "Umbrella",
        "absolute_url": "https://job-boards.greenhouse.io/umbrella/jobs/501", "location": {"name": "Remote"},
        "offices": [], "metadata": [], "departments": [], "first_published": iso(2), "content": "Python."}]}
    cfg = config.load(rules)
    added(cfg, store, "Umbrella", "Staff Field Service Engineer")
    _, got = suggest.auto_watch(cfg, store)
    assert [s.name for s in got] == ["Umbrella"] and suggest.why_watched(cfg, got[0]) == "an office near you"


def test_a_board_guessed_from_the_name_needs_one_of_the_companys_titles(web, rules):
    # lever:hooli answers under the name, but it's another Hooli: none of these jobs are on it
    web.responses[HOOLI] = [lever_job("Pastry Chef")]
    cfg = config.load(rules)
    store = Store(cfg.state)
    added(cfg, store, "Hooli", "Senior Data Platform Engineer")
    added(cfg, store, "Hooli", "Principal Data Platform Engineer")
    assert suggest.auto_watch(cfg, store)[1] == [] and "lever:hooli" not in watching(rules)
    row = next(r for r in store.unwatched() if r["company"] == "hooli")
    assert (row["entry"], row["found_by"]) == ("lever:hooli", "name")  # still suggested, for the person to judge


def test_a_short_title_does_not_prove_a_guessed_board(web, rules):
    web.responses[HOOLI] = [lever_job("Software Engineer")]
    cfg = config.load(rules)
    store = Store(cfg.state)
    added(cfg, store, "Hooli", "Software Engineer")
    added(cfg, store, "Hooli", "Software Engineer", location="Denver")
    added(cfg, store, "Hooli", "Data Engineer")
    assert suggest.auto_watch(cfg, store)[1] == []


def test_a_careers_site_on_the_companys_own_domain_is_found_from_a_jobs_link(web, rules, monkeypatch):
    # A Jibe site whose job pages don't look like one, whose page still links an old ATS with nothing on it
    link = "https://careers.wayne.example/jobs/101/job"
    monkeypatch.setattr(sources, "get_text", FakeWeb({
        "https://careers.wayne.example/robots.txt": "",
        link: '<a href="https://careers-wayne.icims.com/jobs/search">Search</a>'}))
    web.responses[JIBE] = jibe_page("Staff Security Engineer", "Teller",
                                    canonical_url="https://careers.wayne.example/jobs/100?lang=en-us")
    cfg = config.load(rules)
    store = Store(cfg.state)
    added(cfg, store, "Wayne Enterprises", "Staff Security Engineer", status="applied")
    store.set_url("manual:wayne-enterprises:staff-security-engineer", link)
    _, got = suggest.auto_watch(cfg, store)
    assert [s.entry for s in got] == ["jibe:careers.wayne.example"]


def test_linkedin_and_indeed_are_never_read(web, rules, monkeypatch):
    pages = FakeWeb({})
    monkeypatch.setattr(sources, "get_text", pages)
    cfg = config.load(rules)
    store = Store(cfg.state)
    job = added(cfg, store, "Wayne Enterprises", "Staff Security Engineer", status="applied")
    store.set_url(job.key, "https://www.linkedin.com/jobs/view/1234")
    other = added(cfg, store, "Wayne Enterprises", "Principal Security Engineer", status="applied")
    store.set_url(other.key, "https://www.indeed.com/viewjob?jk=abc")
    suggest.auto_watch(cfg, store)
    assert not [u for u in [*pages.calls, *web.calls] if "linkedin" in u or "indeed" in u]


def test_robots_txt_is_kept_to(web, rules, monkeypatch):
    link = "https://careers.wayne.example/jobs/101/job"
    monkeypatch.setattr(sources, "get_text", FakeWeb({
        "https://careers.wayne.example/robots.txt": "User-agent: *\nDisallow: /jobs/\n"}))
    web.responses[JIBE] = jibe_page("Staff Security Engineer")
    cfg = config.load(rules)
    store = Store(cfg.state)
    job = added(cfg, store, "Wayne Enterprises", "Staff Security Engineer", status="applied")
    store.set_url(job.key, link)
    assert suggest.auto_watch(cfg, store)[1] == []
    assert JIBE not in web.calls


def test_a_company_is_looked_into_once_a_week(web, rules):
    cfg = config.load(rules)
    store = Store(cfg.state)
    added(cfg, store, "Hooli", "Senior Data Platform Engineer")
    added(cfg, store, "Hooli", "Principal Data Platform Engineer")
    suggest.auto_watch(cfg, store)
    web.calls.clear()
    assert suggest.auto_watch(cfg, store)[1] == [] and web.calls == []
    web.responses[HOOLI] = [lever_job("Senior Data Platform Engineer")]
    assert suggest.auto_watch(cfg, store)[1] == []  # found under no board yet: waits for its week
    later = NOW + suggest.AUTO_RETRY + timedelta(hours=1)
    job = added(cfg, store, "Hooli", "Staff Platform Engineer", link="")
    store.set_url(job.key, "https://jobs.lever.co/hooli/staff-platform-engineer")  # its link names the board
    assert [s.entry for s in suggest.auto_watch(cfg, store, now=later)[1]] == ["lever:hooli"]


def test_the_most_a_check_adds_and_looks_into(web, rules, monkeypatch):
    monkeypatch.setattr(suggest, "AUTO_ADDS", 1)
    monkeypatch.setattr(suggest, "AUTO_LOOKS", 1)
    cfg = config.load(rules)
    store = Store(cfg.state)
    for company in ("Hooli", "Umbrella", "Vandelay"):
        store.note_unwatched(suggest.company_id(company), company, added(cfg, store, company, "Senior Data Engineer",
                                                                         status="applied").key)
    looked = []
    monkeypatch.setattr(suggest, "find_job_board", lambda st, s, *a: looked.append(s.name))
    assert suggest.auto_watch(cfg, store)[1] == [] and len(looked) == 1
    store.set_unwatched_board("hooli", "lever:hooli", "posting")
    store.set_unwatched_board("umbrella", "greenhouse:umbrella", "posting")
    assert len(suggest.auto_watch(cfg, store)[1]) == 1


def test_a_dismissed_company_stays_out(web, rules):
    web.responses[HOOLI] = [lever_job("Senior Data Platform Engineer")]
    cfg = config.load(rules)
    store = Store(cfg.state)
    added(cfg, store, "Hooli", "Senior Data Platform Engineer", status="applied")
    suggest.dismiss(store, "Hooli")
    assert suggest.auto_watch(cfg, store)[1] == []


def test_two_names_for_one_board_add_it_once(web, rules):
    cfg = config.load(rules)
    store = Store(cfg.state)
    for name in ("Stark", "Stark Financial Group"):
        job = added(cfg, store, name, "Senior Data Engineer", status="applied")
        store.set_url(job.key, "https://stark.wd1.myworkdayjobs.com/Careers/job/Remote/Engineer_R1")
        store.note_unwatched(suggest.company_id(name), name, job.key, "workday:stark.wd1/Careers", "posting")
    assert len(suggest.auto_watch(cfg, store)[1]) == 1


def test_a_check_adds_them_and_says_so(web, rules):
    web.responses[HOOLI] = [lever_job("Senior Data Platform Engineer")]
    cfg = config.load(rules)
    store = Store(cfg.state)
    added(cfg, store, "Hooli", "Senior Data Platform Engineer", status="applied")
    r = watch.fetch_all(cfg, store, by="schedule")
    assert r.watching == ["lever:hooli"] and "now watching: lever:hooli" in report.fetch_summary(r)
    logged = [a for a in store.activity(kind="boards") if a["text"] == "Now watching 1 more board"]
    assert logged and logged[0]["detail"] == ["Hooli: lever:hooli (you applied there)"]
    assert not logged[0]["notable"]  # no need to tell the person
    r = watch.fetch_all(config.load(rules), store)  # the next check reads it
    assert any(k.startswith("lever:hooli:") for k in r.new)


def test_a_failure_adding_boards_never_fails_a_check(web, rules, monkeypatch):
    def broken(*args):
        raise config.ConfigError("the watchlist can't be written")
    monkeypatch.setattr(suggest, "auto_watch", broken)
    cfg = config.load(rules)
    store = Store(cfg.state)
    r = watch.fetch_all(cfg, store)
    assert r.boards == 3 and r.warnings == {"suggestions.auto_watch": "the watchlist can't be written"}


# -- Jibe sites

def test_a_jibe_job_keeps_the_sites_own_link(web):
    web.responses[JIBE] = jibe_page("Engineer", canonical_url="https://careers.wayne.example/jobs/100?lang=en-us")
    assert sources.fetch_jibe("careers.wayne.example")[0].url == "https://careers.wayne.example/jobs/100?lang=en-us"
    web.responses[JIBE] = jibe_page("Engineer", meta={"canonical_url": "https://careers.wayne.example/jobs/100"})
    assert sources.fetch_jibe("careers.wayne.example")[0].url == "https://careers.wayne.example/jobs/100"
    web.responses[JIBE] = jibe_page("Engineer")
    assert sources.fetch_jibe("careers.wayne.example")[0].url == "https://careers.wayne.example/careers-home/jobs/100"


def test_some_other_sites_api_is_not_a_jibe_site(web):
    web.responses[JIBE] = ["not", "jibe"]
    with pytest.raises(sources.SourceError, match="not a Jibe careers site"):
        sources.fetch_jibe("careers.wayne.example")


def test_find_with_a_link_tries_jibe_when_the_boards_on_its_page_are_empty(web, monkeypatch):
    link = "https://careers.wayne.example/jobs/101/job"
    monkeypatch.setattr(sources, "get_text", FakeWeb({
        link: '<a href="https://careers-wayne.icims.com/jobs/search">Search</a>'}))
    web.responses[JIBE] = jibe_page("Staff Security Engineer")
    assert [(s, b) for s, b, _ in sources.probe(link)] == [("jibe", "careers.wayne.example")]
    del web.responses[JIBE]  # not a Jibe site after all, and nothing answers on the board it links to
    assert sources.probe(link) == []


# -- Slow boards

def read_at(store, entry, seconds, days_ago=0, quiet=0):
    store.save_board_read(entry, seconds, 1)
    store.db.execute("UPDATE board_checks SET read_at=?, quiet=? WHERE entry=?",
                     ((NOW - timedelta(days=days_ago)).isoformat(), quiet, entry))
    store.db.commit()


def test_a_slow_board_is_read_every_few_days(web, watchlist):
    cfg = config.load(watchlist)
    assert (cfg.slow_boards.seconds, cfg.slow_boards.every_days) == (120, 2)
    store = Store(cfg.state)
    assert watch.fetch_all(cfg, store).boards == 3  # none timed yet: all of them, and now they are
    assert set(store.board_checks()) == {b.entry for b in cfg.boards}
    read_at(store, "greenhouse:acme", 400, days_ago=1)
    web.calls.clear()
    r = watch.fetch_all(cfg, store)
    assert r.boards == 2 and r.not_due == ["greenhouse:acme"] and ACME not in web.calls
    assert "1 slow board(s) wait for a later check" in report.fetch_summary(r)
    assert store.jobs(("new",)) and any(j.company == "acme" for j, _ in store.jobs(("new",)))  # its jobs stay open
    read_at(store, "greenhouse:acme", 400, days_ago=3)
    assert watch.fetch_all(cfg, store).not_due == []


def test_all_and_reread_read_a_slow_board_anyway(web, watchlist, capsys):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    read_at(store, "greenhouse:acme", 400)
    assert watch.fetch_all(cfg, store, every_board=True).not_due == []
    read_at(store, "greenhouse:acme", 400)
    assert watch.fetch_all(cfg, store, reread=("acme",)).not_due == []
    read_at(store, "greenhouse:acme", 400)
    store.close()
    cli.main(["-c", str(watchlist), "fetch"])
    assert "1 slow board(s) wait" in capsys.readouterr().out
    cli.main(["-c", str(watchlist), "fetch", "--all"])
    assert "slow board" not in capsys.readouterr().out


def test_a_slow_board_that_is_not_answering_stays_due(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    read_at(store, "greenhouse:acme", 400, quiet=1)
    assert watch.boards_due(cfg, store) == cfg.boards


def test_slow_boards_can_be_turned_off(web, watchlist):
    watchlist.write_text(watchlist.read_text() + "slow_boards: {every_days: 0}\n")
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    read_at(store, "greenhouse:acme", 400)
    assert watch.boards_due(cfg, store) == cfg.boards
    for bad, says in (("{every_days: 99}", r"slow_boards\.every_days"), ("{seconds: 0}", r"slow_boards\.seconds"),
                      ("{often: 1}", "unknown slow_boards setting")):
        with pytest.raises(config.ConfigError, match=says):
            config.save(watchlist, {"slow_boards": yaml.safe_load(bad)})


# -- Boards that stop answering

def days_ago(store, entry, days):
    store.db.execute("UPDATE board_checks SET read_at=? WHERE entry=?",
                     ((NOW - timedelta(days=days)).isoformat(), entry))
    store.db.commit()


def test_a_board_that_goes_quiet_is_said_once(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    days_ago(store, "greenhouse:acme", 4)
    web.responses[ACME] = sources.NotFound("gone")
    assert [watch.fetch_all(cfg, store).quiet for _ in range(2)] == [[], []]  # a bad morning: nothing said
    r = watch.fetch_all(cfg, store)
    assert r.quiet == ["greenhouse:acme"] and "moved to another job system" in r.warnings["greenhouse:acme"]
    told = [a for a in store.activity(kind="boards", notable=True)]
    assert told[0]["text"] == "1 board went quiet" and told[0]["detail"][0].startswith("greenhouse:acme: ")
    assert watch.fetch_all(cfg, store).quiet == []  # said once
    web.responses[ACME] = {"jobs": [{
        "id": 7, "title": "Engineer", "company_name": "Acme", "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/7",
        "location": {"name": "Remote"}, "offices": [], "metadata": [], "departments": [], "first_published": iso(1),
        "content": "Python."}]}
    watch.fetch_all(cfg, store)
    assert store.board_checks()["greenhouse:acme"]["quiet"] == 0  # back: it can be said again if it goes again
    assert store.board_checks()["greenhouse:acme"]["told"] is False


def test_a_board_that_comes_back_empty_counts_too(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    days_ago(store, "greenhouse:acme", 4)
    web.responses[ACME] = {"jobs": []}
    for _ in range(2):
        watch.fetch_all(cfg, store)
    assert watch.fetch_all(cfg, store).quiet == ["greenhouse:acme"]


def test_recent_jobs_keep_a_board_from_being_called_quiet(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    web.responses[ACME] = sources.NotFound("gone")
    assert [watch.fetch_all(cfg, store).quiet for _ in range(4)] == [[], [], [], []]  # three checks in one day


def test_no_network_says_nothing_about_any_board(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    for url in list(web.responses):
        web.responses[url] = sources.SourceError("no network")
    assert watch.fetch_all(cfg, store).boards == 0
    assert all(c["quiet"] == 0 for c in store.board_checks().values())
