"""`jobwatch search` (notes and recruiters), `jobwatch answers` (what was answered before) and `find --roles`."""

import asyncio
import json
from datetime import datetime, timezone

import pytest

from jobwatch import answers, cli, config, sources
from jobwatch.models import Job
from jobwatch.store import Store


@pytest.fixture
def store(watchlist):
    s = Store(config.load(watchlist).state)
    yield s
    s.close()


@pytest.fixture
def tracked(store):
    """Acme Robotics: an interview where a recruiter called, a rejected application, a closed posting. Hooli: a
    skipped role."""
    store.add("Acme Robotics", "Perception Engineer", status="interviewing", applied="2026-09-10",
              note="2026-09-11: Dana Reyes from Staffing Co called, $101/hr W2", next_step="onsite with Dana")
    store.add("Acme Robotics", "Sales Lead", status="rejected", applied="2026-08-01", note="no reply")
    store.add("Hooli Inc", "Staff Engineer", status="skipped", note="100% onsite")
    store.set_via(store.add("Globex", "Data Engineer", status="applied", applied="2026-09-01").key, "linkedin-alert")
    key = store.add("Initech", "Closed Role", status="applied", applied="2026-07-01").key
    store.set_closed(key, True)
    return store


# -- search

def titles(found):
    return sorted(j["title"] for j in found)


def test_search_matches_note_next_step_via_title_and_company_in_any_case(tracked):
    assert titles(tracked_search(tracked, "DANA")) == ["Perception Engineer"]  # note and next step
    assert titles(tracked_search(tracked, "linkedin-alert")) == ["Data Engineer"]
    assert titles(tracked_search(tracked, "sales lead")) == ["Sales Lead"]
    assert titles(tracked_search(tracked, "acme")) == ["Perception Engineer", "Sales Lead"]
    assert titles(tracked_search(tracked, "closed role")) == ["Closed Role"]  # closed postings too


def test_search_takes_the_text_literally(tracked):
    assert titles(tracked_search(tracked, "$101/hr")) == ["Perception Engineer"]
    assert titles(tracked_search(tracked, "100%")) == ["Staff Engineer"]
    assert titles(tracked_search(tracked, "_")) == []  # not a wildcard
    assert tracked_search(tracked, "  ") == []


def tracked_search(store, text):
    from jobwatch import company
    return company.mentions(store, text)


def test_search_command(watchlist, tracked, capsys):
    cli.main(["-c", str(watchlist), "search", "dana"])
    out = capsys.readouterr().out
    assert "1 job mentions 'dana':" in out and "Acme Robotics: Perception Engineer" in out
    assert "interviewing · applied 2026-09-10" in out and "Next: onsite with Dana" in out
    assert "Note: 2026-09-11: Dana Reyes from Staffing Co called, $101/hr W2" in out
    cli.main(["-c", str(watchlist), "search", "$101/hr", "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert [j["company"] for j in data] == ["Acme Robotics"] and data[0]["key"].startswith("manual:acme-robotics:")
    cli.main(["-c", str(watchlist), "search", "nobody"])
    assert "No tracked job has 'nobody'" in capsys.readouterr().out


def test_search_shows_the_note_entry_that_matched(watchlist, store, capsys):
    store.add("Acme Robotics", "Perception Engineer", status="applied", applied="2026-09-10",
              note="2026-09-11: Dana called 2026-09-20: sent availability")
    cli.main(["-c", str(watchlist), "search", "dana"])
    out = capsys.readouterr().out
    assert "Note: 2026-09-11: Dana called" in out and "availability" not in out


# -- answers

@pytest.fixture
def with_answers(store):
    def apply(company, title, day, pairs):
        job = store.add(company, title, status="applied", applied=day)
        store.package(job.key).write(answers=[{"question": q, "answer": a} for q, a in pairs])
    apply("Acme Robotics", "Perception Engineer", "2026-09-10", [
        ("What is your notice period?", "Two weeks."), ("Reason for leaving?", "Looking for more scope.")])
    apply("Globex", "Data Engineer", "2026-09-20", [
        ("Notice period", "Immediately available."), ("Salary expectation", "Open to discuss.")])
    apply("Hooli Inc", "Staff Engineer", "2026-08-01", [("Why Hooli?", "The product.")])
    store.add("Initech", "No Package", status="applied", applied="2026-09-25")
    return store


def test_find_answers_by_every_word_newest_first(with_answers):
    found = answers.find(with_answers, "NOTICE period")
    assert [(f["company"], f["question"], f["answer"], f["applied"]) for f in found] == [
        ("Globex", "Notice period", "Immediately available.", "2026-09-20"),
        ("Acme Robotics", "What is your notice period?", "Two weeks.", "2026-09-10")]
    assert [f["question"] for f in answers.find(with_answers, "leaving reason")] == ["Reason for leaving?"]  # any order
    assert answers.find(with_answers, "reason notice") == []  # every word
    assert answers.find(with_answers, "visa") == []


def test_answers_without_a_query_list_each_question_once_with_its_latest_answer(with_answers):
    found = answers.find(with_answers)
    assert [f["question"] for f in found] == [
        "Notice period", "Salary expectation", "What is your notice period?", "Reason for leaving?", "Why Hooli?"]
    assert all(f["asked"] == 1 for f in found)
    again = with_answers.add("Umbrella", "Engineer", status="applied", applied="2026-09-30")
    with_answers.package(again.key).write(answers=[{"question": "notice  PERIOD", "answer": "One month."}])
    latest = answers.find(with_answers)[0]
    # the same question in other case or spacing is one: the latest wording and answer, counted twice
    assert (latest["question"], latest["answer"], latest["asked"]) == ("notice  PERIOD", "One month.", 2)
    assert len(answers.find(with_answers)) == 5


def test_answers_command(watchlist, with_answers, capsys):
    cli.main(["-c", str(watchlist), "answers", "notice", "period"])
    out = capsys.readouterr().out
    assert "Notice period\n  Globex, Data Engineer (2026-09-20)\n    Immediately available." in out
    cli.main(["-c", str(watchlist), "answers", "salary", "--format", "json"])
    assert json.loads(capsys.readouterr().out)[0]["answer"] == "Open to discuss."
    cli.main(["-c", str(watchlist), "answers", "visa"])
    assert "No saved form answer has a question with 'visa' in it." in capsys.readouterr().out


def test_find_past_answers_tool(watchlist, with_answers, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    assert mcp.find_past_answers("salary")[0]["answer"] == "Open to discuss."
    assert len(mcp.find_past_answers()) == 5
    assert "find_past_answers" in {t.name for t in asyncio.run(mcp.server.list_tools())}


# -- find --roles

def ashby_board(web, *jobs):
    web.responses["https://api.ashbyhq.com/posting-api/job-board/globex?includeCompensation=true"] = {"jobs": [
        {"id": id_, "title": title, "location": "Remote", "isListed": True, "workplaceType": "Remote",
         "publishedAt": day, "jobUrl": f"https://jobs.ashbyhq.com/globex/{id_}", "descriptionPlain": text}
        for id_, title, day, text in jobs]}


def test_find_roles_lists_matching_titles_with_place_pay_and_day(web, capsys):
    ashby_board(web,
                ("r1", "Agent Platform Engineer", "2026-09-01T00:00:00+00:00", "Pay range: $200,000 - $270,000 a year"),
                ("r2", "Senior AI Agent Engineer", "2026-10-01T00:00:00+00:00", "Great team."),
                ("r3", "Account Executive", "2026-10-02T00:00:00+00:00", "Sell things."))
    cli.main(["find", "https://jobs.ashbyhq.com/globex", "--roles", "AGENT"])
    out = capsys.readouterr().out
    assert "ashby:globex  (3 open roles)" in out
    assert out.index("Senior AI Agent Engineer  (Remote · posted 2026-10-01)") < out.index(
        "Agent Platform Engineer  (Remote · $200K–$270K · posted 2026-09-01)")  # newest first
    assert "Account Executive" not in out
    cli.main(["find", "https://jobs.ashbyhq.com/globex", "--roles", "pilot"])
    assert "No open role with 'pilot' in its title." in capsys.readouterr().out


def test_find_without_roles_lists_none(web, capsys):
    ashby_board(web, ("r1", "Agent Engineer", "2026-09-01T00:00:00+00:00", ""))
    cli.main(["find", "https://jobs.ashbyhq.com/globex"])
    assert "Agent Engineer  (" not in capsys.readouterr().out


def test_roles_of_a_searched_board_are_searched_and_read_in_full(monkeypatch):
    stub = Job(source="workday", company="x.wd5/Ext", id="1", title="Agent Engineer", url="", salary_min=150000,
               salary_max=180000, posted=datetime(2026, 9, 1, tzinfo=timezone.utc))
    seen = {}

    def fake(source, board, get=None, search=(), wanted=None, known=None, cap=0):
        seen.update(search=search, wanted=wanted("Staff Agent Engineer"))
        return [stub, Job(source="workday", company="x", id="2", title="Cook", url="")]
    monkeypatch.setattr(sources, "fetch", fake)
    found = sources.roles_matching("workday", "x.wd5/Ext", "Agent", [])
    assert [j.title for j in found] == ["Agent Engineer"] and found[0].pay() == "$150K–$180K"
    assert seen == {"search": ("agent",), "wanted": True}
