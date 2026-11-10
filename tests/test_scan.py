"""`jobwatch scan`: a list of companies checked once against the watchlist's filters, and with --add, the ones with
suggestions.min_jobs matching jobs watched. No network: the boards are canned (the `web` fixture)."""

import pytest

from jobwatch import cli, config, scan, sources, suggest
from jobwatch.store import Store
from jobwatch.watch import save_job

from .conftest import iso

HOOLI = "https://api.lever.co/v0/postings/hooli?mode=json"
UMBRELLA = "https://boards-api.greenhouse.io/v1/boards/umbrella/jobs?content=true"


def lever_job(title, location="Remote (United States)", workplace="remote"):
    slug = title.lower().replace(" ", "-")
    return {"id": slug, "text": title, "hostedUrl": f"https://jobs.lever.co/hooli/{slug}",
            "categories": {"location": location, "allLocations": [location]},
            "workplaceType": workplace, "descriptionPlain": "Python services.", "lists": []}


def greenhouse(company_name, *titles):
    return {"jobs": [{
        "id": 500 + i, "title": t, "company_name": company_name,
        "absolute_url": f"https://job-boards.greenhouse.io/umbrella/jobs/{500 + i}", "location": {"name": "Remote"},
        "offices": [], "metadata": [], "departments": [], "first_published": iso(2), "content": "Python."}
        for i, t in enumerate(titles)]}


def watching(path):
    return {b.entry for b in config.load(path).boards}


def test_a_company_with_a_matching_job_is_reported_not_added(web, watchlist):
    web.responses[HOOLI] = [lever_job("Staff Security Engineer"),
                            lever_job("Staff Security Engineer, Onsite", "Boston", "onsite"),
                            lever_job("Security Engineer (Contract)")]  # the test filters leave out contract
    cfg = config.load(watchlist)
    [s] = scan.scan(cfg, ["Hooli"])
    assert (s.entry, [j.title for j in s.matching], s.added) == ("lever:hooli", ["Staff Security Engineer"], False)
    assert "lever:hooli" not in watching(watchlist)
    report = scan.text([s], 1, add=False)
    assert "Hooli: lever:hooli (3 open roles, 1 matching)" in report
    assert "`--add` watches the ones with 1+" in report


def test_add_takes_one_matching_job_unless_told(web, watchlist):
    # A picked list's one job is enough, unlike an alert's (suggestions.min_jobs, 2 here, isn't consulted)
    web.responses[HOOLI] = [lever_job("Staff Security Engineer")]
    cfg = config.load(watchlist)
    assert not scan.scan(cfg, ["Hooli"], add=True, least=2)[0].added
    [s] = scan.scan(cfg, ["Hooli"], add=True)
    assert s.added and "lever:hooli" in watching(watchlist)
    assert watchlist.with_name("jobwatch.yaml.bak").exists()  # rewritten the way add_board does
    assert scan.scan(config.load(watchlist), ["Hooli"])[0].watched  # and not read again


def test_another_companys_board_is_never_added(web, watchlist):
    # greenhouse:umbrella answers under the name, but its roles are Umbrella Pastries'
    web.responses[UMBRELLA] = greenhouse("Umbrella Pastries", "Staff Security Engineer")
    [s] = scan.scan(config.load(watchlist), ["Umbrella"], add=True)
    assert (s.other, s.added) == ("Umbrella Pastries", False) and "greenhouse:umbrella" not in watching(watchlist)
    assert "another company's board? Not added." in scan.text([s], 1, add=True)

    web.responses[UMBRELLA] = greenhouse("Umbrella", "Staff Security Engineer")
    assert scan.scan(config.load(watchlist), ["Umbrella"], add=True)[0].added


def test_watched_companies_and_unknown_ones(web, watchlist):
    cfg = config.load(watchlist)
    web.calls.clear()
    acme, nobody = scan.scan(cfg, ["Acme", "Nobody Inc"])
    assert acme.watched and not any("acme" in c for c in web.calls)  # greenhouse:acme is on the watchlist
    assert not nobody.found and "no board with open roles found" in scan.text([nobody], 2, add=False)


def test_a_source_that_said_slow_down_is_not_asked_again_for_the_rest_of_the_list(web, watchlist, monkeypatch):
    """A 95-company scan kept guessing at Workable after its first 429, and Workable then refused this Mac outright,
    known boards too. One 429 now takes Workable out of the run; every company still says it may be there."""
    asked = []

    def peek(source, board, get=None):
        if source == "workable":
            asked.append(board)
            raise sources.SourceError(f"https://apply.workable.com/api/v1/widget/accounts/{board}: HTTP 429")
        return []
    monkeypatch.setattr(sources, "_peek", peek)
    found = scan.scan(config.load(watchlist), ["Vandelay Industries", "Prestige Worldwide", "Dunder Labs"],
                      workers=1)
    assert len(asked) == 1
    assert [s.error for s in found] == ["no board with open roles found" + sources.slow_down({"workable"})] * 3


def test_names_from_a_list():
    assert scan.names(["# Hiring now", "Hooli", "", "Umbrella  # security", "Hooli", "  Initech "]) == [
        "Hooli", "Umbrella", "Initech"]


def test_the_command_reads_a_file(web, watchlist, tmp_path, capsys):
    web.responses[HOOLI] = [lever_job("Staff Security Engineer")]
    names = tmp_path / "companies.txt"
    names.write_text("# from a post\nHooli\nNobody Inc\n")
    cli.main(["-c", str(watchlist), "scan", "--file", str(names)])
    out, err = capsys.readouterr()
    assert out.startswith("2 companies: 1 with a job that passes your filters")
    # each company on stderr as it finishes, so a long list isn't silent for minutes
    counters, said = zip(*(line.split(" ", 1) for line in err.splitlines()), strict=True)
    assert counters == ("[1/2]", "[2/2]")  # in the order they finish, which threads decide
    assert sorted(said) == ["Hooli: lever:hooli, 1 matching", "Nobody Inc: no board found"]
    assert out.index("Hooli: lever:hooli") < out.index("Nobody Inc:")  # matching ones first
    cli.main(["-c", str(watchlist), "scan", "Hooli", "--add", "--min", "2"])
    assert "0 added" in capsys.readouterr().out and "lever:hooli" not in watching(watchlist)
    with pytest.raises(SystemExit, match="Name the companies to scan"):
        cli.main(["-c", str(watchlist), "scan"])


def test_min_jobs_drives_auto_watch_too(web, watchlist):
    web.responses[HOOLI] = [lever_job("Senior Data Platform Engineer")]
    watchlist.write_text(watchlist.read_text() + "suggestions: {auto_watch: true, min_jobs: 1}\n")
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    save_job(store, company="Hooli", title="Senior Data Platform Engineer", status="queued", location="Remote",
             boards=cfg.boards)
    _, got = suggest.auto_watch(cfg, store)
    assert [s.entry for s in got] == ["lever:hooli"] and suggest.why_watched(cfg, got[0]) == "1 matching job"
    with pytest.raises(config.ConfigError, match=r"suggestions\.min_jobs must be a whole number from 1 to 20"):
        config.save(watchlist, {"suggestions": {"min_jobs": 0}})
