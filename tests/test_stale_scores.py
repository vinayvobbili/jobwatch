"""A new resume doesn't make a fit score stale: that's a decision (`jobwatch scores --stale`, or `--keep`). Until
then a job shows the score it has, flagged when it was made under an older resume, and nothing is scored again."""

from types import SimpleNamespace

import pytest
import yaml

from jobwatch import cli, config, report, score, scorestate, watch
from jobwatch.score import resume_family, resume_id
from jobwatch.store import Store
from jobwatch.web import App

FIT = {"score": 70, "must_haves_met": 2, "must_haves_total": 3, "gaps": [], "summary": ""}
INITECH, GLOBEX, ACME = "ashby:initech:c1", "lever:globex:aaaa-1111", "greenhouse:acme:101"
OLD = "cv.md:000000000000:scorer-00000000"  # made under an earlier version of the resume


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


@pytest.fixture
def asked(monkeypatch):
    """Stand in for shortlist-ai: the job keys it was asked to score, in order; each scores 55."""
    keys = []

    def fake(jobs, resume, backend, cache_dir, workers=1, progress=None, prompts=None, model="", keychain="",
             batch=False, key_command="", provider=None):
        keys.extend(j.key for j in jobs)
        return {j.key: {**FIT, "score": 55, "scored_by": "local:stub"} for j in jobs}, {}

    monkeypatch.setattr(watch, "score_jobs", fake)
    return keys


def fit(score):
    return {**FIT, "score": score, "scored_by": "local:stub"}  # by the backend in use: --rescore leaves it alone


def rebuild(cfg, text="Python, LLMs, RAG, a rebuilt resume"):
    """The resume rebuilt: another content, so another resume id. Returns the new id."""
    cfg.resume.write_text(text)
    return resume_id(cfg.resume, cfg.prompts)


def test_resume_family_ignores_the_scorer_part():
    assert resume_family("cv.md:abc123def456:scorer-0a1b2c3d") == "cv.md:abc123def456"
    assert resume_family("cv.md:abc123def456:scorer-0a1b2c3d:prompts-ffffffffffff") == \
        resume_family("cv.md:abc123def456:prompts-ffffffffffff") == "cv.md:abc123def456:prompts-ffffffffffff"
    assert resume_family("cv.md:abc123def456") == "cv.md:abc123def456"


def test_a_change_to_the_scoring_code_is_another_scorer(tmp_path, monkeypatch):
    """A weight or cap edited in shortlist-ai's source, with no new version or prompt, still has its own scorer id."""
    source = tmp_path / "score.py"
    monkeypatch.setattr(score.importlib.util, "find_spec",
                        lambda name: SimpleNamespace(origin=str(source)) if name == "shortlist_ai.score" else None)
    source.write_text("CAP = 65\n")
    before = score.scorer_id()
    assert score.scorer_id() == before
    source.write_text("CAP = 70\n")
    assert score.scorer_id() != before


def test_a_scorer_change_makes_nothing_stale(env):
    """A shortlist-ai upgrade (or an edit to its score.py) is no reason to flag a score: the same resume made it."""
    cfg, store, rid = env
    store.save_score(ACME, resume_family(rid) + ":scorer-00000000", fit(90))
    assert "stale" not in store.score(ACME, rid)
    assert scorestate.status(cfg, store)["older"] == 0 and scorestate.status(cfg, store)["other_scorer"] == 1


def test_a_stale_score_still_shows_filters_and_ranks(env):
    """Made under an older resume: the score counts for the filters, the order and the digest; it's flagged."""
    cfg, store, rid = env
    store.save_score(ACME, OLD, fit(90))
    store.save_score(GLOBEX, OLD, fit(80))
    store.save_score(INITECH, OLD, fit(30))
    entries, rejected = watch._matching(cfg, store, ("new", "shown"))
    assert rejected["fit"] == 1
    assert [(e.job.key, e.fit["score"], e.fit["stale_why"]) for e in sorted(entries, key=watch._rank)] == \
        [(ACME, 90, "older_resume"), (GLOBEX, 80, "older_resume")]
    assert "(stale score)" in report.to_markdown(watch.build_digest(cfg, store, score_top=0))
    assert watch.hidden(cfg, store)["by"]["fit"] == 1
    # no reason to say "not scored yet", and nothing to score again until it's decided
    assert watch.unscored(cfg, store) == [] and watch.rescore_line(cfg, store) == []
    assert not {ACME, GLOBEX, INITECH} & set(watch.unscored_reasons(cfg, store))
    assert watch.unscored_reason(cfg, store, store.find(ACME)[0]) is None
    assert store.score(ACME, rid)["stale"] is True and watch.job_fit(cfg, store, ACME)["score"] == 90


def test_each_entry_says_which_model_scored_it(env):
    """Claude or the local model: the digest and the queue name the scorer next to the score."""
    cfg, store, rid = env
    store.save_score(ACME, rid, {**fit(90), "scored_by": "claude:claude-sonnet-5-5"})
    store.save_score(GLOBEX, rid, {**fit(80), "scored_by": "local:mlx-community/Qwen3.5-9B-MLX-4bit"})
    md = report.to_markdown(watch.build_digest(cfg, store, score_top=0))
    assert "**Fit 90/100**, must-haves 2/3 (scored by claude-sonnet-5-5)." in md
    assert "**Fit 80/100**, must-haves 2/3 (scored by Qwen3.5-9B-MLX-4bit (local))." in md


def test_a_job_never_scored_has_no_score_at_all(env):
    cfg, store, rid = env
    store.save_score(ACME, OLD, fit(90))
    assert store.score(INITECH, rid) is None
    assert {e.job.key for e in watch.unscored(cfg, store)} == {INITECH, GLOBEX}
    assert {INITECH, GLOBEX} <= set(watch.unscored_reasons(cfg, store))


def test_an_undecided_resume_change_asks_the_scorer_for_nothing(env, asked, capsys):
    """The $4 morning: two rebuilds, and every job was asked for again. Now the page's scorer, `jobwatch score` and
    the rescore list all leave the scores alone until it's decided."""
    cfg, store, rid = env
    for key in (ACME, GLOBEX, INITECH):
        store.save_score(key, rid, fit(75))
    new = rebuild(cfg)
    assert new != rid and resume_family(new) != resume_family(rid)
    rebuild(cfg, "Python, LLMs, RAG, rebuilt twice")
    assert watch.unscored(cfg, store) == [] and watch.rescore_line(cfg, store) == []
    cli.main(["-c", str(cfg.path), "score"])
    assert "Every job on Today has a fit score." in capsys.readouterr().out
    cli.main(["-c", str(cfg.path), "score", "--rescore"])
    assert "Every scored job" in capsys.readouterr().out
    assert asked == []  # no call to the scorer
    assert [store.score(k, resume_id(cfg.resume, cfg.prompts))["score"] for k in (ACME, GLOBEX, INITECH)] == [75] * 3
    assert scorestate.status(cfg, store)["older"] == 3


def test_the_page_scores_nothing_after_an_undecided_resume_change(watchlist, web, asked):
    (watchlist.parent / "cv.md").write_text("Python, LLMs, RAG")
    raw = yaml.safe_load(watchlist.read_text())
    watchlist.write_text(yaml.safe_dump({**raw, "resume": "cv.md"}))  # auto scoring: on, for the local model
    app = App(watchlist, background=True)
    app.post_fetch({})
    app.scorer.wait(10)
    assert len(asked) == 3
    asked.clear()
    (watchlist.parent / "cv.md").write_text("Python, LLMs, RAG, rebuilt")
    app = App(watchlist, background=True)
    app.post_fetch({})
    app.scorer.wait(10)
    jobs = {j["key"]: j for j in app.get_digest({})["jobs"]}
    assert asked == [] and {j["fit"]["stale_why"] for j in jobs.values()} == {"older_resume"}
    assert {j["fit"]["score"] for j in jobs.values()} == {55}


def test_marking_stale_scores_those_jobs_again_with_the_new_resume(env, asked):
    cfg, store, rid = env
    for key, n in ((ACME, 90), (GLOBEX, 80), (INITECH, 70)):
        store.save_score(key, rid, fit(n))
    new = rebuild(cfg)
    assert scorestate.mark_stale(cfg, store, "new summary", min_score=75) == 2
    assert [store.score(k, new)["stale_why"] for k in (ACME, GLOBEX, INITECH)] == ["marked", "marked", "older_resume"]
    marked = store.score(ACME, new)
    assert marked["stale_reason"] == "new summary" and marked["stale_at"]
    assert {e.job.key for e in watch.unscored(cfg, store)} == {ACME, GLOBEX}  # the marked ones, only
    assert [e.job.key for e in watch.rescore_line(cfg, store)] == [ACME, GLOBEX]
    todo = watch.unscored(cfg, store)
    assert watch.score_entries(cfg, store, todo, progress=lambda m: None)[0] == 2
    assert sorted(asked) == [ACME, GLOBEX]
    assert [store.score(k, new).get("stale_why") for k in (ACME, GLOBEX)] == [None, None]  # fresh, under the new one
    assert store.score(INITECH, new)["stale_why"] == "older_resume" and watch.unscored(cfg, store) == []


def test_marking_picks_all_queued_or_a_score_and_up(env):
    cfg, store, rid = env
    for key, n in ((ACME, 90), (GLOBEX, 50), (INITECH, 40)):
        store.save_score(key, rid, fit(n))
    store.set_status([INITECH], "queued")
    keys, scope = scorestate.pick(cfg, store, min_score=80, queued=True)
    assert sorted(keys) == sorted([ACME, INITECH]) and scope == "scoring 80+ and queued"
    assert scorestate.pick(cfg, store, queued=True)[0] == [INITECH]
    assert sorted(scorestate.pick(cfg, store)[0]) == sorted([ACME, GLOBEX, INITECH])


def test_keeping_makes_the_scores_current_without_scoring(env, asked):
    cfg, store, rid = env
    for key in (ACME, GLOBEX):
        store.save_score(key, rid, fit(75))
    new = rebuild(cfg)
    assert scorestate.status(cfg, store)["older"] == 2
    assert scorestate.keep(cfg, store, "only a typo fixed") == 2
    assert not any(store.score(k, new).get("stale") for k in (ACME, GLOBEX))
    assert scorestate.status(cfg, store)["older"] == 0 and asked == []
    # the next rebuild flags them again: a kept score was kept for that resume only
    new = rebuild(cfg, "Python, LLMs, RAG, the third version")
    assert store.score(ACME, new)["stale_why"] == "older_resume"
    assert scorestate.keep(cfg, store) == 2 and "stale" not in store.score(ACME, new)
    # the resume put back to what a score was made under: it's current again, not "older"
    rebuild(cfg, "Python, LLMs, RAG")
    assert "stale" not in store.score(ACME, resume_id(cfg.resume, cfg.prompts))
    assert [d["action"] for d in scorestate.decisions(store.db)] == ["keep", "keep"]


def test_a_mark_survives_keeping_until_the_job_is_scored_or_the_mark_taken_back(env):
    cfg, store, rid = env
    store.save_score(ACME, rid, fit(75))
    new = rebuild(cfg)
    scorestate.mark_stale(cfg, store, "redo")
    scorestate.keep(cfg, store)
    assert store.score(ACME, new)["stale_why"] == "marked"
    assert scorestate.unmark(store) == 1 and "stale" not in store.score(ACME, new)
    assert scorestate.unmark(store) == 0


def test_the_status_counts_what_predates_the_resume_and_the_decisions_are_logged(env):
    cfg, store, rid = env
    store.save_score(ACME, OLD, fit(90))
    store.save_score(GLOBEX, OLD, fit(40))
    store.save_score(INITECH, rid, fit(70))
    store.set_status([ACME], "queued")
    st = scorestate.status(cfg, store)
    assert (st["scored"], st["older"], st["marked"], st["older_open"], st["older_queued"], st["older_min"]) == \
        (3, 2, 0, 2, 1, 1)
    assert st["resume"] == resume_family(rid) and st["min_fit"] == 60
    assert st["by_resume"] == [{"resume": "cv.md:000000000000", "jobs": 2, "last": st["by_resume"][0]["last"]}]
    assert st["last"] is None
    scorestate.mark_stale(cfg, store, "reworded", queued=True, now="2026-11-26T09:00:00-05:00")
    st = scorestate.status(cfg, store)
    assert st["marked"] == 1 and st["last"] == {"at": "2026-11-26T09:00:00-05:00", "action": "stale",
                                                 "reason": "reworded", "resume": resume_family(rid),
                                                 "scope": "queued", "jobs": 1}
    assert scorestate.wording(store.score(ACME, rid)) == "marked stale on 2026-11-26: reworded"
    assert scorestate.wording(store.score(GLOBEX, rid)) == "scored under an older resume"
    assert scorestate.status(SimpleNamespace(resume=None), store) == {"resume": None}


def test_scores_made_before_this_existed_show_as_stale_with_nothing_lost(env):
    """The state file of a jobwatch from before: scores under older resumes, none of the new tables. All of them
    show, flagged; the open and the saved rows are the same after."""
    cfg, store, rid = env
    store.save_score(ACME, "cv.md:111111111111:scorer-00000000", fit(85))  # an earlier one of the same job: not shown
    store.save_score(ACME, OLD, fit(90))
    store.save_score(GLOBEX, OLD, fit(80))
    store.save_score(INITECH, rid, fit(70))
    for table in ("score_stale", "score_kept", "score_decisions"):
        store.db.execute(f"DROP TABLE {table}")
    store.db.commit()
    before = store.db.execute("SELECT key, resume, result, scored_at FROM scores ORDER BY key, resume").fetchall()
    store.close()
    store = Store(cfg.state)  # opening it makes the tables
    assert [tuple(r) for r in store.db.execute("SELECT key, resume, result, scored_at FROM scores "
                                               "ORDER BY key, resume")] == [tuple(r) for r in before]
    assert {k: (f["score"], f.get("stale_why")) for k, f in store.scores(rid).items()} == \
        {ACME: (90, "older_resume"), GLOBEX: (80, "older_resume"), INITECH: (70, None)}
    assert scorestate.status(cfg, store)["older"] == 2
    entries, _ = watch._matching(cfg, store, ("new", "shown"))
    assert {e.job.key: e.fit.get("stale_why") for e in entries} == {ACME: "older_resume", GLOBEX: "older_resume",
                                                                    INITECH: None}
    assert watch.unscored(cfg, store) == []
    store.close()


def test_old_scores_can_be_kept_as_current(env):
    """`jobwatch score --keep-old`: scores a scorer made for this resume before the one in use are copied as current
    scores (their day kept, marked kept_from), for those jobs' sake that no other scorer's score is waiting."""
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
    assert store.score(GLOBEX, rid)["score"] == 70
    assert [e.job.key for e in watch.unscored(cfg, store) if e.job.key in (ACME, INITECH)] == []
    assert store.keep_old_scores(rid) == (0, "11111111")             # nothing more to keep
    assert store.keep_old_scores(rid, "00000000") == (1, "00000000")  # unless that scorer is named
    # --redo-kept: the kept ones are asked for again (their old score shows), the fresh one stays
    dropped = set(store.drop_kept_scores(rid))
    assert dropped == {ACME, INITECH}
    assert store.score(GLOBEX, rid)["score"] == 70 and store.score(ACME, rid) is not None
    assert not {ACME, INITECH} & {e.job.key for e in watch.unscored(cfg, store)}
    assert {ACME, INITECH} <= {e.job.key for e in watch.unscored(cfg, store, again=dropped)}


def test_scores_with_requirements_left_unjudged_are_dropped_to_score_again(env):
    """`jobwatch score --incomplete`: a score saved before such results counted as failures goes, and its job is
    back in the scorer's line; complete scores and other resumes' scores stay."""
    cfg, store, rid = env
    store.save_score(ACME, rid, {**fit(5), "flags": ["no assessment returned for 'ros' (scored as not_met)"]})
    store.save_score(GLOBEX, rid, {**fit(80), "flags": ["core requirement 'ml' partial: score capped at 69"]})
    other = "other.md:000000000000:scorer-00000000"
    store.save_score(INITECH, other, {**fit(65), "flags": ["no assessment returned for 'ros' (scored as not_met)"]})
    assert store.drop_incomplete_scores(rid) == [ACME]
    assert store.score(ACME, rid) is None and store.score(GLOBEX, rid)["score"] == 80
    assert store.score(INITECH, rid)["score"] == 65  # another resume's score isn't touched
    assert ACME in [e.job.key for e in watch.unscored(cfg, store)]


def test_a_fresh_score_wins(env):
    cfg, store, rid = env
    store.save_score(ACME, OLD, fit(90))
    store.save_score(ACME, rid, fit(65))
    e = next(e for e in watch._matching(cfg, store, ("new", "shown"))[0] if e.job.key == ACME)
    assert e.fit["score"] == 65 and "stale" not in e.fit
    assert ACME not in [x.job.key for x in watch.unscored(cfg, store)]
    assert ACME not in watch.unscored_reasons(cfg, store)


def test_the_scores_command_reports_marks_keeps_and_logs(env, capsys):
    cfg, store, rid = env
    for key, n in ((ACME, 90), (GLOBEX, 50), (INITECH, 70)):
        store.save_score(key, rid, fit(n))
    rebuild(cfg)

    def run(*args):
        cli.main(["-c", str(cfg.path), "scores", *args])
        return capsys.readouterr().out

    out = run()
    assert "3 jobs with a fit score" in out and "3 of the scores were made under an older resume" in out
    assert "jobwatch scores --stale" in out
    assert "Marked 2 scores stale" in run("--stale", "--min", "60", "--reason", "new summary")
    out = run()
    assert "2 marked stale, waiting to be scored again" in out and "Last decision: stale" in out
    assert "(new summary)" in out
    assert "Took back 2 marks" in run("--unmark")
    assert "Kept 3 scores as made" in run("--keep", "--reason", "typo")
    assert "Every score was made under the resume now" in run()
    log = run("--log")
    assert [line.split()[2] for line in log.splitlines()] == ["stale", "unmark", "keep"]
    assert "new summary" in log and "typo" in log
    with pytest.raises(SystemExit):
        run("--keep", "--stale")  # one decision at a time


def test_the_page_reports_and_takes_the_decisions(watchlist, web, asked):
    (watchlist.parent / "cv.md").write_text("Python, LLMs, RAG")
    raw = yaml.safe_load(watchlist.read_text())
    watchlist.write_text(yaml.safe_dump({**raw, "resume": "cv.md", "scoring": {"auto": False}}))
    app = App(watchlist)
    app.post_fetch({})
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    store.save_score(ACME, OLD, fit(90))
    store.close()
    assert app.get_scores({})["older"] == 1 and app.get_scores({})["decisions"] == []
    with pytest.raises(Exception, match="min_score"):
        app.post_scores_stale({"min_score": 400})
    r = app.post_scores_stale({"reason": "rewrote it", "queued": True})
    assert (r["count"], r["marked"], r["decisions"][0]["scope"]) == (0, 0, "queued")  # no job is queued
    r = app.post_scores_stale({"reason": "rewrote it", "min_score": 80})
    assert (r["count"], r["marked"]) == (1, 1)
    assert app.get_job({"key": ["c1"]})["fit"] is None  # another job
    assert [e.job.key for e in watch.unscored(cfg, Store(cfg.state))][:1] == [ACME]  # in line to be scored again
    assert app.post_scores_unmark({})["count"] == 1
    assert app.post_scores_keep({"reason": "ok"})["older"] == 0
    assert asked == []


def test_scoring_again_clears_the_mark(env):
    cfg, store, rid = env
    store.save_score(ACME, rid, fit(65))
    scorestate.mark_stale(cfg, store, "x")
    assert store.score(ACME, rid)["stale_why"] == "marked"
    store.save_score(ACME, rid, fit(72))
    assert "stale" not in store.score(ACME, rid) and store.db.execute("SELECT COUNT(*) FROM score_stale"
                                                                      ).fetchone()[0] == 0
