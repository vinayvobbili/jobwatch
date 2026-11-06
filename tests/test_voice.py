"""The voice mock interview: audio forwarded to the speech-to-text server, how an answer was delivered (counted in
code), the order of questions, the report and what is kept. The speech server is a stub on a free port and the chat
model is always a fake."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from jobwatch import config, mock, speech
from jobwatch.web import ApiError, App

from .conftest import TOKEN, request
from .test_mock import fake_model, setup  # noqa: F401  (the fixtures)

WORDS = "alerts " * 150
ANSWERS = [{"question": "Why Initech?", "answer": "I built a Python service that groups alerts.", "seconds": 30},
           {"question": "Tell me about on-call.", "answer": "I cut pages from 120 to 35 a week by grouping them.",
            "seconds": 75}]
REPORT_REPLY = """LANDED:
- Clear ownership of the alert service.
GAPS:
- Nothing on Kubernetes (A3).
OPPORTUNITIES:
1. Add a real example of Kubernetes work.
2. Say the result: pages fell from 120 to 35 a week.
3. Cut the filler words.
ANSWER 1:
Strong: A concrete service.
Missing: The outcome.
ANSWER 2:
Strong: A number.
Missing: Which team.
"""


class Stub:
    """A speech-to-text server on a free port: what it was sent, and what it answers (status, body)."""

    def __init__(self):
        self.sent = []
        self.answer = (200, {"text": " I own detection. ", "duration": 4.5, "segments": [{"id": 0}]})
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                stub.sent.append((self.path, self.headers["Content-Type"], body))
                status, data = stub.answer
                out = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *args):
                pass
        self.http = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.http.server_address[1]}/v1/audio/transcriptions"


@pytest.fixture
def stt(monkeypatch):
    stub = Stub()
    monkeypatch.setenv("LOCAL_STT_URL", stub.url)
    yield stub
    stub.http.shutdown()
    stub.http.server_close()


def test_audio_is_forwarded_as_the_openai_audio_api_and_the_words_come_back(stt, tmp_path):
    got = speech.transcribe(b"RIFFfake-audio", "audio/webm", "answer.webm")
    assert got == {"text": "I own detection.", "duration": 4.5, "segments": [{"id": 0}]}
    path, ctype, body = stt.sent[0]
    assert path == "/v1/audio/transcriptions" and ctype.startswith("multipart/form-data; boundary=")
    assert b'name="response_format"\r\n\r\nverbose_json' in body
    assert b'name="file"; filename="answer.webm"' in body and b"RIFFfake-audio" in body
    assert list(tmp_path.rglob("*.webm")) == []  # the audio is held in memory only
    with pytest.raises(ValueError):
        speech.transcribe(b"")


def test_transcribe_command_prints_the_words_and_how_they_were_said(stt, tmp_path, capsys):
    from jobwatch import cli

    memo = tmp_path / "practice.m4a"
    memo.write_bytes(b"fake-m4a")
    stt.answer = (200, {"text": "Um, at Initech I, um, rebuilt the queue.", "duration": 3.0, "segments": []})
    cli.main(["transcribe", str(memo)])
    out, err = capsys.readouterr()
    assert out.strip() == "Um, at Initech I, um, rebuilt the queue."
    assert "3 seconds, 8 words, 160 words a minute; um x2" in err and "To change:" in err
    assert b'filename="practice.m4a"' in stt.sent[0][2] and b"Content-Type: audio/mp4" in stt.sent[0][2]
    stt.answer = (503, {"error": {"message": "memory is short"}})
    with pytest.raises(SystemExit, match="jobwatch: "):
        cli.main(["transcribe", str(memo)])
    with pytest.raises(SystemExit, match="no such recording"):
        cli.main(["transcribe", str(tmp_path / "missing.webm")])


def test_the_speech_url_follows_the_local_model_server(monkeypatch):
    monkeypatch.delenv("LOCAL_STT_URL", raising=False)
    monkeypatch.setenv("LOCAL_LLM_URL", "http://127.0.0.1:9999/v1/")
    assert speech.speech_url() == "http://127.0.0.1:9999/v1/audio/transcriptions"
    monkeypatch.delenv("LOCAL_LLM_URL")
    assert speech.speech_url() == "http://127.0.0.1:8010/v1/audio/transcriptions"
    monkeypatch.setenv("LOCAL_STT_URL", "http://127.0.0.1:1/x")
    assert speech.speech_url() == "http://127.0.0.1:1/x"


def test_a_busy_server_is_a_clean_503_and_other_trouble_is_a_502(stt, setup):  # noqa: F811
    _, _, path, _ = setup
    app = App(path)
    stt.answer = (503, {"error": {"message": "not enough memory"}})
    with pytest.raises(ApiError) as e:
        app.mock_transcribe(b"audio", "audio/webm", "a.webm")
    assert e.value.status == 503 and "not enough memory" in str(e.value) and "type your answer" in str(e.value)
    stt.answer = (500, {"error": "boom"})
    with pytest.raises(ApiError) as e:
        app.mock_transcribe(b"audio", "audio/webm", "a.webm")
    assert e.value.status == 502 and "boom" in str(e.value)
    with pytest.raises(ApiError, match="no audio"):
        app.mock_transcribe(b"", "audio/webm", "a.webm")


def test_a_server_that_is_down_says_so_and_offers_typing(monkeypatch, setup):  # noqa: F811
    _, _, path, _ = setup
    monkeypatch.setenv("LOCAL_STT_URL", "http://127.0.0.1:9/v1/audio/transcriptions")  # nothing listens on 9
    with pytest.raises(ApiError) as e:
        App(path).mock_transcribe(b"audio", "audio/webm", "a.webm")
    assert e.value.status == 503 and "no speech-to-text server" in str(e.value) and "Type your answer" in str(e.value)


def test_transcribe_over_http_forwards_the_recording_and_passes_503_through(server, stt):
    ok = {"X-Jobwatch-Token": TOKEN, "Content-Type": "audio/webm;codecs=opus"}
    status, data = request(server, "POST", "/api/mock/transcribe?name=answer.webm", raw=b"fake-audio", headers=ok)
    assert status == 200 and json.loads(data)["text"] == "I own detection."
    assert b"fake-audio" in stt.sent[0][2] and b"audio/webm;codecs=opus" in stt.sent[0][2]
    stt.answer = (503, {"error": {"message": "short of memory"}})
    status, data = request(server, "POST", "/api/mock/transcribe?name=answer.webm", raw=b"fake-audio", headers=ok)
    assert status == 503 and "short of memory" in json.loads(data)["error"]
    assert request(server, "POST", "/api/mock/transcribe", raw=b"x")[0] == 403  # needs the page's token


def test_delivery_counts_pace_fillers_and_length_in_code():
    said = ("Um so basically I built a service, you know, that groups alerts and uh sort of pages less, "
            "like a lot less.")
    short = mock.delivery({"question": "Q", "answer": said, "seconds": 30})
    assert short["words"] == 22 and short["wpm"] == 44 and short["length"] == "short"
    assert short["fillers"] == {"um": 1, "basically": 1, "you know": 1, "uh": 1, "sort of": 1, "like": 1}
    assert short["filler_count"] == 6
    assert "under the 60 to 90 second target (30 seconds)" in short["flag"] and "only 22 words" in short["flag"]
    assert "6 filler words" in short["flag"] and "slow, 44 words a minute" in short["flag"]
    fine = mock.delivery({"question": "Q", "answer": WORDS, "seconds": 75})
    assert (fine["words"], fine["wpm"], fine["length"], fine["flag"]) == (150, 120, "ok", "")
    long = mock.delivery({"question": "Q", "answer": WORDS, "seconds": 100})
    assert long["length"] == "long" and "over the 60 to 90 second target (100 seconds)" in long["flag"]
    fast = mock.delivery({"question": "Q", "answer": "alerts " * 200, "seconds": 61})
    assert fast["wpm"] == 197 and "fast, 197 words a minute" in fast["flag"]
    typed = mock.delivery({"question": "Q", "answer": WORDS})
    assert typed["length"] == "untimed" and typed["wpm"] is None and typed["flag"] == ""
    said = "An umbrella, unlikely, alike, Kindergarten kind of"
    assert mock.delivery({"question": "Q", "answer": said, "seconds": 5})["fillers"] == {"kind of": 1}  # whole words
    stutter = mock.delivery({"question": "Q", "answer": "Ummm, uhh, UM.", "seconds": 5})
    assert stutter["fillers"] == {"um": 2, "uh": 1}


def test_the_session_totals_and_the_answers_to_practise_again():
    rows = [{"question": "Fine", "answer": WORDS, "seconds": 75},
            {"question": "Too long", "answer": WORDS, "seconds": 100},
            {"question": "Thin", "answer": "Yes.", "seconds": 3},
            {"question": "Typed", "answer": WORDS}]
    got = mock.delivery_report(rows)
    assert got["target"] == [60, 90] and got["seconds"] == 178 and got["wpm"] == round(301 * 60 / 178)
    assert got["practise"] == [2, 1]  # the thin one first, then the long one; the fine and the typed are left
    assert mock.weakest(got["answers"], most=1) == [2]
    assert mock.delivery_report([rows[0]])["practise"] == []


def test_questions_come_in_order_one_at_a_time_and_a_follow_up_model_has_one_place(setup, fake_model):  # noqa: F811
    cfg, store, _, key = setup
    session = mock.start(cfg, store, key)
    order = [q["question"] for q in session.questions]
    asked = []
    for want in order:
        q = mock.next_question(session, asked)
        assert q["question"] == want
        asked.append({"question": want, "answer": ""})  # a skipped question counts as asked
    assert mock.next_question(session, asked) is None
    assert mock.next_question(session, [{"question": order[0].upper(), "answer": "x"}])["question"] == order[1]
    among = [order[3], order[1]]
    assert mock.next_question(session, [], among)["question"] == order[1]  # the session's order, not the list's
    assert mock.next_question(session, [{"question": order[1], "answer": "x"}], among)["question"] == order[3]


def test_a_prep_sheet_you_wrote_gives_the_questions_and_their_reference_answers(setup, fake_model, tmp_path):  # noqa: F811
    _, store, path, key = setup
    sheets = tmp_path / "sheets"
    sheets.mkdir()
    (sheets / "initech-onsite.html").write_text(
        "<html><title>Initech onsite</title><table><tr><th>Question</th><th>Answer</th></tr>"
        "<tr><td>Why Initech?</td><td>I like detection at scale.</td></tr>"
        "<tr><td>Your biggest incident?</td><td>I led a night of paging cleanup.</td></tr></table></html>")
    path.write_text(path.read_text() + f"prep:\n  sheets: {sheets}\n")
    session = mock.start(config.load(path), store, key)
    assert session.sheet == "initech-onsite.html"
    assert session.questions == [{"question": "Why Initech?", "probes": "", "reference": "I like detection at scale."},
                                 {"question": "Your biggest incident?", "probes": "",
                                  "reference": "I led a night of paging cleanup."}]
    assert mock.next_question(session, [{"question": "Why Initech?", "answer": "x"}])["question"].startswith("Your big")
    path.write_text(path.read_text().replace(f"prep:\n  sheets: {sheets}\n", ""))
    none = mock.start(config.load(path), store, key)
    assert none.sheet == "" and len(none.questions) == 11 and all(q["reference"] == "" for q in none.questions)


def test_the_report_reads_the_answers_against_the_posting_and_sheet(setup, fake_model):  # noqa: F811
    cfg, store, _, key = setup
    session = mock.start(cfg, store, key)
    session.questions[0] = {**session.questions[0], "question": "Why Initech?", "reference": "Detection at scale."}
    fake_model["reply"] = REPORT_REPLY
    out = list(mock.report(session, ANSWERS))
    assert out[0] == {"status": "Warming up"} and out[-2:-1] == [{"input_tokens": 900, "output_tokens": 4}]
    got = out[-1]
    assert got["note"] == "" and got["report"]["landed"] == ["Clear ownership of the alert service."]
    assert got["report"]["opportunities"][1].endswith("from 120 to 35 a week.")
    assert got["report"]["answers"] == [{"strong": "A concrete service.", "missing": "The outcome."},
                                        {"strong": "A number.", "missing": "Which team."}]
    sent = fake_model["messages"][0]["content"]
    assert "Question 1: Why Initech?" in sent and "Detection at scale." in sent
    assert "30 seconds, 16 words a minute" in sent
    assert "Deep Kubernetes" in fake_model["system"] and "ANSWER 1:" in fake_model["system"]
    with pytest.raises(ValueError, match="at least one"):
        mock.report(session, [{"question": "Q", "answer": " ", "seconds": 5}])  # at once, not on first read


def test_the_report_refuses_an_invented_number(setup, fake_model):  # noqa: F811
    cfg, store, _, key = setup
    session = mock.start(cfg, store, key)
    fake_model["reply"] = REPORT_REPLY.replace("Say the result: pages fell from 120 to 35 a week.",
                                               "Say the result: pages fell by 99% in two weeks.") \
        .replace("Strong: A number.", "Strong: Your 4000 users figure.")
    got = list(mock.report(session, ANSWERS))[-1]
    ops = " ".join(got["report"]["opportunities"])
    assert "99" not in ops and "Kubernetes" in ops and len(got["report"]["opportunities"]) == 2
    assert got["report"]["answers"][1]["strong"] == "" and got["report"]["answers"][1]["missing"] == "Which team."
    assert got["note"].startswith("Left out 2 lines of advice with a number")
    assert "4000" not in json.dumps(got["report"])
    # the delivery facts are the user's own numbers: 75 seconds, the 60 to 90 target
    fake_model["reply"] = "LANDED:\n- Strong at 75 seconds.\nGAPS:\nOPPORTUNITIES:\n1. Aim for 60 to 90 seconds.\n"
    got = list(mock.report(session, ANSWERS))[-1]
    assert got["note"] == "" and len(got["report"]["landed"]) == 1
    fake_model["reply"] = "I could not do it."
    assert "nothing usable" in list(mock.report(session, ANSWERS))[-1]["note"]


def test_parse_report_tolerates_markdown_and_extra_answers():
    got = mock.parse_report("Sure!\n## LANDED:\n* **Owned it.**\n\n**GAPS**\n- A3.\n"
                            "OPPORTUNITIES:\n1) One\n2) Two\n3) Three\n4) Four\n5) Five\n6) Six\n"
                            "ANSWER 2:\n**Strong:** Clear.\nMissing: Result,\nand a team.\n")
    assert got["landed"] == ["Owned it."] and got["gaps"] == ["A3."]
    assert got["opportunities"] == ["One", "Two", "Three", "Four", "Five"]
    assert got["answers"] == [{"strong": "", "missing": ""}, {"strong": "Clear.", "missing": "Result, and a team."}]


def test_a_session_is_saved_only_when_asked(setup, fake_model):  # noqa: F811
    cfg, store, path, key = setup
    session = mock.start(cfg, store, key)
    fake_model["reply"] = REPORT_REPLY
    got = list(mock.report(session, ANSWERS))[-1]
    app = App(path)
    info, pieces = app.mock_report({"key": key, "answers": ANSWERS})
    list(pieces)
    assert info["delivery"]["practise"] == [0, 1] and info["delivery"]["answers"][1]["length"] == "ok"
    assert store.package(key).sessions() == []  # making the report keeps nothing
    report = {"delivery": info["delivery"], "content": got["report"], "note": ""}
    assert app.post_mock_report_save({"key": key, "answers": ANSWERS, "report": report}) == {"sessions": 1}
    kept = store.package(key).sessions()
    assert kept[0]["answers"][1] == {"question": "Tell me about on-call.", "seconds": 75.0,
                                     "answer": "I cut pages from 120 to 35 a week by grouping them."}
    assert kept[0]["report"]["content"]["landed"] and kept[0]["saved"]
    store.package(key).write(note="a cover letter")  # other package writes keep it
    assert len(store.package(key).sessions()) == 1
    for bad in ({"answers": [], "report": report}, {"answers": ANSWERS, "report": "x"}):
        with pytest.raises(ValueError):
            app.post_mock_report_save({"key": key, **bad})


def test_the_report_has_delivery_even_when_the_model_is_down(setup, monkeypatch):  # noqa: F811
    from jobwatch import chat
    _, _, path, key = setup
    monkeypatch.setattr(chat, "check", lambda *a: (_ for _ in ()).throw(chat.ChatUnavailable("no model")))
    info, pieces = App(path).mock_report({"key": key, "answers": ANSWERS})
    assert info["delivery"]["answers"][0]["words"] == 8
    with pytest.raises(chat.ChatUnavailable, match="no model"):
        list(pieces)
    with pytest.raises(ApiError, match="at least one"):
        App(path).mock_report({"key": key, "answers": [{"question": "Q", "answer": ""}]})
    with pytest.raises(ApiError):
        App(path).mock_report({"key": key, "answers": "x"})


def test_next_and_report_over_http(server, fake_model):  # noqa: F811
    fake_model["reply"] = REPORT_REPLY
    ok = {"X-Jobwatch-Token": TOKEN}
    request(server, "POST", "/api/fetch", {}, headers=ok)
    status, data = request(server, "POST", "/api/mock/next", {"key": "c1", "asked": []}, headers=ok)
    first = json.loads(data)
    assert status == 200 and first["question"]["question"] and first["total"] >= 1
    status, data = request(server, "POST", "/api/mock/next",
                           {"key": "c1", "asked": [{"question": first["question"]["question"], "answer": ""}]},
                           headers=ok)
    assert json.loads(data)["question"]["question"] != first["question"]["question"]
    assert request(server, "POST", "/api/mock/next", {"key": "c1", "asked": "x"}, headers=ok)[0] == 400
    status, data = request(server, "POST", "/api/mock/report", {"key": "c1", "answers": ANSWERS}, headers=ok)
    lines = [json.loads(x) for x in data.decode().splitlines()]
    assert status == 200 and lines[0]["info"]["delivery"]["answers"][0]["words"] == 8
    assert lines[-1]["done"] and lines[-1]["stats"]["report"]["opportunities"]
    assert request(server, "POST", "/api/mock/report", {"key": "c1", "answers": []}, headers=ok)[0] == 400
