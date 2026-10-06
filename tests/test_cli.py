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
    p.write_text("companies: [monster:acme]\n")
    with pytest.raises(config.ConfigError, match="unknown source 'monster'"):
        config.load(p)
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


def test_mark_on_corrects_the_day_applied(watchlist, capsys):
    """A referral recorded late: `mark applied --on` fixes the day; marking again without it keeps that day."""
    c = ("-c", str(watchlist))
    run(capsys, *c, "add", "Umbrella", "Principal Engineer", "--status", "queued")
    run(capsys, *c, "mark", "applied", "principal-engineer")
    run(capsys, *c, "mark", "applied", "principal-engineer", "--on", "2026-09-01")
    assert "applied 2026-09-01" in run(capsys, *c, "apps").out
    run(capsys, *c, "mark", "screening", "principal-engineer")
    assert "applied 2026-09-01" in run(capsys, *c, "apps").out
