"""A weak fit with no must-haves still says what it found missing: the Gaps row falls back to the requirements the
scorer judged missing or partly shown (score.soft_gaps), nice-to-haves marked as such, missing first."""

import pytest

from jobwatch import cli, config
from jobwatch.score import SOFT_GAPS, brief, resume_id, soft_gaps
from jobwatch.store import Store
from jobwatch.web import App


def row(name, verdict, kind="nice_to_have"):
    return {"id": name.lower(), "requirement": name, "kind": kind, "verdict": verdict, "evidence": [],
            "evidence_verified": True, "reasoning": "why"}


# A posting with only an "ideal candidate has" list: every requirement is a nice to have, so 0 of 0 must-haves.
IDEAL = [row("Umbrella industry experience", "not_met"), row("Python services", "met"),
         row("Two embedded enterprise deployments", "not_met"), row("Strong SQL", "partial"),
         row("Weeks of on-site travel", "not_met"), row("Clear writing", "partial")]


def fit(requirements, gaps=(), met=0, total=0, score=46.0):
    return {"score": score, "must_haves_met": met, "must_haves_total": total, "gaps": list(gaps),
            "summary": "ok", "flags": [], "requirements": requirements}


def test_a_fit_with_no_must_haves_lists_what_is_missing_then_what_is_partly_shown():
    assert soft_gaps(fit(IDEAL)) == [
        "Umbrella industry experience (nice to have, missing)",
        "Two embedded enterprise deployments (nice to have, missing)",
        "Weeks of on-site travel (nice to have, missing)",
        "Strong SQL (nice to have, partly)",
        "Clear writing (nice to have, partly)"]


def test_a_must_have_that_is_not_in_the_gaps_is_marked_as_one():
    got = soft_gaps(fit([row("Initech payroll rules", "partial", kind="must_have")]))
    assert got == ["Initech payroll rules (must-have, partly)"]


@pytest.mark.parametrize("given", [
    fit(IDEAL, gaps=["Globex certification"], met=1, total=2),   # it has gaps of its own
    fit([row("Python services", "met"), row("Strong SQL", "met")]),  # everything met
    fit([]), {"score": 50, "must_haves_met": 0, "must_haves_total": 0, "gaps": []},  # no requirements kept
    None])
def test_nothing_to_add_when_the_fit_has_gaps_or_meets_everything_or_kept_no_requirements(given):
    assert soft_gaps(given) == []


def test_the_list_is_capped():
    many = [row(f"Skill {n}", "not_met") for n in range(SOFT_GAPS + 5)]
    assert len(soft_gaps(fit(many))) == SOFT_GAPS


def test_a_list_carries_the_soft_gaps_without_the_requirements():
    out = brief(fit(IDEAL))
    assert "requirements" not in out and out["soft_gaps"][0].startswith("Umbrella industry experience")
    assert "soft_gaps" not in brief(fit(IDEAL, gaps=["Globex certification"], met=1, total=2))


# -- the page

def _score(web, watchlist, key, given):
    cli.main(["-c", str(watchlist), "fetch"])
    cv = watchlist.parent / "cv.md"
    cv.write_text("# Jane Doe")
    config.save(watchlist, {"resume": str(cv)})
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    store.save_score(key, resume_id(cfg.resume), given)
    store.close()


def test_today_and_the_job_view_carry_the_soft_gaps(web, watchlist):
    _score(web, watchlist, "lever:globex:aaaa-1111", fit(IDEAL))
    app = App(watchlist)
    today = {j["key"]: j for j in app.get_digest({})["jobs"]}["lever:globex:aaaa-1111"]["fit"]
    assert today["soft_gaps"][0] == "Umbrella industry experience (nice to have, missing)"
    assert "requirements" not in today
    detail = app.get_job({"key": ["lever:globex:aaaa-1111"]})["fit"]
    assert detail["soft_gaps"] == today["soft_gaps"] and detail["requirements"] == IDEAL


