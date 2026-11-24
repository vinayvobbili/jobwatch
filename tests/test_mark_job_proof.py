"""mark_job asks for proof of submission (an MCP elicitation) before it records a job as applied."""

import asyncio

import pytest
from mcp.client import Client
from mcp.types import ElicitResult

from jobwatch.store import Store

mcp = pytest.importorskip("jobwatch.mcp_server")

KEY = "manual:initech:field-engineer"
# The negotiation: the handshake of 2025-11-25 and before asks mid-call, 2026-07-28 and after asks in a retry round.
MODES = ["legacy", "2026-07-28"]


@pytest.fixture
def queued(watchlist, monkeypatch):
    monkeypatch.setattr(mcp, "_changed_since_start", lambda: None)
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    mcp.add_application("Initech", "Field Engineer", status="queued")
    return watchlist


def record(watchlist):
    cfg = mcp.config.load(str(watchlist))
    store = Store(cfg.state)
    try:
        return store.find(KEY)[1]
    finally:
        store.close()


def call(args, answer=None, mode="legacy"):
    """Call mark_job through a client; answer is what the person picks in the form (None: a client that can't
    ask). Returns the reply's text and the forms the server showed."""
    shown = []

    async def respond(context, params):
        shown.append(params)
        return answer

    async def run():
        async with Client(mcp.server, elicitation_callback=respond if answer else None, mode=mode) as client:
            result = await client.call_tool("mark_job", {"key": KEY, **args})
            return result.content[0].text

    return asyncio.run(run()), shown


def accept(proof, note=None):
    return ElicitResult(action="accept", content={"proof": proof, **({"note": note} if note else {})})


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("proof, note", [("confirmation page seen", None),
                                         ("confirmation email seen", "Subject: Thanks for applying to Initech")])
def test_a_confirmed_application_is_recorded_with_its_proof(queued, mode, proof, note):
    text, shown = call({"status": "applied"}, accept(proof, note), mode)
    assert text == f"{KEY}: applied"
    assert record(queued)["status"] == "applied"
    assert f"Applied: {proof}" + (f" ({note})" if note else "") in record(queued)["note"]
    form = shown[0]
    assert "confirmation page or email" in form.message
    assert form.requested_schema["required"] == ["proof"]
    assert form.requested_schema["properties"]["proof"]["enum"] == [
        "confirmation page seen", "confirmation email seen", "not yet"]
    assert "note" in form.requested_schema["properties"]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("answer, why", [
    (ElicitResult(action="decline"), "declined"),
    (ElicitResult(action="cancel"), "cancelled"),
    (accept("not yet"), "has not seen a confirmation"),
])
def test_without_proof_nothing_is_recorded(queued, mode, answer, why):
    text, shown = call({"status": "applied", "add_note": "Recruiter Ana."}, answer, mode)
    assert "not marked applied" in text and why in text and "queued" in text
    assert len(shown) == 1
    after = record(queued)
    assert after["status"] == "queued" and "Recruiter Ana." not in (after["note"] or "")


@pytest.mark.parametrize("mode", MODES)
def test_a_client_that_cannot_ask_still_records_it_with_a_warning(queued, mode):
    text, shown = call({"status": "applied"}, mode=mode)
    assert text.startswith(f"{KEY}: applied") and "Warning: proof of submission was not confirmed" in text
    assert shown == [] and record(queued)["status"] == "applied"


def test_the_person_having_seen_proof_skips_the_question(queued):
    text, shown = call({"status": "applied", "proof_seen": True}, accept("not yet"))
    assert text == f"{KEY}: applied" and shown == []
    assert record(queued)["status"] == "applied"


def test_a_job_already_applied_to_is_not_asked_again(queued):
    call({"status": "applied"}, accept("confirmation page seen"))
    text, shown = call({"status": "applied", "add_note": "Recruiter Ana."}, accept("not yet"))
    assert text == f"{KEY}: applied" and shown == []
    assert "Recruiter Ana." in record(queued)["note"]


@pytest.mark.parametrize("status", ["screening", "skipped", "queued", None])
def test_other_statuses_are_not_asked(queued, status):
    text, shown = call({"status": status, "add_note": "Recruiter Ana."} if status else {"add_note": "Hi."},
                       accept("not yet"))
    assert text == f"{KEY}: {status or 'queued'}" and shown == []


def test_called_directly_it_behaves_as_before(queued):
    assert mcp.mark_job(KEY, "applied").endswith(": applied")
