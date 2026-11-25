"""Best fit's order falls with a posting's age (display.age_decay) while its fit score stays as scored, and Today
opens on Posted within 7 days (display.today_defaults.posted)."""

from datetime import UTC, datetime, timedelta

import pytest

from jobwatch import config
from jobwatch.config import AGE_DECAY, AgeDecay
from jobwatch.models import Job
from jobwatch.watch import Entry, _rank, _ranker, _spread

NOW = datetime.now(UTC)


def entry(n, fit, age, focus=0, company=None):
    """An Entry for a posting `age` days old (None: undated) scored `fit` (None: not scored)."""
    job = Job(source="greenhouse", company=(company or f"co{n}").lower(), id=str(n), title=f"Engineer {n}",
              url=f"https://example.com/{n}", company_name=company or f"Co{n}",
              posted=None if age is None else NOW - timedelta(days=age, hours=1))
    return Entry(job, {"status": "new"}, 0.0, [], fit=None if fit is None else {"score": fit}, focus=focus)


def order(entries, decay=AGE_DECAY):
    return [e.job.id for e in sorted(entries, key=lambda e: _rank(e, decay))]


def test_the_defaults_are_one_week_of_grace_then_half_a_point_a_day_and_a_120_day_cutoff():
    d = AgeDecay()
    assert (d.grace_days, d.per_day, d.cutoff_days) == (7, 0.5, 120)
    assert [d.penalty(a) for a in (0, 7, 8, 30, 119)] == [0, 0, 0.5, 11.5, 56.0]


def test_a_month_old_posting_needs_a_clearly_better_fit_than_a_fresh_one():
    assert order([entry(1, 85, 30), entry(2, 72, 1)]) == ["1", "2"]  # 85 - 11.5 = 73.5 beats 72
    assert order([entry(1, 80, 30), entry(2, 72, 1)]) == ["2", "1"]  # 68.5 doesn't
    assert order([entry(1, 71, 6), entry(2, 71, 3)]) == ["2", "1"]  # both in the grace week: the newer, on a tie


def test_a_posting_past_the_cutoff_sorts_below_everything_younger_even_with_the_better_fit():
    old = [entry(1, 100, 372), entry(2, 95, 188)]
    young = [entry(3, 20, 119), entry(4, 5, 3), entry(5, None, 100)]
    assert order([*old, *young]) == ["4", "3", "5", "2", "1"]  # the aged-out keep their own order after them
    assert order([entry(1, 100, 120), entry(2, 20, 121)]) == ["1", "2"]  # 120 is still in; 121 is out


def test_an_undated_posting_is_never_marked_down_more_than_a_month_old_one():
    d = AgeDecay()
    assert d.penalty(None) <= d.penalty(30) and d.penalty(None) == d.penalty(14) == 3.5
    assert not d.aged_out(None)
    assert d.penalty(None) <= AgeDecay(grace_days=0, per_day=1, cutoff_days=0).penalty(30)
    assert order([entry(1, 80, None), entry(2, 80, 40)]) == ["1", "2"]


def test_a_cutoff_shorter_than_the_unknown_age_caps_an_undated_posting_at_the_cutoff():
    assert AgeDecay(grace_days=0, per_day=1, cutoff_days=5).penalty(None) == 5


def test_the_decay_never_changes_the_fit_score_and_unscored_postings_still_follow_scored_ones():
    entries = [entry(1, 90, 60), entry(2, None, 1), entry(3, 40, 2)]
    assert order(entries) == ["1", "3", "2"]  # 90 less 26.5 still beats 40; the unscored one follows both
    assert [e.fit["score"] if e.fit else None for e in entries] == [90, None, 40]  # as scored


def test_the_focus_work_still_leads_among_postings_inside_the_cutoff_but_not_past_it():
    assert order([entry(1, 90, 2), entry(2, 50, 5, focus=1)]) == ["2", "1"]
    assert order([entry(1, 50, 2), entry(2, 99, 200, focus=1)]) == ["1", "2"]


def test_a_decay_of_zero_per_day_with_no_cutoff_is_the_old_order():
    off = AgeDecay(per_day=0, cutoff_days=0)
    assert order([entry(1, 90, 372), entry(2, 80, 1)], off) == ["1", "2"]


def test_the_company_spread_keeps_aged_out_postings_last():
    """A fresh third job from one company drops behind the others, but not behind a posting past the cutoff."""
    ranked = [entry(1, 90, 1, company="Globex"), entry(2, 85, 2, company="Globex"), entry(3, 80, 2, company="Globex"),
              entry(4, 70, 300, company="Initech")]
    assert [e.job.id for e in _spread(ranked, NOW, AgeDecay(cutoff_days=0))] == ["1", "2", "4", "3"]  # no cutoff
    assert [e.job.id for e in _spread(ranked, NOW, AgeDecay())] == ["1", "2", "3", "4"]


def test_the_ranker_reads_the_watchlist(watchlist):
    cfg = config.load(watchlist)
    assert cfg.age_decay == AgeDecay() and cfg.today_posted == 7
    assert _ranker(cfg)(entry(1, 80, 30)) == _rank(entry(1, 80, 30), AgeDecay())


def test_the_page_gets_the_default_chip_and_which_jobs_are_aged_out(watchlist, web):
    from jobwatch.web import App

    app = App(watchlist)
    app.post_fetch({})
    d = app.get_digest({})
    assert d["defaults"] == {"fit": 0, "pay": 0, "posted": 7}
    assert d["jobs"] and all(j["aged_out"] is False for j in d["jobs"])
    app.post_settings({"display": {"today_defaults": {"posted": 0}, "age_decay": {"cutoff_days": 2}}})
    d = app.get_digest({})
    assert d["defaults"]["posted"] == 0
    assert {j["aged_out"] for j in d["jobs"]} == {j["age_days"] is not None and j["age_days"] > 2 for j in d["jobs"]}


def test_the_digest_orders_by_the_decayed_rank_and_leaves_the_fit_alone(watchlist, web):
    """Acme 101 is 3 days old (fit 70), Globex 10 days (fit 76), Initech 0 days (fit 65): the digest, which the
    CLI and the MCP get_digest share with the page, follows display.age_decay, and each score stays as saved."""
    from jobwatch.score import resume_id
    from jobwatch.store import Store
    from jobwatch.watch import build_digest, fetch_all

    (watchlist.parent / "cv.md").write_text("Python, LLMs, RAG")
    watchlist.write_text(watchlist.read_text() + "resume: cv.md\n")

    def ranked(display=""):
        cfg = config.load(watchlist)
        if display:
            watchlist.write_text(watchlist.read_text() + display)
            cfg = config.load(watchlist)
        store = Store(cfg.state)
        try:
            fetch_all(cfg, store)
            rid = resume_id(cfg.resume, cfg.prompts)
            for key, score in (("greenhouse:acme:101", 70), ("lever:globex:aaaa-1111", 76), ("ashby:initech:c1", 65)):
                store.save_score(key, rid, {"score": score, "must_haves_met": 1, "must_haves_total": 1, "gaps": [],
                                            "summary": ""})
            entries = build_digest(cfg, store, include_seen=True, score_top=0).entries
            return [(e.job.key.split(":")[1], e.fit["score"]) for e in entries]
        finally:
            store.close()

    assert ranked() == [("globex", 76), ("acme", 70), ("initech", 65)]  # 10 days old: 1.5 points off, no more
    assert ranked("display:\n  age_decay: {grace_days: 0, per_day: 2}\n") == \
        [("initech", 65), ("acme", 70), ("globex", 76)]  # 65, 70 - 6, 76 - 20
    assert ranked("") == [("initech", 65), ("acme", 70), ("globex", 76)]


def write(watchlist, display):
    watchlist.write_text(watchlist.read_text() + f"display:\n{display}")
    return config.load(watchlist)


def test_the_knobs_are_in_the_watchlist(watchlist):
    cfg = write(watchlist, "  age_decay: {grace_days: 3, per_day: 1, cutoff_days: 60}\n"
                           "  today_defaults: {posted: 14}\n")
    assert cfg.age_decay == AgeDecay(3, 1.0, 60) and cfg.today_posted == 14
    assert config.defaults()["display"]["age_decay"] == {"grace_days": 7, "per_day": 0.5, "cutoff_days": 120}
    assert config.defaults()["display"]["today_defaults"] == {"posted": 7}


def test_posted_0_starts_on_any_and_a_partial_age_decay_keeps_the_other_defaults(watchlist):
    cfg = write(watchlist, "  today_defaults: {posted: 0}\n  age_decay: {per_day: 0}\n")
    assert cfg.today_posted == 0 and cfg.age_decay == AgeDecay(per_day=0.0)


@pytest.mark.parametrize("display, message", [
    ("  today_defaults: {posted: week}\n", r"display\.today_defaults\.posted must be a whole number"),
    ("  today_defaults: {posted: 7, days: 3}\n", r"display\.today_defaults is"),
    ("  age_decay: {per_day: fast}\n", r"display\.age_decay\.per_day must be a number"),
    ("  age_decay: {per_day: -1}\n", r"display\.age_decay\.per_day must be a number"),
    ("  age_decay: {grace_days: -1}\n", r"display\.age_decay\.grace_days must be a whole number"),
    ("  age_decay: {cutoff_days: 1.5}\n", r"display\.age_decay\.cutoff_days must be a whole number"),
    ("  age_decay: {halflife: 9}\n", r"display\.age_decay is"),
    ("  age_decay: soon\n", r"display\.age_decay is"),
])
def test_a_bad_knob_is_refused_by_name(watchlist, display, message):
    with pytest.raises(config.ConfigError, match=message):
        write(watchlist, display)
