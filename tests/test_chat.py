import json
import sys
import types

import pytest

from jobwatch import chat
from jobwatch.web import App

from .conftest import TOKEN, request


@pytest.fixture
def fake_model(monkeypatch):
    """Stands in for Claude or the local model: records what it was sent, answers in two pieces."""
    seen = {}

    def reply(backend, system, messages):
        seen.update(backend=backend, system=system, messages=messages)
        yield {"status": "Waiting for a fit score to finish"}
        yield "Hello"
        yield ", there."
        yield {"input_tokens": 900, "output_tokens": 4}
    monkeypatch.setattr(chat, "check", lambda backend: None)
    monkeypatch.setattr(chat, "reply", reply)
    return seen


def test_clean_keeps_a_well_formed_conversation():
    msgs = [{"role": "assistant", "content": "hi"}, {"role": "user", "content": " a "},
            {"role": "user", "content": "b"}, {"role": "assistant", "content": ""}]
    with pytest.raises(ValueError, match="last message"):
        chat.clean(msgs[:1])
    assert chat.clean(msgs) == [{"role": "user", "content": "a\n\nb"}]
    for bad in (None, [], [{"role": "system", "content": "x"}], [{"role": "user", "content": 3}]):
        with pytest.raises(ValueError):
            chat.clean(bad)


def test_backends_say_what_is_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    # Whether or not the SDK is installed here: first as if it were, then as if it weren't.
    monkeypatch.setitem(sys.modules, "anthropic", types.ModuleType("anthropic"))
    with pytest.raises(chat.ChatUnavailable, match="ANTHROPIC_API_KEY"):
        chat.check("claude")
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(chat.ChatUnavailable, match=r"jobwatch\[score\]"):
        chat.check("claude")
    with pytest.raises(chat.ChatUnavailable, match="unknown"):
        chat.check("gpt")
    assert chat.where("claude")["local"] is False and chat.where("local")["local"] is True


def test_home_chat_sees_todays_jobs_and_applications(watchlist, web, fake_model):
    app = App(watchlist)
    app.post_fetch({})
    app.post_track({"key": "c1", "status": "applied", "follow_up": "2000-01-01", "next_step": "ping the recruiter"})
    info, pieces = app.chat({"messages": [{"role": "user", "content": "What should I do first?"}]})
    assert "".join(p for p in pieces if isinstance(p, str)) == "Hello, there."
    assert info["backend"] == fake_model["backend"]
    system = fake_model["system"]
    assert "Today's matching jobs" in system and "Staff AI Engineer: applied" in system
    assert "follow up 2000-01-01 (due)" in system and "ping the recruiter" in system
    assert "Never invent experience" in system and "Not added yet" in system  # no resume in this watchlist
    assert fake_model["messages"] == [{"role": "user", "content": "What should I do first?"}]


def test_job_chat_sees_the_posting_as_data(watchlist, web, fake_model):
    app = App(watchlist)
    app.post_fetch({})
    (watchlist.parent / "cv.md").write_text("Built RAG systems.")
    app.post_settings({"resume": "cv.md"})
    _, pieces = app.chat({"key": "c1", "messages": [{"role": "user", "content": "Do I fit?"}]})
    list(pieces)
    system = fake_model["system"]
    assert "<posting>\n# Staff AI Engineer" in system and "Today's matching jobs" not in system
    assert "<resume>\nBuilt RAG systems.\n</resume>" in system and "Not scored" in system
    with pytest.raises(KeyError):
        app.chat({"key": "nope", "messages": [{"role": "user", "content": "?"}]})


def lines(data: bytes) -> list[dict]:
    return [json.loads(line) for line in data.decode().splitlines()]


def test_chat_streams_lines(server, fake_model):
    ok = {"X-Jobwatch-Token": TOKEN}
    request(server, "POST", "/api/fetch", {}, headers=ok)
    status, data = request(server, "POST", "/api/chat", {"messages": [{"role": "user", "content": "hi"}]}, headers=ok)
    out = lines(data)
    assert status == 200 and "info" in out[0] and out[2]["text"] == "Hello"
    assert [o for o in out if "text" in o] == [{"text": "Hello"}, {"text": ", there."}]
    assert out[1] == {"status": "Waiting for a fit score to finish"}
    stats = out[-1]["stats"]
    assert out[-1]["done"] and (stats["input_tokens"], stats["output_tokens"]) == (900, 4)
    assert stats["model"] and stats["seconds"] >= stats["first_seconds"] >= 0 and "tokens_per_sec" in stats
    assert request(server, "POST", "/api/chat", {"messages": []}, headers=ok)[0] == 400
    assert request(server, "POST", "/api/chat", {"messages": [{"role": "user", "content": "hi"}]})[0] == 403
    status, data = request(server, "GET", "/api/chat", headers=ok)
    assert status == 200 and "label" in json.loads(data)


def test_a_failed_reply_ends_with_an_error_line(server, monkeypatch):
    def broken(backend, system, messages):
        yield "Partial"
        raise RuntimeError("model fell over")
    monkeypatch.setattr(chat, "check", lambda backend: None)
    monkeypatch.setattr(chat, "reply", broken)
    status, data = request(server, "POST", "/api/chat", {"messages": [{"role": "user", "content": "hi"}]},
                           headers={"X-Jobwatch-Token": TOKEN})
    assert status == 200 and lines(data)[-1] == {"error": "RuntimeError: model fell over"}


def test_ask_from_the_command_line(watchlist, web, fake_model, capsys, monkeypatch):
    from jobwatch import cli

    cli.main(["-c", str(watchlist), "fetch"])
    cli.main(["-c", str(watchlist), "ask", "Do", "I", "fit?", "--job", "c1"])
    out = capsys.readouterr()
    assert out.out.endswith("Hello, there.\n") and "<posting>" in fake_model["system"]
    assert "(Waiting for a fit score to finish…)" in out.err and "4 tokens out · 900 in" in out.err
    assert fake_model["messages"] == [{"role": "user", "content": "Do I fit?"}]
    monkeypatch.setattr(chat, "check", lambda backend: (_ for _ in ()).throw(chat.ChatUnavailable("no model")))
    with pytest.raises(SystemExit, match="no model"):
        cli.main(["-c", str(watchlist), "ask", "hi"])
