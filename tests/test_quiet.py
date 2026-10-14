"""Applications that have gone quiet: detection by stage, what to do next, snoozing, the due list, where it shows."""

from datetime import date

import pytest

from jobwatch import cli, config, quiet, report
from jobwatch import store as store_module
from jobwatch import web as web_module
from jobwatch.contacts import Contacts
from jobwatch.store import Store
from jobwatch.web import ApiError, App

from .conftest import TOKEN

TODAY = date(2026, 10, 14)
RULES = config.Quiet()  # applied 21 days, screening 14, interviewing 10, long 45


class Frozen(date):
    @classmethod
    def today(cls):
        return TODAY


@pytest.fixture(autouse=True)
def frozen(monkeypatch):
    for module in (store_module, quiet, report, web_module):
        monkeypatch.setattr(module, "date", Frozen)


def put(store, company, title, status="applied", news="2026-10-01", note=None, follow_up=None, closed=False):
    """An application whose last news was on `news` (the day applied, for one still at applied)."""
    job = store.add(company, title, status=status, applied=news, follow_up=follow_up)
    store.db.execute("UPDATE jobs SET status_at=?, note=?, closed=? WHERE key=?",
                     (f"{news}T09:00:00+00:00", note, "2026-10-10T00:00:00+00:00" if closed else None, job.key))
    store.db.commit()
    return job.key


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state.db")
    yield s
    s.close()


def assess(store, key, **kw):
    job, rec = store.find(key)
    return quiet.assess(job, rec, kw.pop("rules", RULES), TODAY, **kw)


@pytest.mark.parametrize("status, news, days", [
    ("applied", "2026-09-23", 21), ("screening", "2026-09-30", 14), ("interviewing", "2026-10-04", 10)])
def test_quiet_after_the_days_set_for_its_stage(store, status, news, days):
    key = put(store, "Acme Robotics", "Controls Engineer", status, news)
    got = assess(store, key)
    assert (got["days"], got["since"], got["posting_open"], got["long"]) == (days, news, True, False)


@pytest.mark.parametrize("status, news", [
    ("applied", "2026-09-24"), ("screening", "2026-10-01"), ("interviewing", "2026-10-05"),
    ("offer", "2026-01-01"), ("rejected", "2026-01-01"), ("withdrawn", "2026-01-01")])
def test_not_quiet_yet_or_not_open(store, status, news):
    assert assess(store, put(store, "Globex", "Data Engineer", status, news)) is None


def test_a_stage_set_to_zero_is_never_quiet(store):
    key = put(store, "Globex", "Data Engineer", "screening", "2026-01-01")
    assert assess(store, key, rules=config.Quiet(screening=0)) is None


def test_a_note_is_news_but_a_snooze_is_not(store):
    key = put(store, "Initech", "Platform Engineer", news="2026-08-01", note="2026-08-02: recruiter replied")
    assert assess(store, key)["since"] == "2026-08-02"
    store.db.execute("UPDATE jobs SET note=note || ' 2026-10-08: sent the take-home' WHERE key=?", (key,))
    assert assess(store, key) is None  # news 6 days ago
    key = put(store, "Initech", "Data Engineer", news="2026-08-01")
    store.snooze(key, 7)
    assert assess(store, key)["since"] == "2026-08-01"


def test_applied_counts_from_the_day_applied_not_the_day_it_was_added(store):
    key = put(store, "Acme Robotics", "Controls Engineer", news="2026-08-20")
    store.db.execute("UPDATE jobs SET status_at='2026-10-13T09:00:00+00:00' WHERE key=?", (key,))
    assert assess(store, key)["days"] == 55


def test_nudge_names_who_you_know(store):
    known = Contacts([{"name": "Ana Li", "position": "Engineer", "company": "Acme Robotics"}])
    key = put(store, "Acme Robotics", "Controls Engineer", news="2026-09-10")
    got = assess(store, key, known=known)
    assert got["move"] == "nudge" and got["advice"] == quiet.NUDGE and got["contacts"] == known.at("Acme Robotics")
    assert got["contacts"][0]["name"] == "Ana Li"


def test_a_closed_posting_or_a_very_old_one_is_likely_closed(store):
    gone = assess(store, put(store, "Globex", "Data Engineer", news="2026-09-20", closed=True))
    assert (gone["move"], gone["posting_open"], gone["long"]) == ("close", False, False)
    assert gone["advice"] == "Likely closed (its posting is gone): mark it rejected or withdrawn."
    assert not gone["contacts"]
    old = assess(store, put(store, "Initech", "Data Engineer", news="2026-08-01"))
    assert (old["move"], old["long"], old["days"]) == ("close", True, 74)
    assert "nothing for 74 days" in old["advice"]


def test_snooze_pushes_the_follow_up_and_keeps_the_stage(store):
    key = put(store, "Acme Robotics", "Controls Engineer", "screening", "2026-09-01", note="2026-09-01: call Ana",
              follow_up="2026-09-15")
    assert store.snooze(key, 7) == "2026-10-21"
    _, rec = store.find(key)
    assert (rec["status"], rec["follow_up"]) == ("screening", "2026-10-21")
    assert rec["note"] == "2026-09-01: call Ana 2026-10-14: Snoozed 7 days: follow up 2026-10-21."
    store.snooze(key, 1)
    assert store.find(key)[1]["note"].endswith("2026-10-14: Snoozed 1 day: follow up 2026-10-15.")


def test_snooze_refuses_what_is_not_open(store):
    done = put(store, "Globex", "Data Engineer", "rejected")
    with pytest.raises(ValueError, match="isn't an open application"):
        store.snooze(done)
    with pytest.raises(ValueError, match="at least a day"):
        store.snooze(put(store, "Initech", "Data Engineer"), 0)


def test_long_quiet_follow_ups_sort_below_the_fresh_ones(store):
    stale = put(store, "Initech", "Old", news="2026-08-01", follow_up="2026-08-15")
    fresh = put(store, "Globex", "Fresh", news="2026-10-10", follow_up="2026-10-12")
    short = put(store, "Acme Robotics", "Shortly quiet", news="2026-09-20", follow_up="2026-09-30")
    ended = put(store, "Umbrella", "Ended", "rejected", follow_up="2026-01-01")
    rows = store.applications()  # soonest follow-up first
    assert [j.key for j, _ in rows] == [stale, short, fresh, ended]
    found = quiet.find(rows, RULES, TODAY)
    assert set(found) == {stale, short}
    assert [j.key for j, _ in quiet.order(rows, found)] == [short, fresh, stale, ended]


@pytest.fixture
def seeded(watchlist, tmp_path):
    s = Store(tmp_path / "state.db")
    keys = {"stale": put(s, "Initech", "Old Role", news="2026-08-01", follow_up="2026-08-15"),
            "quiet": put(s, "Acme Robotics", "Controls Engineer", news="2026-09-10", follow_up="2026-09-20"),
            "fresh": put(s, "Globex", "Data Engineer", news="2026-10-12", follow_up="2026-10-13")}
    s.close()
    return keys


def test_cli_quiet_lists_the_longest_first_with_the_next_move(watchlist, seeded, capsys):
    cli.main(["-c", str(watchlist), "quiet"])
    out = capsys.readouterr().out
    assert out.startswith("# Gone quiet (2)")
    assert out.index("Initech") < out.index("Acme Robotics") and "Globex" not in out
    assert "**Gone quiet:** 74 days (since 2026-08-01), posting open. Likely closed (nothing for 74 days)" in out
    assert "**Gone quiet:** 34 days (since 2026-09-10), posting open. A short check-in to the recruiter" in out
    assert "jobwatch snooze KEY" in out


def test_cli_quiet_says_so_when_nothing_is_quiet(watchlist, capsys):
    cli.main(["-c", str(watchlist), "quiet"])
    assert capsys.readouterr().out.startswith("Nothing has gone quiet.")


def test_cli_names_who_you_know_and_follows_the_quiet_settings(watchlist, seeded, tmp_path, capsys):
    (tmp_path / "Connections.csv").write_text("First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
                                              "Ana,Li,https://example.test/ana,,Acme Robotics,Engineer,01 Jan 2024\n")
    watchlist.write_text(watchlist.read_text() + "connections: Connections.csv\nquiet: {applied: 30}\n")
    cli.main(["-c", str(watchlist), "quiet"])
    out = capsys.readouterr().out
    assert "Gone quiet (2)" in out and "You know: Ana Li (Engineer)" in out


def test_cli_apps_sorts_stale_below_and_due_collapses_them(watchlist, seeded, capsys):
    cli.main(["-c", str(watchlist), "apps"])
    out = capsys.readouterr().out
    assert "3 applied. **3 to follow up on now.** 2 gone quiet (`jobwatch quiet`)." in out
    assert out.index("Acme Robotics") < out.index("Globex") < out.index("Initech")  # the stale one last
    cli.main(["-c", str(watchlist), "apps", "--due"])
    out = capsys.readouterr().out
    assert "Initech" not in out and "Acme Robotics" in out and "Globex" in out
    assert out.rstrip().endswith("1 more due, quiet for 45+ days: `jobwatch quiet`.")


def test_cli_snooze(watchlist, seeded, capsys):
    cli.main(["-c", str(watchlist), "snooze", "controls-engineer", "--days", "14"])
    assert capsys.readouterr().out == "controls-engineer: follow up 2026-10-28\n"
    with pytest.raises(SystemExit, match="at least a day"):
        cli.main(["-c", str(watchlist), "snooze", "controls-engineer", "--days", "0"])


def test_mcp_list_applications_has_a_quiet_field(watchlist, seeded, monkeypatch):
    mcp_server = pytest.importorskip("jobwatch.mcp_server")
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    monkeypatch.setattr(quiet, "date", Frozen)
    rows = mcp_server.list_applications()
    assert [r["key"] for r in rows] == [seeded["quiet"], seeded["fresh"], seeded["stale"]]  # the stale one last
    got = {r["key"]: r["quiet"] for r in rows}
    assert got[seeded["fresh"]] is None
    assert (got[seeded["quiet"]]["move"], got[seeded["quiet"]]["days"]) == ("nudge", 34)
    assert got[seeded["stale"]]["long"] and got[seeded["stale"]]["move"] == "close"
    assert [r["key"] for r in mcp_server.list_applications(due_only=True)][-1] == seeded["stale"]
    assert "quiet" in mcp_server.list_applications.__doc__


def test_web_applications_carry_quiet_and_the_page_actions_work(watchlist, seeded):
    app = App(watchlist)
    d = app.get_applications({})
    assert [a["key"] for a in d["applications"]] == [seeded["quiet"], seeded["fresh"], seeded["stale"]]
    assert [bool(a["quiet"]) for a in d["applications"]] == [True, False, True]
    assert d["applications"][0]["quiet"]["advice"] == quiet.NUDGE

    assert app.post_snooze({"key": seeded["quiet"], "days": 3}) == {"follow_up": "2026-10-17"}
    app.post_track({"key": seeded["quiet"], "add_note": "emailed the recruiter"})
    app.post_track({"key": seeded["stale"], "status": "withdrawn"})
    d = {a["key"]: a for a in app.get_applications({})["applications"]}
    assert d[seeded["quiet"]]["follow_up"] == "2026-10-17" and d[seeded["quiet"]]["quiet"] is None  # news: not quiet
    assert d[seeded["quiet"]]["note"].endswith("2026-10-14: emailed the recruiter")
    assert d[seeded["stale"]]["status"] == "withdrawn" and d[seeded["stale"]]["quiet"] is None
    with pytest.raises(ApiError, match="days must be"):
        app.post_snooze({"key": seeded["fresh"], "days": 0})
    with pytest.raises(ApiError, match="isn't an open application"):
        app.post_snooze({"key": seeded["stale"]})


def test_the_snooze_endpoint_needs_the_token(server):
    from .conftest import request

    assert request(server, "POST", "/api/snooze", {"key": "x"})[0] in (401, 403)
    assert request(server, "POST", "/api/snooze", {"key": "nope"}, headers={"X-Jobwatch-Token": TOKEN})[0] == 404


def test_quiet_settings(tmp_path):
    path = tmp_path / "w.yaml"
    path.write_text("companies: []\nquiet: {applied: 30, long: 0}\n")
    assert config.load(path).quiet == config.Quiet(applied=30, screening=14, interviewing=10, long=0)
    path.write_text("companies: []\n")
    assert config.load(path).quiet == RULES
    for bad, match in (("{applied: -1}", r"quiet\.applied"), ("{offer: 3}", "unknown quiet"),
                       ("7", "quiet looks like")):
        path.write_text(f"companies: []\nquiet: {bad}\n")
        with pytest.raises(config.ConfigError, match=match):
            config.load(path)
