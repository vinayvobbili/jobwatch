"""A score made by an older scorer stands in (marked stale) until the job is scored afresh: it still hides a poor
fit and orders Today, but the job stays in the scorer's line."""

from types import SimpleNamespace

import pytest
import yaml

from jobwatch import config, report, score, watch
from jobwatch.score import resume_family, resume_id
from jobwatch.store import Store

FIT = {"score": 70, "must_haves_met": 2, "must_haves_total": 3, "gaps": [], "summary": ""}
INITECH, GLOBEX, ACME = "ashby:initech:c1", "lever:globex:aaaa-1111", "greenhouse:acme:101"


@pytest.fixture
def env(watchlist, web):
    (watchlist.parent / "cv.md").write_text("Python, LLMs, RAG")
    raw = yaml.safe_load(watchlist.read_text())
    watchlist.write_text(yaml.safe_dump({**raw, "resume": "cv.md", "filters": {**raw.get("filters", {}),
                                                                                "min_fit": 60}}))
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    yield cfg, store, resume_id(cfg.resume, cfg.prompts)
    store.close()


def fit(score):
    return {**FIT, "score": score}


def test_resume_family_ignores_the_scorer_part():
    assert resume_family("cv.md:abc123def456:scorer-0a1b2c3d") == "cv.md:abc123def456"
    assert resume_family("cv.md:abc123def456:scorer-0a1b2c3d:prompts-ffffffffffff") == \
        resume_family("cv.md:abc123def456:prompts-ffffffffffff") == "cv.md:abc123def456:prompts-ffffffffffff"
    assert resume_family("cv.md:abc123def456") == "cv.md:abc123def456"


def test_a_change_to_the_scoring_code_is_another_scorer(tmp_path, monkeypatch):
    """A weight or cap edited in shortlist-ai's source, with no new version or prompt, still scores afresh."""
    source = tmp_path / "score.py"
    monkeypatch.setattr(score.importlib.util, "find_spec",
                        lambda name: SimpleNamespace(origin=str(source)) if name == "shortlist_ai.score" else None)
    source.write_text("CAP = 65\n")
    before = score.scorer_id()
    assert score.scorer_id() == before
    source.write_text("CAP = 70\n")
    assert score.scorer_id() != before


def test_a_stale_score_hides_ranks_and_is_marked(env):
    cfg, store, rid = env
    family = resume_family(rid)
    store.save_score(ACME, family, fit(90))                       # made before the scorer part existed
    store.save_score(GLOBEX, family + ":scorer-00000000", fit(80))  # made by another scorer
    store.save_score(INITECH, family + ":scorer-00000000", fit(30))
    entries, rejected = watch._matching(cfg, store, ("new", "shown"))
    assert rejected["fit"] == 1
    assert [(e.job.key, e.fit["score"], e.fit.get("stale")) for e in sorted(entries, key=watch._rank)] == \
        [(ACME, 90, True), (GLOBEX, 80, True)]
    assert "(old score, rescoring)" in report.to_markdown(watch.build_digest(cfg, store, score_top=0))
    assert watch.hidden(cfg, store)["by"]["fit"] == 1
    # still in the scorer's line, with their old score deciding the order
    assert [e.job.key for e in watch.unscored(cfg, store)] == [ACME, GLOBEX]
    assert watch.unscored_reasons(cfg, store)[ACME]["code"] == "queued"
    assert store.score(ACME, rid) is None


def test_another_resume_or_other_prompts_are_not_used(env):
    cfg, store, rid = env
    name, digest = resume_family(rid).split(":")[:2]
    store.save_score(ACME, f"{name}:000000000000:scorer-00000000", fit(10))
    store.save_score(GLOBEX, f"{name}:{digest}:scorer-00000000:prompts-ffffffffffff", fit(10))
    entries, rejected = watch._matching(cfg, store, ("new", "shown"))
    assert "fit" not in rejected and all(e.fit is None for e in entries)


def test_a_fresh_score_wins(env):
    cfg, store, rid = env
    store.save_score(ACME, resume_family(rid) + ":scorer-00000000", fit(90))
    store.save_score(ACME, rid, fit(65))
    e = next(e for e in watch._matching(cfg, store, ("new", "shown"))[0] if e.job.key == ACME)
    assert e.fit["score"] == 65 and "stale" not in e.fit
    assert ACME not in [x.job.key for x in watch.unscored(cfg, store)]
    assert ACME not in watch.unscored_reasons(cfg, store)
