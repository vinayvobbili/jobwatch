"""A score made by an older scorer stands in (marked stale) until the job is scored afresh: it still hides a poor
fit and orders Today, but the job stays in the scorer's line, a hidden one too (else it would stay hidden)."""

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
    # still in the scorer's line, with their old score deciding the order; the hidden one too, last
    assert [e.job.key for e in watch.unscored(cfg, store)] == [ACME, GLOBEX, INITECH]
    assert watch.unscored_reasons(cfg, store)[ACME]["code"] == "queued"
    assert store.score(ACME, rid) is None


def test_each_entry_says_which_model_scored_it(env):
    """Claude or the local model: the digest and the queue name the scorer next to the score."""
    cfg, store, rid = env
    store.save_score(ACME, rid, {**fit(90), "scored_by": "claude:claude-sonnet-5-5"})
    store.save_score(GLOBEX, rid, {**fit(80), "scored_by": "local:mlx-community/Qwen3.5-9B-MLX-4bit"})
    md = report.to_markdown(watch.build_digest(cfg, store, score_top=0))
    assert "**Fit 90/100**, must-haves 2/3 (scored by claude-sonnet-5-5)." in md
    assert "**Fit 80/100**, must-haves 2/3 (scored by Qwen3.5-9B-MLX-4bit (local))." in md


def test_another_resume_or_other_prompts_are_not_used(env):
    cfg, store, rid = env
    name, digest = resume_family(rid).split(":")[:2]
    store.save_score(ACME, f"{name}:000000000000:scorer-00000000", fit(10))
    store.save_score(GLOBEX, f"{name}:{digest}:scorer-00000000:prompts-ffffffffffff", fit(10))
    entries, rejected = watch._matching(cfg, store, ("new", "shown"))
    assert "fit" not in rejected and all(e.fit is None for e in entries)


def test_old_scores_can_be_kept_as_current(env):
    """`jobwatch score --keep-old`: after a scorer change that doesn't change what scores mean, the scores of the
    scorer in use just before stay (its day kept, marked kept_from) and those jobs leave the scorer's line. A
    score from a scorer replaced before that stays set aside, so its job is still scored again."""
    cfg, store, rid = env
    family = resume_family(rid)
    store.save_score(INITECH, family + ":scorer-00000000", fit(65))  # from a scorer replaced on purpose
    store.save_score(ACME, family + ":scorer-00000000", fit(60))
    store.save_score(ACME, family + ":scorer-11111111", fit(90))     # the scorer in use just before
    store.save_score(GLOBEX, family + ":scorer-11111111", fit(80))
    store.save_score(GLOBEX, rid, fit(70))                           # already scored afresh: left alone
    store.save_score(INITECH, "other.md:000000000000:scorer-11111111", fit(70))  # another resume: not kept
    assert store.keep_old_scores(rid) == (1, "11111111")
    assert store.score(ACME, rid)["score"] == 90 and store.score(ACME, rid)["kept_from"].endswith("scorer-11111111")
    assert store.score(GLOBEX, rid)["score"] == 70 and store.score(INITECH, rid) is None
    assert [e.job.key for e in watch.unscored(cfg, store) if e.job.key in (ACME, INITECH)] == [INITECH]
    assert store.keep_old_scores(rid) == (0, "11111111")             # nothing more to keep
    assert store.keep_old_scores(rid, "00000000") == (1, "00000000")  # unless that scorer is named
    # --redo-kept: the kept ones go back in line (their old score shows, stale), the fresh one stays
    assert sorted(store.drop_kept_scores(rid)) == sorted([ACME, INITECH])
    assert store.score(GLOBEX, rid)["score"] == 70 and store.score(ACME, rid) is None
    assert {ACME, INITECH} <= {e.job.key for e in watch.unscored(cfg, store)}


def test_scores_with_requirements_left_unjudged_are_dropped_to_score_again(env):
    """`jobwatch score --incomplete`: a score saved before such results counted as failures goes, and its job is
    back in the scorer's line; complete scores and other resumes' scores stay."""
    cfg, store, rid = env
    store.save_score(ACME, rid, {**fit(5), "flags": ["no assessment returned for 'ros' (scored as not_met)"]})
    store.save_score(GLOBEX, rid, {**fit(80), "flags": ["core requirement 'ml' partial: score capped at 69"]})
    other = "other.md:000000000000:scorer-00000000"
    store.save_score(ACME, other, {**fit(5), "flags": ["no assessment returned for 'ros' (scored as not_met)"]})
    assert store.drop_incomplete_scores(rid) == [ACME]
    assert store.score(ACME, rid) is None and store.score(GLOBEX, rid)["score"] == 80
    assert store.score(ACME, other)["score"] == 5
    assert ACME in [e.job.key for e in watch.unscored(cfg, store)]


def test_a_fresh_score_wins(env):
    cfg, store, rid = env
    store.save_score(ACME, resume_family(rid) + ":scorer-00000000", fit(90))
    store.save_score(ACME, rid, fit(65))
    e = next(e for e in watch._matching(cfg, store, ("new", "shown"))[0] if e.job.key == ACME)
    assert e.fit["score"] == 65 and "stale" not in e.fit
    assert ACME not in [x.job.key for x in watch.unscored(cfg, store)]
    assert ACME not in watch.unscored_reasons(cfg, store)
