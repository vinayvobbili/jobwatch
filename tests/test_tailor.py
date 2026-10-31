"""Tailoring a resume to a job with resume-kit: the subprocess is faked, so no resume-kit, node or LibreOffice."""

import json
import re
import subprocess
from pathlib import Path

import pytest

from jobwatch import cli, config, tailor
from jobwatch.autofill import resume_for
from jobwatch.models import Job
from jobwatch.store import Store
from jobwatch.web import ApiError, App

from .conftest import TOKEN, request


class FakeKit:
    """Stands in for subprocess.run of `resume`: keeps versions by name, 'renders' a PDF into --out."""

    def __init__(self, versions=(), build_code=0, build_out=None, build_err="", pdf_name="Jordan_Rivera_Resume_X.pdf"):
        self.versions = list(versions)
        self.calls: list[tuple[list[str], str | None]] = []
        self.build_code, self.build_err, self.pdf_name = build_code, build_err, pdf_name
        self.build_out = build_out
        self.pdf = b"%PDF-1 built"

    def __call__(self, argv, input=None, capture_output=None, text=None, timeout=None, **kw):
        assert kw.get("shell") is not True and isinstance(argv, list) and timeout
        self.calls.append((argv, input))
        verb = argv[1]
        done = lambda code=0, out="", err="": subprocess.CompletedProcess(argv, code, out, err)  # noqa: E731
        if verb == "list":
            return done(out="content: /somewhere\n" + "".join(f"{v:<14} A title\n" for v in self.versions))
        if verb == "draft":
            self.versions.append(argv[2])
            return done(out=f"Drafted {argv[2]}")
        if verb == "build":
            if self.build_code and self.build_out is None:
                return done(1, err=self.build_err)
            out = Path(argv[argv.index("--out") + 1])
            (out / self.pdf_name).write_bytes(self.pdf)
            summary = self.build_out or f"{argv[2]}: 2 page(s) -> {out / self.pdf_name}\n"
            return done(self.build_code, summary, self.build_err)
        raise AssertionError(argv)

    def verbs(self):
        return [argv[1] for argv, _ in self.calls]


@pytest.fixture
def kit(monkeypatch):
    fake = FakeKit()
    monkeypatch.setattr(tailor.subprocess, "run", fake)
    monkeypatch.setattr(tailor.shutil, "which", lambda name: "/bin/" + Path(name).name)
    return fake


@pytest.fixture
def ctx(watchlist, web):
    App(watchlist).post_fetch({})
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    yield cfg, store
    store.close()


def test_a_new_job_is_drafted_from_its_posting_built_and_kept_as_its_resume(ctx, kit):
    cfg, store = ctx
    r = tailor.tailor(cfg, store, "c1")
    assert [v for v in kit.verbs()] == ["list", "draft", "build"]
    draft_argv, posting = kit.calls[1]
    assert draft_argv[:4] == ["resume", "draft", "initech-staff-data-engineer", "-"]
    assert draft_argv[draft_argv.index("--title") + 1] == "Initech: Staff Data Engineer"
    assert "Agents, RAG and evaluation" in posting  # the posting text goes in on stdin
    assert r["new"] is True and r["ok"] is True and r["pages"] == 2 and r["problems"] == []
    assert r["version"] == "initech-staff-data-engineer" and r["pdf"] == "Jordan_Rivera_Resume_X.pdf"
    kept = store.package("c1").resume()
    assert kept.name == "Jordan_Rivera_Resume_X.pdf" and kept.read_bytes() == b"%PDF-1 built"


def test_an_existing_version_is_rebuilt_not_redrafted(ctx, kit):
    cfg, store = ctx
    kit.versions = ["initech-staff-data-engineer", "base"]  # you may have edited it
    r = tailor.tailor(cfg, store, "c1")
    assert kit.verbs() == ["list", "build"] and r["new"] is False
    kit.pdf = b"%PDF-1 rebuilt"
    tailor.tailor(cfg, store, "c1")
    pkg = store.package("c1")
    assert pkg.resume().read_bytes() == b"%PDF-1 rebuilt" and len(pkg.data()["files"]) == 1  # replaced, same name


def test_a_rebuild_after_applying_keeps_the_copy_that_was_sent(ctx, kit):
    cfg, store = ctx
    kit.versions = ["initech-staff-data-engineer"]
    tailor.tailor(cfg, store, "c1")
    store.set_status([store.find("c1")[0].key], "applied")
    kit.pdf = b"%PDF-1 later"
    tailor.tailor(cfg, store, "c1")
    files = store.package("c1").data()["files"]
    assert sorted(f["name"] for f in files) == ["Jordan_Rivera_Resume_X-2.pdf", "Jordan_Rivera_Resume_X.pdf"]
    assert (store.package("c1").dir / "Jordan_Rivera_Resume_X.pdf").read_bytes() == b"%PDF-1 built"


def test_a_build_that_misses_its_target_is_kept_but_flagged(ctx, kit):
    cfg, store = ctx
    kit.build_code = 1
    kit.build_out = "initech: 3 page(s) -> /x/y.pdf\n  spills onto page 3:\n    Skills line\n"
    r = tailor.tailor(cfg, store, "c1")
    assert r["ok"] is False and r["pages"] == 3
    assert r["problems"] == ["spills onto page 3:", "Skills line"]
    assert store.package("c1").resume()  # still there to review


def test_a_failed_fact_check_builds_nothing_and_says_why(ctx, kit):
    cfg, store = ctx
    kit.versions = ["initech-staff-data-engineer"]
    kit.build_code, kit.build_err = 1, "error: initech-staff-data-engineer fails fact checks:\n  retired claim"
    with pytest.raises(tailor.TailorError, match=r"build failed: error: .*fails fact checks:\n  retired claim"):
        tailor.tailor(cfg, store, "c1")
    assert store.package("c1").resume() is None


def test_a_failing_draft_shows_the_tools_error_trimmed(ctx, kit, monkeypatch):
    cfg, store = ctx

    def fail(argv, **kw):
        if argv[1] == "list":
            return subprocess.CompletedProcess(argv, 0, "content: /x\n", "")
        return subprocess.CompletedProcess(argv, 1, "", "error: boom " + "x" * 2000)
    monkeypatch.setattr(tailor.subprocess, "run", fail)
    with pytest.raises(tailor.TailorError, match=r"draft failed: …x+$") as e:
        tailor.tailor(cfg, store, "c1")
    assert len(str(e.value)) < 700


def test_resume_kit_missing_says_how_to_set_it_up(ctx, monkeypatch):
    cfg, store = ctx
    monkeypatch.setattr(tailor.shutil, "which", lambda name: None)
    assert tailor.ready(cfg.resume_kit) is False
    with pytest.raises(tailor.NotInstalled, match=r"resume-kit.*PATH.*Settings"):
        tailor.tailor(cfg, store, "c1")


def test_a_timeout_is_an_error_not_a_hang(ctx, kit, monkeypatch):
    cfg, store = ctx

    def slow(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])
    monkeypatch.setattr(tailor.subprocess, "run", slow)
    with pytest.raises(tailor.TailorError, match="took over"):
        tailor.tailor(cfg, store, "c1")


def test_the_command_comes_from_the_setting_else_path(watchlist, monkeypatch):
    monkeypatch.setattr(tailor.shutil, "which", lambda name: name)
    assert tailor.command(config.load(watchlist).resume_kit) == ["resume"]
    app = App(watchlist)
    app.post_settings({"resume_kit": "~/tools/kit/.venv/bin/resume --content ~/x"})
    argv = tailor.command(config.load(watchlist).resume_kit)
    assert argv[0].endswith("/tools/kit/.venv/bin/resume") and not argv[0].startswith("~")
    assert argv[1:] == ["--content", "~/x"]
    assert app.get_settings({})["resume_kit"].startswith("~/tools/kit")
    with pytest.raises(config.ConfigError, match="resume_kit"):
        app.post_settings({"resume_kit": ["a list"]})


@pytest.mark.parametrize("company, title", [
    ("Initech", "Staff Data Engineer"),
    ("Umbrella Pharmaceuticals International", "Principal Machine Learning Platform Engineer (Remote, Boulder, CO)"),
    ("Globex", "Sr. Engineer / Architect, AI & Data"),
    ("Ünïcode Co", "资深工程师"),
    ("", ""),
])
def test_version_names_are_slugs_within_the_limit(company, title):
    job = Job("ashby", "", "k1", title, "https://example.com/1", company_name=company)
    name = tailor.version_name(job)
    assert name and len(name) <= tailor.NAME_MAX <= 55
    assert re.fullmatch(r"[a-z0-9][a-z0-9-]*", name) and not name.endswith("-")


def test_a_long_name_is_cut_at_a_word():
    job = Job("ashby", "x", "k1", "Principal Machine Learning Platform Engineer", "https://example.com/1",
              company_name="Umbrella Pharmaceuticals")
    assert tailor.version_name(job) == "umbrella-pharmaceuticals-principal"


def test_the_extension_attaches_the_tailored_resume_over_the_default(ctx, kit, tmp_path):
    cfg, store = ctx
    default = tmp_path / "general.pdf"
    default.write_bytes(b"%PDF general")
    cfg.resume = default
    job, _ = store.find("c1")
    assert resume_for(cfg, store, job) == default  # nothing tailored yet
    tailor.tailor(cfg, store, "c1")
    assert resume_for(cfg, store, job).name == "Jordan_Rivera_Resume_X.pdf"
    other, _ = store.find("aaaa-1111")
    assert resume_for(cfg, store, other) == default  # another job still gets the general one


def test_the_endpoint_and_the_queue_card(watchlist, web, kit):
    app = App(watchlist)
    app.post_fetch({})
    app.post_mark({"keys": ["c1"], "status": "queued"})
    card = app.get_queue({})[0]
    assert card["can_tailor"] is True and card["resume"] is None and card["tailor_setup"] is None
    r = app.post_tailor({"key": "c1"})
    assert r["pdf"] == "Jordan_Rivera_Resume_X.pdf" and r["new"] is True
    assert app.get_queue({})[0]["resume"] == "Jordan_Rivera_Resume_X.pdf"
    assert app.post_tailor({"key": "c1"})["new"] is False
    with pytest.raises(ApiError) as e:
        app.post_tailor({"key": "no-such-job"})
    assert e.value.status == 404
    kit.build_code, kit.build_err = 1, "error: fails fact checks"
    kit.build_out = None
    with pytest.raises(ApiError, match="fails fact checks"):
        app.post_tailor({"key": "c1"})


def test_the_queue_says_when_resume_kit_is_missing(watchlist, web, monkeypatch):
    monkeypatch.setattr(tailor.shutil, "which", lambda name: None)
    app = App(watchlist)
    app.post_fetch({})
    app.post_mark({"keys": ["c1"], "status": "queued"})
    card = app.get_queue({})[0]
    assert card["can_tailor"] is False and "resume-kit" in card["tailor_setup"]
    s = app.get_settings({})
    assert s["tailor_ready"] is False and s["tailor_setup"] == card["tailor_setup"]
    with pytest.raises(ApiError, match="resume-kit"):
        app.post_tailor({"key": "c1"})


def test_the_route_needs_the_token(server, kit):
    ok = {"X-Jobwatch-Token": TOKEN}
    request(server, "POST", "/api/fetch", {}, headers=ok)
    assert request(server, "POST", "/api/tailor", {"key": "c1"})[0] == 403
    status, data = request(server, "POST", "/api/tailor", {"key": "c1"}, headers=ok)
    assert status == 200 and json.loads(data)["version"] == "initech-staff-data-engineer"


def test_command_line_and_mcp(watchlist, web, kit, capsys, monkeypatch):
    cli.main(["-c", str(watchlist), "fetch"])
    cli.main(["-c", str(watchlist), "tailor", "c1"])
    out = capsys.readouterr().out
    assert "Drafted initech-staff-data-engineer: 2 page(s), ok; kept Jordan_Rivera_Resume_X.pdf" in out
    assert "Review the PDF before you apply." in out
    cli.main(["-c", str(watchlist), "tailor", "c1"])
    assert "Rebuilt " in capsys.readouterr().out
    mcp = pytest.importorskip("jobwatch.mcp_server")
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    assert mcp.tailor_resume("c1")["new"] is False
    monkeypatch.setattr(tailor.shutil, "which", lambda name: None)
    with pytest.raises(Exception, match="resume-kit"):
        mcp.tailor_resume("c1")
    with pytest.raises(SystemExit, match="resume-kit"):
        cli.main(["-c", str(watchlist), "tailor", "c1"])
