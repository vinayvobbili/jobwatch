"""The suggestion on each job (advice.py): queue it or skip it, and why; and that the page gets it."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from jobwatch import cli, config
from jobwatch.advice import Advice, History, advise, verdict
from jobwatch.models import Job
from jobwatch.score import resume_id
from jobwatch.store import Store
from jobwatch.watch import Entry, save_job
from jobwatch.web import App

PAY = "pay: {target: 170000-240000, floor: 180000}\n"


def cfg_with(watchlist, text=PAY):
    watchlist.write_text(watchlist.read_text() + text)
    return config.load(watchlist)


def job(n=1, low=None, high=None, days=10, company="Globex"):
    return Job("lever", company.lower(), str(n), "Staff Engineer", f"https://example.com/{n}", company_name=company,
               salary_min=low, salary_max=high, posted=datetime.now(UTC) - timedelta(days=days))


def entry(j, fit=None, contacts=(), status="new"):
    return Entry(j, {"status": status}, 0, [], fit=fit, contacts=list(contacts))


def fit(score, met=3, total=4):
    return {"score": score, "must_haves_met": met, "must_haves_total": total}


def test_good_pay_a_strong_fit_and_someone_you_know_say_queue(watchlist):
    cfg = cfg_with(watchlist)
    store = Store(cfg.state)
    said = advise(cfg, entry(job(low=190000, high=260000, days=1), fit(82), [{"name": "Pat Lee"}]), History(store))
    assert said.action == "queue"
    assert said.reasons == ["the posted pay goes up to $260K, above your $170K–$240K target", "a strong fit (82/100)",
                            "you know Pat Lee there: ask for a referral first", "posted yesterday, so it's read early"]
    assert said.line.startswith("Queue: the posted pay goes up to $260K")
    store.close()


def test_nothing_standing_out_says_nothing(watchlist):
    unset = config.load(watchlist)  # no pay settings: pay says nothing
    cfg = cfg_with(watchlist)
    store = Store(cfg.state)
    assert advise(cfg, entry(job(days=1), fit(60)), History(store)) is None  # fresh alone isn't a reason
    assert advise(unset, entry(job(low=100000, high=150000)), History(store)) is None
    store.close()


def test_two_applications_there_this_week_say_skip_whatever_the_pay(watchlist):
    cfg = cfg_with(watchlist)
    store = Store(cfg.state)
    today = date.today()
    for n, ago in enumerate((1, 5, 20)):
        save_job(store, company="Globex", title=f"Engineer {n}", status="applied",
                 applied=(today - timedelta(days=ago)).isoformat())
    said = advise(cfg, entry(job(high=260000), fit(80)), History(store))
    assert said == Advice("skip", ["you've applied to 2 roles at Globex this past week"],
                          ["the posted pay goes up to $260K, above your $170K–$240K target", "a strong fit (80/100)"],
                          ["busy"])
    assert said.line.endswith("this past week (though the posted pay goes up to $260K, above your $170K–$240K target)")
    assert advise(cfg, entry(job(company="Initech", high=260000)), History(store)).action == "queue"
    store.close()


def test_a_company_that_turned_you_down_twice_says_apply_somewhere_new(watchlist):
    """One rejection is no reason to skip another role there; a second is: variety does more good."""
    cfg = cfg_with(watchlist)
    store = Store(cfg.state)
    long_ago = (date.today() - timedelta(days=60)).isoformat()
    save_job(store, company="Globex", title="Engineer 1", status="rejected", applied=long_ago)
    assert advise(cfg, entry(job(high=260000), fit(85)), History(store)).action == "queue"
    save_job(store, company="Globex", title="Engineer 2", status="rejected", applied=long_ago)
    said = advise(cfg, entry(job(high=260000), fit(85)), History(store))
    assert (said.action, said.codes) == ("skip", ["turned_down"])
    assert said.reasons == ["Globex has turned you down 2 times: this application does more good at a company "
                            "that hasn't said no"]
    e, history = entry(job(high=260000), fit(85)), History(store)
    assert verdict(e, history, advise(cfg, e, history))["text"].startswith("Skip it: Globex has turned you down")
    assert advise(cfg, entry(job(company="Initech", high=260000), fit(85)), History(store)).action == "queue"
    store.close()


def test_an_interview_there_now_outweighs_old_rejections(watchlist):
    """Turned down twice, but screening for a third role: not a no. Ask the recruiter about this one instead."""
    cfg = cfg_with(watchlist)
    store = Store(cfg.state)
    long_ago, lately = (date.today() - timedelta(days=60)).isoformat(), (date.today() - timedelta(days=5)).isoformat()
    for n in (1, 2):
        save_job(store, company="Globex", title=f"Engineer {n}", status="rejected", applied=long_ago)
    save_job(store, company="Globex", title="Engineer 3", status="screening", applied=lately)
    e, history = entry(job(high=260000), fit(85)), History(store)
    said = advise(cfg, e, history)
    assert "turned_down" not in said.codes
    assert verdict(e, history, said) == {
        "call": "hold", "text": "Hold off: another role at Globex is at screening now; ask your recruiter there "
                                "about this one instead of applying cold, or leave it, don't skip: this turns to "
                                "Queue once one of those is settled or goes quiet."}
    store.close()


def test_the_bottom_line_says_apply_stretch_hold_or_skip(watchlist):
    cfg = cfg_with(watchlist)
    store = Store(cfg.state)

    def call(e, history=None):
        history = history or History(store)
        return verdict(e, history, advise(cfg, e, history))

    paid = dict(low=190000, high=260000)
    # On Today the next step is to queue it; once it's queued, to apply.
    assert call(entry(job(**paid), fit(88, 4, 4))) == {
        "call": "apply", "text": "Queue it: the posted pay goes up to $260K, above your $170K–$240K target."}
    assert call(entry(job(**paid), fit(88, 4, 4), status="queued"))["text"].startswith("Apply: the posted pay")
    assert call(entry(job(**paid), fit(80, 1, 4))) == {  # most must-haves missing: advise says skip
        "call": "skip", "text": "Skip it: it meets 1 of 4 must-haves."}
    # Missing must-haves with a strong score: a caveat that agrees with the score, not "a stretch" against it.
    assert call(entry(job(**paid), fit(80, 5, 7))) == {
        "call": "stretch", "text": "Queue it: a strong score (80/100), but only 5 of 7 must-haves are met, so "
                                   "check the gaps first."}
    assert call(entry(job(**paid), fit(84, 7, 10), status="queued"))["text"] == \
        "Apply: a strong score (84/100), but only 7 of 10 must-haves are met, so check the gaps first."
    # A fair score with missing must-haves: the stretch wording doesn't contradict anything.
    assert call(entry(job(**paid), fit(68, 7, 10))) == {
        "call": "stretch", "text": "Queue it, but it's a stretch: it meets 7 of 10 must-haves."}
    assert call(entry(job(**paid), fit(68, 4, 4), status="queued"))["text"] == \
        "Apply, but it's a stretch: a fair fit (68/100)."
    assert call(entry(job(**paid), fit(55, 4, 4)))["text"] == "Skip it: not a close match (55/100)."
    assert call(entry(job(low=100000, high=150000), fit(90, 4, 4)))["text"] == \
        "Skip it: the posted pay tops out at $150K, under your floor."
    assert call(entry(job())) is None  # no score and nothing to go on
    # Two other roles queued or in progress at the company: hold off, however good this one looks. Not a skip: it
    # turns back once one of those is settled.
    save_job(store, company="Globex", title="Engineer 1", status="queued")
    settles = save_job(store, company="Globex", title="Engineer 2", status="screening")[0]
    assert call(entry(job(**paid), fit(90, 4, 4))) == {
        "call": "hold", "text": "Hold off: 2 other roles at Globex already queued or applied to; leave it, don't "
                                "skip: this turns to Queue once one of those is settled or goes quiet."}
    # Many never answer: one with no news for quiet.long days (45) is likely closed and no longer holds it.
    later = date.today() + timedelta(days=cfg.quiet.long)
    assert call(entry(job(**paid), fit(90, 4, 4)), History(store, later, cfg.quiet))["call"] == "apply"
    assert call(entry(job(**paid), fit(90, 4, 4)), History(store, later - timedelta(days=1), cfg.quiet))["call"] \
        == "hold"
    store.set_status([settles.key], "rejected")
    assert call(entry(job(**paid), fit(90, 4, 4)))["call"] == "apply"
    assert call(entry(job(company="Initech", **paid), fit(90, 4, 4)))["call"] == "apply"
    store.close()


def test_pay_alone_is_no_reason_to_queue_a_poor_fit(watchlist):
    """The posted pay (or Levels.fyi's ask) counts only with a fit score of 60 or more, or none yet."""
    cfg = cfg_with(watchlist)
    store = Store(cfg.state)
    history = History(store)
    rich = dict(low=300000, high=375000)
    assert advise(cfg, entry(job(**rich), fit(59, 0, 0)), history) is None
    assert advise(cfg, entry(job(**rich), fit(60, 0, 0)), history).codes == ["pay"]
    assert advise(cfg, entry(job(**rich)), history).codes == ["pay"]  # no score yet: nothing else to go on
    ask = {"base": 230000, "ask": 245000}
    assert advise(cfg, entry(job(), fit(45)), history, ask) is None
    assert advise(cfg, entry(job(), fit(65)), history, ask).codes == ["pay"]
    # The other reasons stand, without the pay: someone you know there, or a strong fit.
    said = advise(cfg, entry(job(**rich), fit(50), [{"name": "Pat Lee"}]), history)
    assert said.codes == ["contact"]
    assert advise(cfg, entry(job(**rich), fit(80)), history).codes == ["pay", "strong_fit"]
    # The bottom line agrees: a poor fit is a skip however much the job pays.
    e = entry(job(**rich), fit(59, 0, 0))
    assert verdict(e, history, advise(cfg, e, history)) == {
        "call": "skip", "text": "Skip it: not a close match (59/100)."}
    store.close()


@pytest.mark.parametrize("status", ["new", "queued"])
@pytest.mark.parametrize("score", [60, 68, 71, 74])
@pytest.mark.parametrize("met, total", [(0, 0), (10, 17), (4, 4)])
def test_a_fair_fit_never_gets_a_plain_queue_it_bottom_line(watchlist, score, met, total, status):
    """Whatever carries the advice (pay, a contact), a fit under 75 reads as a stretch, never a plain go-ahead."""
    cfg = cfg_with(watchlist)
    store = Store(cfg.state)
    history = History(store)
    for e in (entry(job(low=300000, high=375000), fit(score, met, total), status=status),
              entry(job(), fit(score, met, total), [{"name": "Pat Lee"}], status=status)):
        said = verdict(e, history, advise(cfg, e, history))
        assert said["call"] == "stretch" and "it's a stretch" in said["text"]
    store.close()


def test_a_rejection_there_is_no_reason_to_skip_another_role(watchlist):
    cfg = cfg_with(watchlist)
    store = Store(cfg.state)
    save_job(store, company="Globex", title="Platform Engineer", status="rejected")
    assert advise(cfg, entry(job(high=260000)), History(store)).action == "queue"
    store.close()


def test_pay_under_the_floor_and_missing_must_haves_say_skip(watchlist):
    cfg = cfg_with(watchlist)
    store = Store(cfg.state)
    assert advise(cfg, entry(job(low=140000, high=170000)), History(store)).reasons == [
        "the posted pay tops out at $170K, under your floor"]
    low = {"base": 160000, "ask": 170000}
    assert advise(cfg, entry(job()), History(store), low).reasons == [
        "Levels.fyi's median base for this level is $160K, under your floor"]
    assert advise(cfg, entry(job()), History(store), {"base": 230000, "ask": 245000}).reasons == [
        "Levels.fyi suggests asking ~$245K base, above your $170K–$240K target"]
    assert advise(cfg, entry(job(low=180000, high=230000)), History(store)).reasons == [
        "the posted pay goes up to $230K, within your $170K–$240K target"]
    assert advise(cfg, entry(job()), History(store), {"pending": True}) is None
    assert advise(cfg, entry(job(), fit(70, met=1, total=4)), History(store)).reasons == [
        "it meets 1 of 4 must-haves"]
    store.close()


def test_the_same_opening_already_applied_to_says_skip(watchlist):
    cfg = cfg_with(watchlist)
    store = Store(cfg.state)

    class Same:  # a dupes.Match by a req id, to an application
        strong, applied, day = True, True, "2026-01-05"
    e = entry(job())
    e.duplicate = Same()
    assert advise(cfg, e, History(store)).reasons == ["you already applied to this opening on 2026-01-05"]
    e.duplicate.strong = False  # the same title only: maybe another opening
    assert advise(cfg, e, History(store)) is None
    store.close()


def test_today_and_the_queue_carry_the_advice(watchlist, web):
    cfg = cfg_with(watchlist, "pay: {target: 100000, floor: 90000}\n")
    app = App(watchlist)
    app.post_fetch({})
    jobs = app.get_digest({})["jobs"]
    assert jobs and all("advice" in j and "verdict" in j for j in jobs)
    paid = [j for j in jobs if j["salary_max"]]
    assert paid and all(j["advice"]["action"] == "queue" for j in paid)
    store = Store(cfg.state)
    store.set_status([jobs[0]["key"]], "queued")
    store.close()
    assert [("advice" in j) for j in app.get_queue({})] == [True]


def test_the_cli_counts_the_advice_by_rule(watchlist, web, capsys):
    cfg_with(watchlist, "pay: {target: 100000, floor: 90000}\n")
    cli.main(["-c", str(watchlist), "fetch"])
    capsys.readouterr()
    cli.main(["-c", str(watchlist), "advice"])
    out = capsys.readouterr().out
    assert out.startswith("3 jobs: queue 3, skip 0, no suggestion 0\n") and "  3  pay: the posted pay" in out
    cli.main(["-c", str(watchlist), "advice", "--format", "json"])
    s = json.loads(capsys.readouterr().out)
    assert s["jobs"] == sum(s["by_action"].values()) == 3 and s["by_reason"]["pay"] == s["by_action"]["queue"]


HUBS = ["Austin, Texas", "Chicago, Illinois", "Portland, Oregon", "Atlanta, Georgia"]  # none is Denver
OFFICE = "Logistics: on-site visits to clients and our office in Austin (Downtown) 2/week."
BIG_PAY = "pay: {target: 225000-250000, floor: 180000}\n"


def abroad(locations=HUBS, remote=True, description=OFFICE, company="Globex"):
    """A job on the board's remote flag over places that aren't Denver, with pay at the top of the target."""
    j = job(low=180000, high=250000, company=company)
    j.locations, j.remote, j.description = list(locations), remote, description
    return j


def test_a_job_on_site_only_outside_your_places_never_says_queue_whatever_the_pay(watchlist):
    """The board's remote flag over a list of other cities passed the place filter, and good pay made the advice
    green: "Queue it" for a job with nothing in Denver."""
    cfg = cfg_with(watchlist, BIG_PAY)
    store = Store(cfg.state)
    history = History(store)
    for fit_ in (fit(85), None):  # scored well, or not scored yet
        e = entry(abroad(), fit_)
        said = advise(cfg, e, history)
        assert (said.action, said.codes) == ("skip", ["place"])
        assert said.reasons == ["on-site in Austin, Texas; Chicago, Illinois; Portland, Oregon and 1 more, "
                                "not Denver or remote"]
        assert said.line.endswith("(though the posted pay goes up to $250K, within your $225K–$250K target)")
        call = verdict(e, history, said)  # still the person's call (they may pick an office elsewhere), never green
        assert call["call"] == "stretch" and "not Denver or remote" in call["text"]
    poor = entry(abroad(), fit(40))
    assert verdict(poor, history, advise(cfg, poor, history)) == {
        "call": "skip", "text": "Skip it: not a close match (40/100)."}
    store.close()


@pytest.mark.parametrize("job_", [
    abroad(locations=["Denver, Colorado", "Austin, Texas"]),                   # one of the places is theirs
    abroad(locations=["Remote - US"], remote=None),                            # remote in words: place rules own it
    abroad(locations=["Austin, Texas"], description="Python services."),      # the flag over one office
    abroad(description="In-office 3 days a week unless designated remote."),  # remote by arrangement
])
def test_jobs_in_your_places_or_remote_get_no_place_reason(watchlist, job_):
    cfg = cfg_with(watchlist, BIG_PAY)
    store = Store(cfg.state)
    assert advise(cfg, entry(job_, fit(85)), History(store)).action == "queue"
    store.close()


def test_a_job_with_no_remote_flag_in_one_other_city_is_on_site_there(watchlist):
    cfg = cfg_with(watchlist, BIG_PAY)
    store = Store(cfg.state)
    said = advise(cfg, entry(abroad(["Austin, Texas"], remote=None, description="Python."), fit(85)), History(store))
    assert said.codes == ["place"] and said.reasons == ["on-site in Austin, Texas, not Denver or remote"]
    store.close()


def test_a_score_that_comes_in_changes_the_cards_advice_and_bottom_line(watchlist, web):
    """A card drawn before its job was scored said "Queue it: the posted pay ..."; the score (40, from Read posting
    or Score) then swapped the rings but left that line, so the card read Weak fit over a green Queue. The page asks
    /api/advice for the card's lines again when a score comes in."""
    (watchlist.parent / "cv.md").write_text("Python, LLMs, RAG")
    cfg_with(watchlist, "pay: {target: 100000, floor: 90000}\nresume: cv.md\n")
    app = App(watchlist)
    app.post_fetch({})
    paid = next(j for j in app.get_digest({})["jobs"] if j["salary_max"])
    key = paid["key"]
    assert paid["advice"]["action"] == "queue" and paid["verdict"]["call"] == "apply"  # unscored: pay is all there is
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    store.save_score(key, resume_id(cfg.resume, cfg.prompts), fit(40, 7, 10) | {"gaps": [], "summary": ""})
    store.close()
    now = app.post_advice({"keys": [key, "no:such:key"]})["advice"]
    assert list(now) == [key]
    assert now[key]["advice"] is None  # pay alone is no reason under a fit of 60
    assert now[key]["verdict"] == {"call": "skip", "text": "Skip it: not a close match (40/100)."}
    store = Store(cfg.state)
    store.set_status([key], "applied")
    store.close()
    assert app.post_advice({"keys": [key]})["advice"][key] == {"advice": None, "verdict": None}  # past advice


def test_the_cli_explains_one_jobs_card(watchlist, capsys):
    cfg = cfg_with(watchlist, BIG_PAY)
    store = Store(cfg.state)
    j = abroad()
    store.sync(j.source, j.company, [j])
    key = j.key
    store.close()
    cli.main(["-c", str(watchlist), "advice", key])
    out = capsys.readouterr().out
    assert "fit:     not scored" in out and "advice:  Skip: on-site in Austin, Texas; Chicago, Illinois;" in out
    assert "verdict: Queue it, but it's a stretch: on-site in" in out
    cli.main(["-c", str(watchlist), "advice", key, "--format", "json"])
    row = json.loads(capsys.readouterr().out)[0]
    assert row["key"] == key and row["fit"] is None and row["places"][0] == "Austin, Texas (Remote)"
    with pytest.raises(SystemExit):
        cli.main(["-c", str(watchlist), "advice", "nope"])


def test_a_nearby_office_job_on_site_elsewhere_says_why_it_shows_and_to_ask_first(watchlist):
    """A job at a company with an office near you passes the place rules wherever it's posted. When it's on-site
    somewhere else it isn't a plain green Queue: one line says why it shows, and the bottom line says to ask first."""
    cfg = cfg_with(watchlist, BIG_PAY)
    cfg.filters.nearby_offices = ["Initech"]
    store = Store(cfg.state)
    history = History(store)
    hybrid = abroad(["Austin, Texas"], remote=None, description="Hybrid, 3 days a week.", company="Initech")
    e = entry(hybrid, fit(85))
    said = advise(cfg, e, history)
    assert (said.action, said.codes) == ("ask", ["place_office"])
    assert said.reasons == ["Initech has an office near Denver; role is on-site Austin, Texas: ask if the Denver "
                            "office is an option"]
    assert said.line.startswith("Ask first: Initech has an office near Denver;")
    assert verdict(e, history, said) == {
        "call": "stretch", "text": "Queue it, ask first: Initech has an office near Denver; role is on-site Austin, "
                                   "Texas: ask if the Denver office is an option."}
    poor = entry(hybrid, fit(40))  # a poor match is skipped for that, as before
    assert verdict(poor, history, advise(cfg, poor, history))["text"] == "Skip it: not a close match (40/100)."
    # in one of your places, or at a company without a nearby office elsewhere: nothing to ask
    here = abroad(["Denver, Colorado"], remote=None, description="Python.", company="Initech")
    assert advise(cfg, entry(here, fit(85)), history).action == "queue"
    other = abroad(["Austin, Texas"], remote=None, description="Python.", company="Umbrella")
    assert advise(cfg, entry(other, fit(85)), history).codes == ["place"]
    store.close()
