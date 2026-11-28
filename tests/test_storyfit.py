"""Your stories against a fit score's gaps (storyfit.py, `jobwatch scores --story-check`): checked by tags and the
local model only, kept beside the score as story evidence, shown on the page, in `show` and the digest, and counted
toward the fit minimum only with display.story_fit. The score itself never changes, and stories never reach a
cloud scorer or any model server that isn't on this computer or your network."""

import http.client
import json
import shutil
import subprocess

import pytest
import yaml

from jobwatch import chat, cli, config, filters, report, storyfit, watch
from jobwatch.models import Job
from jobwatch.score import resume_id
from jobwatch.store import Store
from jobwatch.stories import Story
from jobwatch.web import App

from .test_page_js import page_const, page_function

QUEUE = Story("queue-backpressure", "Tamed a backed-up event queue",
              "Added backpressure to the Kafka consumers and moved the stream processing to small batches.",
              "Three teams read the same topic at different speeds.", "Consumer lag went from hours to minutes.",
              skills=("Kafka", "stream processing"))
GUILD = Story("design-guild", "Started a design review guild",
              "Got six teams at Globex to adopt written design reviews, by asking and showing, never by mandate.",
              "No one reported to me.", "Reviews became the default within a quarter.",
              skills=("influence without authority", "engineering practices"))
BANK = [QUEUE, GUILD]

KAFKA = "Hands-on experience with Kafka and stream processing"
KAFKA_YEARS = "5+ years of Kafka in production"
GPU = "Deep expertise in GPU kernel optimization"
ADOPTION = "Driving adoption of new engineering practices through influence"
FIT = {"score": 50.0, "must_haves_met": 1, "must_haves_total": 3, "summary": "",
       "gaps": [KAFKA, GPU], "flags": [],
       "requirements": [
           {"id": "python", "requirement": "Python", "kind": "must_have", "verdict": "met", "evidence": ["Python"]},
           {"id": "kafka", "requirement": KAFKA, "kind": "must_have", "verdict": "not_met", "evidence": []},
           {"id": "gpu", "requirement": GPU, "kind": "must_have", "verdict": "not_met", "evidence": []},
           {"id": "adoption", "requirement": ADOPTION, "kind": "nice_to_have", "verdict": "partial",
            "evidence": ["design reviews"]}]}


def test_a_tagged_requirement_is_covered_by_tags():
    found = storyfit.by_tags(KAFKA, BANK)
    assert found and found.verdict == "covered" and found.story is QUEUE and found.how == "tags"
    assert "'Kafka'" in found.reason


def test_a_story_that_doesnt_match_leaves_the_gap():
    assert storyfit.by_tags(GPU, BANK) is None
    assert storyfit.by_tags("", BANK) is None


def test_a_years_requirement_is_at_most_partly_covered():
    found = storyfit.by_tags(KAFKA_YEARS, BANK)
    assert found and found.verdict == "partly"


def test_stemming_and_common_words():
    assert storyfit.words("Driving adoption of engineering practices") == storyfit.words(
        "drive adopt engineer practice")
    assert "experience" not in " ".join(storyfit.words("5+ years of experience"))


def test_no_stories_or_no_gaps_is_no_change():
    assert storyfit.check(FIT, []) is None
    assert storyfit.check({**FIT, "gaps": [], "requirements": []}, BANK) is None
    assert storyfit.annotate(FIT, None) is FIT


def test_the_check_keeps_only_what_a_story_covers_and_never_touches_the_fit():
    before = json.dumps(FIT, sort_keys=True)
    ev = storyfit.check(FIT, BANK, model=False)
    assert ev["by"] == "tags" and ev["checked"] == 3
    by_req = {i["requirement"]: i for i in ev["items"]}
    assert by_req[KAFKA]["verdict"] == "covered" and by_req[KAFKA]["story"] == "queue-backpressure"
    assert GPU not in by_req
    # skills "engineering practices" named whole, and most of the words: the nice-to-have the score called partly
    assert by_req[ADOPTION]["verdict"] == "covered" and by_req[ADOPTION]["story"] == "design-guild"
    shown = storyfit.annotate(FIT, ev)
    assert json.dumps(FIT, sort_keys=True) == before  # the fit itself is never changed
    assert shown["score"] == 50.0 and shown["must_haves_met"] == 1 and shown["gaps"] == [KAFKA, GPU]
    s = shown["story"]
    assert s["must_met"] == 2 and s["must_total"] == 3 and "story_score" not in shown  # not counted: off
    assert storyfit.open_gaps(shown) == [GPU]


def test_counting_stories_works_the_score_out_with_shortlists_weights():
    ev = storyfit.check({**FIT, "requirements": FIT["requirements"][:3]}, BANK, model=False)
    counted = storyfit.annotate(FIT, ev, count=True)
    # Python met (3), Kafka now met (3), GPU missing (0), the nice-to-have still partly (0.5): 6.5 of 10, not 3.5
    assert counted["story_score"] == 80.0
    assert counted["score"] == 50.0 and storyfit.fit_value(counted) == counted["story_score"]
    assert storyfit.fit_value(FIT) == 50.0


def test_a_core_cap_goes_when_a_story_covers_the_core_must_have():
    rows = [{"id": "core", "requirement": KAFKA, "kind": "must_have", "verdict": "partial"},
            {"id": "other", "requirement": "Python", "kind": "must_have", "verdict": "met"}]
    # 4.5 of 6 is 75, capped at 65 plus a quarter of the 10 above it
    fit = {"score": 67.5, "requirements": rows,
           "flags": ["core requirement 'core' partial: score capped at 67.5 (was 75.0)"]}
    assert storyfit.adjusted_score(fit, {storyfit._norm(KAFKA): "met"}) == 100.0
    # not covered: the cap stays, so nothing changes
    assert storyfit.adjusted_score(fit, {}) == 67.5


def test_evidence_for_a_gap_the_fit_no_longer_has_is_left_out():
    ev = storyfit.check(FIT, BANK, model=False)
    rescored = {**FIT, "requirements": [{**r, "verdict": "met"} for r in FIT["requirements"]], "gaps": []}
    assert "story" not in storyfit.annotate(rescored, ev)


def test_the_fit_minimum_compares_the_story_fit_only_when_counted():
    f = filters.Filters(min_fit=70)
    job = Job(source="greenhouse", company="acme", id="1", title="Engineer", url="https://example.com/1")
    assert filters.rejection(job, f, {"score": 60}) == ("fit", "fit 60/100")
    assert filters.rejection(job, f, {"score": 60, "story_score": 75}) is None
    assert filters.rejection(job, f, {"score": 60, "story_score": 65}) == ("fit", "fit 60/100 (65 with your stories)")


# -- the local model, and only the local model

def test_the_local_models_verdicts_win_and_are_read_carefully():
    reply = json.dumps({"verdicts": [
        {"requirement": "R1", "verdict": "no", "story": ""},                 # Kafka: the model says no
        {"requirement": "R2", "verdict": "covered", "story": "made-up-id"},  # GPU: a story not in the bank: left out
        {"requirement": "R3", "verdict": "covered", "story": "design-guild", "reason": "six teams adopted reviews"},
        {"requirement": "R9", "verdict": "covered", "story": "design-guild"}]})  # no such requirement
    asked = []
    ev = storyfit.check(FIT, BANK, model=True, ask=lambda system, messages: asked.append(system) or reply)
    assert ev["by"] == "local" and len(asked) == 1
    by_req = {i["requirement"]: i for i in ev["items"]}
    assert KAFKA not in by_req and GPU not in by_req
    assert by_req[ADOPTION] == {**by_req[ADOPTION], "verdict": "covered", "story": "design-guild", "how": "local",
                                "reason": "six teams adopted reviews"}


def test_a_reply_that_isnt_json_keeps_the_tags_verdicts():
    ev = storyfit.check(FIT, BANK, model=True, ask=lambda s, m: "I think so!")
    assert {i["requirement"]: i["how"] for i in ev["items"]}[KAFKA] == "tags"


def test_the_local_reply_is_kept_and_asked_once(tmp_path):
    store = Store(tmp_path / "state.db")
    calls = []

    def ask(system, messages):
        calls.append(1)
        return json.dumps({"verdicts": [{"requirement": "R2", "verdict": "partly", "story": "queue-backpressure"}]})
    storyfit.check(FIT, BANK, store, "greenhouse:acme:1", model=True, ask=ask)
    storyfit.check(FIT, BANK, store, "greenhouse:acme:1", model=True, ask=ask)
    assert len(calls) == 1
    store.close()


def test_no_local_model_falls_back_to_tags(monkeypatch):
    def down(backend, *a):
        raise chat.ChatUnavailable("no local model server at http://127.0.0.1:8010/v1")
    monkeypatch.setattr(chat, "check", down)
    monkeypatch.delenv("LOCAL_LLM_URL", raising=False)
    ev = storyfit.check(FIT, BANK, model=True)
    assert ev["by"] == "tags" and "checked by tags only" in ev["note"]
    assert any(i["requirement"] == KAFKA for i in ev["items"])


@pytest.mark.parametrize("url, local", [
    ("http://127.0.0.1:8010/v1", True), ("http://localhost:8010/v1", True), ("http://llm.localhost:8010/v1", True),
    ("http://[::1]:8010/v1", True), ("http://192.168.1.20:8010/v1", True), ("http://studio.local:8010/v1", True),
    ("https://api.anthropic.com/v1", False), ("https://api.example.com/v1", False), ("http://8.8.8.8/v1", False),
    ("", False)])
def test_only_this_computer_or_your_network_is_local(url, local):
    assert storyfit.is_local(url) is local


def test_a_hosted_endpoint_is_never_sent_your_stories(monkeypatch):
    """LOCAL_LLM_URL set to a hosted API: the check refuses before connecting to anything, and says why."""
    monkeypatch.setenv("LOCAL_LLM_URL", "https://api.example.com/v1")
    tried = []

    class Refused:
        def __init__(self, host, *a, **kw):
            tried.append(host)
            raise AssertionError(f"the story check connected to {host}")
    monkeypatch.setattr(http.client, "HTTPConnection", Refused)
    monkeypatch.setattr(http.client, "HTTPSConnection", Refused)
    ev = storyfit.check(FIT, BANK, model=True)
    assert tried == [] and ev["by"] == "tags"
    assert "isn't on this computer or your network" in ev["note"]


def test_the_local_call_goes_to_the_local_backend_only(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_URL", raising=False)
    monkeypatch.setattr(chat, "check", lambda backend, *a: None)
    seen = []

    def reply(backend, system, messages, model="", max_tokens=0):
        seen.append(backend)
        return iter(['{"verdicts": []}'])
    monkeypatch.setattr(chat, "reply", reply)
    storyfit.check(FIT, BANK, model=True)
    assert seen == ["local"]


# -- the store, the CLI, show and the digest, the page

@pytest.fixture
def env(watchlist, web):
    base = watchlist.parent
    (base / "cv.md").write_text("Python, LLMs, RAG")
    (base / "stories.yaml").write_text(yaml.safe_dump([s.to_dict() for s in BANK], sort_keys=False))
    raw = yaml.safe_load(watchlist.read_text())
    watchlist.write_text(yaml.safe_dump({**raw, "resume": "cv.md", "stories": "stories.yaml"}))
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    rid = resume_id(cfg.resume, cfg.prompts)
    key = store.db.execute("SELECT key FROM jobs ORDER BY key LIMIT 1").fetchone()["key"]
    store.save_score(key, rid, {**FIT, "scored_by": "local:stub"})
    yield cfg, store, rid, key
    store.close()


def test_dry_run_keeps_nothing_and_apply_keeps_evidence_without_touching_the_score(env, capsys):
    cfg, store, rid, key = env
    before = store.db.execute("SELECT result FROM scores WHERE key=?", (key,)).fetchone()["result"]
    cli.main(["-c", str(cfg.path), "scores", "--story-check", "--by", "tags"])
    out = capsys.readouterr().out
    assert "Checked 1 scored job against your 2 stories" in out and "1 job would have gaps covered" in out
    assert "+1 must-have  1/3 -> 2/3  fit 50 -> 85" in out and "Dry run: nothing was kept" in out
    assert store.story_evidence(key) is None
    with pytest.raises(SystemExit):
        cli.main(["-c", str(cfg.path), "scores", "--story-check", "--apply"])  # names no job: refused
    cli.main(["-c", str(cfg.path), "scores", "--story-check", "--apply", "--all", "--by", "tags"])
    assert "Kept story evidence for 1 job" in capsys.readouterr().out
    assert store.story_evidence(key)["items"][0]["story"] == "queue-backpressure"
    assert store.db.execute("SELECT result FROM scores WHERE key=?", (key,)).fetchone()["result"] == before
    fit = store.score(key, rid)
    assert fit["score"] == 50.0 and fit["story"]["must_met"] == 2 and "story_score" not in fit


def test_no_stories_file_says_so(env, capsys):
    cfg, store, rid, key = env
    raw = yaml.safe_load(cfg.path.read_text())
    del raw["stories"]
    cfg.path.write_text(yaml.safe_dump(raw))
    cli.main(["-c", str(cfg.path), "scores", "--story-check"])
    assert "No stories yet" in capsys.readouterr().out
    assert store.score(key, rid).get("story") is None


def test_show_and_the_digest_say_what_your_stories_cover(env):
    _cfg, store, rid, key = env
    store.save_story_evidence(key, storyfit.check(store.score(key, rid), BANK, model=False))
    fit = store.score(key, rid)
    lines = report.fit_lines(fit)
    assert any(line.startswith("With your stories (checked by tags only): must-haves 1/3 from the resume · 2/3 "
                               "with your stories") for line in lines)
    assert any(f'covered [must] {KAFKA}: your story "Tamed a backed-up event queue"' in line for line in lines)


def test_story_fit_counts_toward_the_fit_minimum_when_set(env):
    cfg, store, rid, key = env
    store.save_story_evidence(key, storyfit.check(store.score(key, rid), BANK, model=False))
    counted = Store(cfg.state, story_fit=True)
    assert counted.score(key, rid)["story_score"] == counted.scores(rid)[key]["story_score"] == 85.0
    assert counted.score(key, rid)["score"] == 50.0
    counted.close()
    raw = yaml.safe_load(cfg.path.read_text())
    cfg.path.write_text(yaml.safe_dump({**raw, "display": {"story_fit": True}}))
    assert config.load(cfg.path).story_fit is True
    cfg.path.write_text(yaml.safe_dump({**raw, "display": {"story_fit": "yes"}}))
    with pytest.raises(config.ConfigError, match=r"display\.story_fit"):
        config.load(cfg.path)


def test_a_story_too_long_is_left_out_and_the_rest_are_checked(env, capsys):
    cfg = env[0]
    long = {**GUILD.to_dict(), "id": "too-long", "result": "word " * 300}
    cfg.stories.write_text(yaml.safe_dump([long, QUEUE.to_dict()], sort_keys=False))
    cli.main(["-c", str(cfg.path), "scores", "--story-check", "--by", "tags"])
    out = capsys.readouterr()
    assert "Left out of the check: stories.yaml: story 1 (too-long): result is" in out.err
    assert "against your 1 story" in out.out and "1 job would have gaps covered" in out.out


def test_the_page_reads_a_story_by_id(env):
    cfg, store, rid, key = env
    app = App(cfg.path)
    assert app.get_story({"id": ["design-guild"]})["story"]["title"] == "Started a design review guild"
    with pytest.raises(Exception, match="No story"):
        app.get_story({"id": ["nope"]})
    job = app.get_job({"key": [key]})
    assert job["fit"].get("story") is None  # nothing kept yet: nothing shown
    store.save_story_evidence(key, storyfit.check(store.score(key, rid), BANK, model=False))
    assert app.get_job({"key": [key]})["fit"]["story"]["covered"][0]["title"] == "Tamed a backed-up event queue"


def test_cloud_scorers_never_get_story_text(env, monkeypatch):
    """The scorer (Claude, agy, a provider) is sent the resume and the postings only."""
    cfg, store, _rid, _key = env
    store.db.execute("DELETE FROM scores")
    store.db.commit()
    sent = []

    def fake(jobs, resume, backend, cache_dir, *a, **kw):
        sent.append(" ".join([resume.read_text(), repr(a), repr(kw), *(j.to_text() for j in jobs)]))
        return {j.key: {**FIT, "scored_by": "claude:stub"} for j in jobs}, {}
    monkeypatch.setattr(watch, "score_jobs", fake)
    cli.main(["-c", str(cfg.path), "score"])
    assert sent
    for story in BANK:
        for text in (story.title, story.did, story.result, *story.skills):
            assert all(text not in s for s in sent)


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_page_marks_covered_gaps_and_shows_both_counts(tmp_path):
    fit = {"score": 68, "must_haves_met": 7, "must_haves_total": 10, "story_score": 74,
           "gaps": ["Kafka and stream processing", "GPU kernels", "Influence across teams"],
           "story": {"by": "local", "must_met": 8, "must_total": 10, "note": "",
                     "covered": [{"requirement": "Kafka and stream processing", "kind": "must_have",
                                  "verdict": "covered", "story": "queue-backpressure", "title": "Tamed a queue",
                                  "reason": "r", "how": "local"}],
                     "partly": [{"requirement": "Influence across teams", "kind": "must_have", "verdict": "partly",
                                 "story": "design-guild", "title": "A review guild", "reason": "r", "how": "tags"}]}}
    js = tmp_path / "story.js"
    js.write_text("""
const h = (tag, attrs, ...kids) => ({ tag, attrs: attrs || {},
  kids: kids.flat(Infinity).filter(k => k != null && k !== false) });
const icon = () => null, openStory = () => null;
const text = n => n == null ? "" : typeof n !== "object" ? String(n) : n.kids.map(text).join("");
""" + "\n".join([page_function("fitGaps"), page_function("gapsLine"), page_const("normGap"), page_function("storyFor"),
                 page_function("openGaps"), page_const("storyHow"), page_function("storyChip"),
                 page_function("storyGapItems"), page_function("storyCovered"), page_function("storyMust"),
                 page_const("fitValue")]) + f"""
const fit = {json.dumps(fit)};
const [gaps, covered] = gapsLine(fit, true);
const must = storyMust(fit);
console.log(JSON.stringify({{ gaps: text(gaps), covered: text(covered), must: must.filter(Boolean).map(text),
  open: openGaps(fit), value: fitValue(fit), plain: fitValue({{ score: 68 }}), none: gapsLine({{ gaps: [] }}) }}));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["gaps"] == "GPU kernels · Influence across teams partly: A review guild"
    assert out["covered"] == "Covered by your stories: Tamed a queue"
    assert out["must"] == ["8/10 with stories", "68 · 74 with stories"]
    assert out["open"] == ["GPU kernels", "Influence across teams"] and out["value"] == 74 and out["plain"] == 68
    assert out["none"] is None
