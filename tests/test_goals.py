"""Goals: what you want next, in the watchlist (config.Goals), the Comps career part that scores from them, the
Settings API that saves them, and first-run onboarding's optional title suggestions. No network: the people,
companies and the model are made up."""

import json
import re
import shutil
import subprocess

import pytest
import yaml

from jobwatch import chat, comps, config, onboard
from jobwatch.web import ApiError, App
from tests.test_page_js import page_function


def load(tmp_path, text):
    path = tmp_path / "jobwatch.yaml"
    path.write_text(text)
    return config.load(path)


def career(goals, kind, role):
    row = {"health": {"kind": kind} if kind else None, "comp": {"role": role}}
    return comps._career(row, goals)


def test_no_goals_keep_the_fixed_numbers(tmp_path):
    cfg = load(tmp_path, "companies: []\n")
    assert cfg.goals == config.Goals() and not cfg.goals.scores
    assert [career(cfg.goals, k, "product")[0] for k in config.GOAL_KINDS] == [95, 70, 55]
    assert [career(cfg.goals, k, None)[0] for k in config.GOAL_KINDS] == [80, 55, 40]
    assert career(cfg.goals, "tech", "internal") == (75, "tech company, internal tools",
                                                      "its career value is 75/100 (tech company, internal tools)")
    # only the free-text parts set: still the fixed rules
    cfg = load(tmp_path, "goals: {about: Staff engineer, track: ic, horizon: 3 years}\n")
    assert career(cfg.goals, "enterprise", "customer")[0] == 45


def test_goals_score_first_choice_best(tmp_path):
    cfg = load(tmp_path, "goals:\n  company_kinds: [consulting, tech, enterprise]\n"
                         "  roles: [customer, product, internal]\n")
    g = cfg.goals
    assert [career(g, k, None)[0] for k in ("consulting", "tech", "enterprise")] == [90, 65, 40]
    assert [career(g, "tech", r)[0] for r in ("customer", "product", "internal")] == [75, 65, 55]
    part, words, why = career(g, "consulting", "customer")
    assert part == 100 and words == "consulting (your 1st choice), customer-facing (your 1st choice)"
    assert why.endswith("(consulting (your 1st choice), customer-facing (your 1st choice)), by your goals")
    # a role with no kind kept starts from the neutral 50; a kind with no role keeps just the kind
    assert career(g, None, "product")[0] == 50 and career(g, "tech", None)[:2] == (65, "tech company (your 2nd choice)")


def test_any_is_neutral_and_a_name_left_out_ranks_last(tmp_path):
    g = load(tmp_path, "goals: {company_kinds: any, roles: [product]}\n").goals
    assert g.company_kinds == ("any",)
    assert [career(g, k, "product")[0] for k in config.GOAL_KINDS] == [75, 75, 75]  # 65 + 10 for every kind
    assert career(g, "tech", "internal")[0] == 55  # not on your list: -10
    assert career(g, "tech", "internal")[1] == "tech company, internal tools (not on your list)"
    # only the roles said: the kind keeps the fixed rule
    g = load(tmp_path, "goals: {roles: [internal, product]}\n").goals
    assert career(g, "tech", "internal")[0] == 90 and career(g, "enterprise", None)[0] == 40


@pytest.mark.parametrize("health, stage", [
    ({"listing": "public", "stage": "Series B"}, "public"),  # listed: whatever round it once raised
    ({"listing": "private", "stage": "Series B, $50M, July 2025"}, "startup"),
    ({"stage": "Seed, $4M"}, "startup"),
    ({"stage": "Series D, $250M ARR"}, "growth"),
    ({"stage": "late-stage, pre-IPO"}, "growth"),
    ({"listing": "private", "stage": ""}, None),  # private, but how far along isn't kept
    (None, None),
])
def test_a_companys_stage_is_read_from_its_health(health, stage):
    assert comps.stage_of(health) == stage


def test_the_stage_you_prefer_lifts_the_career_part_only_where_it_is_known(tmp_path):
    g = load(tmp_path, "goals: {company_kinds: [tech, consulting, enterprise], stages: [growth, startup]}\n").goals
    assert g.stages == ("growth", "startup") and g.scores
    tech = lambda stage, listing="private": comps._career(  # noqa: E731
        {"health": {"kind": "tech", "listing": listing, "stage": stage}, "comp": {"role": None}}, g)
    assert tech("Series D")[:2] == (100, "tech company (your 1st choice), growth stage (your 1st choice)")
    assert tech("Series B")[0] == 90  # 2nd choice: +0
    assert tech("", "public")[:2] == (80, "tech company (your 1st choice), public company (not on your list)")
    assert tech("")[:2] == (90, "tech company (your 1st choice)")  # stage not kept: no lift either way
    # no stage preference: a stage changes nothing, and alone it isn't a career value
    g = load(tmp_path, "goals: {company_kinds: [tech]}\n").goals
    assert comps._career({"health": {"kind": "tech", "stage": "Seed"}, "comp": {"role": None}}, g)[0] == 90
    assert comps._career({"health": {"stage": "Seed"}, "comp": {"role": None}}, config.Goals())[1] == \
        "no kind or role kept"


def test_the_suggestion_shows_the_goals_behind_the_career_part(tmp_path):
    cfg = load(tmp_path, "goals: {company_kinds: [enterprise, tech], roles: [internal]}\n")
    health = dict.fromkeys(("listing", "stage", "raised", "layoffs", "rating", "risk", "headcount"))
    row = {"key": "k", "company": "Acme", "title": "Engineer", "status": "interviewing",
           "health": {**health, "kind": "enterprise", "stale": False}, "comp": {"role": "internal"}, "fit": None,
           "pay_mid": None, "base_mid": None, "asked_mid": None, "offered_mid": None}
    ranked = comps.suggest(cfg, [row])["ranking"][0]
    both = "enterprise (your 1st choice), internal tools (your 1st choice)"
    assert ranked["parts"]["career"] == {"score": 100, "input": both, "known": True}
    assert "by your goals" in ranked["reason"]


@pytest.mark.parametrize("text, message", [
    ("goals: [tech]", "goals looks like"),
    ("goals: {company_kinds: [startup]}", "goals.company_kinds can only name tech, consulting, enterprise or any"),
    ("goals: {roles: [product, product]}", "names product twice"),
    ("goals: {roles: [any, product]}", "any means no preference"),
    ("goals: {stages: [unicorn]}", "goals.stages can only name startup, growth, public or any"),
    ("goals: {track: boss}", "goals.track must be one of ic, manager, either"),
    ("goals: {about: 3}", "goals.about is text"),
    ("goals: {salary: 3}", "unknown goals setting(s): salary"),
])
def test_bad_goals_are_refused_with_why(tmp_path, text, message):
    with pytest.raises(config.ConfigError, match=re.escape(message)):
        load(tmp_path, text + "\n")


def test_goals_save_through_the_settings_page_and_keep_other_keys(watchlist):
    app = App(watchlist)
    assert app.get_settings({})["goals"] == {}
    goals = {"about": "Ten years in tooling.", "company_kinds": ["tech", "consulting"], "roles": ["any"],
             "track": "ic", "horizon": "take risks for 3-5 years"}
    app.post_settings({"goals": goals, "pay": {"target": "170000-200000", "floor": 150000},
                       "comps": {"weights": {"career": 50, "pay": 50, "fit": 0, "progress": 0, "health": 0}}})
    s = app.get_settings({})
    assert s["goals"] == goals and s["pay"]["floor"] == 150000 and s["state"] == "state.db"
    cfg = config.load(watchlist)
    assert cfg.goals.company_kinds == ("tech", "consulting") and cfg.goals.roles == ("any",) and cfg.goals.track == "ic"
    assert (cfg.pay.target, cfg.pay.target_max, cfg.pay.floor) == (170000, 200000, 150000)
    assert cfg.comps.weights["career"] == 0.5 and cfg.comps.weights["fit"] == 0
    with pytest.raises(config.ConfigError, match=r"goals\.track"):
        app.post_settings({"goals": {"track": "boss"}})
    assert config.load(watchlist).goals.track == "ic"  # refused: the file is as it was
    app.post_settings({"goals": None})
    assert "goals" not in yaml.safe_load(watchlist.read_text()) and not config.load(watchlist).goals.scores


def test_the_example_watchlist_has_a_goals_block(tmp_path):
    assert "# goals:" in config.EXAMPLE and "company_kinds:" in config.EXAMPLE
    uncommented = config.EXAMPLE.replace("# goals:", "goals:").replace("#   about", "  about") \
        .replace("#   company_kinds", "  company_kinds").replace("#   roles", "  roles") \
        .replace("#   track", "  track").replace("#   horizon", "  horizon")
    path = tmp_path / "jobwatch.yaml"
    path.write_text(uncommented)
    g = config.load(path).goals
    assert g.company_kinds == ("tech", "consulting", "enterprise") and g.track == "ic" and g.about


# --- onboarding's optional "Suggest titles from my resume"

@pytest.fixture
def with_resume(watchlist):
    (watchlist.parent / "resume.md").write_text("# Jane Doe\nTen years building Python data platforms.")
    watchlist.write_text(watchlist.read_text() + "resume: resume.md\ngoals: {about: Build product again, track: ic}\n")
    return watchlist


@pytest.fixture
def fake_model(monkeypatch):
    titles = '["Senior Data Engineer", "Platform Engineer", "Senior Data Engineer"]'
    seen = {"calls": 0, "reply": f'```json\n{{"titles": {titles}, "keywords": ["Python", "ETL", 7]}}\n```'}

    def reply(backend, system, messages, model="", max_tokens=0):
        seen.update(calls=seen["calls"] + 1, system=system)
        yield seen["reply"]
        yield {"input_tokens": 10}
    monkeypatch.setattr(chat, "check", lambda backend, keychain="": None)
    monkeypatch.setattr(chat, "reply", reply)
    return seen


def test_titles_are_suggested_from_the_resume_and_goals(with_resume, fake_model):
    app = App(with_resume)
    assert app.get_onboarding({})["ready"] is True
    assert fake_model["calls"] == 0  # asking whether it can is no call
    got = app.post_onboarding_titles({})
    assert got["titles"] == ["Senior Data Engineer", "Platform Engineer"] and got["keywords"] == ["Python", "ETL"]
    assert got["where"]["local"] is True
    assert "Ten years building Python" in fake_model["system"] and "Build product again" in fake_model["system"]
    # suggestions only: nothing was saved
    assert "titles" not in yaml.safe_load(with_resume.read_text())["filters"]
    assert config.load(with_resume).keywords == {"Python": 2.0, "LLM": 3.0, "RAG": 3.0}


def test_no_titles_without_a_resume_or_a_model_and_no_call_is_made(watchlist, fake_model, monkeypatch):
    app = App(watchlist)
    got = app.get_onboarding({})
    assert got["ready"] is False and got["why"] == "Add your resume first."
    with pytest.raises(ApiError, match="Add your resume first"):
        app.post_onboarding_titles({})
    assert fake_model["calls"] == 0

    (watchlist.parent / "resume.md").write_text("Jane Doe, engineer")
    watchlist.write_text(watchlist.read_text() + "resume: resume.md\n")

    def unavailable(backend, keychain=""):
        raise chat.ChatUnavailable("chat on this computer needs Apple Silicon")
    monkeypatch.setattr(chat, "check", unavailable)
    assert App(watchlist).get_onboarding({})["why"] == "chat on this computer needs Apple Silicon"
    with pytest.raises(ApiError, match="Apple Silicon"):
        App(watchlist).post_onboarding_titles({})
    assert fake_model["calls"] == 0


def test_a_reply_that_isnt_titles_is_said_so(with_resume, fake_model):
    fake_model["reply"] = "I would try product roles."
    with pytest.raises(ApiError, match="wasn't the titles asked for"):
        App(with_resume).post_onboarding_titles({})
    assert onboard.parse('{"titles": [], "keywords": ["x"]}') is None


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_pay_target_is_written_and_read_back(tmp_path):
    js = tmp_path / "target.js"
    js.write_text(page_function("targetText") + page_function("targetValues") + """
console.log(JSON.stringify([targetText({}), targetText({ target: 180000 }),
  targetText({ target: 170000, target_max: 200000 }), targetValues(" "), targetValues("180000"),
  targetValues("170K-200K")]));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ["", "180000", "170000-200000", {"target": None, "target_max": None},
                                    {"target": 180000, "target_max": None}, {"target": "170K-200K", "target_max": None}]
