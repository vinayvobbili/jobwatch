"""A job whose posting is closed ("closed": found closed on two looks) or being checked ("checking": found closed
once) is not fit-scored by anything automatic: nobody can apply to it and every score is a paid call. Pressing Score
on that one job (or `jobwatch score KEY --force`) still scores it, and a job found open again scores as any other.
The scorer here is a recorder: a test that expects no call asserts it was never asked."""

import json
import re
import shutil
import subprocess
import threading
from datetime import date
from importlib import resources

import pytest
import yaml

from jobwatch import autofill, cli, config, scorestats, sources, watch
from jobwatch.store import Store, closed_state
from jobwatch.web import App

from .test_page_js import page_const, page_function

FIT = {"score": 70, "must_haves_met": 2, "must_haves_total": 3, "gaps": [], "summary": "", "scored_by": "local:stub"}
INITECH, GLOBEX, ACME = "ashby:initech:c1", "lever:globex:aaaa-1111", "greenhouse:acme:101"
LI = "https://www.linkedin.com/jobs/view/4000000001/"
POSTING = "https://jobs.lever.co/globex/aaaa-1111"


@pytest.fixture
def env(watchlist, web):
    (watchlist.parent / "cv.md").write_text("Python, LLMs, RAG")
    raw = yaml.safe_load(watchlist.read_text())
    watchlist.write_text(yaml.safe_dump({**raw, "resume": "cv.md"}))
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    yield cfg, store
    store.close()


@pytest.fixture
def asked(monkeypatch):
    """Stand in for shortlist-ai: the job keys it was asked to score, in order."""
    keys = []

    def fake(jobs, resume, backend, cache_dir, workers=1, progress=None, prompts=None, model="", keychain="",
             batch=False, key_command="", provider=None):
        keys.extend(j.key for j in jobs)
        return {j.key: FIT for j in jobs}, {}

    monkeypatch.setattr(watch, "score_jobs", fake)
    return keys


def close(store, key, twice=True):
    """The posting found closed: once ('checking'), or on a second look too ('closed')."""
    store.set_closed(key, True)
    if twice:
        store.confirm_closed([key])
    return store.find(key)[1]


def entry(cfg, store, key):
    return watch.Entry(*store.find(key), 0.0, [])


# -- what a closed record says

def test_closed_and_checking_each_have_a_code_a_card_line_and_a_clause(env):
    _, store = env
    assert watch.closed_why(store.find(INITECH)[1]) is None
    store.db.execute("UPDATE jobs SET closed=? WHERE key=?", ("2026-11-28T12:00:00+00:00", INITECH))
    store.db.commit()
    checking = watch.closed_why(store.find(INITECH)[1])
    assert checking["code"] == "checking"
    assert checking["text"] == "Found closed once (Nov 28), being checked: not scored. Press Score to score it anyway."
    store.confirm_closed([INITECH])
    closed = watch.closed_why(store.find(INITECH)[1])
    assert closed == {"code": "closed", "text": "Closed Nov 28: not scored. Press Score to score it anyway.",
                      "said": "the posting is closed (Nov 28), so it was not scored"}


# -- every way of scoring leaves a closed job alone

@pytest.mark.parametrize("twice", [True, False], ids=["closed", "checking"])
def test_the_background_line_and_every_listing_leave_it_out(env, asked, twice):
    cfg, store = env
    assert INITECH in [e.job.key for e in watch.unscored(cfg, store)]
    close(store, INITECH, twice)
    assert INITECH not in [e.job.key for e in watch.unscored(cfg, store)]
    assert INITECH not in [e.job.key for e in watch.unscored(cfg, store, again={INITECH})]
    assert INITECH not in watch.unscored_reasons(cfg, store)  # not in line: its own reason below
    assert asked == []


@pytest.mark.parametrize("twice", [True, False], ids=["closed", "checking"])
def test_the_digest_scoring_and_rescore_leave_it_out(env, asked, twice):
    cfg, store = env
    rid = watch.resume_id(cfg.resume, cfg.prompts)
    store.save_score(INITECH, rid, {**FIT, "scored_by": "agy:other"})  # scored by another model: --rescore's job
    close(store, INITECH, twice)
    assert watch.rescore_line(cfg, store) == []
    digest = watch.build_digest(cfg, store, include_seen=True, score_top=10)
    assert INITECH not in asked and INITECH not in [e.job.key for e in digest.entries]


@pytest.mark.parametrize("twice", [True, False], ids=["closed", "checking"])
def test_score_entries_never_calls_the_scorer_for_it(env, asked, twice):
    """The one place every score goes through: a closed job handed to it anyway (lined up before it closed, say) is
    dropped, counted, and no error."""
    cfg, store = env
    stale = entry(cfg, store, INITECH)  # read while open: its record says so
    close(store, INITECH, twice)
    skipped = {}
    assert watch.score_entries(cfg, store, [stale], progress=lambda m: None, background=True, by="background",
                               skipped=skipped) == (0, {})
    assert asked == [] and skipped[INITECH]["code"] == ("closed" if twice else "checking")
    assert store.score(INITECH, watch.resume_id(cfg.resume, cfg.prompts)) is None
    assert store.scores_skipped() == {("closed" if twice else "checking"): 1}
    assert store.company_usage() == {}  # a skipped job counts toward no cap


def test_a_job_lined_up_open_and_closed_before_its_turn_is_dropped_at_dequeue(env, asked):
    cfg, store = env
    group = watch.unscored(cfg, store)[:2]
    assert group[0].job.key == INITECH
    close(store, INITECH)  # found closed after it was in line, before the scorer took it
    scored, errors = watch.score_entries(cfg, store, group, progress=lambda m: None, background=True)
    assert (scored, errors) == (1, {}) and asked == [group[1].job.key]


def test_the_page_scorer_drops_a_job_closed_while_it_waited(env, asked, monkeypatch):
    cfg, _ = env
    app = App(cfg.path, background=True)
    real = watch.unscored

    def line(*args, **kwargs):
        got = real(*args, **kwargs)
        other = Store(cfg.state)  # the scorer's thread has its own connection, and so does the closing
        close(other, INITECH)  # closes between the line being read and the scorer's turn
        other.close()
        return got
    monkeypatch.setattr("jobwatch.web.unscored", line)
    app.post_fetch({})
    app.scorer.wait(10)
    assert INITECH not in asked and {GLOBEX, ACME} <= set(asked)


def test_force_scores_one_closed_job_and_a_press_of_score_does_too(env, asked):
    cfg, store = env
    close(store, INITECH)
    assert watch.score_entries(cfg, store, [entry(cfg, store, INITECH)], progress=lambda m: None,
                               force=True) == (1, {})
    assert asked == [INITECH]
    close(store, GLOBEX, twice=False)
    got = App(cfg.path).post_score({"key": GLOBEX})  # the Score button
    assert got["score"] == 70 and asked == [INITECH, GLOBEX]
    assert store.scores_skipped() == {}  # a press is no skip


def test_a_rescore_from_the_dialog_is_the_persons_choice_too(env, asked):
    cfg, store = env
    close(store, INITECH)
    app = App(cfg.path)
    pick = app._with_store(lambda c, s: app._choices(c)[0])
    app.post_rescore({"key": INITECH, "backend": pick["backend"], "model": pick["model"]})
    join("jobwatch-rescore")
    assert asked == [INITECH]


def join(name):
    """Wait for the background thread with this name (a score asked for in the page) to finish."""
    for t in threading.enumerate():
        if t.name == name:
            t.join(10)


# -- a job found open again is scoreable again

def test_a_reopened_job_scores_again(env, asked):
    cfg, store = env
    close(store, INITECH)
    assert INITECH not in [e.job.key for e in watch.unscored(cfg, store)]
    assert store.set_closed(INITECH, False)
    assert closed_state(store.find(INITECH)[1]) is None and watch.closed_why(store.find(INITECH)[1]) is None
    line = watch.unscored(cfg, store)
    assert line[0].job.key == INITECH
    assert watch.score_entries(cfg, store, line[:1], progress=lambda m: None, background=True) == (1, {})
    assert asked == [INITECH]
    close(store, GLOBEX, twice=False)  # found closed once, then found open by the next look: no sticky mark
    store.set_closed(GLOBEX, False)
    assert GLOBEX in [e.job.key for e in watch.unscored(cfg, store)]


# -- the reason shown to the user

def test_a_closed_job_says_why_it_is_not_scored(env):
    cfg, store = env
    job, rec = store.find(INITECH)
    assert watch.unscored_reason(cfg, store, job, record=rec)["code"] == "queued"  # open: in line
    store.set_status([INITECH], "queued")
    for twice, code in ((False, "checking"), (True, "closed")):
        rec = close(store, INITECH, twice)
        why = watch.unscored_reason(cfg, store, job)
        assert why["code"] == code and why["text"].endswith("not scored. Press Score to score it anyway.")
        assert watch.unscored_reason(cfg, store, job, record=rec) == why
        assert next(j for j in App(cfg.path).get_queue({}) if j["key"] == INITECH)["unscored"]["code"] == code


# -- Read posting

def alert_job(store):
    return store.add("Globex", "Machine Learning Engineer", url=LI, status="queued",
                     note="From a LinkedIn job alert").key


def read(app, **more):
    return app.ext_posting({"linkedin": "4000000001", "company": "Globex", "title": "Machine Learning Engineer",
                            "text": "Train machine learning models for Globex. " * 8, **more})


def test_read_posting_on_a_closed_page_reads_it_and_does_not_score(env, asked):
    cfg, store = env
    key = alert_job(store)
    app = App(cfg.path)
    got = read(app, closed=True)
    assert got["closed"] and got["has_text"] and got["scoring"] is False
    assert got["not_scored"]["code"] == "closed"
    assert re.search(r"the posting is closed \([A-Z][a-z]{2} \d{1,2}\), so it was not scored$", got["said"])
    assert "scoring now" not in got["said"]
    assert store.find(key)[0].description  # the text was kept
    assert asked == [] and not app.rescoring
    assert watch.unscored_reason(cfg, store, store.find(key)[0])["code"] == "closed"
    assert store.scores_skipped() == {"closed": 1}  # the score this read would have asked for


def test_read_posting_on_a_job_already_marked_closed_does_not_score(env, asked):
    """The card says closed, Read posting is pressed and the page says nothing about it (an older extension): still
    closed, not scored."""
    cfg, store = env
    key = alert_job(store)
    close(store, key)
    got = read(App(cfg.path))
    assert got["not_scored"]["code"] == "closed" and got["scoring"] is False and asked == []
    assert store.scores_skipped() == {"closed": 1}


def test_read_posting_on_an_open_page_still_scores(env, asked):
    cfg, store = env
    key = alert_job(store)
    app = App(cfg.path)
    got = read(app, closed=False)
    assert "not_scored" not in got and got["scoring"] is True and "scoring now" in got["said"]
    join("jobwatch-score-posted")
    assert asked == [key]


def test_read_posting_on_a_reopened_page_scores(env, asked):
    cfg, store = env
    key = alert_job(store)
    close(store, key)
    got = read(App(cfg.path), linkedin=LI, closed=False)  # the job's own page, taking applications again
    assert got["reopened"] and "not_scored" not in got and got["scoring"] is True


def test_a_posting_that_answers_404_is_closed_and_not_scored(env, asked):
    """The company's own posting page answers not found (404 or 410): positive evidence the job is gone, a first look
    ('checking') that already keeps it from being scored."""
    cfg, store = env
    key = alert_job(store)

    def gone(url, *args, **kwargs):
        raise sources.NotFound(f"{url}: HTTP 410")
    got = autofill.posting(cfg, store, {"linkedin": "4000000001", "company": "Globex",
                                        "title": "Machine Learning Engineer", "page_url": POSTING,
                                        "text": "Train machine learning models for Globex. " * 8}, get=gone)
    assert got["not_scored"]["code"] == "checking" and "404 or 410" in got["said"]
    assert "so it looks closed" in store.find(key)[1]["note"]
    assert closed_state(store.find(key)[1]) == "checking"


def test_a_short_page_saying_it_is_closed_marks_the_job_for_a_check(env):
    cfg, store = env
    alert_job(store)
    filled = "Globex Machine Learning Engineer. This position has been filled. " * 4
    got = autofill.posting(cfg, store, {"linkedin": "4000000001", "company": "Globex",
                                        "title": "Machine Learning Engineer", "text": filled})
    assert got["not_scored"]["code"] == "checking" and "position has been filled" in got["said"]


def test_a_page_that_is_open_marks_nothing(env):
    cfg, store = env
    key = alert_job(store)
    got = autofill.posting(cfg, store, {"linkedin": "4000000001", "company": "Globex",
                                        "title": "Machine Learning Engineer",
                                        "text": "Train machine learning models for Globex. " * 8})
    assert "not_scored" not in got and closed_state(store.find(key)[1]) is None


# -- the saving shows

def test_the_saving_is_counted_once_a_job_a_day_and_shown(env, asked, capsys):
    cfg, store = env
    close(store, INITECH)
    close(store, GLOBEX, twice=False)
    for _ in range(3):  # asked again and again: one skip a job a day
        watch.score_entries(cfg, store, [entry(cfg, store, INITECH), entry(cfg, store, GLOBEX)],
                            progress=lambda m: None, background=True)
    today = date.today()
    s = scorestats.closed_skipped(store, average=0.05, today=today)
    assert s == {"today": 2, "week": 2, "month": 2, "total": 2, "closed": 1, "checking": 1, "saved_usd": 0.1}
    assert scorestats.summary(cfg, store)["closed_skipped"]["total"] == 2
    cli.main(["-c", str(cfg.path), "scores", "--closed"])
    out = capsys.readouterr().out
    assert "2 today" in out and "2 in all (1 found closed twice, 1 found closed once" in out


def test_scores_closed_says_so_when_nothing_was_spared(env, capsys):
    cfg, _ = env
    cli.main(["-c", str(cfg.path), "scores", "--closed"])
    assert "No score has been skipped for a closed posting yet" in capsys.readouterr().out


# -- jobwatch score KEY [--force]

def test_score_key_skips_a_closed_job_and_force_scores_it(env, asked, capsys):
    cfg, store = env
    close(store, INITECH)
    cli.main(["-c", str(cfg.path), "score", INITECH])
    out = capsys.readouterr().out
    assert "the posting is closed" in out and f"jobwatch score {INITECH} --force" in out and asked == []
    cli.main(["-c", str(cfg.path), "score", INITECH, "--force"])
    assert "70/100" in capsys.readouterr().out and asked == [INITECH]
    assert store.score(INITECH, watch.resume_id(cfg.resume, cfg.prompts))["score"] == 70


def test_score_key_scores_an_open_job_and_force_alone_is_refused(env, asked, capsys):
    cfg, _ = env
    cli.main(["-c", str(cfg.path), "score", GLOBEX])
    assert "70/100" in capsys.readouterr().out and asked == [GLOBEX]
    cli.main(["-c", str(cfg.path), "score", GLOBEX])
    assert "already scored 70/100" in capsys.readouterr().out and asked == [GLOBEX]
    with pytest.raises(SystemExit):
        cli.main(["-c", str(cfg.path), "score", "--force"])


# -- the page

def page_text():
    return resources.files("jobwatch").joinpath("static/index.html").read_text(encoding="utf-8")


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_toast_and_the_card_say_a_closed_posting_was_not_scored(tmp_path):
    js = tmp_path / "read.js"
    js.write_text(page_const("readToast") + page_function("afterRead") + """
const closed = { has_text: true, said: "Filled in; scoring now",
  not_scored: { code: "closed", text: "Closed Nov 28: not scored. Press Score to score it anyway.",
                said: "the posting is closed (Nov 28), so it was not scored" } };
const open = { has_text: true, said: "Filled in from Lever; scoring now" };
const a = { key: "a" }, b = { key: "b" }, c = { key: "c" };
afterRead(a, closed); afterRead(b, open); afterRead(c, { has_text: false });
console.log(JSON.stringify({ closed: readToast(closed), open: readToast(open), a: a.unscored, b: b.unscored,
  c: c.unscored }));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["closed"] == "Read it: the posting is closed (Nov 28), so it was not scored."
    assert out["a"] == {"code": "closed", "text": "Closed Nov 28: not scored. Press Score to score it anyway."}
    assert out["open"] == "Filled in from Lever; scoring now" and out["b"]["code"] == "scoring" and "c" not in out


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_a_closed_card_keeps_its_score_button_and_shows_the_reason(tmp_path):
    """Score on a closed job's card is the way to score it anyway: the reason codes are not in NO_SCORE_BUTTON, and
    the note under the button is the server's text."""
    js = tmp_path / "card.js"
    js.write_text(page_const("NO_SCORE_BUTTON") + page_const("SCORING_WORD") + page_const("scoringNow")
                  + page_const("ACT") + page_const("actLabel") + page_function("actButton")
                  + page_function("unscoredNote") + page_function("scoreButton") + """
const h = (tag, attrs, ...kids) =>
  ({ tag, attrs: attrs || {}, kids: kids.flat(Infinity).filter(k => k != null && k !== false) });
const icon = name => ({ svg: name });
const closedState = () => "closed", openDetails = () => {}, api = async () => ({}), toast = () => {};
const words = kids => kids.map(k => typeof k === "string" ? k : k.kids ? words(k.kids) : "").join("");
const job = { key: "k", url: "https://example.com/j",
  unscored: { code: "closed", text: "Closed Nov 28: not scored. Press Score to score it anyway." } };
const out = scoreButton(job, true);
console.log(JSON.stringify({ n: out.length, button: out[0].tag, cls: out[0].attrs.class, note: words(out[1].kids) }));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["button"] == "button" and "act-score" in out["cls"]
    assert out["note"] == "Closed Nov 28: not scored. Press Score to score it anyway."


def test_the_page_listens_for_a_skipped_score_and_settings_says_closed_jobs_are_not_scored():
    page = page_text()
    assert 'es.addEventListener("score-skipped"' in page and "Not scored: ${d.said}" in page
    assert "never scored on its own" in page and "closed_skipped" in page
    assert "function closedSavedNote" in page
    assert "function afterRead" in page and "toast(readToast(r))" in page
