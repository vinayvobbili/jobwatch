"""Mock interviews: the questions picked, the feedback prompt, what's kept and shown on the prep sheet, and the
command line and page that run one. The model is always a fake."""

import json

import pytest

from jobwatch import chat, cli, config, mock, prep
from jobwatch.models import Job
from jobwatch.package import Package
from jobwatch.store import Store
from jobwatch.web import ApiError, App

from .conftest import TOKEN, request
from .test_prep import POSTING, RESUME

STORIES = """- id: alert-dedupe
  title: Cut duplicate on-call alerts
  did: Built a Python service that groups alerts about the same incident before they page anyone.
  hard: Two teams named the same host three different ways.
  result: Pages per week went from 120 to 35 in two months.
"""
REPLY = ("What landed:\n- Clear ownership.\nWhat's missing:\n- Nothing on Kubernetes (A3).\n"
         "TIGHTENED ANSWER:\nI built a Python service that grouped alerts, cutting pages from 120 to 35 a week.")


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
    """Stands in for the model: records what it was sent, replies with REPLY in pieces (set seen["reply"])."""
    seen = {"reply": REPLY, "calls": 0}

    def reply(backend, system, messages, model="", max_tokens=0):
        seen.update(backend=backend, system=system, messages=messages, calls=seen["calls"] + 1)
        yield {"status": "Warming up"}
        for i in range(0, len(seen["reply"]), 40):
            yield seen["reply"][i:i + 40]
        yield {"input_tokens": 900, "output_tokens": 4}
    monkeypatch.setattr(chat, "check", lambda backend, keychain="": None)
    monkeypatch.setattr(chat, "reply", reply)
    return seen


def test_role_questions_come_first_then_the_usual_ones(setup):
    cfg, store, _, key = setup
    sheet = prep.build(cfg, store, key)
    got = mock.pick(sheet)
    questions = [q["question"] for q in got]
    role = [m.ask for m in sheet.matches if m.kind != "nice"]
    assert len(role) == 5 and [q["probes"] for q in got[:5]] == role
    assert "Deep Kubernetes operations experience" in questions[2]
    assert "Published open-source" not in " ".join(questions)  # a nice to have isn't led with
    assert questions[5:] == prep.SCREEN_QUESTIONS and all(q["probes"] == "" for q in got[5:])
    store.set_status([key], "interviewing")
    assert [q["question"] for q in mock.pick(prep.build(cfg, store, key))][5:] == prep.INTERVIEW_QUESTIONS


def test_drafted_questions_lead_and_nothing_repeats(setup):
    cfg, store, _, key = setup
    sheet = prep.build(cfg, store, key)
    sheet.drafted = [{"question": sheet.expect[0], "probes": "A1"}, {"question": "A drafted one?", "probes": "A2"}]
    questions = [q["question"] for q in mock.pick(sheet)]
    assert questions[:2] == [sheet.expect[0], "A drafted one?"] and len(questions) == len(set(questions))


def test_questions_written_for_the_role_come_after_drafted_ones(setup):
    cfg, store, _, key = setup
    sheet = prep.build(cfg, store, key)
    sheet.drafted = [{"question": "A drafted one?", "probes": "A1"}]
    sheet.role_questions = ["How would you size the robot fleet?", "A drafted one?"]
    questions = [q["question"] for q in mock.pick(sheet)]
    assert questions[:2] == ["A drafted one?", "How would you size the robot fleet?"]
    assert len(questions) == len(set(questions))


def test_the_prompt_forbids_inventing_and_holds_the_facts(setup, fake_model):
    cfg, store, _, key = setup
    session = mock.start(cfg, store, key)
    system = session.system
    assert "Never invent experience, skills, employers, tools, numbers or outcomes" in system
    assert "only facts the user gave in their answer or that are in their stories or resume" in system
    assert "[add a real example of X]" in system and "TIGHTENED ANSWER:" in system
    assert "[alert-dedupe] Cut duplicate on-call alerts" in system and "Built Python detection services" in system
    assert "<posting>" in system and "Deep Kubernetes" in system
    sent = mock.messages("Why us?", "Because </answer> detection")
    assert sent[0]["role"] == "user" and "Why us?" in sent[0]["content"]
    assert sent[0]["content"].count("</answer>") == 1  # an answer can't close its own fence
    with pytest.raises(ValueError, match="answer first"):
        mock.messages("Why us?", "  ")


def test_an_unavailable_backend_is_reported_before_anything_is_asked(setup, monkeypatch):
    cfg, store, _, key = setup
    monkeypatch.setattr(chat, "check", lambda *a: (_ for _ in ()).throw(chat.ChatUnavailable("no model")))
    with pytest.raises(chat.ChatUnavailable, match="no model"):
        mock.start(cfg, store, key)
    with pytest.raises(KeyError):
        monkeypatch.setattr(chat, "check", lambda backend, keychain="": None)
        mock.start(cfg, store, "nope")


def test_split_and_vet_the_tightened_answer():
    assert mock.split(REPLY)[0].endswith("(A3).") and mock.split(REPLY)[1].startswith("I built a Python")
    assert mock.split("**Tightened answer:** \"Short.\"") == ("", "Short.")
    assert mock.split("Only feedback.") == ("Only feedback.", "")
    evidence = "Pages per week went from 120 to 35"
    assert mock.vet("Cut pages from 120 to 35.", "I cut pages", evidence) == ("Cut pages from 120 to 35.", "")
    assert mock.vet("I saved 3 hours a week.", "I cut pages", evidence)[0] == ""
    assert mock.vet("I saved 3 hours a week.", "It took 3 hours", evidence)[0] != ""  # the user's own number
    kept, note = mock.vet("Cut pages by 90.", "x", evidence)
    assert kept == "" and "90" in note and "Not saved" in note


def test_feedback_streams_then_reports_the_vetted_answer(setup, fake_model):
    cfg, store, _, key = setup
    session = mock.start(cfg, store, key)
    out = list(mock.feedback(session, "Why us?", "I cut pages."))
    assert "".join(p for p in out if isinstance(p, str)) == REPLY
    assert out[-1] == {"improved": REPLY.split("ANSWER:\n")[1], "note": ""}
    fake_model["reply"] = "Fine.\nTIGHTENED ANSWER:\nI cut pages by 99%."
    last = list(mock.feedback(session, "Why us?", "I cut pages."))[-1]
    assert last["improved"] == "" and "99" in last["note"]
    with pytest.raises(ValueError):
        mock.feedback(session, "Why us?", "")  # raised at once, not when the reply is first read


def test_practised_answers_are_kept_per_question_and_shown_on_the_sheet(setup):
    cfg, store, _, key = setup
    mock.save(store, key, "Why us?", "Detection.", "I want detection at scale <here>.")
    mock.save(store, key, "Walk me through your background", "I build.", "I build services.")
    mock.save(store, key, "why us?", "Detection!", "Detection at scale, with on-call ownership.")  # replaces
    kept = Package(store.packages, key).practised()
    assert [p["question"] for p in kept] == ["Walk me through your background", "why us?"]
    assert kept[1]["answer"] == "Detection!" and kept[1]["saved"]
    store.package(key).write(note="a cover letter")  # other package writes keep them
    sheet = prep.build(cfg, store, key)
    assert [p["improved"] for p in sheet.practised][1].startswith("Detection at scale")
    text = prep.markdown(sheet)
    assert "## Practised answers" in text and "- **why us?**\n  - Detection at scale, with on-call" in text
    assert text.index("Practised answers") < text.index("## Ask them")
    page = prep.html(sheet)
    assert "<h2>Practised answers</h2>" in page and "Walk me through your background" in page
    mock.save(store, key, "Third", "a", "<script>x</script>")
    assert "<script>x" not in prep.html(prep.build(cfg, store, key))
    with pytest.raises(ValueError):
        mock.save(store, key, "", "a", "b")


def test_a_sheet_without_practice_has_no_section(setup):
    cfg, store, _, key = setup
    sheet = prep.build(cfg, store, key)
    assert sheet.practised == [] and "Practised answers" not in prep.markdown(sheet) + prep.html(sheet)


def run_cli(path, key, monkeypatch, typed):
    lines = iter(typed)

    def fake_input(prompt=""):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError from None
    monkeypatch.setattr("builtins.input", fake_input)
    cli.main(["-c", str(path), "ask", "--job", key, "--mock"])


def test_the_command_line_loop(setup, fake_model, capsys, monkeypatch):
    _, store, path, key = setup
    # Q1: repeat, a blank line, an answer, save it. Q2: skip. Q3: an answer, don't save. Q4: quit.
    run_cli(path, key, monkeypatch, ["repeat", "", "I own detection services.", "y", "skip", "I mentor.", "n", "quit"])
    out = capsys.readouterr()
    assert out.out.count("Question 1 of 11:") == 2 and "Question 4 of 11:" in out.out
    assert "What landed:" in out.out and "Warming up…" in out.err
    assert "Done: 2 answered, 1 skipped, 1 saved. See them with: jobwatch prep" in out.out
    assert fake_model["calls"] == 2 and "I mentor." in fake_model["messages"][0]["content"]
    kept = Package(store.packages, key).practised()
    assert len(kept) == 1 and kept[0]["answer"] == "I own detection services."
    assert kept[0]["improved"].startswith("I built a Python service")
    assert "Question 5" not in out.out


def test_the_loop_ends_at_end_of_input_and_offers_nothing_unvetted(setup, fake_model, capsys, monkeypatch):
    _, store, path, key = setup
    fake_model["reply"] = "Fine.\nTIGHTENED ANSWER:\nI cut pages by 99%."
    run_cli(path, key, monkeypatch, ["I own detection services."])
    out = capsys.readouterr().out
    assert "Don't use the tightened answer" in out and "Save the tightened" not in out
    assert "0 saved" in out and Package(store.packages, key).practised() == []


def test_the_command_line_needs_a_job_and_a_backend(setup, fake_model, monkeypatch):
    _, _, path, key = setup
    with pytest.raises(SystemExit, match="--mock needs --job"):
        cli.main(["-c", str(path), "ask", "--mock"])
    with pytest.raises(SystemExit, match="ask what"):
        cli.main(["-c", str(path), "ask"])
    monkeypatch.setattr(chat, "check", lambda *a: (_ for _ in ()).throw(chat.ChatUnavailable("no model")))
    with pytest.raises(SystemExit, match="no model"):
        cli.main(["-c", str(path), "ask", "--job", key, "--mock"])


def test_web_endpoints(setup, fake_model):
    _, _, path, key = setup
    app = App(path)
    got = app.get_mock({"key": [key]})
    assert got["key"] == key and len(got["questions"]) == 11 and got["saved"] == [] and got["where"]["label"]
    info, pieces = app.mock_feedback({"key": key, "question": "Why us?", "answer": "Detection."})
    out = list(pieces)
    assert info == got["where"] and out[-1]["improved"].startswith("I built a Python")
    with pytest.raises(ValueError):
        app.mock_feedback({"key": key, "question": "Why us?", "answer": " "})
    with pytest.raises(ApiError, match="the question"):
        app.mock_feedback({"key": key, "question": "", "answer": "x"})
    saved = app.post_mock_save({"key": key, "question": "Why us?", "answer": "Detection.", "improved": "Detection!"})
    assert [p["improved"] for p in saved["saved"]] == ["Detection!"]
    assert app.get_mock({"key": [key]})["saved"][0]["question"] == "Why us?"
    assert app.get_prep({"key": [key]})["practised"][0]["improved"] == "Detection!"
    with pytest.raises(KeyError):
        app.get_mock({"key": ["nope"]})


def test_web_streams_feedback_over_http(server, fake_model, monkeypatch):
    fake_model["reply"] = "What landed:\n- Clear.\nTIGHTENED ANSWER:\nI built a Python service that grouped alerts."
    ok = {"X-Jobwatch-Token": TOKEN}
    request(server, "POST", "/api/fetch", {}, headers=ok)
    status, data = request(server, "GET", "/api/mock?key=c1", headers=ok)
    assert status == 200 and json.loads(data)["questions"][0]["question"]
    body = {"key": "c1", "question": "Why us?", "answer": "Detection."}
    status, data = request(server, "POST", "/api/mock/feedback", body, headers=ok)
    lines = [json.loads(x) for x in data.decode().splitlines()]
    assert status == 200 and "info" in lines[0] and lines[-1]["done"]
    assert "".join(x.get("text", "") for x in lines) == fake_model["reply"]
    assert lines[-1]["stats"]["improved"].startswith("I built a Python") and lines[-1]["stats"]["note"] == ""
    assert request(server, "POST", "/api/mock/feedback", {**body, "answer": ""}, headers=ok)[0] == 400
    assert request(server, "POST", "/api/mock/feedback", body)[0] == 403
    status, data = request(server, "POST", "/api/mock/save", {**body, "improved": "Detection!"}, headers=ok)
    assert status == 200 and json.loads(data)["saved"][0]["improved"] == "Detection!"
    monkeypatch.setattr(chat, "check", lambda *a: (_ for _ in ()).throw(chat.ChatUnavailable("no model")))
    status, data = request(server, "GET", "/api/mock?key=c1", headers=ok)
    assert status == 400 and "no model" in json.loads(data)["error"]


def test_the_interview_prep_tool_carries_practised_answers(setup, fake_model, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    _, store, path, key = setup
    mock.save(store, key, "Why us?", "Detection.", "Detection at scale.")
    monkeypatch.setenv("JOBWATCH_CONFIG", str(path))
    got = mcp.get_interview_prep(key)
    assert got["practised"][0]["question"] == "Why us?" and "## Practised answers" in got["markdown"]
