import os
import sys
from pathlib import Path

import pytest
import yaml

from jobwatch import cli, config


def run(capsys, *argv):
    cli.main(list(argv))
    return capsys.readouterr()


def test_init_writes_a_loadable_example(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run(capsys, "init")
    cfg = config.load(tmp_path / "jobwatch.yaml")
    assert cfg.boards and cfg.filters.locations
    with pytest.raises(SystemExit, match="exists"):
        cli.main(["init"])


def test_example_config_is_valid_yaml():
    assert yaml.safe_load(config.EXAMPLE)["companies"]


def test_find(web, capsys):
    out = run(capsys, "find", "Globex", "Nobody").out
    assert ("Globex: lever:globex  (2 open roles)  https://jobs.lever.co/globex\n"
            "    e.g. Machine Learning Engineer") in out
    assert "Acme: greenhouse:acme  (2 open roles, Acme)" in run(capsys, "find", "Acme").out
    assert "Nobody: no Greenhouse, Lever, Ashby, Workday, Eightfold or Rippling board found" in out


def test_run_then_digest_shows_only_new_jobs(web, watchlist, capsys):
    out = run(capsys, "-c", str(watchlist), "run")
    assert "Checked 3 board(s): 5 open roles, 5 new." in out.err
    assert "3 matching job(s)." in out.out
    # Shown jobs don't come back unless asked for.
    assert "0 matching job(s)." in run(capsys, "-c", str(watchlist), "digest").out
    assert "3 matching job(s)." in run(capsys, "-c", str(watchlist), "digest", "--all").out


def test_peek_leaves_jobs_new(web, watchlist, capsys):
    run(capsys, "-c", str(watchlist), "fetch")
    run(capsys, "-c", str(watchlist), "digest", "--peek")
    assert "3 matching job(s)." in run(capsys, "-c", str(watchlist), "digest").out


def test_mark_list_show(web, watchlist, capsys):
    run(capsys, "-c", str(watchlist), "fetch")
    assert "lever:globex:aaaa-1111: applied" in run(capsys, "-c", str(watchlist), "mark", "applied", "aaaa-1111",
                                                     "--note", "referral").out
    listed = run(capsys, "-c", str(watchlist), "list", "--status", "applied").out
    assert "Machine Learning Engineer" in listed and "(referral)" in listed
    shown = run(capsys, "-c", str(watchlist), "show", "aaaa-1111").out
    assert shown.startswith("# Machine Learning Engineer") and "applied (referral)" in shown


def test_errors_are_one_line(web, watchlist, tmp_path):
    with pytest.raises(SystemExit, match="jobwatch: no job matches 'nope'"):
        cli.main(["-c", str(watchlist), "show", "nope"])
    with pytest.raises(SystemExit, match="no config found"):
        cli.main(["-c", str(tmp_path / "missing.yaml"), "fetch"])


def test_config_validation(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("companies: [monster:acme, lever:a]\n")
    cfg = config.load(p)  # a source this version doesn't know is set aside, not fatal
    assert [b.board for b in cfg.boards] == ["a"]
    assert [(b.source, b.board) for b in cfg.unknown] == [("monster", "acme")]
    p.write_text("companies: [lever:a, lever:a]\n")
    with pytest.raises(config.ConfigError, match="listed twice"):
        config.load(p)
    p.write_text("companies: [lever:a]\nfilters: {min_pay: 1}\n")
    with pytest.raises(config.ConfigError, match="min_pay"):
        config.load(p)


def test_mcp_server_imports():
    pytest.importorskip("mcp")
    from jobwatch import mcp_server

    assert mcp_server.server


def test_add_mark_and_list_applications(watchlist, capsys):
    c = ("-c", str(watchlist))
    assert run(capsys, *c, "add", "Umbrella", "Principal Engineer", "--on", "2026-09-01", "--next", "call Ana",
               "--follow-up", "2000-01-02").out == "manual:umbrella:principal-engineer: applied\n"
    run(capsys, *c, "add", "Globex", "Staff Engineer", "--url", "https://globex.example/1")
    run(capsys, *c, "mark", "screening", "staff-engineer", "--note", "recruiter screen done")
    out = run(capsys, *c, "apps").out
    assert "2 applied" not in out and "1 applied, 1 screening. **1 to follow up on now.**" in out
    assert "### Umbrella: Principal Engineer\n**applied** · applied 2026-09-01\n**Due:** call Ana by 2000-01-02" in out
    assert "### Globex: [Staff Engineer](https://globex.example/1)" in out and "Note: recruiter screen done" in out
    assert "Globex" not in run(capsys, *c, "applications", "--due").out
    with pytest.raises(SystemExit, match="isn't a date"):
        cli.main([*c, "add", "X", "Y", "--follow-up", "someday"])


def test_mark_without_a_status_keeps_it(watchlist, capsys):
    """News on an application (the recruiter replied) shouldn't need its stage looked up and said again."""
    c = ("-c", str(watchlist))
    run(capsys, *c, "add", "Umbrella", "Principal Engineer", "--on", "2026-09-01")
    run(capsys, *c, "mark", "screening", "principal-engineer")
    assert run(capsys, *c, "mark", "principal-engineer", "--add-note", "screen moved to Friday", "--next",
               "screen Friday").out == "manual:umbrella:principal-engineer: screening\n"
    out = run(capsys, *c, "apps").out
    assert "**screening** · applied 2026-09-01" in out and ": screen moved to Friday" in out
    run(capsys, *c, "mark", "principal-engineer", "--add-note", "2026-09-30: recruiter called")  # recorded late
    assert "screen moved to Friday 2026-09-30: recruiter called" in run(capsys, *c, "apps").out
    with pytest.raises(SystemExit, match="which job"):
        cli.main([*c, "mark", "applied"])
    with pytest.raises(SystemExit, match="no job"):
        cli.main([*c, "mark", "nothing-like-this", "--add-note", "x"])



def test_mark_by_company_name_with_the_status_after(watchlist, capsys):
    """The company is enough when you've applied there once; when it names more, nothing changes."""
    c = ("-c", str(watchlist))
    run(capsys, *c, "add", "Umbrella", "Principal Engineer")
    run(capsys, *c, "add", "Hooli", "Staff Engineer")
    run(capsys, *c, "add", "Hooli", "Platform Engineer")
    assert run(capsys, *c, "mark", "umbrella", "interviewing", "--next", "panel Thursday").out == \
        "manual:umbrella:principal-engineer: interviewing\n"
    assert "**interviewing**" in run(capsys, *c, "apps").out and "panel Thursday" in run(capsys, *c, "apps").out
    assert run(capsys, *c, "show", "UMBRELLA").out.startswith("# Principal Engineer")
    with pytest.raises(SystemExit) as e:
        cli.main([*c, "mark", "hooli", "screening"])
    assert str(e.value).startswith("jobwatch: 'hooli' matches 2 jobs; give the key of one:")
    assert "  manual:hooli:platform-engineer  Hooli: Platform Engineer (applied)" in str(e.value)
    assert "screening" not in run(capsys, *c, "list").out  # neither changed
    assert run(capsys, *c, "mark", "screening", "manual:hooli:staff-engineer").out == \
        "manual:hooli:staff-engineer: screening\n"

def test_mark_text_gives_a_hand_added_job_its_posting(watchlist, web, tmp_path, capsys):
    """The posting found later (or a copy, once it's gone): scored, prepped and kept with the application."""
    c = ("-c", str(watchlist))
    run(capsys, *c, "add", "Umbrella", "Principal Engineer")
    posting = tmp_path / "posting.txt"
    posting.write_text("Build LLM agents and RAG in Python. The base pay range is 180,000 - 220,000 USD.")
    run(capsys, *c, "mark", "principal-engineer", "--text", str(posting))
    shown = run(capsys, *c, "show", "principal-engineer").out
    assert "Build LLM agents and RAG in Python." in shown and "applied" in shown
    assert "· $180K–$220K" in run(capsys, *c, "apps").out
    kept = run(capsys, *c, "package", "principal-engineer").out.split("Posting as it read on ")[1].split(": ", 1)[1]
    assert "Build LLM agents" in Path(kept.splitlines()[0]).read_text()
    run(capsys, *c, "fetch")
    with pytest.raises(SystemExit, match="comes from its board"):
        cli.main([*c, "mark", "aaaa-1111", "--text", str(posting)])


def test_mark_on_corrects_the_day_applied(watchlist, capsys):
    """A referral recorded late: `mark applied --on` fixes the day; marking again without it keeps that day."""
    c = ("-c", str(watchlist))
    run(capsys, *c, "add", "Umbrella", "Principal Engineer", "--status", "queued")
    run(capsys, *c, "mark", "applied", "principal-engineer")
    run(capsys, *c, "mark", "applied", "principal-engineer", "--on", "2026-09-01")
    assert "applied 2026-09-01" in run(capsys, *c, "apps").out
    run(capsys, *c, "mark", "screening", "principal-engineer")
    assert "applied 2026-09-01" in run(capsys, *c, "apps").out


def test_mcp_runs_the_server_with_the_watchlist_given(watchlist, monkeypatch):
    pytest.importorskip("mcp")
    from jobwatch import mcp_server

    seen = []
    monkeypatch.delenv("JOBWATCH_CONFIG", raising=False)
    monkeypatch.setattr(mcp_server, "main", lambda: seen.append(os.environ["JOBWATCH_CONFIG"]))
    cli.main(["-c", str(watchlist), "mcp"])
    assert seen == [str(watchlist)]


def test_mcp_without_the_extra_says_how_to_get_it(monkeypatch):
    import jobwatch

    monkeypatch.delitem(sys.modules, "jobwatch.mcp_server", raising=False)
    monkeypatch.delattr(jobwatch, "mcp_server", raising=False)
    for name in [m for m in sys.modules if m == "mcp" or m.startswith("mcp.")] or ["mcp"]:
        monkeypatch.setitem(sys.modules, name, None)
    with pytest.raises(SystemExit, match=r"pip install 'jobwatch\[mcp\]'"):
        cli.main(["mcp"])


def test_registry_entry_matches_the_release():
    """The MCP Registry lists the version in server.json and checks the README on PyPI names the server."""
    import json

    from jobwatch import __version__

    root = Path(__file__).parent.parent
    entry = json.loads((root / "server.json").read_text())
    assert entry["version"] == entry["packages"][0]["version"] == __version__
    assert f"mcp-name: {entry['name']}" in (root / "README.md").read_text()
