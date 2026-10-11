"""The fit-score prompts in Settings: shown, edited (scoring.prompts holds only the edited ones), checked, and
part of what a score is stored under, so a score made with other prompts is never shown as current. Works with
a shortlist-ai that takes edited prompts, one from before that (shown read-only), and none at all."""

import sys
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace

import pytest
import yaml

from jobwatch import cli, config, score, watch
from jobwatch.score import ScoringUnavailable, prompt_info, resume_id, score_jobs
from jobwatch.store import Store
from jobwatch.web import App

FIT = {"score": 70, "must_haves_met": 2, "must_haves_total": 3, "gaps": [], "summary": ""}
STRICT = "Judge strictly. Quote the profile."


@dataclass(frozen=True)
class Prompt:
    name: str
    about: str
    default: str
    placeholders: tuple[str, ...] = ()


class PromptError(ValueError):
    pass


PROMPTS = {p.name: p for p in (
    Prompt("score_system", "Judges each requirement.", "Judge each requirement."),
    Prompt("score_request", "The request.", "Role: {title}\n{requirements}\n{profile}",
           ("title", "requirements", "profile")),
)}


def check(name, text):
    if name not in PROMPTS:
        raise PromptError(f"unknown prompt {name!r}")
    missing = [p for p in PROMPTS[name].placeholders if "{" + p + "}" not in text]
    if missing:
        raise PromptError(f"prompt {name!r} must keep {{{missing[0]}}}")
    return text


def _module(name, **attrs):
    m = ModuleType(name)
    m.__dict__.update(attrs)
    return m


@pytest.fixture
def shortlist(monkeypatch):
    """Stand in for shortlist-ai, as the version given: "editable" (takes edited prompts), "old" (0.1.1: prompts
    as constants, no shortlist_ai.prompts) or "missing". Records what extract_job and match_jobs were given."""
    calls = []

    def install(version="editable"):
        if version == "missing":  # submodules too: one imported already is found without its package
            for name in ("", ".backends", ".extract", ".pipeline", ".prompts", ".score", ".years"):
                monkeypatch.setitem(sys.modules, "shortlist_ai" + name, None)
            return calls

        def extract_job(path, model, cache, **kw):
            calls.append(("extract_job", kw))
            return SimpleNamespace(requirements=[])

        def match_jobs(resume, specs, model, **kw):
            calls.append(("match_jobs", {k: v for k, v in kw.items() if k == "prompts"}))
            result = SimpleNamespace(score=70, must_haves_met=2, must_haves_total=3, summary="", flags=[],
                                     requirements=[])
            return SimpleNamespace(errors={}, matches=[SimpleNamespace(job_id=k, result=result, gaps=[])
                                                      for k in specs])

        modules = {
            "shortlist_ai": _module("shortlist_ai"),
            "shortlist_ai.backends": _module("shortlist_ai.backends", get_backend=lambda name: name),
            "shortlist_ai.extract": _module("shortlist_ai.extract", Cache=lambda d: d, extract_job=extract_job,
                                            RESUME_SYSTEM="Read the resume.", JOB_SYSTEM="List the requirements."),
            "shortlist_ai.pipeline": _module("shortlist_ai.pipeline", match_jobs=match_jobs),
            "shortlist_ai.score": _module("shortlist_ai.score", SCORE_SYSTEM="Judge each requirement."),
            "shortlist_ai.years": _module("shortlist_ai.years", ROLES_SYSTEM="Count the years."),
            "shortlist_ai.prompts": (_module("shortlist_ai.prompts", PROMPTS=PROMPTS, PromptError=PromptError,
                                             check=check) if version == "editable" else None),
        }
        for name, module in modules.items():
            monkeypatch.setitem(sys.modules, name, module)
        return calls
    return install


@pytest.fixture
def resume_watchlist(watchlist, web):
    (watchlist.parent / "cv.md").write_text("Dana Acme\nPython, ROS")
    raw = yaml.safe_load(watchlist.read_text())
    watchlist.write_text(yaml.safe_dump({**raw, "resume": "cv.md"}))
    return watchlist


def _with_prompts(path, prompts):
    raw = yaml.safe_load(path.read_text())
    path.write_text(yaml.safe_dump({**raw, "scoring": {"backend": "local", "prompts": prompts}}))


def test_an_edited_prompt_is_part_of_what_a_score_is_stored_under(tmp_path):
    cv = tmp_path / "cv.md"
    cv.write_text("Dana Acme")
    plain = resume_id(cv)
    assert resume_id(cv, {}) == resume_id(cv, None) == plain  # nothing edited: the key scores always had
    strict = resume_id(cv, {"score_system": STRICT})
    assert strict.startswith(plain + ":prompts-") and strict == resume_id(cv, {"score_system": STRICT})
    assert resume_id(cv, {"score_system": STRICT + " Be brief."}) != strict


def test_the_watchlist_keeps_only_edited_prompts_checked_by_shortlist_ai(watchlist, shortlist):
    shortlist("editable")
    assert config.load(watchlist).prompts == {}
    _with_prompts(watchlist, {"score_system": STRICT})
    assert config.load(watchlist).prompts == {"score_system": STRICT}
    for bad, message in (({"tone": "Be kind."}, "unknown prompt 'tone'"),
                         ({"score_request": "Role: {title}\n{profile}"}, "must keep {requirements}"),
                         ({"score_system": 3}, "maps a prompt's name to its text"),
                         ("Be strict.", "maps a prompt's name to its text")):
        _with_prompts(watchlist, bad)
        with pytest.raises(config.ConfigError, match=r"scoring\.prompts") as e:
            config.load(watchlist)
        assert message in str(e.value)


def test_without_a_shortlist_ai_that_takes_them_edited_prompts_load_unchecked(watchlist, shortlist):
    shortlist("old")
    _with_prompts(watchlist, {"tone": "Be kind."})
    assert config.load(watchlist).prompts == {"tone": "Be kind."}  # scoring refuses them instead (below)


def test_settings_show_every_prompt_and_which_are_edited(watchlist, shortlist):
    shortlist("editable")
    _with_prompts(watchlist, {"score_system": STRICT})
    info = App(watchlist).get_settings({})["fit_prompts"]
    assert (info["installed"], info["editable"], info["note"]) == (True, True, None)
    by_name = {p["name"]: p for p in info["prompts"]}
    assert list(by_name) == ["score_system", "score_request"]
    assert by_name["score_system"] == {"name": "score_system", "about": "Judges each requirement.",
                                       "placeholders": [], "default": "Judge each requirement.",
                                       "text": STRICT, "edited": True}
    assert by_name["score_request"]["placeholders"] == ["title", "requirements", "profile"]
    assert not by_name["score_request"]["edited"]


def test_an_older_shortlist_ai_shows_its_prompts_read_only(shortlist):
    shortlist("old")
    info = prompt_info()
    assert (info["installed"], info["editable"]) == (True, False) and "pip install -U shortlist-ai" in info["note"]
    assert [(p["name"], p["text"]) for p in info["prompts"]] == [
        ("resume_system", "Read the resume."), ("job_system", "List the requirements."),
        ("score_system", "Judge each requirement."), ("years_system", "Count the years.")]
    assert "scoring stops" in prompt_info({"score_system": STRICT})["note"]


def test_no_prompts_without_scoring_installed(shortlist):
    shortlist("missing")
    info = prompt_info()
    assert (info["installed"], info["editable"], info["prompts"]) == (False, False, [])


def test_saving_an_edit_sets_old_scores_aside_and_putting_it_back_brings_them_back(resume_watchlist, shortlist):
    shortlist("editable")
    app = App(resume_watchlist)
    app.post_fetch({})
    cfg = config.load(resume_watchlist)
    store = Store(cfg.state)
    store.save_score("ashby:initech:c1", resume_id(cfg.resume), FIT)
    store.close()
    assert app.get_job({"key": ["c1"]})["fit"]["score"] == 70

    app.post_settings({"scoring": {"backend": "local", "prompts": {"score_system": STRICT + "\nOne per line."}}})
    text = resume_watchlist.read_text()
    assert "score_system: |-\n" in text  # written as a block: still readable by hand
    assert config.load(resume_watchlist).prompts == {"score_system": STRICT + "\nOne per line."}
    assert app.get_job({"key": ["c1"]})["fit"] is None  # made with the other prompt
    store = Store(cfg.state)
    assert "ashby:initech:c1" in [e.job.key for e in watch.unscored(config.load(resume_watchlist), store)]
    store.close()

    app.post_settings({"scoring": {"backend": "local"}})
    assert config.load(resume_watchlist).prompts == {}
    assert app.get_job({"key": ["c1"]})["fit"]["score"] == 70


def test_scores_are_made_and_stored_with_the_edited_prompts(resume_watchlist, shortlist):
    calls = shortlist("editable")
    _with_prompts(resume_watchlist, {"score_system": STRICT})
    cfg = config.load(resume_watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    todo = watch.unscored(cfg, store)[:1]
    assert watch.score_entries(cfg, store, todo, progress=lambda m: None) == (1, {})
    assert calls == [("extract_job", {"prompts": {"score_system": STRICT}}),
                     ("match_jobs", {"prompts": {"score_system": STRICT}})]
    assert store.score(todo[0].job.key, resume_id(cfg.resume, cfg.prompts))["score"] == 70
    assert store.score(todo[0].job.key, resume_id(cfg.resume)) is None
    store.close()


def test_with_nothing_edited_shortlist_ai_is_called_as_before(tmp_path, shortlist):
    calls = shortlist("old")  # 0.1.1 takes no prompts argument
    cv = tmp_path / "cv.md"
    cv.write_text("Dana Acme")
    job = SimpleNamespace(key="greenhouse:acme:1", display_company="Acme Robotics", title="Robotics Engineer",
                          to_text=lambda: "Robotics Engineer\nROS")
    results, errors = score_jobs([job], cv, "local", tmp_path)
    assert results[job.key]["score"] == 70 and not errors
    assert calls == [("extract_job", {}), ("match_jobs", {})]


def test_scoring_model_is_the_model_fit_scores_use(resume_watchlist, shortlist, monkeypatch):
    shortlist("editable")
    asked = []
    monkeypatch.setattr(sys.modules["shortlist_ai.backends"], "get_backend",
                        lambda name, *model: asked.append((name, *model)) or name)
    raw = yaml.safe_load(resume_watchlist.read_text())
    for scoring, want in (({"backend": "local", "model": "mlx-community/Tiny-Test-4bit"},
                           ("local", "mlx-community/Tiny-Test-4bit")),
                          ({"backend": "local"}, ("local",))):  # unset: shortlist-ai's own, asked as before
        resume_watchlist.write_text(yaml.safe_dump({**raw, "scoring": scoring}))
        cfg = config.load(resume_watchlist)
        store = Store(cfg.state)
        watch.fetch_all(cfg, store)
        asked.clear()
        watch.score_entries(cfg, store, watch.unscored(cfg, store)[:1], progress=lambda m: None)
        assert asked == [want]
        store.close()


def test_edited_prompts_need_a_shortlist_ai_that_takes_them(tmp_path, shortlist):
    calls = shortlist("old")
    with pytest.raises(ScoringUnavailable, match="pip install -U shortlist-ai"):
        score_jobs([], tmp_path / "cv.md", "local", tmp_path, prompts={"score_system": STRICT})
    shortlist("editable")
    with pytest.raises(ScoringUnavailable, match="must keep"):
        score_jobs([], tmp_path / "cv.md", "local", tmp_path, prompts={"score_request": "{title}"})
    assert calls == []


def test_score_show_prompts(watchlist, shortlist, capsys):
    shortlist("editable")
    _with_prompts(watchlist, {"score_system": STRICT})
    cli.main(["-c", str(watchlist), "score", "--show-prompts"])
    out = capsys.readouterr().out
    assert f"== score_system (edited): Judges each requirement.\n{STRICT}\n" in out
    assert "== score_request: The request.\nRole: {title}" in out


def test_with_a_real_shortlist_ai_that_takes_edited_prompts(tmp_path, monkeypatch):
    """The real pipeline (when installed) with a stand-in model: the edited prompt reaches it, the rest stay."""
    prompts = pytest.importorskip("shortlist_ai.prompts")
    from shortlist_ai import backends
    from shortlist_ai.schema import CandidateAssessment, JobSpec, Requirement, RequirementAssessment, Resume

    class Model:
        name, model, reads_documents = "fake", "fake-1", False

        def __init__(self):
            self.systems: list[str] = []

        def structured(self, system, content, output_type):
            self.systems.append(system)
            if output_type is Resume:
                return Resume(full_name="Dana Acme", email=None, phone=None, location=None, links=[], summary=None,
                              experience=[], education=[], skills=["ROS"], certifications=[], languages=[])
            if output_type is JobSpec:
                return JobSpec(title="Robotics Engineer",
                               requirements=[Requirement(id="ros", description="ROS", kind="must_have")])
            return CandidateAssessment(summary="", assessments=[
                RequirementAssessment(requirement_id="ros", verdict="met", evidence=["ROS"], reasoning="")])

    model = Model()
    monkeypatch.setattr(backends, "get_backend", lambda name: model)
    cv = tmp_path / "cv.md"
    cv.write_text("Dana Acme\nSkills: Python, ROS")
    job = SimpleNamespace(key="greenhouse:acme:1", display_company="Acme Robotics", title="Robotics Engineer",
                          to_text=lambda: "Robotics Engineer at Acme Robotics. Must know ROS.")
    results, errors = score_jobs([job], cv, "local", tmp_path, prompts={"score_system": STRICT})
    assert results[job.key]["score"] == 100 and not errors
    assert model.systems == [prompts.JOB_SYSTEM, prompts.RESUME_SYSTEM, STRICT]


def test_the_scorer_module_needs_no_shortlist_ai_to_import(shortlist):
    shortlist("missing")
    assert score.check_prompts({"anything": "goes"}) is None
