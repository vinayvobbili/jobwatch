"""The rehearsal page's mic: how a spoken try sounded (counted in code, on made-up transcripts), the /rehearse/ calls
`jobwatch ui` takes from the page (the speech server is a stub), and the speech.url setting."""

import json
import re
import shutil
import subprocess

import pytest

from jobwatch import config, drill, rehearse
from jobwatch.web import App

from .conftest import request
from .test_voice import Stub

ANSWER = ("Latency first. Each region drains its own queue, so a slow region can't hold the others back. We cut the "
          "backlog from 40 hours to 6.")
GOOD = ("Latency comes first. " + "Each region drains its own queue, so a slow region never holds the others back. " * 9
        + "We cut the backlog from 40 hours to 6 hours.")


def test_a_smooth_try_has_nothing_to_change():
    f = rehearse.feedback(GOOD, ANSWER, 70)
    assert f["length"] == "ok" and f["pace"] == "ok" and 110 <= f["wpm"] <= 180
    assert f["filler_count"] == 0 and f["headline"]["ok"] and f["headline"]["sentence"] == "Latency comes first."
    assert f["terms"]["missed"] == [] and f["terms"]["coverage"] == 100
    assert "40" in f["terms"]["hit"] and "6" in f["terms"]["hit"]
    assert f["tips"] == [] and f["timed_pauses"] is False and f["pauses"] == []


def test_fillers_a_warm_up_and_a_short_answer_are_called_out():
    said = "Um, so, like, I think basically we, uh, you know, sort of moved the queues around. Um, like, it was fine."
    f = rehearse.feedback(said, ANSWER, 20)
    assert f["fillers"] == {"um": 2, "like": 2, "basically": 1, "uh": 1, "you know": 1, "sort of": 1}
    assert f["filler_count"] == 8 and f["length"] == "short"
    assert not f["headline"]["ok"] and "warm-up" in f["headline"]["why"]
    assert f["terms"]["hit"] == ["queue"]   # queues counts as queue
    tips = " ".join(f["tips"])
    assert "headline" in tips and "8 filler words" in tips and "Run longer: 20 s" in tips
    assert "Say the key points" in tips


def test_pace_and_length_against_the_target():
    fast = rehearse.feedback(GOOD, ANSWER, 40)
    assert fast["pace"] == "fast" and fast["length"] == "short" and any("Slow down" in t for t in fast["tips"])
    slow = rehearse.feedback(GOOD, ANSWER, 120)
    assert slow["pace"] == "slow" and slow["length"] == "long"
    assert any("Tighten it: 120 s" in t for t in slow["tips"]) and any("Pick up the pace" in t for t in slow["tips"])
    assert rehearse.feedback(GOOD, ANSWER, 0)["length"] == "untimed"
    assert rehearse.feedback(GOOD, ANSWER, 0)["wpm"] is None
    custom = rehearse.feedback(GOOD, ANSWER, 70, target=(30, 45))
    assert custom["length"] == "long" and custom["target"] == [30, 45]


def test_a_headline_is_short_and_states_the_point():
    long = ("Latency was the thing that I kept coming back to over and over again when we sat down and looked at "
            "the whole design together. Then more.")
    assert "keep the first sentence under 20" in rehearse.feedback(long, ANSWER, 70)["headline"]["why"]
    off = rehearse.feedback("I worked at Globex for five years. Then queues.", ANSWER, 70)["headline"]
    assert not off["ok"] and "doesn't say the point" in off["why"] and "latency" in off["why"]
    # No punctuation from the speech-to-text: the first segment stands in for the first sentence.
    bare = "latency comes first each region drains its own queue um we cut the backlog from 40 hours to 6"
    segments = [{"start": 0.0, "end": 3.0, "text": " latency comes first each region drains its own queue"},
                {"start": 3.0, "end": 6.0, "text": " um we cut the backlog from 40 hours to 6"}]
    head = rehearse.feedback(bare, ANSWER, 6, segments)["headline"]
    assert head["ok"] and head["sentence"] == "latency comes first each region drains its own queue"
    assert rehearse.feedback(bare, ANSWER, 6)["headline"]["sentence"] == bare
    assert rehearse.feedback("", ANSWER, 0)["headline"] == {"sentence": "", "words": 0, "ok": False,
                                                             "why": "nothing was said"}


def test_key_terms_are_content_words_and_numbers():
    key = rehearse.terms(ANSWER)
    assert {"latency", "region", "drains", "queue", "backlog", "40", "6"} <= set(key)
    assert not {"can't", "its", "the", "so", "from"} & set(key)
    assert len(key) <= rehearse.MOST_TERMS
    assert rehearse.terms("Umbrella's pipeline") == ["umbrella", "pipeline"]


def test_long_pauses_come_from_segment_timestamps():
    segments = [{"id": 0, "start": 0.0, "end": 4.0, "text": " Latency comes first."},
                {"id": 1, "start": 7.5, "end": 12.0, "text": " Each region drains its own queue."},
                {"id": 2, "start": 12.4, "end": 20.0, "text": " We cut the backlog."},
                {"id": 3, "start": "bad"}]
    f = rehearse.feedback(GOOD, ANSWER, 70, segments)
    assert f["timed_pauses"] is True
    assert f["pauses"] == [{"at": 4.0, "seconds": 3.5, "after": "Latency comes first."}]
    two = [*segments[:3], {"start": 25.0, "end": 30.0, "text": "x"}]
    assert any("2 long pauses" in t for t in rehearse.feedback(GOOD, ANSWER, 70, two)["tips"])


# -- the speech.url setting


def _load(tmp_path, speech):
    path = tmp_path / "jobwatch.yaml"
    path.write_text("companies: [greenhouse:acme]\nspeech: " + json.dumps(speech) + "\n", encoding="utf-8")
    return config.load(path)


def test_speech_url_is_checked(tmp_path):
    assert config.load(_write(tmp_path)).speech.url == ""
    url = "http://127.0.0.1:8010/v1/audio/transcriptions"
    assert _load(tmp_path, {"url": url + "/"}).speech.url == url
    assert _load(tmp_path, {"url": "https://stt.example/v1/audio/transcriptions"}).speech.url.startswith("https:")
    assert _load(tmp_path, {}).speech.url == ""
    for bad in ("ftp://127.0.0.1/v1/audio/transcriptions", "http://127.0.0.1:8010/v1/models", "127.0.0.1:8010",
                "http:///v1/audio/transcriptions", "http://127.0.0.1:x/v1/audio/transcriptions",
                "http://127.0.0.1:8010/v1/audio/transcriptions?key=1", 8010):
        with pytest.raises(config.ConfigError, match=r"speech\.url"):
            _load(tmp_path, {"url": bad})
    with pytest.raises(config.ConfigError, match="unknown speech setting"):
        _load(tmp_path, {"url": url, "model": "whisper"})
    with pytest.raises(config.ConfigError, match="speech looks like"):
        _load(tmp_path, url)


def _write(tmp_path):
    path = tmp_path / "plain.yaml"
    path.write_text("companies: [greenhouse:acme]\n", encoding="utf-8")
    return path


def test_speech_url_can_be_saved_and_a_bad_one_is_refused(tmp_path):
    path = _write(tmp_path)
    url = "http://127.0.0.1:8010/v1/audio/transcriptions"
    assert config.save(path, {"speech": {"url": url}}).speech.url == url
    with pytest.raises(config.ConfigError, match=r"speech\.url"):
        config.save(path, {"speech": {"url": "http://127.0.0.1:8010/"}})
    assert config.load(path).speech.url == url   # the refused one never replaced the file


# -- the calls the page makes


@pytest.fixture
def stt():
    stub = Stub()
    segments = [{"id": 0, "start": 0.0, "end": 1.5, "text": " Latency comes first."},
                {"id": 1, "start": 4.0, "end": 6.0, "text": " Each region drains its own queue."}]
    stub.answer = (200, {"text": " Latency comes first. Each region drains its own queue. ", "duration": 6.0,
                         "segments": segments})
    yield stub
    stub.http.shutdown()
    stub.http.server_close()


@pytest.fixture
def speech_on(watchlist, stt, monkeypatch):
    """The test watchlist with speech.url at the stub. LOCAL_STT_URL names a port nothing listens on, so a call
    that ignored the setting would fail."""
    monkeypatch.setenv("LOCAL_STT_URL", "http://127.0.0.1:9/v1/audio/transcriptions")
    watchlist.write_text(watchlist.read_text() + f"speech:\n  url: {stt.url}\n")
    return stt


FILE_PAGE = {"origin": "null"}   # what a browser sends from a page opened as a file (header names ignore case)


def _named(headers: dict) -> dict:
    """Response headers by lower-case name: HTTP header names ignore case."""
    return {k.lower(): v for k, v in headers.items()}


def test_the_page_gets_words_then_feedback_from_the_configured_endpoint(server, speech_on):
    status, data, headers = request(server, "POST", "/rehearse/transcribe?name=answer.webm", raw=b"fake-audio",
                                    headers={**FILE_PAGE, "Content-Type": "audio/webm;codecs=opus"},
                                    with_headers=True)
    assert status == 200 and _named(headers)["access-control-allow-origin"] == "null"
    said = json.loads(data)
    assert said["text"] == "Latency comes first. Each region drains its own queue." and said["duration"] == 6.0
    path, ctype, body = speech_on.sent[0]
    assert path == "/v1/audio/transcriptions" and ctype.startswith("multipart/form-data")
    assert b"fake-audio" in body and b'filename="answer.webm"' in body and b"verbose_json" in body

    status, data = request(server, "POST", "/rehearse/feedback", headers=FILE_PAGE,
                           body={"transcript": said["text"], "answer": ANSWER, "seconds": said["duration"],
                                 "segments": said["segments"]})
    f = json.loads(data)
    assert status == 200 and f["headline"]["ok"] and f["length"] == "short"
    assert f["pauses"] == [{"at": 1.5, "seconds": 2.5, "after": "Latency comes first."}]
    assert "backlog" in f["terms"]["missed"] and "latency" in f["terms"]["hit"]


def test_status_says_where_speech_goes_and_whether_it_answers(server, speech_on, watchlist):
    status, data = request(server, "GET", "/rehearse/status", headers=FILE_PAGE)
    assert status == 200 and json.loads(data) == {"endpoint": speech_on.url, "reachable": True}
    assert speech_on.sent == []   # only a connection: nothing is sent, so no model loads
    down = "http://127.0.0.1:9/v1/audio/transcriptions"
    watchlist.write_text(watchlist.read_text().replace(speech_on.url, down))
    assert json.loads(request(server, "GET", "/rehearse/status", headers=FILE_PAGE)[1]) == {"endpoint": down,
                                                                                            "reachable": False}
    status, data = request(server, "POST", "/rehearse/transcribe", raw=b"audio", headers=FILE_PAGE)
    assert status == 503 and "no speech-to-text server at " + down in json.loads(data)["error"]


def test_a_busy_speech_server_is_passed_through(server, speech_on):
    speech_on.answer = (503, {"error": {"message": "short of memory"}})
    status, data = request(server, "POST", "/rehearse/transcribe", raw=b"audio", headers=FILE_PAGE)
    assert status == 503 and "short of memory" in json.loads(data)["error"]
    assert request(server, "POST", "/rehearse/transcribe", raw=b"", headers=FILE_PAGE)[0] == 400


def test_other_sites_cannot_call_it(server, speech_on):
    evil = {"origin": "https://evil.example"}
    assert request(server, "POST", "/rehearse/transcribe", raw=b"audio", headers=evil)[0] == 403
    assert request(server, "GET", "/rehearse/status", headers=evil)[0] == 403
    assert request(server, "OPTIONS", "/rehearse/transcribe", headers=evil)[0] == 403
    assert request(server, "GET", "/rehearse/status", headers=FILE_PAGE, host="evil.example")[0] == 403
    assert speech_on.sent == []
    # The page's own calls still need the token: only /rehearse/ is open to the file page.
    assert request(server, "POST", "/api/mock/transcribe", raw=b"audio", headers=FILE_PAGE)[0] == 403


def test_the_browser_preflight_is_answered_for_the_file_page(server, speech_on):
    status, _, headers = request(server, "OPTIONS", "/rehearse/transcribe",
                                 headers={**FILE_PAGE, "Access-Control-Request-Method": "POST",
                                          "Access-Control-Request-Headers": "content-type"}, with_headers=True)
    headers = _named(headers)
    assert status == 204 and headers["access-control-allow-origin"] == "null"
    assert "POST" in headers["access-control-allow-methods"]
    assert headers["access-control-allow-headers"] == "Content-Type"
    assert headers["access-control-allow-private-network"] == "true"
    assert request(server, "OPTIONS", "/api/settings", headers=FILE_PAGE)[0] == 403


FAKE_DOM = """
const els = {};
const mk = () => ({ innerHTML: "", textContent: "", children: [], dataset: {}, style: {}, checked: false, value: "",
  classList: { toggle() {} }, addEventListener() {}, querySelectorAll: () => [],
  querySelector: () => ({ style: {} }) });
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.matchMedia = () => ({ matches: false, addEventListener() {} });
globalThis.document = { getElementById: id => els[id] || (els[id] = mk()), documentElement: { dataset: {} },
  addEventListener() {} };
"""


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_page_shows_how_it_sounded_beside_the_sheet_answer(tmp_path):
    """The feedback panel, drawn by the page's own script (in node, with a stand-in for the page) from what
    /rehearse/feedback answers: the transcript beside the sheet's answer, the tiles, the key terms and the trend."""
    said = "Latency comes first. Um, each region drains its own <queue>."
    got = rehearse.feedback(said, ANSWER, 64, [{"start": 0, "end": 2, "text": "Latency comes first."},
                                               {"start": 5, "end": 9, "text": "Each region."}])
    page = rehearse.build("Initech", [drill.Card("Why one queue per region?", ANSWER)])
    script = re.search(r"<script>(.*)</script>", page, re.S).group(1)
    shown = (f"phase = 'shown';\nfb = {{ state: 'done', text: {json.dumps(said)}, result: {json.dumps(got)} }};\n"
             "tries[CARDS[0].q] = [{ t: 0, wpm: 150, fillers: 4, seconds: 95, terms: 40, headline: false },\n"
             "  { t: 1, wpm: 140, fillers: 1, seconds: 64, terms: 55, headline: true }];\n"
             "render(); console.log(document.getElementById('view').innerHTML);")
    js = tmp_path / "page.js"
    js.write_text(FAKE_DOM + script + shown, encoding="utf-8")
    done = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    html = done.stdout
    assert "How it sounded" in html and "What you said" in html and "The sheet's answer" in html
    assert '<span class="lead">Latency comes first.</span>' in html and "&lt;queue&gt;" in html
    assert "<queue>" not in html   # the transcript is escaped
    assert '<span class="miss">backlog</span>' in html and '<span class="hit">latency</span>' in html
    assert "Try 2" in html and 'class="spark"' in html and "Say it again" in html
    assert "1:04" in html   # 64 seconds, against the 60 to 90 target


def test_feedback_checks_what_it_is_sent(watchlist):
    app = App(watchlist)
    for bad in ({"transcript": 3, "answer": "a"}, {"transcript": "a"}, {"transcript": "a", "answer": "b",
                                                                         "seconds": "ten"},
                {"transcript": "a", "answer": "b", "segments": "x"}):
        with pytest.raises(Exception, match=r"text|number"):
            app.rehearse_feedback(bad)
    assert app.rehearse_feedback({"transcript": GOOD, "answer": ANSWER, "seconds": 70})["tips"] == []
