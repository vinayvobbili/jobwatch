"""Why a fit score is what it is (each requirement's verdict and evidence), and the min_fit filter."""

from types import SimpleNamespace

import pytest

from jobwatch import cli, config, report, watch
from jobwatch.filters import KINDS, Filters, rejection
from jobwatch.models import Job
from jobwatch.score import brief, requirement_rows, resume_id
from jobwatch.store import Store
from jobwatch.web import App

REQUIREMENTS = [
    {"id": "python", "requirement": "5 years of Python", "kind": "must_have", "verdict": "met",
     "evidence": ["Built Python services for 6 years"], "evidence_verified": True, "reasoning": "Shown."},
    {"id": "go", "requirement": "Experience with Go", "kind": "nice_to_have", "verdict": "not_met",
     "evidence": [], "evidence_verified": True, "reasoning": "Not shown."},
]
FIT = {"score": 81.0, "must_haves_met": 1, "must_haves_total": 1, "gaps": [], "summary": "Good.", "flags": [],
       "requirements": REQUIREMENTS}


def scored(req_id, verdict, evidence, unverified=(), kind="must_have"):
    return SimpleNamespace(requirement_id=req_id, verdict=verdict, evidence=list(evidence),
                           unverified_quotes=list(unverified), kind=kind, evidence_verified=not unverified,
                           reasoning="why")


def test_requirement_rows_keep_verified_quotes_and_the_requirement_text():
    spec = SimpleNamespace(requirements=[SimpleNamespace(id="python", description="5 years of Python")])
    result = SimpleNamespace(requirements=[
        scored("python", "met", ["Built Python services", "made-up quote"], unverified=["made-up quote"]),
        scored("unlisted", "partial", ["Some line"], kind="nice_to_have"),
    ])
    rows = requirement_rows(result, spec)
    assert rows[0] == {"id": "python", "requirement": "5 years of Python", "kind": "must_have", "verdict": "met",
                       "evidence": ["Built Python services"], "evidence_verified": False, "reasoning": "why"}
    assert rows[1]["requirement"] == "unlisted"  # no description: the id stands in
    assert requirement_rows(SimpleNamespace(), None) == []


def test_brief_drops_only_the_requirements():
    assert brief(FIT) == {k: v for k, v in FIT.items() if k != "requirements"}
    assert brief(None) is None


def test_store_round_trip_and_bulk_read(tmp_path):
    store = Store(tmp_path / "s.db")
    store.save_score("k1", "cv:1", FIT)
    store.save_score("k2", "cv:1", {"score": 50})  # saved before requirements were kept
    store.save_score("k3", "cv:2", {"score": 99})
    assert store.score("k1", "cv:1")["requirements"] == REQUIREMENTS
    assert store.scores("cv:1") == {"k1": FIT, "k2": {"score": 50}}
    store.close()


def test_fit_lines_with_and_without_requirements():
    lines = report.fit_lines(FIT)
    assert lines[0] == "Fit 81/100, must-haves 1/1"
    assert lines[1] == '  met     [must] 5 years of Python  "Built Python services for 6 years"'
    assert lines[2] == "  missing [nice] Experience with Go"
    assert report.fit_lines({"score": 50, "must_haves_met": 2, "must_haves_total": 3}) == [
        "Fit 50/100, must-haves 2/3"]


def _resume(watchlist):
    cv = watchlist.parent / "cv.md"
    cv.write_text("# Jane Doe")
    config.save(watchlist, {"resume": str(cv)})
    cfg = config.load(watchlist)
    return cfg, resume_id(cfg.resume)


def test_show_prints_why(web, watchlist, capsys):
    cli.main(["-c", str(watchlist), "fetch"])
    cfg, rid = _resume(watchlist)
    store = Store(cfg.state)
    store.save_score("lever:globex:aaaa-1111", rid, FIT)
    store.close()
    capsys.readouterr()
    cli.main(["-c", str(watchlist), "show", "aaaa-1111"])
    out = capsys.readouterr().out
    assert "Fit 81/100, must-haves 1/1" in out and "missing [nice] Experience with Go" in out


def test_mcp_get_job_has_the_requirements_and_lists_stay_brief(web, watchlist, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    cli.main(["-c", str(watchlist), "fetch"])
    cfg, rid = _resume(watchlist)
    store = Store(cfg.state)
    store.save_score("lever:globex:aaaa-1111", rid, FIT)
    store.close()
    assert mcp.get_job("aaaa-1111")["fit"]["requirements"] == REQUIREMENTS
    store = Store(cfg.state)
    entry = next(e for e in watch.build_digest(cfg, store, include_seen=True, score_top=0).entries
                 if e.job.key == "lever:globex:aaaa-1111")
    store.close()
    assert entry.fit["score"] == 81.0 and "requirements" not in entry.fit


# -- min_fit

def job() -> Job:
    return Job(source="greenhouse", company="acme", id="1", title="Engineer", url="u", locations=["Denver"])


def test_min_fit_hides_low_scores_but_not_unscored_jobs():
    f = Filters(min_fit=70)
    assert rejection(job(), f, {"score": 65.0}) == ("fit", "fit 65/100")
    assert rejection(job(), f, {"score": 70.0}) is None
    assert rejection(job(), f, None) is None  # not scored yet: still shows
    assert rejection(job(), Filters(), {"score": 5.0}) is None  # 0: off
    assert KINDS[-1] == "fit"


@pytest.mark.parametrize("bad", [101, -5, "high"])
def test_min_fit_must_be_a_score(bad):
    with pytest.raises(ValueError, match="min_fit"):
        Filters.from_dict({"min_fit": bad})


def test_min_fit_round_trips_through_the_watchlist(watchlist):
    filters = {**config.load(watchlist).filters.__dict__}
    raw = {k: v for k, v in filters.items() if v not in (None, "", [], {}, 0, False)}
    config.save(watchlist, {"filters": {**raw, "min_fit": 75}})
    assert config.load(watchlist).filters.min_fit == 75
    assert "min_fit: 75" in watchlist.read_text()


def test_digest_and_hidden_count_jobs_below_min_fit(web, watchlist):
    cli.main(["-c", str(watchlist), "fetch"])
    cfg, rid = _resume(watchlist)
    store = Store(cfg.state)
    store.save_score("lever:globex:aaaa-1111", rid, {**FIT, "score": 40.0})
    store.save_score("ashby:initech:c1", rid, FIT)
    store.close()
    filters = {k: v for k, v in cfg.filters.__dict__.items() if v not in (None, "", [], {}, 0, False)}
    config.save(watchlist, {"filters": {**filters, "min_fit": 60}})
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    d = watch.build_digest(cfg, store, include_seen=True, score_top=0)
    store.close()
    keys = [e.job.key for e in d.entries]
    assert "lever:globex:aaaa-1111" not in keys and "ashby:initech:c1" in keys
    assert "greenhouse:acme:101" in keys  # unscored
    assert d.rejected.get("fit") == 1
    hidden = App(watchlist).get_hidden({"kind": ["fit"]})
    assert hidden["by"]["fit"] == 1 and hidden["jobs"][0]["why"] == "fit 40/100"
