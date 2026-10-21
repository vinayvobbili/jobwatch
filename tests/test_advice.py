"""The suggestion on each job (advice.py): queue it or skip it, and why; and that the page gets it."""

import json
from datetime import date, datetime, timedelta, timezone

from jobwatch import cli, config
from jobwatch.advice import Advice, History, advise
from jobwatch.models import Job
from jobwatch.store import Store
from jobwatch.watch import Entry, save_job
from jobwatch.web import App

PAY = "pay: {target: 200000-240000, floor: 180000}\n"


def cfg_with(watchlist, text=PAY):
    watchlist.write_text(watchlist.read_text() + text)
    return config.load(watchlist)


def job(n=1, low=None, high=None, days=10, company="Globex"):
    return Job("lever", company.lower(), str(n), "Staff Engineer", f"https://example.com/{n}", company_name=company,
               salary_min=low, salary_max=high, posted=datetime.now(timezone.utc) - timedelta(days=days))


def entry(j, fit=None, contacts=(), status="new"):
    return Entry(j, {"status": status}, 0, [], fit=fit, contacts=list(contacts))


def fit(score, met=3, total=4):
    return {"score": score, "must_haves_met": met, "must_haves_total": total}


def test_good_pay_a_strong_fit_and_someone_you_know_say_queue(watchlist):
    cfg = cfg_with(watchlist)
    store = Store(cfg.state)
    said = advise(cfg, entry(job(low=190000, high=260000, days=1), fit(82), [{"name": "Pat Lee"}]), History(store))
    assert said.action == "queue"
    assert said.reasons == ["the posted pay goes up to $260K, above your $200K–$240K target", "a strong fit (82/100)",
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
                          ["the posted pay goes up to $260K, above your $200K–$240K target", "a strong fit (80/100)"],
                          ["busy"])
    assert said.line.endswith("this past week (though the posted pay goes up to $260K, above your $200K–$240K target)")
    assert advise(cfg, entry(job(company="Initech", high=260000)), History(store)).action == "queue"
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
        "Levels.fyi suggests asking ~$245K base, above your $200K–$240K target"]
    assert advise(cfg, entry(job(low=180000, high=230000)), History(store)).reasons == [
        "the posted pay goes up to $230K, within your $200K–$240K target"]
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
    assert jobs and all("advice" in j for j in jobs)
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
