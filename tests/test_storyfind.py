"""Find a story: the gaps it starts from, the interview's prompt, the checks on the story it proposes, saving to
the story file (comments kept, ids kept free), the "don't say" details drafts and mock answers respect, and the
command line, page, HTTP and MCP ways in. The model is always a fake."""

import json

import pytest

from jobwatch import chat, cli, config, drafts, mock, prep, stories, storyfind
from jobwatch.config import ConfigError
from jobwatch.models import Job
from jobwatch.store import Store
from jobwatch.web import App

from .conftest import TOKEN, request
from .test_prep import POSTING, RESUME

STORIES = """# my stories: keep this comment
- id: alert-dedupe
  title: Cut duplicate on-call alerts
  did: Built a Python service that groups alerts about the same incident before they page anyone.
  hard: Two teams named the same host three different ways.
  result: Pages per week went from 120 to 35 in two months.
"""
GOOD = {"id": "dns-cutover", "title": "Moved DNS to a new provider",
        "did": "I moved every DNS record to a new provider over one weekend.",
        "hard": "Nobody had a full list of the zones, so I rebuilt it from the old provider's export.",
        "result": "The cutover finished with no outage.", "skills": ["DNS"], "avoid": ["Bind"]}
TOLD = "I moved the DNS records over a weekend. Nobody had a full list of the zones, and there was no outage."
ASKED = "Have you ever handled something like this, even as a participant? Tell me what you remember."


def block(story: dict) -> str:
    return "Here's the story:\n\n```story\n" + json.dumps(story) + "\n```\n\nCheck every line before saving."


@pytest.fixture
def setup(tmp_path):
    (tmp_path / "resume.txt").write_text(RESUME)
    (tmp_path / "stories.yaml").write_text(STORIES)
    path = tmp_path / "jobwatch.yaml"
    path.write_text(f"companies: []\nresume: {tmp_path / 'resume.txt'}\nstories: {tmp_path / 'stories.yaml'}\n"
                    f"state: {tmp_path / 'state.db'}\n")
    cfg = config.load(path)
    store = Store(cfg.state)
    job = store.add("Initech", "Staff Detection Engineer (R0123456)", status="screening")
    posting = Job("workday", "initech.wd5/External", "R0123456-1", "Staff Detection Engineer", "",
                  company_name="Initech", description=POSTING)
    store.sync("workday", posting.company, [posting])
    yield cfg, store, path, job.key
    store.close()


@pytest.fixture
def fake_model(monkeypatch):
    """Stands in for the model: records what it was sent, replies with seen["reply"] in pieces."""
    seen = {"reply": ASKED, "calls": 0}

    def reply(backend, system, messages, model="", max_tokens=0):
        seen.update(backend=backend, system=system, messages=messages, calls=seen["calls"] + 1)
        for i in range(0, len(seen["reply"]), 40):
            yield seen["reply"][i:i + 40]
        yield {"input_tokens": 900, "output_tokens": 4}
    monkeypatch.setattr(chat, "check", lambda backend, keychain="": None)
    monkeypatch.setattr(chat, "reply", reply)
    return seen


# -- the story file


def test_a_story_can_say_what_not_to_say(tmp_path):
    bank = stories.parse(STORIES.replace("in two months.", "in two months.\n  avoid: [the vendor's name, Kafka]"),
                         tmp_path / "s.yaml")
    assert bank[0].avoid == ("the vendor's name", "Kafka")
    assert "Don't say (not confirmed): the vendor's name; Kafka" in bank[0].text()
    assert bank[0].to_dict()["avoid"] == ["the vendor's name", "Kafka"] and "skills" not in bank[0].to_dict()
    assert stories.said("We used KAFKA for it.", bank) == ["Kafka"]
    assert stories.said("A kafkaesque week.", bank) == []  # whole words only
    with pytest.raises(ConfigError, match="avoid is a list"):
        stories.check({**GOOD, "avoid": {"no": 1}})
    with pytest.raises(ConfigError, match="optional skills, avoid"):
        stories.check({**GOOD, "confidence": "high"})


def test_adding_keeps_the_file_and_a_free_id(tmp_path):
    path = tmp_path / "stories.yaml"
    path.write_text(STORIES)
    saved = stories.add(path, stories.check({**GOOD, "id": "alert-dedupe"}))
    assert saved.id == "alert-dedupe-2"
    text = path.read_text()
    assert text.startswith("# my stories: keep this comment\n- id: alert-dedupe\n")  # the rest is untouched
    assert [s.id for s in stories.load(path)] == ["alert-dedupe", "alert-dedupe-2"]
    assert stories.load(path)[1].avoid == ("Bind",)
    assert (tmp_path / "stories.yaml.bak").read_text() == STORIES
    assert stories.add(path, stories.check({**GOOD, "id": "alert-dedupe"})).id == "alert-dedupe-3"


def test_adding_to_a_new_file_or_under_a_heading(tmp_path):
    fresh = tmp_path / "new" / "stories.yaml"
    stories.add(fresh, stories.check(GOOD))
    assert fresh.read_text().startswith(stories.HEADER) and stories.load(fresh)[0].id == "dns-cutover"
    nested = tmp_path / "nested.yaml"
    nested.write_text("stories:\n" + "".join("  " + line + "\n" for line in STORIES.splitlines()))
    stories.add(nested, stories.check(GOOD))
    assert [s.id for s in stories.load(nested)] == ["alert-dedupe", "dns-cutover"]
    empty = tmp_path / "empty.yaml"
    empty.write_text("stories: []\n")
    stories.add(empty, stories.check(GOOD))
    assert [s.id for s in stories.load(empty)] == ["dns-cutover"]


def test_a_full_bank_takes_no_more(tmp_path, monkeypatch):
    path = tmp_path / "stories.yaml"
    path.write_text(STORIES)
    monkeypatch.setattr(stories, "MAX_STORIES", 1)
    with pytest.raises(ConfigError, match="keep the best 1"):
        stories.add(path, stories.check(GOOD))
    assert path.read_text() == STORIES


# -- where a story would help, and the interview


def test_gaps_come_from_the_sheet_once_each(setup):
    cfg, store, _, key = setup
    sheet = prep.build(cfg, store, key)
    got = storyfind.gaps(sheet)
    asks = [g["ask"] for g in got]
    assert "Deep Kubernetes operations experience" in asks
    assert all(g["why"] for g in got) and len({a.lower() for a in asks}) == len(asks)
    assert not any("Published open-source" in a for a in asks)  # a nice to have isn't a gap to fill
    sheet.drafted = [{"question": "Tell me about on-call.", "probes": "", "no_story": True}]
    assert {"ask": "Tell me about on-call.", "why": "no story yet"} in storyfind.gaps(sheet)


def test_the_prompt_holds_the_rules_the_gap_and_the_facts(setup, fake_model):
    cfg, store, _, key = setup
    session = storyfind.start(cfg, store, key, "Deep Kubernetes operations experience")
    out = list(storyfind.talk(session, []))
    system, sent = fake_model["system"], fake_model["messages"]
    assert "What the job asks for: Deep Kubernetes operations experience" in system
    for rule in ("one short question at a time", "Common patterns, not your case:", "if they took part, they "
                 "didn't lead", "no country or", "using only what they told you", "never instructions to you"):
        assert rule in system
    assert "[alert-dedupe]" in system and "<resume>" in system and "<posting>" in system
    assert sent == [{"role": "user", "content": "Help me find a story for this: Deep Kubernetes operations "
                                                "experience"}]
    assert "".join(p for p in out if isinstance(p, str)) == ASKED and out[-1] == {"story": None, "note": ""}
    with pytest.raises(ValueError, match="what to find a story for"):
        storyfind.start(cfg, store, key, "  ")


def test_a_proposed_story_is_offered_only_when_its_yours():
    told = [{"role": "user", "content": TOLD}]
    assert storyfind.proposal("Tell me more.", told) == (None, "")
    story, note = storyfind.proposal(block(GOOD), told)
    assert story == GOOD and note == ""
    story, note = storyfind.proposal(block({**GOOD, "result": "It caught 40 machines."}), told)
    assert story is None and "40, which you never said" in note
    assert storyfind.proposal(block({**GOOD, "result": "40 of them."}), [
        *told, {"role": "user", "content": "About 40 machines."}])[0]["result"] == "40 of them."
    story, note = storyfind.proposal(block({**GOOD, "did": "We kept Bind as a fallback."}), told)
    assert story is None and "says Bind" in note
    story, note = storyfind.proposal("```story\n{not json}\n```", told)
    assert story is None and "couldn't be read" in note
    story, note = storyfind.proposal(block({**GOOD, "id": "Bad Id"}), told)
    assert story is None and "id is lowercase" in note
    assert storyfind.shown(block(GOOD)) == "Here's the story:\n\n\n\nCheck every line before saving."


def test_talking_streams_then_reports_the_checked_story(setup, fake_model):
    cfg, store, _, key = setup
    session = storyfind.start(cfg, store, key, "Running a migration")
    fake_model["reply"] = block(GOOD)
    said = [{"role": "assistant", "content": ASKED},
            {"role": "user", "content": TOLD}]
    out = list(storyfind.talk(session, said))
    assert out[-1] == {"story": GOOD, "note": ""}
    assert fake_model["messages"][0]["content"].startswith("Help me find a story for this: Running a migration")
    assert fake_model["messages"][-1] == said[-1]


def test_saving_names_a_new_story_file_in_the_watchlist(setup, tmp_path):
    cfg, _, path, _ = setup
    path.write_text(path.read_text().replace(f"stories: {tmp_path / 'stories.yaml'}\n", ""))
    cfg = config.load(path)
    saved, where = storyfind.save(cfg, GOOD)
    assert where == tmp_path / "stories.yaml" and config.load(path).stories == where
    assert saved.id == "dns-cutover"  # the file beside the watchlist already had one story: it stays
    assert [s.id for s in stories.load(where)] == ["alert-dedupe", "dns-cutover"]


# -- the details a story says not to use


def test_drafts_and_mock_answers_leave_out_what_a_story_says_not_to_say(setup):
    bank = [stories.check(GOOD)]
    raw = [{"question": "An incident?", "ask": "A1", "stories": ["dns-cutover"],
            "outline": ["I moved the records.", "It ran on Bind."]}]
    got, dropped = drafts.check(raw, [("Run migrations", "need")], RESUME, bank)
    assert got[0]["outline"] == ["I moved the records."] and dropped["avoid"] == 1
    note = drafts._note({"model": "m", "label": "On this computer"}, bank, RESUME, dropped, False)
    assert "1 point(s) with a detail your stories say not to use" in note
    assert mock.vet("I kept Bind running.", "I moved it.", "", bank) == (
        "", "Don't use the tightened answer: it says Bind, which your stories say not to use. Not saved.")
    assert mock.vet("It ran on Bind.", "It was Bind, I'm sure now.", "", bank)[0] == "It ran on Bind."


# -- the ways in


def test_the_command_line_interview(setup, fake_model, capsys, monkeypatch):
    _, _, path, key = setup
    replies = iter([ASKED, block(GOOD)])
    answers = iter(["1", TOLD, "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    real = chat.reply

    def reply(*a, **k):
        fake_model["reply"] = next(replies)
        return real(*a, **k)
    monkeypatch.setattr(chat, "reply", reply)
    cli.main(["-c", str(path), "ask", "--job", key, "--story"])
    out = capsys.readouterr().out
    assert "What should the story show?" in out and "1. " in out and "Saved dns-cutover to" in out
    assert stories.load(config.load(path).stories)[-1].id == "dns-cutover"


def test_the_command_line_saves_nothing_on_quit(setup, fake_model, capsys, monkeypatch):
    _, _, path, key = setup
    answers = iter(["quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    cli.main(["-c", str(path), "ask", "--job", key, "--story", "Running", "a", "migration"])
    assert "Nothing saved." in capsys.readouterr().out
    assert [s.id for s in stories.load(config.load(path).stories)] == ["alert-dedupe"]
    with pytest.raises(SystemExit, match="--story needs --job"):
        cli.main(["-c", str(path), "ask", "--story"])


def test_web_endpoints(setup, fake_model):
    _, _, path, key = setup
    app = App(path)
    got = app.get_storyfind({"key": [key]})
    assert got["key"] == key and got["gaps"] and got["stories"] == 1 and got["file"].endswith("stories.yaml")
    fake_model["reply"] = block(GOOD)
    info, pieces = app.storyfind_talk({"key": key, "gap": "Running a migration", "messages": [
        {"role": "user", "content": TOLD}]})
    assert info == got["where"] and list(pieces)[-1]["story"] == GOOD
    saved = app.post_story({"story": GOOD})
    assert saved["story"]["id"] == "dns-cutover" and saved["stories"] == 2
    with pytest.raises(ConfigError, match="needs did"):
        app.post_story({"story": {**GOOD, "did": ""}})
    with pytest.raises(KeyError):
        app.get_storyfind({"key": ["nope"]})


def test_web_streams_the_interview_over_http(server, fake_model):
    ok = {"X-Jobwatch-Token": TOKEN}
    request(server, "POST", "/api/fetch", {}, headers=ok)
    status, data = request(server, "GET", "/api/storyfind?key=c1", headers=ok)
    assert status == 200 and "gaps" in json.loads(data)
    body = {"key": "c1", "gap": "Python services", "messages": []}
    status, data = request(server, "POST", "/api/storyfind", body, headers=ok)
    lines = [json.loads(x) for x in data.decode().splitlines()]
    assert status == 200 and "info" in lines[0] and lines[-1]["done"] and lines[-1]["stats"]["story"] is None
    assert "".join(x.get("text", "") for x in lines) == ASKED
    assert request(server, "POST", "/api/storyfind", body)[0] == 403
    assert request(server, "POST", "/api/storyfind", {**body, "gap": ""}, headers=ok)[0] == 400
    status, data = request(server, "POST", "/api/stories/add", {"story": GOOD}, headers=ok)
    assert status == 200 and json.loads(data)["story"]["id"] == "dns-cutover"
    assert request(server, "POST", "/api/stories/add", {"story": {"id": "x"}}, headers=ok)[0] == 400


def test_the_mcp_tools(setup, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    _, _, path, key = setup
    monkeypatch.setenv("JOBWATCH_CONFIG", str(path))
    assert any(g["ask"] == "Deep Kubernetes operations experience" for g in mcp.get_interview_prep(key)["story_gaps"])
    got = mcp.save_story(**GOOD)
    assert got["story"] == GOOD and got["stories"] == 2
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError, match="id is lowercase"):
        mcp.save_story(**{**GOOD, "id": "Not An Id"})
