"""Ranked, typed likely questions (`jobwatch prep KEY --ranked`): written by the local model only, ordered by the code,
kept per posting, and the seed for a rehearsal page. The model is always a fake."""

import json

import pytest

from jobwatch import chat, cli, config, drafts, prep, questions, rehearse
from jobwatch.store import Store

POSTING = """About Initech
Initech builds widgets for logistics teams.

What you'll do:
- Lead the design of detection pipelines for cloud workloads
- Partner with product teams on threat models

Requirements:
- 8+ years building Python services in production
- Deep Kubernetes operations experience

Benefits
- Dental
"""
RESUME = "Built Python services in production for 9 years\nRan Kubernetes operations for a logistics company\n"
GOOD = [
    {"question": "Why Initech, and why this role?", "kind": "why_us", "ask": "", "likelihood": 5},
    {"question": "Walk me through a Kubernetes outage you ran.", "kind": "technical", "ask": "A2", "likelihood": 4},
    {"question": "Tell me about a time you disagreed with a product team.", "kind": "behavioral", "ask": "A4",
     "likelihood": 4},
    {"question": "How would you design a detection pipeline for cloud workloads?", "kind": "Technical", "ask": "A1",
     "likelihood": 4},
    {"question": "How did you reach 99 percent uptime?", "kind": "technical", "ask": "A3", "likelihood": 5},  # 99?
    {"question": "Why Initech, and why this role?", "kind": "why_us", "ask": "", "likelihood": 5},  # a repeat
    {"question": "What do you know about logistics teams?", "kind": "company", "ask": "", "likelihood": "high"},
    {"question": "Unfiled under any kind?", "kind": "other", "ask": "", "likelihood": 2},  # no ask: dropped
    {"question": "Which part of the pipeline would you test first?", "kind": "", "ask": "A3", "likelihood": 1},
]


def make(tmp_path, backend="local"):
    path = tmp_path / "jobwatch.yaml"
    (tmp_path / "resume.txt").write_text(RESUME)
    path.write_text(f"companies: []\nstate: state.db\nresume: resume.txt\nchat: {{backend: {backend}}}\n")
    cfg = config.load(path)
    store = Store(cfg.state)
    job = store.add("Initech", "Staff Detection Engineer", status="screening", description=POSTING)
    return cfg, store, job.key, path


@pytest.fixture
def setup(tmp_path):
    cfg, store, key, path = make(tmp_path)
    yield cfg, store, key, path
    store.close()


@pytest.fixture
def fake_model(monkeypatch):
    seen = {"reply": json.dumps({"questions": GOOD}), "calls": 0, "backends": [], "systems": [], "checked": []}

    def reply(backend, system, messages, model="", max_tokens=0):
        seen["calls"] += 1
        seen["backends"].append(backend)
        seen["systems"].append(system)
        yield seen["reply"]
    monkeypatch.setattr(chat, "check", lambda backend, keychain="", key_command="": seen["checked"].append(backend))
    monkeypatch.setattr(chat, "reply", reply)
    return seen


def test_the_questions_are_typed_ranked_and_checked(setup, fake_model):
    cfg, store, key, _ = setup
    got, note = questions.ranked(cfg, store, key, prep.asks(POSTING), True, POSTING)
    assert [q["rank"] for q in got] == list(range(1, len(got) + 1))
    texts = [q["question"] for q in got]
    assert "How did you reach 99 percent uptime?" not in texts  # a number the posting never wrote
    assert texts.count("Why Initech, and why this role?") == 1  # a repeat
    assert "Unfiled under any kind?" not in texts
    assert {q["kind"] for q in got} == {"why_us", "technical", "behavioral"}
    by = {q["question"]: q for q in got}
    assert by["How would you design a detection pipeline for cloud workloads?"]["kind"] == "technical"  # "Technical"
    assert by["What do you know about logistics teams?"]["kind"] == "why_us" and \
        by["What do you know about logistics teams?"]["likelihood"] == 3  # "company"; "high" isn't a number
    assert by["Which part of the pipeline would you test first?"]["kind"] == "technical"  # an ask: technical
    assert by["Walk me through a Kubernetes outage you ran."]["ask"].startswith("Deep Kubernetes")
    assert by["Why Initech, and why this role?"]["ask"] == ""
    assert note.startswith("Written by the local model (on this computer)") and "ranked" in note


def test_the_order_is_likelihood_then_the_stages_lean():
    raw = [{"question": "T?", "kind": "technical", "ask": "A1", "likelihood": 4},
           {"question": "B?", "kind": "behavioral", "ask": "", "likelihood": 4},
           {"question": "W?", "kind": "why_us", "ask": "", "likelihood": 4},
           {"question": "Low?", "kind": "why_us", "ask": "", "likelihood": 2},
           {"question": "Top?", "kind": "technical", "ask": "A2", "likelihood": 5}]
    asks = prep.asks(POSTING)
    screen = [q["question"] for q in questions.check(raw, asks, POSTING, screen=True)]
    assert screen == ["Top?", "W?", "B?", "T?", "Low?"]  # a first call leans to why-us, then behavioral
    interview = [q["question"] for q in questions.check(raw, asks, POSTING, screen=False)]
    assert interview == ["Top?", "T?", "B?", "W?", "Low?"]  # the interviews lean to technical


def test_the_most_kept_and_a_bad_reply_gives_none(setup):
    asks = prep.asks(POSTING)
    many = [{"question": f"Tell me about topic {'x' * n}?", "kind": "technical", "ask": "A1", "likelihood": 3}
            for n in range(30)]
    assert len(questions.check(many, asks, POSTING, True)) == questions.MOST
    assert questions.check([None, "text", {"question": 4}, {"kind": "technical"}], asks, POSTING, True) == []


def test_it_asks_the_local_model_even_when_the_chat_is_claude_and_sends_only_the_posting(tmp_path, fake_model):
    cfg, store, key, _ = make(tmp_path, backend="claude")
    assert cfg.chat.backend == "claude"
    got, note = questions.ranked(cfg, store, key, prep.asks(POSTING), True, POSTING)
    assert got and fake_model["backends"] == ["local"] and fake_model["checked"] == ["local"]
    system = fake_model["systems"][0]
    assert "Initech builds widgets" in system  # the posting goes
    assert all(line not in system for line in RESUME.splitlines()) and "Claude" not in note  # the resume doesn't
    store.close()


def test_a_reply_is_kept_so_asking_twice_asks_once_and_reading_never_asks(setup, fake_model):
    cfg, store, key, _ = setup
    asks = prep.asks(POSTING)
    assert questions.ranked(cfg, store, key, asks, True, POSTING, generate=False) == ([], "")
    assert fake_model["calls"] == 0
    first, _ = questions.ranked(cfg, store, key, asks, True, POSTING)
    again, note = questions.ranked(cfg, store, key, asks, True, POSTING)
    assert again == first and fake_model["calls"] == 1 and note.endswith("saved earlier.")
    assert questions.ranked(cfg, store, key, asks, True, POSTING, generate=False)[0] == first


def test_no_model_no_asks_or_a_bad_reply_leave_the_sheet_as_it_was(setup, fake_model, monkeypatch):
    cfg, store, key, _ = setup
    asks = prep.asks(POSTING)
    assert "no requirements" in questions.ranked(cfg, store, key, [], True, "nothing")[1]
    fake_model["reply"] = "I could not do that."
    got, note = questions.ranked(cfg, store, key, asks, True, POSTING)
    assert got == [] and "wasn't the questions asked for" in note
    assert store.draft(key, "x") is None and prep.build(cfg, store, key).ranked_questions == []

    def down(backend, keychain="", key_command=""):
        raise chat.ChatUnavailable("the local model server isn't running")
    monkeypatch.setattr(chat, "check", down)
    got, note = questions.ranked(cfg, store, key, asks, False, POSTING)
    assert got == [] and note == "Not drafted: the local model server isn't running."
    assert prep.build(cfg, store, key, ranked=True).expect  # the usual questions stand


def test_the_sheet_shows_them_in_markdown_html_and_the_dict(setup, fake_model):
    cfg, store, key, _ = setup
    assert prep.build(cfg, store, key).ranked_questions == []  # not asked for: nothing, and no section
    assert "ranked" not in prep.markdown(prep.build(cfg, store, key)).lower()
    sheet = prep.build(cfg, store, key, ranked=True)
    md = prep.markdown(sheet)
    assert "## Likely questions, ranked" in md and "1. **Why us** Why Initech, and why this role?" in md
    assert "**Technical** Walk me through a Kubernetes outage you ran. (probes: Deep Kubernetes" in md
    page = prep.html(sheet)
    assert "<h2>Likely questions, ranked</h2>" in page and "1. Why us" in page and "probes: Deep Kubernetes" in page
    assert prep.to_dict(sheet)["ranked_questions"][0]["kind"] == "why_us"
    assert prep.build(cfg, store, key).ranked_questions == sheet.ranked_questions  # saved ones are always read


def test_the_cards_answer_with_what_the_sheet_holds_never_a_model(setup, fake_model):
    cfg, store, key, _ = setup
    sheet = prep.build(cfg, store, key, ranked=True)
    cards = {c.question: c.answer for c in questions.cards(sheet)}
    assert len(cards) == len(sheet.ranked_questions)
    assert cards["Why Initech, and why this role?"].startswith("What the posting says about Initech: ")
    assert cards["Walk me through a Kubernetes outage you ran."] == (
        "Your closest line: Ran Kubernetes operations for a logistics company")
    assert cards["Tell me about a time you disagreed with a product team."].startswith("Pick a story of your own")
    assert cards["Which part of the pipeline would you test first?"] == drafts.NO_STORY
    assert all(a for a in cards.values())


def test_the_command_prints_the_sheet_and_the_note(setup, fake_model, capsys):
    _, _, key, path = setup
    cli.main(["-c", str(path), "prep", key, "--ranked"])
    out, err = capsys.readouterr()
    assert "## Likely questions, ranked" in out and "Written by the local model" in err
    assert fake_model["backends"] == ["local"]


def test_rehearse_writes_the_page_from_the_ranked_questions(setup, fake_model, tmp_path, capsys, monkeypatch):
    _, _, key, path = setup
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    out = tmp_path / "ranked-rehearse.html"
    cli.main(["-c", str(path), "prep", key, "--rehearse", "-o", str(out)])
    page = out.read_text()
    assert "Why Initech, and why this role?" in page and "Your closest line: Ran Kubernetes operations" in page
    assert "Initech: Staff Detection Engineer" in page and len(opened) == 1 and "Sheet" not in capsys.readouterr().out
    out.unlink()
    cli.main(["-c", str(path), "prep", key, "--rehearse", "-o", str(out), "--no-open", "--ui", "http://x.test:1"])
    assert out.exists() and len(opened) == 1 and "x.test:1" in out.read_text()
    assert rehearse.write_cards  # the same writer the hand-written sheets use


def test_rehearse_with_nothing_to_rehearse_says_why(setup, fake_model):
    _, _, key, path = setup
    fake_model["reply"] = "no json"
    with pytest.raises(SystemExit, match="no ranked questions to rehearse: Not written"):
        cli.main(["-c", str(path), "prep", key, "--rehearse"])


def test_the_mcp_tool_returns_them(setup, fake_model, monkeypatch):
    _, _, key, path = setup
    mcp = pytest.importorskip("jobwatch.mcp_server")
    monkeypatch.setenv("JOBWATCH_CONFIG", str(path))
    assert mcp.get_interview_prep(key)["ranked_questions"] == []
    got = mcp.get_interview_prep(key, ranked=True)
    assert got["ranked_questions"][0]["rank"] == 1 and got["ranked_note"].startswith("Written by")
    assert "ranked_questions" in mcp.get_interview_prep.__doc__
