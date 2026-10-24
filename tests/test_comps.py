"""The Comps tab: open applications side by side with what recruiters said about pay; `jobwatch comp` and `comps`, the
set_comp and get_comps tools, and the page's API. No network: the jobs are made-up and added by hand."""

import asyncio
import json
from datetime import date

import pytest

from jobwatch import cli, comps, config
from jobwatch.score import resume_id
from jobwatch.store import Store
from jobwatch.web import ApiError, App


@pytest.fixture
def tracked(watchlist, tmp_path):
    """Three open applications (Acme interviewing, Globex screening, Initech at an offer), one only applied
    (Hooli), one rejected (Umbrella); Acme and Globex post a pay range, Acme and Initech have a fit score."""
    resume = tmp_path / "cv.md"
    resume.write_text("# Jane Doe")
    watchlist.write_text(watchlist.read_text() + f"resume: {resume}\n")
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    for company, title, status in [("Acme", "Platform Engineer", "interviewing"), ("Globex", "Data Lead", "screening"),
                                   ("Initech", "ML Engineer", "offer"), ("Hooli", "SRE", "applied"),
                                   ("Umbrella", "Architect", "rejected")]:
        store.add(company, title, status=status, applied="2026-10-01", location="Remote")
    for key, low, high in [("manual:acme:platform-engineer", 180000, 220000),
                           ("manual:globex:data-lead", 150000, 200000)]:
        job, _ = store.find(key)
        job.salary_min, job.salary_max = low, high
        store.update(job)
    rid = resume_id(cfg.resume, cfg.prompts)
    store.save_score("manual:acme:platform-engineer", rid, {"score": 84, "must_haves_met": 5, "must_haves_total": 6,
                                                            "gaps": ["Rust", "Kafka", "Go", "Terraform"]})
    store.save_score("manual:initech:ml-engineer", rid, {"score": 61, "must_haves_met": 3, "must_haves_total": 6})
    store.close()
    return watchlist


def test_amounts_are_read_as_dollars():
    assert comps.amount("170-200K") == (170000, 200000)
    assert comps.amount("$170K - $215K") == (170000, 215000)
    assert comps.amount("$150,000 to $180,000") == (150000, 180000)
    assert comps.amount("200K most likely their max") == (200000, 200000)
    assert comps.amount("2 offers, 200K") == (200000, 200000)
    assert comps.amount("1.2M") == (1_200_000, 1_200_000)


def test_what_isnt_pay_is_not_read():
    assert [comps.amount(t) for t in ("10% target", "3-4 rounds", "5", "", None)] == [None] * 5


def test_store_sets_keeps_the_rest_clears_and_forgets(tmp_path):
    store = Store(tmp_path / "s.db")
    job = store.add("Acme", "Engineer", status="screening")
    assert store.comp(job.key) is None
    store.set_comp("acme", base=" 170-200K ", bonus="10%")
    store.set_comp(job.key, note="200K likely their max")  # the rest stays
    kept = store.comp(job.key)
    assert (kept["base"], kept["bonus"], kept["note"], kept["equity"]) == ("170-200K", "10%", "200K likely their max",
                                                                         None)
    store.set_comp(job.key, bonus="")  # cleared
    assert store.comp(job.key)["bonus"] is None and list(store.comps()) == [job.key]
    store.set_comp(job.key, base="", note="")  # nothing left: forgotten
    assert store.comp(job.key) is None and store.comps() == {}
    with pytest.raises(ValueError, match="unknown compensation field"):
        store.set_comp(job.key, salary="1")
    with pytest.raises(KeyError, match="no job matches"):
        store.set_comp("nobody", base="1")
    store.close()


def test_view_lists_live_stages_furthest_along_first(tracked):
    cfg = config.load(tracked)
    store = Store(cfg.state)
    store.set_comp("manual:acme:platform-engineer", base="170-200K", asked="215-250K", note="max is 200K")
    store.set_comp("manual:globex:data-lead", base="150-190K", offered="180K")
    v = comps.view(cfg, store)
    assert v["today"] == date.today().isoformat()  # what the page counts "3 days ago" from
    assert [o["company"] for o in v["opportunities"]] == ["Initech", "Acme", "Globex"]
    acme = v["opportunities"][1]
    assert acme["pay"] == "$180K–$220K" and acme["places"] == ["Remote"] and acme["base_max"] == 200000
    assert acme["comp"]["asked"] == "215-250K" and acme["asked_max"] == 250000 and acme["offered_max"] is None
    assert acme["fit"] == {"score": 84, "met": 5, "total": 6, "gaps": ["Rust", "Kafka", "Go"], "stale": False}
    assert v["opportunities"][0]["fit"]["met"] == 3 and v["opportunities"][2]["fit"] is None
    assert v["best"] == {"pay": ["manual:acme:platform-engineer"], "base": ["manual:acme:platform-engineer"],
                         "offered": [], "fit": ["manual:acme:platform-engineer"]}  # one offer isn't a comparison
    store.close()


def test_applied_on_request_and_named_jobs(tracked):
    cfg = config.load(tracked)
    store = Store(cfg.state)
    more = comps.view(cfg, store, (*comps.LIVE, "applied"))
    assert [o["company"] for o in more["opportunities"]] == ["Initech", "Acme", "Globex", "Hooli"]
    named = comps.view(cfg, store, keys=["hooli", "umbrella"])  # whatever the stage
    assert [o["status"] for o in named["opportunities"]] == ["applied", "rejected"]
    with pytest.raises(ValueError, match="can only compare open application stages"):
        comps.view(cfg, store, ("rejected",))
    store.close()


def test_a_tie_marks_neither_and_no_pay_marks_nothing(tracked):
    cfg = config.load(tracked)
    store = Store(cfg.state)
    store.set_comp("acme", offered="200K")
    store.set_comp("globex", offered="$200,000")
    store.set_comp("initech", offered="150K")
    assert sorted(comps.view(cfg, store)["best"]["offered"]) == ["manual:acme:platform-engineer",
                                                                 "manual:globex:data-lead"]
    store.set_comp("initech", offered="200K")
    assert comps.view(cfg, store)["best"]["offered"] == []  # all the same: nothing stands out
    store.close()


def test_text_marks_the_highest_in_a_row(tracked):
    cfg = config.load(tracked)
    store = Store(cfg.state)
    store.set_comp("acme", base="170-200K", note="max is 200K")
    store.set_comp("globex", base="150-190K")
    out = comps.text(comps.view(cfg, store))
    assert "Acme: Platform Engineer [interviewing]" in out and "  base: 170-200K *" in out
    assert "  base: 150-190K\n" in out and "  posted pay: $180K–$220K *" in out and "  note: max is 200K" in out
    assert "gaps: Rust; Kafka; Go" in out and out.endswith("* highest in its row")
    assert comps.text({"stages": ["offer"], "opportunities": [], "best": {}}).startswith("Nothing to compare")
    store.close()


def test_cli_sets_clears_and_compares(tracked, capsys):
    c = ["-c", str(tracked)]
    cli.main([*c, "comp", "acme", "--base", "170-200K", "--bonus", "10%", "--asked", "215-250K"])
    assert capsys.readouterr().out == "manual:acme:platform-engineer: base 170-200K; bonus 10%; asked 215-250K\n"
    cli.main([*c, "comp", "acme", "--bonus", "", "--note", "max is 200K"])
    assert "base 170-200K; asked 215-250K; note max is 200K" in capsys.readouterr().out
    cli.main([*c, "comps"])
    out = capsys.readouterr().out
    blocks = [out.index(head) for head in ("\nInitech: ML Engineer [", "\nAcme: Platform Engineer [",
                                           "\nGlobex: Data Lead [")]
    assert blocks == sorted(blocks) and "Hooli" not in out and out.startswith("Suggestion (pay vs the best of these")
    cli.main([*c, "comps", "--applied"])
    assert "Hooli: SRE [applied]" in capsys.readouterr().out
    cli.main([*c, "comps", "--format", "json", "hooli"])
    assert [o["company"] for o in json.loads(capsys.readouterr().out)["opportunities"]] == ["Hooli"]
    cli.main([*c, "comp", "acme", "--clear"])
    assert "no compensation kept" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="no job matches"):
        cli.main([*c, "comp", "nobody", "--base", "1"])


def test_the_page_api_reads_and_saves(tracked):
    app = App(tracked)
    assert app.post_comp({"key": "globex", "base": "150-190K", "note": "  "}) == {"key": "manual:globex:data-lead"}
    d = app.get_comps({})
    assert d["stages"] == ["screening", "interviewing", "offer"]
    assert {o["company"]: o["comp"]["base"] for o in d["opportunities"]}["Globex"] == "150-190K"
    assert len(app.get_comps({"stages": ["applied,offer"]})["opportunities"]) == 2
    with pytest.raises(ApiError, match="can only compare"):
        app.get_comps({"stages": ["rejected"]})
    with pytest.raises(KeyError):
        app.post_comp({"key": "nobody", "base": "1"})


def test_the_page_has_a_comps_tab(server):
    from .conftest import TOKEN, request
    page = request(server, "GET", f"/?token={TOKEN}")[1].decode()
    assert 'data-tab="comps"' in page and "renderComps" in page and "comparePicker" in page


def test_set_and_get_comps_tools(tracked, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    ToolError = pytest.importorskip("mcp.server.mcpserver.exceptions").ToolError
    monkeypatch.setenv("JOBWATCH_CONFIG", str(tracked))
    got = mcp.set_comp("globex", base="150-190K", note="flexible")
    assert got["company"] == "Globex" and got["comp"]["base"] == "150-190K"
    mcp.set_comp("globex", note="")
    v = mcp.get_comps()
    assert [o["company"] for o in v["opportunities"]] == ["Initech", "Acme", "Globex"]
    assert v["opportunities"][2]["comp"] == {"base": "150-190K", "bonus": None, "equity": None, "signon": None,
                                             "asked": None, "offered": None, "note": None, "role": None,
                                             "career_note": None}
    assert len(mcp.get_comps(stages=["applied"])["opportunities"]) == 1
    assert [o["company"] for o in mcp.get_comps(keys=["umbrella"])["opportunities"]] == ["Umbrella"]
    with pytest.raises(ToolError, match="no job matches"):
        mcp.set_comp("nobody", base="1")
    with pytest.raises(ToolError, match="no job matches"):
        mcp.get_comps(keys=["nobody"])
    assert {"get_comps", "set_comp"} <= {t.name for t in asyncio.run(mcp.server.list_tools())}


# -- company health, the company-only columns and the suggestion

def test_health_is_kept_per_company_whatever_its_spelling(tmp_path):
    store = Store(tmp_path / "s.db")
    assert store.health("Acme") is None
    store.set_health("Acme, Inc.", listing="Private", stage="Series B, $50M, 2025", layoffs="none")
    kept = store.health("acme")
    assert (kept["name"], kept["listing"], kept["layoffs"], kept["as_of"]) == ("Acme, Inc.", "private", "none",
                                                                               date.today().isoformat())
    store.set_health("ACME", rating="4.1", as_of="2026-01-05")  # the rest stays; the day as given
    kept = store.health("Acme")
    assert (kept["stage"], kept["rating"], kept["as_of"]) == ("Series B, $50M, 2025", "4.1", "2026-01-05")
    store.set_health("acme", layoffs="")  # one cleared
    assert store.health("acme")["layoffs"] is None and list(store.healths()) == ["acme"]
    for field in ("listing", "stage", "rating"):
        store.set_health("acme", **{field: ""})
    assert store.health("acme") is None  # only the day was left: forgotten
    with pytest.raises(ValueError, match="listing must be"):
        store.set_health("acme", listing="startup")
    with pytest.raises(ValueError, match="unknown company health field"):
        store.set_health("acme", mood="good")
    with pytest.raises(ValueError, match="needs a company name"):
        store.set_health("  ", risk="x")
    store.close()


def test_health_older_than_ninety_days_is_stale():
    fresh = {"as_of": "2026-10-20"}
    assert comps.aged(fresh, date(2026, 10, 24)) == {**fresh, "age_days": 4, "stale": False}
    assert comps.aged(fresh, date(2027, 1, 18))["stale"] is False  # 90 days exactly isn't over
    assert comps.aged(fresh, date(2027, 1, 25)) == {**fresh, "age_days": 97, "stale": True}
    assert comps.aged({"as_of": None}, date(2026, 10, 24))["stale"] is True  # no day: can't be trusted
    assert comps.aged(None) is None


def test_a_company_with_no_job_is_a_column_of_its_own(tracked):
    cfg = config.load(tracked)
    store = Store(cfg.state)
    store.set_health("Hooli", listing="public", rating="3.9", as_of="2020-01-01")
    store.set_health("Wayne Enterprises", listing="private", stage="Series A")  # no job here at all
    v = comps.view(cfg, store, keys=["acme"], companies=["Wayne Enterprises, Inc.", "Hooli"])
    assert [(o["kind"], o["company"]) for o in v["opportunities"]] == [
        ("job", "Acme"), ("company", "Wayne Enterprises"), ("company", "Hooli")]
    wayne, hooli = v["opportunities"][1:]
    assert wayne["health"]["stage"] == "Series A" and wayne["health"]["stale"] is False and wayne["status"] == ""
    assert hooli["health"]["stale"] is True and hooli["health"]["listing"] == "public"
    assert [r["company"] for r in v["suggestion"]["ranking"]] == ["Acme"]  # only jobs are ranked
    ids = {c["id"]: c for c in v["choices"]}
    assert ids["manual:acme:platform-engineer"]["kind"] == "job" and "manual:umbrella:architect" not in ids
    assert ids["Wayne Enterprises"]["label"] == "Wayne Enterprises (company only)"  # not listed twice if it has a job
    assert "Hooli" not in ids  # it has a job (applied), so the job is the choice
    assert "Wayne Enterprises [company only]" in comps.text(v) and "company: private / Series A" in comps.text(v)
    store.close()


def test_the_suggestion_weighs_pay_fit_progress_and_health(tracked):
    tracked.write_text(tracked.read_text() + "pay:\n  target: 180000-210000\n")
    cfg = config.load(tracked)
    store = Store(cfg.state)
    store.set_comp("initech", offered="200K")
    store.set_health("Initech", listing="public", rating="4.2")
    store.set_health("Globex", layoffs="15% in March", headcount="shrinking", listing="private", raised="$12M")
    s = comps.view(cfg, store)["suggestion"]
    assert s["target"] == "$180K-$210K" and s["weights"] == comps.WEIGHTS
    assert sum(s["weights"].values()) == pytest.approx(1)
    assert [r["company"] for r in s["ranking"]] == ["Initech", "Acme", "Globex"]
    initech, acme, globex = s["ranking"]
    assert initech["parts"]["pay"]["input"] == "$200K offered vs your $180K-$210K target"
    assert initech["parts"]["progress"] == {"score": 100, "input": "offer", "known": True}
    assert initech["total"] == round(sum(comps.WEIGHTS[k] * p["score"] for k, p in initech["parts"].items()))
    # nothing known: neutral, and marked so it shows as "?", not a middling 50
    assert acme["parts"]["health"] == {"score": 50, "input": "no company health kept", "known": False}
    assert "health ? (no company health kept, counts as 50)" in comps.suggestion_text(s)
    assert "health 20 (recent layoffs" in comps.suggestion_text(s)
    assert acme["parts"]["fit"]["score"] == 84 and "fit is 84/100" not in initech["reason"]
    # layoffs -25, shrinking -10, thin funding -15 from 70
    assert globex["parts"]["health"] == {"score": 20, "input": "recent layoffs, shrinking headcount, "
                                                                "thin funding ($12.0M raised)", "known": True}
    # pay is the middle of the range posted ($150K-$200K): a band's top isn't what anyone is paid
    assert globex["reason"] == ("Posted pay $175K is 10% under your $180K-$210K target, but its health counts against "
                                "it: recent layoffs, shrinking headcount, thin funding ($12.0M raised).")
    assert comps.suggestion_text(s).startswith("Suggestion (pay vs your $180K-$210K target; weights: career 25%, "
                                               "pay 30%, fit 20%, progress 10%, health 15%)")
    store.close()


def test_pay_is_measured_against_the_best_of_them_without_a_target(tracked):
    cfg = config.load(tracked)
    store = Store(cfg.state)
    s = comps.view(cfg, store)["suggestion"]
    assert s["target"] is None
    pay = {r["company"]: r["parts"]["pay"] for r in s["ranking"]}
    # the middle of $180K-$220K
    assert pay["Acme"] == {"score": 80, "input": "$200K posted vs the best of these", "known": True}
    assert pay["Initech"] == {"score": 50, "input": "no pay known", "known": False}  # nothing to go on: neutral
    store.close()


@pytest.mark.parametrize("headcount, reads", [("66-128 (sources disagree), likely growing", "growing headcount"),
                                              ("1,400-1,480", None), ("down 10%", "shrinking headcount"),
                                              ("-5% this year", "shrinking headcount"), ("+20%", "growing headcount")])
def test_a_range_of_heads_is_no_fall(tracked, headcount, reads):
    cfg = config.load(tracked)
    store = Store(cfg.state)
    store.set_health("Acme", headcount=headcount)
    acme = next(r for r in comps.view(cfg, store)["suggestion"]["ranking"] if r["company"] == "Acme")
    seen = acme["parts"]["health"]["input"]
    assert (reads in seen) if reads else ("headcount" not in seen)
    store.close()


def test_cli_keeps_health_and_compares_a_company_alone(tracked, capsys):
    c = ["-c", str(tracked)]
    cli.main([*c, "health", "Wayne Enterprises", "--listing", "private", "--stage", "Series A, $9M, 2026",
              "--rating", "3.2", "--sources", "https://example.com/wayne"])
    out = capsys.readouterr().out
    assert out.startswith("Wayne Enterprises: company private / Series A, $9M, 2026; rating 3.2; sources "
                          "https://example.com/wayne; health as of ")
    cli.main([*c, "health", "acme", "--risk", "one big customer", "--as-of", "2026-01-01"])  # a job's company
    assert "health as of 2026-01-01 (stale, " in capsys.readouterr().out
    cli.main([*c, "comps", "--company", "wayne enterprises"])
    out = capsys.readouterr().out
    assert "Wayne Enterprises [company only]" in out and "Suggestion" not in out
    cli.main([*c, "health", "Wayne Enterprises", "--clear"])
    assert "no company health kept" in capsys.readouterr().out


def test_the_page_api_keeps_health_and_compares_a_pick(tracked):
    app = App(tracked)
    assert app.post_health({"company": "globex", "layoffs": "none", "listing": "public"}) == {"company": "Globex"}
    with pytest.raises(ApiError, match="listing must be"):
        app.post_health({"company": "Globex", "listing": "maybe"})
    d = app.get_comps({"key": ["initech"], "company": ["Globex", "Newco"]})
    assert [o["company"] for o in d["opportunities"]] == ["Initech", "Globex", "Newco"]
    assert d["opportunities"][1]["health"]["layoffs"] == "none" and d["opportunities"][2]["health"] is None
    with pytest.raises(ApiError, match="no job matches"):
        app.get_comps({"key": ["nobody"]})


def test_set_company_health_tool(tracked, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    ToolError = pytest.importorskip("mcp.server.mcpserver.exceptions").ToolError
    monkeypatch.setenv("JOBWATCH_CONFIG", str(tracked))
    got = mcp.set_company_health("globex", listing="private", stage="Series C", layoffs="none",
                                 sources="https://example.com/globex", as_of="2026-10-01")
    assert got["company"] == "Globex" and got["health"]["stage"] == "Series C" and got["health"]["stale"] is False
    v = mcp.get_comps(companies=["Globex", "Newco"])
    assert [o["company"] for o in v["opportunities"]] == ["Globex", "Newco"]
    assert v["opportunities"][0]["health"]["sources"] == "https://example.com/globex"
    with pytest.raises(ToolError, match="listing must be"):
        mcp.set_company_health("globex", listing="startup")
    assert "set_company_health" in {t.name for t in asyncio.run(mcp.server.list_tools())}


def test_career_follows_the_kind_of_company_and_the_role(tracked):
    cfg = config.load(tracked)
    store = Store(cfg.state)
    store.set_health("Acme", kind="Tech")  # a kind alone is no health: it doesn't make the health known or fresh
    store.set_comp("acme", role="product", career_note="agentic SOC product, principal IC")
    store.set_health("Globex", kind="enterprise")
    store.set_comp("globex", role="internal")
    store.set_comp("initech", role="customer")  # a role with no kind: from the neutral 50
    v = comps.view(cfg, store)
    parts = {r["company"]: r["parts"] for r in v["suggestion"]["ranking"]}
    assert parts["Acme"]["career"] == {"score": 95, "input": "tech company, builds product", "known": True}
    assert parts["Globex"]["career"] == {"score": 35, "input": "enterprise, internal tools", "known": True}
    assert parts["Initech"]["career"] == {"score": 55, "input": "customer-facing", "known": True}
    assert parts["Acme"]["health"] == {"score": 50, "input": "no company health kept", "known": False}
    acme = next(o for o in v["opportunities"] if o["company"] == "Acme")
    assert acme["comp"]["career_note"] == "agentic SOC product, principal IC" and acme["health"]["kind"] == "tech"
    assert "career note: agentic SOC product, principal IC" in comps.text(v)
    assert "career 95 (tech company, builds product)" in comps.suggestion_text(v["suggestion"])
    store.close()


def test_career_by_the_rules_clamped_and_neutral_when_unknown():
    def career(kind, role):
        return comps._career({"health": {"kind": kind} if kind else None, "comp": {"role": role}})[:2]

    assert career(None, None) == (50, "no kind or role kept")
    assert [career(k, "product")[0] for k in ("tech", "consulting", "enterprise")] == [95, 70, 55]
    assert [career(k, None)[0] for k in ("tech", "consulting", "enterprise")] == [80, 55, 40]
    assert career("consulting", "customer") == (60, "consulting, customer-facing")
    assert career("tech", "customer")[0] == 85 and career("enterprise", "internal")[0] == 35


def test_kind_and_role_are_checked_and_cleared(tracked, capsys):
    c = ["-c", str(tracked)]
    cli.main([*c, "comp", "acme", "--role", "product", "--career-note", "principal IC"])
    assert "role product; career_note principal IC" in capsys.readouterr().out
    cli.main([*c, "health", "Acme", "--kind", "tech"])
    assert "kind tech company" in capsys.readouterr().out
    cli.main([*c, "comp", "acme", "--role", "", "--career-note", ""])
    assert "no compensation kept" in capsys.readouterr().out
    store = Store(config.load(tracked).state)
    with pytest.raises(ValueError, match="role must be product, customer or internal"):
        store.set_comp("acme", role="boss")
    with pytest.raises(ValueError, match="kind must be tech, consulting or enterprise"):
        store.set_health("Acme", kind="startup")
    assert store.health("Acme")["as_of"] is None  # the kind alone doesn't date the health
    store.close()
    app = App(tracked)
    with pytest.raises(ApiError, match="role must be"):
        app.post_comp({"key": "acme", "role": "boss"})
    assert app.post_health({"company": "Acme", "kind": "consulting"}) == {"company": "Acme"}


def test_old_state_files_get_the_new_columns(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE comps (key TEXT PRIMARY KEY, base TEXT, bonus TEXT, equity TEXT, signon TEXT, "
                     "asked TEXT, offered TEXT, note TEXT, set_at TEXT NOT NULL);"
                     "CREATE TABLE company_health (company TEXT PRIMARY KEY, name TEXT NOT NULL, listing TEXT, "
                     "stage TEXT, raised TEXT, revenue TEXT, headcount TEXT, layoffs TEXT, rating TEXT, risk TEXT, "
                     "sources TEXT, as_of TEXT, set_at TEXT NOT NULL);"
                     "INSERT INTO company_health VALUES ('acme', 'Acme', 'private', NULL, NULL, NULL, NULL, NULL, "
                     "NULL, NULL, NULL, '2026-10-01', 'x');")
    db.commit()
    db.close()
    store = Store(path)
    assert store.health("Acme")["kind"] is None and store.health("Acme")["listing"] == "private"
    store.set_health("Acme", kind="tech")
    assert store.health("Acme")["kind"] == "tech"
    store.close()


def test_the_watchlist_sets_the_weights(tracked):
    def load(text):
        tracked.write_text(tracked.read_text().split("comps:")[0] + text)
        return config.load(tracked)

    assert config.load(tracked).comps.weights == pytest.approx(config.COMP_WEIGHTS)
    cfg = load("comps:\n  weights: {career: 50, pay: 50, fit: 0, progress: 0, health: 0}\n")
    assert cfg.comps.weights == pytest.approx({"career": .5, "pay": .5, "fit": 0, "progress": 0, "health": 0})
    cfg = load("comps:\n  weights: {career: 2}\n")  # the rest keep their defaults, then all add up to 1
    assert sum(cfg.comps.weights.values()) == pytest.approx(1) and cfg.comps.weights["career"] > 0.6
    for bad, message in [("{taste: 1}", "unknown comps.weights name"), ("{pay: -1}", "comps.weights.pay must be"),
                         ("{pay: x}", "comps.weights.pay must be"), ("[1]", "comps.weights looks like"),
                         ("{career: 0, pay: 0, fit: 0, progress: 0, health: 0}", "can't all be 0")]:
        with pytest.raises(config.ConfigError, match=message):
            load(f"comps:\n  weights: {bad}\n")
    with pytest.raises(config.ConfigError, match="unknown comps setting"):
        load("comps:\n  mood: 1\n")


def test_the_weights_change_the_ranking(tracked):
    cfg = config.load(tracked)
    store = Store(cfg.state)
    store.set_health("Globex", kind="tech")
    store.set_comp("globex", role="product")
    tracked.write_text(tracked.read_text() + "comps:\n  weights: {career: 1, pay: 0, fit: 0, progress: 0, health: 0}\n")
    only_career = config.load(tracked)
    s = comps.view(only_career, store)["suggestion"]
    assert s["ranking"][0]["company"] == "Globex" and s["ranking"][0]["total"] == 95
    assert comps.suggestion_text(s).startswith("Suggestion (pay vs the best of these; weights: career 100%, pay 0%")
    store.close()


def test_worth_orders_jobs_by_the_same_rules_as_the_suggestion(tracked):
    tracked.write_text(tracked.read_text() + "pay:\n  target: 180000-210000\ncomps:\n"
                               "  weights: {career: 25, pay: 25, fit: 20, progress: 15, health: 15}\n")
    cfg = config.load(tracked)
    store = Store(cfg.state)
    store.set_health("Acme", kind="tech")
    store.set_comp("acme", role="product")
    jobs = {c: store.find(c)[0] for c in ("acme", "globex", "initech")}
    fits = {"acme": {"score": 84, "must_haves_met": 5, "must_haves_total": 6}, "globex": None, "initech": None}
    w = comps.worth(cfg, store, [(jobs[c], fits[c]) for c in jobs])
    acme, globex = w[jobs["acme"].key], w[jobs["globex"].key]
    # pay $200K posted middle is above the $195K target middle; career tech + product = 95; no progress part
    assert acme["parts"]["career"] == {"score": 95, "input": "tech company, builds product", "known": True}
    assert acme["parts"]["fit"]["score"] == 84 and "progress" not in acme["parts"]
    assert globex["parts"]["career"]["score"] == 50 and globex["parts"]["fit"]["input"] == "not scored"
    assert globex["parts"]["pay"]["input"] == "$175K posted vs your $180K-$210K target"
    parts = acme["parts"]
    assert acme["score"] == round((0.25 * parts["career"]["score"] + 0.25 * parts["pay"]["score"]
                                   + 0.2 * parts["fit"]["score"] + 0.15 * parts["health"]["score"]) / 0.85)
    assert acme["score"] > globex["score"] > 0
    assert w[jobs["initech"].key]["parts"]["pay"]["input"] == "no pay known"
    store.close()


def test_the_page_lists_carry_a_worth_score(tracked):
    app = App(tracked)
    app.post_health({"company": "Initech", "kind": "tech"})
    app.post_comp({"key": "initech", "role": "product"})
    store = Store(config.load(tracked).state)
    store.set_status(["manual:initech:ml-engineer"], "queued")
    store.close()
    jobs = app.get_queue({})
    initech = next(j for j in jobs if j["key"] == "manual:initech:ml-engineer")
    assert initech["worth"]["parts"]["career"]["score"] == 95 and 0 <= initech["worth"]["score"] <= 100
    assert set(initech["worth"]["parts"]) == {"career", "pay", "fit", "health"}
    page = (__import__("pathlib").Path(config.__file__).parent / "static" / "index.html").read_text()
    assert '["worth", "Worth it"]' in page and 'remember("today.sort"' in page and 'remember("queue.sort"' in page
