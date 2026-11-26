"""Who to contact about a job and the note to them: the people a posting names, the ones in your notes and
connections, the LinkedIn searches, the drafts and the checks on them. The model is faked: these tests never call
one, and nothing is sent."""

import json
from datetime import date

import pytest
import yaml

from jobwatch import chat, cli, config, followup, outreach
from jobwatch.store import Store
from jobwatch.web import ApiError, App

TODAY = date(2026, 3, 16)
POSTING = """About the role
Initech builds widgets for logistics teams. We are an Equal Opportunity employer.

Hiring Manager: Jane Okafor, Director of Security Engineering
Recruiter: Sam Lee <sam.lee@initech.example>
Interviewers: Priya Nair (Staff Engineer) and Omar Haddad, Principal Engineer
You will report to Jane Okafor.

Requirements:
- 6+ years of Python and AWS in production
"""
RESUME = """Jordan Rivera

Experience
Platform Engineer, Globex (2019-2024)
- Ran 40 clusters on AWS with Terraform
- Cut deploy time from 40 minutes to 9 by caching builds
"""
CONNECTIONS = """First Name,Last Name,URL,Email Address,Company,Position,Connected On
Ana,Li,https://www.linkedin.com/in/example-ana,,"Initech, Inc.",Staff Engineer,01 Jan 2024
Bo,Chen,https://www.linkedin.com/in/example-bo,,Initech,Technical Recruiter,02 Jan 2024
Cy,Diaz,https://www.linkedin.com/in/example-cy,,Globex Corporation,Engineering Manager,03 Jan 2024
"""
SAID = ("LINKEDIN:\nHi Jane, I found the Security Engineer role at Initech and my platform work on AWS and Terraform "
        "fits it. Would you be open to a short chat about the role?\nSUBJECT:\nThe Security Engineer role at Initech\n"
        "BODY:\nHi Jane,\n\nI found the Security Engineer role at Initech. At Globex I ran 40 clusters on AWS with "
        "Terraform, which matches what the posting asks for.\n\nWould you be open to a short chat about the role?")


@pytest.fixture
def cfg(tmp_path):
    (tmp_path / "resume.txt").write_text(RESUME)
    (tmp_path / "Connections.csv").write_text(CONNECTIONS)
    path = tmp_path / "jobwatch.yaml"
    path.write_text(yaml.safe_dump({"companies": [], "state": "state.db", "resume": "resume.txt",
                                    "connections": "Connections.csv", "reply": {"followup": "local"}}))
    return config.load(path)


@pytest.fixture
def store(cfg):
    s = Store(cfg.state)
    yield s
    s.close()


@pytest.fixture
def job(store):
    return store.add("Initech", "Senior Security Engineer, Platform", status="queued", description=POSTING)


@pytest.fixture
def model(monkeypatch):
    """A fake local model: records what it was sent and answers with `said`."""
    seen = {"said": SAID}

    def fake(backend, system, messages, model="", max_tokens=0):
        seen.update(backend=backend, prompt="\n".join([system, *(m["content"] for m in messages)]))
        yield seen["said"]
        yield {"output_tokens": 9}

    monkeypatch.setattr(chat, "check", lambda *a: None)
    monkeypatch.setattr(chat, "reply", fake)
    return seen


@pytest.fixture
def no_model(monkeypatch):
    def down(*a):
        raise chat.ChatUnavailable("the local model server isn't running")

    monkeypatch.setattr(chat, "check", down)


def names(found):
    return [(p["name"], p["role"]) for p in found]


@pytest.mark.parametrize("text, want", [
    ("Hiring Manager: Jane Okafor", [("Jane Okafor", "manager")]),
    ("Your recruiter is Sam Lee.", [("Sam Lee", "recruiter")]),
    ("You will report to Jane Okafor, Director of Security.", [("Jane Okafor", "manager")]),
    ("Interviewers: Priya Nair, Omar Haddad and Lee Chen", [("Priya Nair", "interviewer"),
                                                          ("Omar Haddad", "interviewer"),
                                                          ("Lee Chen", "interviewer")]),
    ("Team lead - Ana Silva (Staff Engineer)", [("Ana Silva", "lead")]),
    ("Questions? Email Dana Whitaker at dana@initech.example", [("Dana Whitaker", "contact")]),
    ("Recruiter: Sam J. Lee-Park", [("Sam J. Lee-Park", "recruiter")]),
    ("Hiring Manager: Mary McDonald", [("Mary McDonald", "manager")]),
    # titles, teams and technologies are not people
    ("Reports to: Senior Director of Engineering", []),
    ("You will report to the Head of Security", []),
    ("Contact: Hiring Manager", []),
    ("Recruiter: Initech Recruiting", []),
    ("You will work with Python and Kubernetes every day", []),
    ("Our recruiter will reach out to Python developers", []),
    ("Contact: Jane Okafor. We are an Equal Opportunity Employer", [("Jane Okafor", "contact")]),
    ("Reach out to Priya", []),   # a posting needs a first and last name
    ("", []),
])
def test_the_posting_names_people_only_after_a_cue(text, want):
    assert names(outreach.people_in(text, "Initech")) == want


def test_a_title_an_email_and_a_profile_go_with_the_person():
    got = outreach.people_in("Hiring Manager: Jane Okafor, Director of Security Engineering "
                             "<jane@initech.example>, Recruiter: Sam Lee at linkedin.com/in/example-sam")
    jane, sam = got
    assert jane["title"] == "Director of Security Engineering" and jane["email"] == "jane@initech.example"
    assert sam["name"] == "Sam Lee" and sam["url"] == "linkedin.com/in/example-sam" and sam["email"] == ""
    assert jane["evidence"].startswith("Hiring Manager: Jane Okafor")


def test_a_person_named_twice_is_listed_once_with_the_most_useful_role():
    got = outreach.people_in("Interviewers: Jane Okafor and Lee Chen.\nHiring Manager: Jane Okafor")
    assert names(got) == [("Jane Okafor", "manager"), ("Lee Chen", "interviewer")]


@pytest.mark.parametrize("text, want", [
    ("Call with Dana Whitaker, the recruiter, Thursday", [("Dana Whitaker", "contact")]),
    ("Recruiter Priya Nair called; met Lee Chen and Ana on Monday", [("Priya Nair", "recruiter"),
                                                                   ("Lee Chen", "contact"), ("Ana", "contact")]),
    ("Phone screen with the team on Friday about Kubernetes", []),
    ("Call with Initech Recruiting", []),
])
def test_your_notes_may_name_just_a_first_name_and_use_a_loose_cue(text, want):
    assert names(outreach.people_in(text, "Initech", strict=False)) == want


@pytest.mark.parametrize("title, fn", [
    ("Senior Security Engineer, Platform", "Security"),
    ("Staff Machine Learning Engineer", "Machine Learning"),
    ("Principal Engineer", "Engineering"),
    ("Director of Data Platform (Remote)", "Data Platform"),
])
def test_the_function_comes_from_the_title(title, fn):
    assert outreach.function_of(title) == fn


def test_the_searches_are_links_for_you_to_open():
    links = outreach.search_links("Initech", "Senior Security Engineer")
    assert [s["kind"] for s in links] == ["manager", "recruiter", "lead", "connection"]
    assert all(s["url"].startswith("https://www.linkedin.com/search/results/people/?keywords=") for s in links)
    assert "Head%20of%20Security" in links[0]["url"] and "Initech" in links[1]["url"]


def test_who_lists_the_posting_the_notes_and_your_connections_best_first(cfg, store, job):
    other = store.add("Initech", "Data Engineer", status="applied", applied="2026-03-01",
                      note="2026-03-02: Call with Dana Whitaker, the recruiter")
    got = outreach.who(cfg, store, job.key)
    people = [(p["name"], p["source"], p["role"]) for p in got["people"]]
    assert people[:3] == [("Jane Okafor", "posting", "manager"), ("Sam Lee", "posting", "recruiter"),
                          ("Priya Nair", "posting", "interviewer")]
    assert ("Dana Whitaker", "notes", "contact") in people and ("Ana Li", "connection", "connection") in people
    assert ("Bo Chen", "connection", "recruiter") in people
    dana = next(p for p in got["people"] if p["name"] == "Dana Whitaker")
    assert "Initech: Data Engineer" in dana["why"] and "2026-03-02" in dana["why"]
    assert next(p for p in got["people"] if p["name"] == "Sam Lee")["email"] == "sam.lee@initech.example"
    assert got["has_connections"] and got["existing"] == "" and other.key != job.key
    assert all(p["name"] != "Cy Diaz" for p in got["people"])  # Globex is another company


def test_a_marked_use_connection_comes_before_names_in_the_posting_other_than_the_manager(cfg, store, job):
    from jobwatch.contacts import key_for
    store.rate_contact(key_for("https://www.linkedin.com/in/example-ana"), "use", "worked together")
    people = outreach.who(cfg, store, job.key)["people"]
    assert [p["name"] for p in people][:3] == ["Jane Okafor", "Sam Lee", "Ana Li"]
    assert "worked together" in people[2]["why"]


def test_a_person_in_the_posting_you_also_know_keeps_the_posting_role_and_your_tie(cfg, store):
    j = store.add("Initech", "Platform Engineer", status="queued", description="Recruiter: Bo Chen")
    got = outreach.who(cfg, store, j.key)["people"]
    bo = next(p for p in got if p["name"] == "Bo Chen")
    assert bo["role"] == "recruiter" and bo["source"] == "posting" and "you know them" in bo["why"]
    assert bo["url"].endswith("example-bo") and sum(p["name"] == "Bo Chen" for p in got) == 1


def test_no_one_is_made_up_when_nothing_names_anyone(cfg, store):
    j = store.add("Umbrella", "Analyst", status="queued", description="Analyze things. No names here.")
    got = outreach.who(cfg, store, j.key)
    assert got["people"] == [] and len(got["search"]) == 4


def test_an_application_already_sent_is_said_first(cfg, store):
    j = store.add("Initech", "Security Engineer", status="applied", applied="2026-03-09", description=POSTING)
    assert outreach.who(cfg, store, j.key)["existing"] == "You already applied to this job on 2026-03-09 (now applied)."
    twin = store.add("Initech", "Security Engineer", status="queued", description=POSTING)
    got = outreach.who(cfg, store, twin.key)["existing"]
    assert "already applied" in got and "refer you again" in got


def test_the_prompt_for_the_local_model_has_the_resume_and_the_rules(cfg, store, job, model):
    got = outreach.draft(cfg, store, job.key, today=TODAY)
    p = model["prompt"]
    assert got["drafted"] and got["person"]["name"] == "Jane Okafor" and got["written_by"] == "local model"
    assert got["linkedin"].startswith("Hi Jane,") and len(got["linkedin"]) <= 300
    assert got["subject"] == "The Security Engineer role at Initech" and got["body"].startswith("Hi Jane,")
    assert got["warnings"] == []
    assert "Never add the user's pronouns" in p and "Never mention pay" in p and "never invent" in p.lower()
    assert "short chat about the role" in p     # a hiring manager is asked for a chat
    assert "First name: Jane" in p and "Who they are to this job: hiring manager" in p
    assert "Ran 40 clusters on AWS" in p and "<posting>" in p and "Okafor" not in p.split("<posting>")[0]


def test_what_goes_to_claude_is_the_allowlist_and_nothing_else(cfg, store, job, monkeypatch):
    store.track(job.key, note="2026-03-02: Mentioned my pay ask of 300K")
    store.add_note(job.key, "Call with Dana Whitaker")
    path = cfg.path
    path.write_text(yaml.safe_dump({"companies": [], "state": "state.db", "resume": "resume.txt",
                                    "connections": "Connections.csv"}))   # reply.followup: claude by default
    cfg = config.load(path)
    sent = {}

    def claude(cfg, prompt):
        sent["prompt"] = prompt
        return SAID, {"backend": "claude", "model": "claude-haiku", "label": "Claude", "local": False}

    monkeypatch.setattr(followup, "_claude_text", claude)
    got = outreach.draft(cfg, store, job.key, today=TODAY)
    p = sent["prompt"]
    assert got["drafted"] and got["written_by"] == "Claude" and not got["local"]
    assert "Company: Initech" in p and "Role: Senior Security Engineer, Platform" in p and "First name: Jane" in p
    assert "Stage: not applied yet" in p
    for private in ("Okafor", "Ran 40 clusters", "Jordan", "300K", "Dana", "Equal Opportunity", "<posting>",
                    "sam.lee@initech.example", "Director of Security"):
        assert private not in p


def test_a_claude_that_cant_answer_falls_back_to_the_local_model_with_the_fuller_prompt(cfg, store, job, model):
    path = cfg.path
    path.write_text(yaml.safe_dump({"companies": [], "state": "state.db", "resume": "resume.txt"}))
    got = outreach.draft(config.load(path), store, job.key, today=TODAY)  # conftest: no Claude key in tests
    assert got["drafted"] and got["local"] and any("Claude couldn't write it" in w for w in got["warnings"])
    assert "Ran 40 clusters on AWS" in model["prompt"]


def test_a_connection_is_asked_to_refer_the_user_to_the_role(cfg, store, model):
    j = store.add("Initech", "Platform Engineer", status="queued", description="Build the platform.")
    got = outreach.draft(cfg, store, j.key, to="Ana Li", today=TODAY)
    assert got["person"]["source"] == "connection" and got["person"]["name"] == "Ana Li"
    assert "refer the user for this role" in model["prompt"] and "fine to say no" in model["prompt"]
    assert "Who they are to this job: someone you know there" in model["prompt"]


def test_a_person_you_found_yourself_is_used_as_named(cfg, store, job, model):
    got = outreach.draft(cfg, store, job.key, to="Rae Quinn", role="recruiter", today=TODAY)
    assert got["person"] == {"name": "Rae Quinn", "role": "recruiter", "title": "", "email": "", "url": "",
                             "evidence": "", "source": "you", "why": "named by you"}
    assert "First name: Rae" in model["prompt"] and "whether the role is still open" in model["prompt"]
    assert any("doesn't greet Rae" in w for w in got["warnings"])   # the fake still says Hi Jane


def test_a_person_is_picked_by_position(cfg, store, job, model):
    assert outreach.draft(cfg, store, job.key, index=1, today=TODAY)["person"]["name"] == "Sam Lee"
    with pytest.raises(ValueError, match="no person number 99"):
        outreach.draft(cfg, store, job.key, index=98)
    with pytest.raises(ValueError, match="role must be one of"):
        outreach.draft(cfg, store, job.key, role="boss")


def test_with_no_one_named_the_note_greets_hi_and_says_how_to_find_someone(cfg, store, model):
    j = store.add("Umbrella", "Analyst", status="queued", description="Analyze things.")
    model["said"] = "LINKEDIN:\nHi, I found the Analyst role at Umbrella. Could you point me to the right person?\n" \
                    "SUBJECT:\nThe Analyst role\nBODY:\nHi,\n\nI found the Analyst role at Umbrella.\n\nCould you " \
                    "point me to the right person?"
    got = outreach.draft(cfg, store, j.key, today=TODAY)
    assert got["person"] is None and got["drafted"]
    assert any("No one is named" in w and "--to NAME" in w for w in got["warnings"])
    assert "No one is named: greet with Hi," in model["prompt"]


@pytest.mark.parametrize("said, flag", [
    ("I hope this finds you well. Would you chat? Hi Jane", "stock opener"),
    ("Hi Jane, thrilled to apply! Would you chat?", "exclamation mark"),
    ("Hi Jane, I cut costs by 80% at Globex. Would you chat?", "names a figure your resume and the posting don't hold"),
    ("Hi Jane, I can do it at a lower salary. Would you chat?", "mentions pay"),
    ("Hello there. Would you chat?", "doesn't greet Jane"),
])
def test_the_code_flags_what_the_model_got_wrong_and_leaves_the_text_alone(cfg, store, job, model, said, flag):
    model["said"] = f"LINKEDIN:\n{said}\nSUBJECT:\nHello\nBODY:\n{said}"
    got = outreach.draft(cfg, store, job.key, today=TODAY)
    assert got["drafted"] and any(flag in w for w in got["warnings"]) and got["linkedin"] == said


def test_a_note_over_300_characters_is_cut_at_a_sentence_and_flagged(cfg, store, job, model):
    long = "Hi Jane, I found the role at Initech. " + "I would love to hear how the team works. " * 9 + "Chat?"
    model["said"] = f"LINKEDIN:\n{long}\nSUBJECT:\nHello\nBODY:\nHi Jane,\n\nI found the role."
    got = outreach.draft(cfg, store, job.key, today=TODAY)
    assert len(got["linkedin"]) <= 300 and got["linkedin"].endswith(".")
    assert any("ran" in w and "cut to fit 300" in w for w in got["warnings"])


def test_trim_note_cuts_at_a_word_when_there_is_no_sentence_to_stop_at():
    out = outreach.trim_note("word " * 100)
    assert len(out) <= 300 and out.endswith("…") and not out.endswith(" …")
    assert outreach.trim_note("Short note.") == "Short note."


def test_with_no_model_a_fixed_template_is_the_draft(cfg, store, job, no_model):
    got = outreach.draft(cfg, store, job.key, today=TODAY)
    assert got["drafted"] and got["written_by"] == "fixed template" and got["model"] is None
    assert got["linkedin"] == ("Hi Jane, I am interested in the Senior Security Engineer, Platform role at Initech. "
                               "Would you be open to a short chat about the role?")
    assert got["body"].startswith("Hi Jane,") and "short chat" in got["body"]
    assert any("No model" in w and "fixed template" in w for w in got["warnings"])


def test_the_template_asks_a_connection_for_a_referral_to_the_role_and_notes_an_application(cfg, store, no_model):
    j = store.add("Initech", "Platform Engineer", status="applied", applied="2026-03-09", description="x")
    got = outreach.draft(cfg, store, j.key, to="Ana Li", today=TODAY)
    assert "I found the Platform Engineer role at Initech and thought of you" in got["linkedin"]
    assert "refer me for it" in got["linkedin"] and "fine to say no" in got["linkedin"]
    assert "I have already applied." in got["body"]
    assert any("already applied" in w for w in got["warnings"])


def test_an_answer_with_no_usable_messages_falls_back_to_the_template(cfg, store, job, model):
    model["said"] = "Sure! Here you go."
    got = outreach.draft(cfg, store, job.key, today=TODAY)
    assert got["written_by"] == "fixed template" and any("no usable messages" in w for w in got["warnings"])


def test_nothing_is_sent_or_saved(cfg, store, job, model):
    outreach.draft(cfg, store, job.key, today=TODAY)
    assert store.package(job.key).data()["note"] == "" and store.find(job.key)[1]["status"] == "queued"


def test_the_command_lists_people_and_prints_the_note(cfg, job, model, capsys):
    cli.main(["-c", str(cfg.path), "contact", job.key])
    out = capsys.readouterr().out
    assert "1. Jane Okafor (hiring manager, Director of Security Engineering): named in the posting" in out
    assert "Search LinkedIn yourself (jobwatch never reads it):" in out and "linkedin.com/search" in out
    assert "Note to Jane Okafor (by local model):" in out and "LinkedIn (" in out and "Email subject:" in out
    cli.main(["-c", str(cfg.path), "contact", job.key, "--to", "Rae Quinn", "--role", "recruiter", "--format", "json"])
    got = json.loads(capsys.readouterr().out)
    assert got["person"]["name"] == "Rae Quinn" and got["drafted"]
    cli.main(["-c", str(cfg.path), "contact", job.key, "--no-draft"])
    assert "Note to" not in capsys.readouterr().out


def test_the_page_endpoints_list_then_draft_and_error_plainly(cfg, store, job, model):
    app = App(cfg.path)
    found = app.get_contact({"key": [job.key]})
    assert found["people"][0]["name"] == "Jane Okafor" and "linkedin" not in found
    got = app.post_contact({"key": job.key, "index": 1})
    assert got["person"]["name"] == "Sam Lee" and got["drafted"]
    with pytest.raises(ApiError, match="no job"):
        app.post_contact({"key": "nope"})
    with pytest.raises(ApiError, match="role must be one of"):
        app.post_contact({"key": job.key, "role": "boss"})
    with pytest.raises(ApiError, match="index"):
        app.post_contact({"key": job.key, "index": "x"})


def test_the_mcp_tool_drafts_and_says_it_sends_nothing(cfg, store, job, model, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    monkeypatch.setattr(mcp, "_open", lambda: (cfg, Store(cfg.state)))
    got = mcp.find_contact(job.key, to="Rae Quinn")
    assert got["person"]["name"] == "Rae Quinn" and got["drafted"] and got["search"]
    assert "nothing is sent" in mcp.find_contact.__doc__
    listed = mcp.find_contact(job.key, draft=False)
    assert listed["people"][0]["name"] == "Jane Okafor" and "linkedin" not in listed
    with pytest.raises(mcp.ToolError, match="no job"):
        mcp.find_contact("nope")
