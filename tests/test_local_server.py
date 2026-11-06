"""The local chat backend talks to a shared OpenAI-compatible model server: tested against a fake one."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from jobwatch import ai, chat


class Fake:
    """What the fake server was asked and what it answers with; the tests set the answers."""

    def __init__(self):
        self.requests = []  # (method, path, parsed body)
        self.models_status = 200
        self.completion_status = 200
        self.error_body = b""
        self.pieces = ["Initech ", "wants ", "Python."]
        self.usage = {"prompt_tokens": 120, "completion_tokens": 3}
        self.tail = []  # raw SSE lines after the pieces, before [DONE]


@pytest.fixture
def server(monkeypatch):
    fake = Fake()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, status, body, kind="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            fake.requests.append(("GET", self.path, None))
            self._send(fake.models_status, json.dumps({"data": [{"id": "tiny-model"}]}).encode())

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            fake.requests.append(("POST", self.path, body))
            if fake.completion_status != 200:
                return self._send(fake.completion_status, fake.error_body)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            events = [{"choices": [{"delta": {"content": p}}]} for p in fake.pieces]
            events.append({"choices": [], "usage": fake.usage})
            for event in events:
                self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
                self.wfile.flush()
            for line in fake.tail:
                self.wfile.write(line.encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setenv("LOCAL_LLM_URL", f"http://127.0.0.1:{httpd.server_port}/v1")
    yield fake
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def nothing_listening(monkeypatch):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = httpd.server_port
    httpd.server_close()  # the port is free again: connecting is refused
    monkeypatch.setenv("LOCAL_LLM_URL", f"http://127.0.0.1:{port}/v1")
    return port


def ask(**kw):
    return list(chat.reply("local", "You are Globex's assistant.", [{"role": "user", "content": "Hi"}], **kw))


def test_the_reply_streams_in_pieces_and_the_stats_come_last(server):
    out = ask(max_tokens=77)
    assert out == ["Initech ", "wants ", "Python.", {"input_tokens": 120, "output_tokens": 3}]
    assert chat.stats_line(out[-1]) == "3 tokens out · 120 in"


def test_the_request_names_no_model_and_carries_the_system_message(server):
    ask(model="mlx-community/Some-Model", max_tokens=77)  # a model set in the config isn't sent on
    (method, path, body), = server.requests
    assert (method, path) == ("POST", "/v1/chat/completions")
    assert body["model"] == "local" and body["stream"] is True and body["max_tokens"] == 77
    assert body["stream_options"] == {"include_usage": True}
    assert body["messages"] == [{"role": "system", "content": "You are Globex's assistant."},
                                {"role": "user", "content": "Hi"}]


def test_a_503_surfaces_the_servers_message(server):
    server.completion_status = 503
    server.error_body = json.dumps({"error": {"message": "not enough memory to load the model"}}).encode()
    with pytest.raises(chat.ChatUnavailable, match="not enough memory to load the model"):
        ask()


def test_an_error_that_is_not_json_still_says_what_happened(server):
    server.completion_status = 500
    server.error_body = b"<html>oops</html>"
    with pytest.raises(chat.ChatUnavailable, match="500"):
        ask()


def test_an_error_in_the_stream_is_raised(server):
    server.tail = ['data: {"error": {"message": "the model was unloaded"}}']
    with pytest.raises(chat.ChatUnavailable, match="the model was unloaded"):
        ask()


def test_nothing_listening_says_where_to_look(nothing_listening):
    with pytest.raises(chat.ChatUnavailable, match=r"no local model server at http://127\.0\.0\.1:") as e:
        ask()
    assert "set LOCAL_LLM_URL" in str(e.value)


def test_the_default_address_is_the_shared_server(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_URL", raising=False)
    assert chat.local_url() == "http://127.0.0.1:8010/v1"
    monkeypatch.setenv("LOCAL_LLM_URL", "http://127.0.0.1:9999/v1/")
    assert chat.local_url() == "http://127.0.0.1:9999/v1"


def test_the_precheck_passes_when_the_server_answers_and_asks_for_models_only(server):
    chat.check("local")
    assert server.requests == [("GET", "/v1/models", None)]  # no completion: the model isn't loaded for it
    assert ai.local_server_up() is True


def test_the_precheck_fails_when_nothing_answers(nothing_listening):
    with pytest.raises(chat.ChatUnavailable, match="no local model server"):
        chat.check("local")
    assert ai.local_server_up() is False


def test_the_precheck_fails_when_the_server_errors(server):
    server.models_status = 500
    with pytest.raises(chat.ChatUnavailable, match="500"):
        chat.check("local")
