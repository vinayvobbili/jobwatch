"""Prep sheets' role questions, company brief and pay section: written from the posting, notes and settings only,
with the pay floor kept off anything that goes to a cloud model. The model is always a fake."""

import json

import pytest

from jobwatch import chat, cli, config, drafts, prep
from jobwatch.config import ConfigError
from jobwatch.store import Store
from jobwatch.web import App

POSTING = """About Initech
Initech builds widgets for logistics teams.
We are a remote-first company.

What you'll do:
- Lead the design of detection pipelines for cloud workloads
- Partner with product teams on threat models

Requirements:
- 8+ years building Python services in production
- Deep Kubernetes operations experience

Benefits
- Dental
The salary range is $150,000 - $190,000.
"""
FLOOR, TARGET = 151000, 185000
CONNECTIONS = ("First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
               "Ana,Li,https://www.linkedin.com/in/ana-li,,Initech,Staff Engineer,01 Jan 2024\n"
               "Bo,Chen,https://www.linkedin.com/in/bo-chen,,Globex,Recruiter,01 Jan 2024\n")
REPLY = json.dumps({"questions": [
    {"question": "How have you run Python services in production for 8 years?", "ask": "A1"},
    {"question": "Describe your Kubernetes operations experience.", "ask": "A2"},
    {"question": "How did you hit a target of 99 percent uptime?", "ask": "A2"},  # 99 isn't in the posting
    {"question": "Describe your Kubernetes operations experience.", "ask": "A2"},  # a repeat
]})


def make(tmp_path, backend="local", pay="", description=POSTING):
    (tmp_path / "Connections.csv").write_text(CONNECTIONS)
    path = tmp_path / "jobwatch.yaml"
    path.write_text(f"companies: []\nconnections: Connections.csv\nstate: state.db\nscoring: {{backend: {backend}}}\n"
                    f"{pay}")
    cfg = config.load(path)
    store = Store(cfg.state)
    job = store.add("Initech", "Staff Detection Engineer", status="screening", description=description)
    store.add_note(job.key, "Recruiter said the team is small")
    return cfg, store, job.key, path


@pytest.fixture
def setup(tmp_path):
    cfg, store, key, path = make(tmp_path, pay=f"pay: {{target: {TARGET}, floor: {FLOOR}}}\n")
    yield cfg, store, key, path
    store.close()


@pytest.fixture
def fake_model(monkeypatch):
    seen = {"reply": REPLY, "calls": 0, "systems": []}

    def reply(backend, system, messages, model="", max_tokens=0):
        seen["calls"] += 1
        seen["systems"].append(system)
        seen["backend"] = backend
        yield seen["reply"]
    monkeypatch.setattr(chat, "check", lambda backend: None)
    monkeypatch.setattr(chat, "reply", reply)
    return seen


# --- role questions ---------------------------------------------------------------------------------------------

def test_questions_come_from_the_asks_and_numbers_the_posting_lacks_are_dropped(setup, fake_model):
    cfg, store, key, _ = setup
    got = prep.role_questions(cfg, store, key)
    assert got == ["How have you run Python services in production for 8 years?",
                   "Describe your Kubernetes operations experience."]
    system = fake_model["systems"][0]
    assert "A1 (they ask for): 8+ years building Python" in system and "<posting>" in system
    assert "<resume>" not in system and "<stories>" not in system  # nothing of the person's goes with it


def test_questions_are_saved_per_posting_text(setup, fake_model):
    cfg, store, key, _ = setup
    prep.role_questions(cfg, store, key)
    prep.role_questions(cfg, store, key)
    assert fake_model["calls"] == 1
    store.db.execute("UPDATE jobs SET data=json_set(data, '$.description', ?) WHERE key=?",
                     (POSTING + "\n- Terraform experience\n", key))
    store.db.commit()
    prep.role_questions(cfg, store, key)
    assert fake_model["calls"] == 2


def test_generic_questions_stand_without_a_model_and_without_asking(setup, fake_model, monkeypatch):
    cfg, store, key, _ = setup
    assert prep.role_questions(cfg, store, key, generate=False) == prep.SCREEN_QUESTIONS
    assert fake_model["calls"] == 0
    sheet = prep.build(cfg, store, key)  # a plain sheet never calls the model
    assert sheet.role_questions == [] and sheet.expect == prep.SCREEN_QUESTIONS and fake_model["calls"] == 0

    def unavailable(backend):
        raise chat.ChatUnavailable("chat on this computer needs Apple Silicon")
    monkeypatch.setattr(chat, "check", unavailable)
    assert prep.role_questions(cfg, store, key) == prep.SCREEN_QUESTIONS
    sheet = prep.build(cfg, store, key, questions=True)
    assert sheet.role_questions == [] and sheet.questions_note.startswith("Not drafted: chat on this computer")
    assert sheet.expect[0] in prep.markdown(sheet) and "Not drafted: chat on this" in prep.html(sheet)


def test_an_unusable_reply_is_not_saved(setup, fake_model):
    cfg, store, key, _ = setup
    fake_model["reply"] = "Sure! Here are some questions."
    assert prep.role_questions(cfg, store, key) == prep.SCREEN_QUESTIONS
    fake_model["reply"] = REPLY
    assert len(prep.role_questions(cfg, store, key)) == 2 and fake_model["calls"] == 2


def test_the_sheet_shows_questions_written_for_the_role(setup, fake_model):
    cfg, store, key, _ = setup
    sheet = prep.build(cfg, store, key, questions=True)
    assert sheet.role_questions and "Written by" in sheet.questions_note
    assert prep.to_dict(sheet)["role_questions"] == sheet.role_questions
    for out in (prep.markdown(sheet), prep.html(sheet)):
        assert "Describe your Kubernetes operations experience." in out and "Written by" in out
        assert prep.SCREEN_QUESTIONS[0] not in out
    again = prep.build(cfg, store, key)  # saved ones are read without asking
    assert again.role_questions == sheet.role_questions and "saved earlier" in again.questions_note
    assert fake_model["calls"] == 1


def test_drafted_questions_are_the_role_questions_too(setup, fake_model):
    cfg, store, key, _ = setup
    fake_model["reply"] = json.dumps({"questions": [{"question": "Tell me about Python.", "ask": "A1",
                                                     "stories": [], "outline": [], "angle": ""}]})
    sheet = prep.build(cfg, store, key, draft=True, questions=True)
    assert sheet.role_questions == ["Tell me about Python."] and fake_model["calls"] == 1


# --- the company brief ------------------------------------------------------------------------------------------

def test_the_brief_is_the_posting_notes_and_contacts(setup):
    cfg, store, key, _ = setup
    brief = prep.build(cfg, store, key).brief
    assert brief["about"] == ["Initech builds widgets for logistics teams.", "We are a remote-first company."]
    assert "Recruiter said the team is small" in brief["notes"]
    assert [p["name"] for p in brief["contacts"]] == ["Ana Li"]  # the other connection works elsewhere
    assert "nothing else was looked up" in brief["source"]
    text, page = prep.markdown(prep.build(cfg, store, key)), prep.html(prep.build(cfg, store, key))
    for out in (text, page):
        assert "Company brief" in out and "Initech builds widgets" in out and "Ana Li" in out
        assert "Recruiter said the team is small" in out and "Drawn from the posting and your notes" in out


def test_the_brief_falls_back_to_sentences_naming_the_company(tmp_path):
    cfg, store, key, _ = make(
        tmp_path,
        description="Initech makes widgets for logistics teams. Great team.\n\n"
                    "Requirements:\n- Python")
    brief = prep.build(cfg, store, key).brief
    assert brief["about"] == ["Initech makes widgets for logistics teams."]
    store.close()


def test_a_posting_that_says_nothing_gives_no_invented_brief(tmp_path):
    cfg, store, key, _ = make(tmp_path, description="Requirements:\n- Python and more")
    store.db.execute("UPDATE jobs SET note=NULL WHERE key=?", (key,))
    store.db.commit()
    (tmp_path / "Connections.csv").write_text(CONNECTIONS.replace("Initech", "Acme"))
    cfg = config.load(cfg.path)
    sheet = prep.build(cfg, store, key)
    assert sheet.brief == {} and "Company brief" not in prep.markdown(sheet)
    assert "Company brief" not in prep.html(sheet)
    store.close()


def test_the_brief_never_goes_to_the_web(setup, monkeypatch):
    import socket

    def no_network(*a, **k):
        raise AssertionError("the brief must not use the network")
    monkeypatch.setattr(socket, "create_connection", no_network)
    cfg, store, key, _ = setup
    assert prep.build(cfg, store, key).brief["about"]


# --- pay ---------------------------------------------------------------------------------------------------------

def test_pay_settings_are_read_checked_and_documented(tmp_path):
    cfg, store, _key, path = make(tmp_path, pay="pay: {target: 180000, floor: 150000}\n")
    assert (cfg.pay.target, cfg.pay.floor) == (180000, 150000) and config.Pay().floor == 0
    store.close()
    path.write_text("companies: []\npay: {floor: lots}\n")
    with pytest.raises(ConfigError, match=r"pay.floor must be a whole number"):
        config.load(path)
    assert "target:" in config.EXAMPLE and "floor:" in config.EXAMPLE and "never sent to Claude" in config.EXAMPLE
    assert "floor" not in config.defaults()["pay"] and "target" not in config.defaults()["pay"]


def test_the_local_sheet_shows_the_range_the_target_and_the_private_floor(setup):
    cfg, store, key, _ = setup
    sheet = prep.build(cfg, store, key)
    assert sheet.pay["posted"] == "$150K–$190K" and sheet.pay["target"] == TARGET and sheet.pay["floor"] == FLOOR
    assert sheet.pay["target_note"] == "inside the posted range" and sheet.pay["floor_note"] == \
        "inside the posted range"
    text, page = prep.markdown(sheet), prep.html(sheet)
    assert "**Posted range:** $150K–$190K (from the posting)" in text
    assert "**Your target:** $185K, inside the posted range" in text
    assert "**Your floor (private):** $151K" in text and "Never sent to Claude" in text
    assert "Your floor (private):" in page and "$151K" in page


def test_pay_notes_compare_with_the_range(tmp_path):
    cfg, store, key, _ = make(tmp_path, pay="pay: {target: 120000, floor: 200000}\n")
    pay = prep.build(cfg, store, key).pay
    assert pay["target_note"] == "below the posted range" and "above the top" in pay["floor_note"]
    store.close()


def test_no_pay_section_without_pay_or_settings(tmp_path):
    cfg, store, key, _ = make(tmp_path, description=POSTING.replace("The salary range is $150,000 - $190,000.", ""))
    sheet = prep.build(cfg, store, key)
    assert sheet.pay == {} and "## Pay" not in prep.markdown(sheet) and "<h2>Pay</h2>" not in prep.html(sheet)
    store.close()


def test_the_posted_range_alone_still_shows(tmp_path):
    cfg, store, key, _ = make(tmp_path)
    text = prep.markdown(prep.build(cfg, store, key))
    assert "## Pay" in text and "Your floor" not in text and "Your target" not in text


def test_the_floor_never_appears_in_a_prompt_for_the_claude_backend(tmp_path, fake_model):
    cfg, store, key, _ = make(tmp_path, backend="claude", pay=f"pay: {{target: {TARGET}, floor: {FLOOR}}}\n")
    assert cfg.chat.backend == "claude"
    sheet = prep.build(cfg, store, key, questions=True)
    prep.build(cfg, store, key, draft=True)
    assert fake_model["calls"] == 2 and fake_model["backend"] == "claude"
    for system in fake_model["systems"]:
        assert str(FLOOR) not in system and "151,000" not in system and "151K" not in system
        assert "private floor" not in system
    pay_prompt = next(s for s in fake_model["systems"] if "## The pay" in s)
    assert "Posted range: $150K–$190K" in pay_prompt and f"{TARGET:,}" in pay_prompt  # the target may go
    assert "left out of what was sent to Claude" in drafts.questions(cfg, store, key, prep.asks(POSTING), True,
                                                                     POSTING, sheet.pay)[1]
    assert sheet.pay["floor"] == FLOOR  # still on the local sheet, labelled private
    store.close()


def test_the_floor_may_go_to_the_local_model_only(setup, fake_model):
    cfg, store, key, _ = setup
    prep.role_questions(cfg, store, key)
    assert "The user's private floor: $151,000" in fake_model["systems"][0]
    text, withheld = drafts.pay_context({"posted": "", "floor": FLOOR}, "claude")
    assert text == "" and withheld
    assert drafts.pay_context({"floor": FLOOR}, "local") == (f"The user's private floor: ${FLOOR:,}", False)


def test_a_changed_floor_asks_afresh_but_never_leaks_through_the_cache_key(setup, fake_model):
    cfg, store, key, path = setup
    prep.role_questions(cfg, store, key)
    path.write_text(path.read_text().replace(str(FLOOR), "160000"))
    prep.role_questions(config.load(path), store, key)
    assert fake_model["calls"] == 2
    rows = store.db.execute("SELECT inputs FROM drafts").fetchall()
    assert all(str(FLOOR) not in r[0] for r in rows)  # the key is a hash


def test_what_leaves_for_an_assistant_has_no_floor(setup):
    cfg, store, key, _ = setup
    sheet = prep.without_floor(prep.build(cfg, store, key))
    blob = json.dumps(prep.to_dict(sheet)) + prep.markdown(sheet)
    assert str(FLOOR) not in blob and "$151K" not in blob
    assert sheet.pay["floor_withheld"] and sheet.pay["target"] == TARGET
    assert "left out of this copy" in prep.markdown(sheet)
    assert prep.without_floor(prep.build(cfg, store, key)).pay["posted"] == "$150K–$190K"


def test_the_mcp_sheet_has_the_new_sections_and_no_floor(setup, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    _cfg, store, key, path = setup
    store.close()
    monkeypatch.setenv("JOBWATCH_CONFIG", str(path))
    got = mcp.get_interview_prep(key)
    assert got["brief"]["about"] and got["pay"]["posted"] == "$150K–$190K" and got["role_questions"] == []
    assert str(FLOOR) not in json.dumps(got) and got["pay"]["floor_withheld"] is True
    doc = mcp.get_interview_prep.__doc__
    assert "brief" in doc and "role_questions" in doc and "private pay floor is never returned" in doc


# --- the CLI and the page ----------------------------------------------------------------------------------------

def test_cli_and_web_carry_the_new_sections(setup, fake_model, capsys):
    _cfg, _store, key, path = setup
    cli.main(["--config", str(path), "prep", key, "--questions"])
    out = capsys.readouterr()
    assert "## Company brief" in out.out and "## Pay" in out.out and "Your floor (private)" in out.out
    assert "Describe your Kubernetes operations experience." in out.out and "Written by" in out.err
    got = App(path).get_prep({"key": [key]})
    assert got["brief"]["about"] and got["pay"]["floor"] == FLOOR and got["role_questions"]
    assert "Company brief" in got["html"] and "private" in got["html"]


def test_the_page_shows_them():
    from pathlib import Path

    page = (Path(prep.__file__).parent / "static" / "index.html").read_text()
    assert '"Company brief"' in page and '"Your floor (private): "' in page
    assert "Write questions for this role" in page and "&questions=1" in page


# --- a target range ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("pay, want", [
    ("{target: 180000}", (180000, 0)),
    ("{target: 180000-210000}", (180000, 210000)),
    ("{target: 180K-210K}", (180000, 210000)),
    ("{target: '$180,000 to $210,000'}", (180000, 210000)),
    ("{target: 180000, target_max: 210000}", (180000, 210000)),
    ("{target: 200000-200000}", (200000, 0)),
])
def test_the_target_is_a_number_or_a_range(tmp_path, pay, want):
    cfg, store, _key, _ = make(tmp_path, pay=f"pay: {pay}\n")
    assert (cfg.pay.target, cfg.pay.target_max) == want
    store.close()


@pytest.mark.parametrize("pay", ["{target: 210000-180000}", "{target: lots-more}", "{target: 1-2-3}",
                                 "{target: 180000, target_max: 150000}", "{target: 180000, target_max: -1}"])
def test_a_bad_target_range_is_refused(tmp_path, pay):
    path = tmp_path / "jobwatch.yaml"
    path.write_text(f"companies: []\npay: {pay}\n")
    with pytest.raises(ConfigError, match=r"pay\.target"):
        config.load(path)


@pytest.mark.parametrize("target, note", [
    ("120000-140000", "below the posted range"), ("160000-180000", "inside the posted range"),
    ("200000-220000", "above the posted range"), ("140000-170000", "starts below the posted range"),
    ("170000-210000", "reaches above the posted range"), ("140000-210000", "wider than the posted range")])
def test_a_target_range_shows_and_sits_against_the_posted_range(tmp_path, target, note):
    cfg, store, key, _ = make(tmp_path, pay=f"pay: {{target: {target}, floor: {FLOOR}}}\n")
    sheet = prep.build(cfg, store, key)
    low, high = (int(n) for n in target.split("-"))
    assert sheet.pay["target_note"] == note and (sheet.pay["target"], sheet.pay["target_max"]) == (low, high)
    assert f"**Your target:** ${low // 1000}K–${high // 1000}K, {note}" in prep.markdown(sheet)
    assert f"${low // 1000}K–${high // 1000}K, {note}" in prep.html(sheet)
    assert str(FLOOR) not in str(prep.without_floor(sheet).pay.get("floor"))
    store.close()


def test_a_target_range_may_go_to_claude_but_the_floor_may_not(tmp_path, fake_model):
    cfg, store, key, _ = make(tmp_path, backend="claude", pay=f"pay: {{target: 170000-190000, floor: {FLOOR}}}\n")
    prep.build(cfg, store, key, questions=True)
    prep.build(cfg, store, key, draft=True)
    pay_prompt = next(s for s in fake_model["systems"] if "## The pay" in s)
    assert "$170,000 to $190,000" in pay_prompt and f"{FLOOR:,}" not in pay_prompt
    store.close()
