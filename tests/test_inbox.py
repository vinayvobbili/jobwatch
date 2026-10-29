"""Status updates from application emails: each kind classified, matched to an application by sender, name, req id
or title, proposed (never applied by itself), forward only; the CLI's apply loop and the MCP tool. No network."""

import json
from pathlib import Path

import pytest

from jobwatch import alerts, cli, inbox
from jobwatch.store import Store

FIXTURES = Path(__file__).parent / "fixtures" / "inbox"


def mail(name):
    return alerts.message((FIXTURES / name).read_bytes())


def tracked(store):
    """Applications at the fictional companies the fixture emails are from."""
    store.add("Acme Robotics", "Senior Platform Engineer", "https://job-boards.greenhouse.io/acmerobotics/jobs/4012345",
              "applied", applied="2026-09-28")
    store.add("Globex", "Machine Learning Engineer", "https://jobs.lever.co/globex/aaaa-1111", "applied",
              follow_up="2026-10-20")
    store.add("Initech", "Data Engineer (482913)", status="applied")
    store.add("Initech", "Staff Data Engineer", status="applied")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state.db")
    tracked(s)
    yield s
    s.close()


def one(store, name):
    r = inbox.propose(store, [mail(name)])
    assert len(r.proposals) == 1, inbox.summary(r)
    return r.proposals[0]


# -- Each kind of email

@pytest.mark.parametrize("name, kind, suggested, phrase", [
    ("rejection_lever.eml", "rejection", "rejected", "decided to move forward with other candidates"),
    ("interview_scheduling.eml", "interview", "interviewing", "invite you to a video interview"),
    ("assessment_workday.eml", "assessment", "screening", "take-home assignment"),
    ("offer.eml", "offer", "offer", "pleased to offer you the position"),
])
def test_each_kind_is_classified_and_quoted(store, name, kind, suggested, phrase):
    email = inbox.read(mail(name))
    assert (email.kind, email.status) == (kind, suggested)
    assert phrase in email.phrase


def test_a_confirmation_that_mentions_a_possible_interview_is_still_a_confirmation():
    email = inbox.read(mail("confirmation_greenhouse.eml"))
    assert (email.kind, email.status) == ("confirmation", "applied")


def test_a_scheduling_link_alone_says_interview():
    msg = alerts.message("<html><body><p>Hello, my calendar: <a href='https://calendly.com/pat-example/30'>"
                         "book</a></p></body></html>")
    email = inbox.read(msg)
    assert (email.kind, email.phrase) == ("interview", "a link to calendly.com")


def test_a_recruiter_call_is_a_screening_not_an_interview():
    msg = alerts.message("Subject: Intro call\nFrom: Pat Example <pat@acmerobotics.example>\n\n"
                         "I'd like to schedule a quick intro call with you this week.\n")
    assert inbox.read(msg).status == "screening"


def test_an_email_about_nothing_is_other():
    assert inbox.read(mail("newsletter.eml")).kind == "other"
    assert inbox.read(mail("recruiter_reply.eml")).kind == "other"


def test_a_rejection_that_wont_invite_you_to_the_next_round_with_a_curly_apostrophe():
    msg = alerts.message("Subject: Thank you for your application to Initech\nFrom: no-reply@initech.example\n"
                         "Date: 2026-10-27T12:30:15Z\n\nWe received a large number of applications, and after "
                         "carefully reviewing all of them, unfortunately, we have to inform you that this time we "
                         "won’t be able to invite you to the next round of our hiring process.\n".encode())
    email = inbox.read(msg)
    assert (email.kind, email.status, email.date) == ("rejection", "rejected", "2026-10-27")


def test_rejection_beats_the_interview_it_mentions(store):
    assert one(store, "rejection_lever.eml").kind == "rejection"


# -- Proposals

def test_an_interview_invitation_proposes_interviewing_with_a_dated_note(store):
    p = one(store, "interview_scheduling.eml")
    assert (p.company, p.current, p.suggested) == ("Acme Robotics", "applied", "interviewing")
    assert p.note == '2026-10-06: interview email: "invite you to a video interview"'
    assert p.next_step == "Schedule the interview"
    assert p.email.to_dict() == {"date": "2026-10-06", "sender": "Pat Example <pat@acmerobotics.example>",
                                 "subject": "Interview invitation: Senior Platform Engineer"}
    assert p.confidence == "high" and "sender" in p.why and "title" in p.why


def test_a_rejection_clears_the_next_step_and_follow_up(store):
    store.track("manual:globex:machine-learning-engineer", next_step="Wait for the recruiter")
    p = one(store, "rejection_lever.eml")
    assert (p.key, p.suggested, p.next_step) == ("manual:globex:machine-learning-engineer", "rejected", "")
    inbox.apply(store, p)
    _, rec = store.find(p.key)
    assert (rec["status"], rec["next_step"], rec["follow_up"]) == ("rejected", None, None)
    assert rec["note"].startswith("2026-10-12: rejection email:")


def test_an_offer_proposes_offer(store):
    p = one(store, "offer.eml")
    assert (p.current, p.suggested, p.next_step) == ("applied", "offer", "Review the offer")


def test_an_existing_next_step_is_kept(store):
    store.track("manual:acme-robotics:senior-platform-engineer", next_step="Recruiter call Tuesday")
    p = one(store, "interview_scheduling.eml")
    assert p.next_step is None
    inbox.apply(store, p)
    assert store.find(p.key)[1]["next_step"] == "Recruiter call Tuesday"


def test_a_recruiter_reply_is_a_note_only(store):
    p = one(store, "recruiter_reply.eml")
    assert (p.kind, p.suggested) == ("other", None)
    assert p.note == '2026-10-08: recruiter email from Pat Example: "Quick question"'


def test_a_confirmation_moves_a_queued_job_to_applied(tmp_path):
    store = Store(tmp_path / "state.db")
    store.add("Acme Robotics", "Senior Platform Engineer", "https://job-boards.greenhouse.io/acmerobotics/jobs/4012345",
              "queued")
    p = one(store, "confirmation_greenhouse.eml")
    assert (p.current, p.suggested) == ("queued", "applied")
    inbox.apply(store, p)
    rec = store.find(p.key)[1]
    assert (rec["status"], rec["applied_at"]) == ("applied", "2026-10-02")


# -- Matching

def test_matches_by_sender_domain_display_name_and_ats_mailbox(store):
    assert one(store, "interview_scheduling.eml").company == "Acme Robotics"  # the domain
    assert "sender" in one(store, "rejection_lever.eml").why                  # the display name, behind an ATS
    assert one(store, "assessment_workday.eml").company == "Initech"          # the ATS mailbox name


def test_matches_by_the_company_named_in_the_body(store):
    msg = alerts.message("Subject: Application update\nFrom: Pat Example <pat@mail.example.org>\n\n"
                         "We have decided to move forward with other candidates for the Senior Platform "
                         "Engineer position at Acme Robotics.\n")
    r = inbox.propose(store, [msg])
    assert r.proposals[0].company == "Acme Robotics" and "body" in r.proposals[0].why


def test_matches_by_req_id_among_several_applications_at_a_company(store):
    p = one(store, "assessment_workday.eml")
    assert p.key == "manual:initech:data-engineer-482913"
    assert "req or posting id" in p.why


def test_matches_a_bare_body_by_its_body_and_the_id_in_brackets(store):
    r = inbox.propose(store, [alerts.message((FIXTURES / "body_only.html").read_text())])
    assert r.nothing_new and r.nothing_new[0]["key"] == "manual:initech:data-engineer-482913"


def test_several_applications_and_nothing_to_tell_them_apart_is_unmatched(store):
    r = inbox.propose(store, [mail("ambiguous_initech.eml")])
    assert not r.proposals
    assert r.unmatched[0].company == "Initech"
    assert "2 applications" in r.unmatched[0].reason and "staff-data-engineer" in r.unmatched[0].reason


def test_an_untracked_company_is_unmatched_with_the_company_and_title_it_guessed(store):
    r = inbox.propose(store, [mail("unmatched_confirmation.eml")])
    assert not r.proposals
    (u,) = r.unmatched
    assert (u.company, u.title, u.suggested) == ("Hooli", "Backend Engineer", "applied")


def test_a_mention_of_a_company_alone_is_not_enough(store):
    msg = alerts.message("Subject: Newsletter\nFrom: News <news@example.com>\n\n"
                         "Globex and Acme Robotics were in the news. We have decided to move forward with other "
                         "candidates for our own team.\n")
    r = inbox.propose(store, [msg])
    assert not r.proposals and len(r.unmatched) == 1


def test_emails_that_are_none_of_the_kinds_are_counted(store):
    r = inbox.propose(store, [mail("newsletter.eml")])
    assert (r.other, r.proposals, r.unmatched) == (1, [], [])


# -- Forward only

def test_a_late_confirmation_does_not_move_an_interviewing_application_back(store):
    store.set_status(["manual:acme-robotics:senior-platform-engineer"], "interviewing")
    r = inbox.propose(store, [mail("confirmation_greenhouse.eml")])
    assert not r.proposals
    assert r.nothing_new[0]["why"] == "already interviewing"


def test_an_assessment_after_interviewing_is_a_note_not_a_move_back(store):
    store.set_status(["manual:initech:data-engineer-482913"], "interviewing")
    p = one(store, "assessment_workday.eml")
    assert (p.current, p.suggested) == ("interviewing", None)


def test_an_email_about_an_ended_application_is_a_note_at_most(store):
    store.set_status(["manual:globex:machine-learning-engineer"], "rejected")
    p = one(store, "offer.eml")
    assert (p.suggested, p.current) == (None, "rejected")
    assert "already rejected" in p.why
    assert not inbox.propose(store, [mail("rejection_lever.eml")]).proposals


def test_apply_rechecks_the_stage(store):
    p = one(store, "interview_scheduling.eml")
    store.set_status([p.key], "offer")
    assert inbox.apply(store, p).endswith("noted (offer)")
    assert store.find(p.key)[1]["status"] == "offer"


def test_emails_in_one_batch_are_read_in_date_order(store):
    r = inbox.propose(store, [mail("interview_scheduling.eml"), mail("recruiter_reply.eml"),
                              mail("confirmation_greenhouse.eml")])
    assert [(p.kind, p.current) for p in r.proposals] == [("interview", "applied"), ("other", "interviewing")]
    assert [x["kind"] for x in r.nothing_new] == ["confirmation"]


def test_a_proposal_already_in_the_note_is_not_proposed_again(store):
    p = one(store, "interview_scheduling.eml")
    inbox.apply(store, p)
    r = inbox.propose(store, [mail("interview_scheduling.eml")])
    assert not r.proposals and r.nothing_new[0]["why"] == "already in the note"


def test_proposing_changes_nothing(store):
    before = store.jobs(include_closed=True)
    inbox.propose(store, [mail(f.name) for f in sorted(FIXTURES.glob("*.eml"))])
    assert store.jobs(include_closed=True) == before


# -- The command line

def run(capsys, watchlist, *argv):
    cli.main(["-c", str(watchlist), "inbox", *argv])
    return capsys.readouterr().out


@pytest.fixture
def mine(watchlist):
    s = Store(watchlist.parent / "state.db")
    tracked(s)
    s.close()
    return watchlist


def status(watchlist, key):
    s = Store(watchlist.parent / "state.db")
    try:
        return s.find(key)[1]
    finally:
        s.close()


def test_cli_prints_proposals_and_records_nothing(mine, capsys):
    out = run(capsys, mine, str(FIXTURES))
    assert "applied -> interviewing" in out and "Not matched to an application" in out
    assert "Nothing is recorded" in out
    assert status(mine, "manual:globex:machine-learning-engineer")["status"] == "applied"


def test_cli_apply_asks_about_each_proposal(mine, capsys, monkeypatch):
    answers = iter(["y", "n", "y", "y", "n"])
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt: asked.append(prompt) or next(answers))
    out = run(capsys, mine, str(FIXTURES), "--apply")
    assert len(asked) == 5 and "Record this for manual:acme-robotics:senior-platform-engineer? [y/N]" in asked[0]
    assert out.count(" -> ") >= 2
    assert status(mine, "manual:acme-robotics:senior-platform-engineer")["status"] == "interviewing"
    assert status(mine, "manual:initech:data-engineer-482913")["status"] == "applied"  # said no: nothing changed


def test_cli_yes_records_every_proposal(mine, capsys):
    run(capsys, mine, str(FIXTURES / "rejection_lever.eml"), str(FIXTURES / "interview_scheduling.eml"), "--yes")
    assert status(mine, "manual:globex:machine-learning-engineer")["status"] == "rejected"
    rec = status(mine, "manual:acme-robotics:senior-platform-engineer")
    assert rec["status"] == "interviewing" and rec["next_step"] == "Schedule the interview"
    assert "2026-10-06: interview email:" in rec["note"]


def test_cli_json(mine, capsys):
    out = json.loads(run(capsys, mine, str(FIXTURES / "offer.eml"), "--format", "json"))
    assert out["proposals"][0]["mark_job"] == {"key": "manual:globex:machine-learning-engineer",
                                               "add_note": out["proposals"][0]["note"], "status": "offer",
                                               "next_step": "Review the offer"}


def test_cli_needs_emails_and_cannot_ask_on_stdin(mine):
    with pytest.raises(SystemExit, match="give the emails"):
        cli.main(["-c", str(mine), "inbox"])
    with pytest.raises(SystemExit, match="nowhere to ask"):
        cli.main(["-c", str(mine), "inbox", "-", "--apply"])


def test_cli_reads_stdin(mine, capsys, monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO((FIXTURES / "offer.eml").read_text()))
    assert "applied -> offer" in run(capsys, mine, "-")


# -- The MCP tool

def test_mcp_tool_proposes_and_changes_nothing(mine, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    monkeypatch.setenv("JOBWATCH_CONFIG", str(mine))
    out = mcp.read_status_emails([(FIXTURES / n).read_text() for n in ("rejection_lever.eml", "newsletter.eml",
                                                                         "unmatched_confirmation.eml")])
    assert [p["suggested_status"] for p in out["proposals"]] == ["rejected"]
    assert out["proposals"][0]["mark_job"]["status"] == "rejected"
    assert out["proposals"][0]["mark_job"]["follow_up"] == ""
    assert out["unmatched"][0]["company"] == "Hooli" and out["other"] == 1
    assert status(mine, "manual:globex:machine-learning-engineer")["status"] == "applied"


def test_mcp_tool_says_to_confirm_before_mark_job():
    mcp = pytest.importorskip("jobwatch.mcp_server")
    doc = mcp.read_status_emails.__doc__
    assert "only call mark_job for the ones they confirm" in doc
