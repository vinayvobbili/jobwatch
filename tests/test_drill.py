"""Drill videos: the cards a prep sheet gives, and the slides and lines that would go to slidecast."""

import importlib.machinery
import sys
import types

import pytest

from jobwatch import cli, drill
from jobwatch.prep import Sheet
from jobwatch.stories import Story

PAGE = """<!doctype html><html><head><title>Initech: interview prep</title></head><body>
<h1>Initech: interview prep</h1>
<table><tr><th>Question</th><th>Answer (say this)</th></tr>
<tr><td>Why one queue per region?</td><td>"Latency. Each region drains its own queue, so one slow region can't hold
the rest back. We tested it with a replay."<br><span class="muted">Source: the design doc.</span></td></tr>
<tr><td>How did you test it?</td><td>"Unit tests locally, then a replay of a day's traffic."</td></tr>
</table>
<table><tr><th>Step</th><th>What</th></tr><tr><td>S1</td><td>Fetch</td></tr></table>
<table><tr><th>Question</th><th>Answer</th></tr>
<tr><td>How did you test it?</td><td>A second answer to the same question.</td></tr>
<tr><td>No answer here?</td><td></td></tr>
</table></body></html>"""

STORY = Story("queue-split", "Split the job queue", "Split one job queue into one per region.",
              "Two regions shared a worker pool.", "Late jobs went from 40 a day to 3", ("Python",))


def sheet(**kw):
    return Sheet(key="k", company="Initech", title="Staff Engineer", status="interviewing", **kw)


def test_cues_are_each_sentences_first_words():
    assert drill.cues("Latency first. Each region drains its own queue, so one slow region can't hold it.") == (
        "Latency first.", "Each region drains its own queue, so…")


def test_page_cards_come_from_question_and_answer_tables():
    title, cards = drill.from_page(PAGE)
    assert title == "Initech: interview prep"
    assert [c.question for c in cards] == ["Why one queue per region?", "How did you test it?"]
    first = cards[0]
    assert first.answer == ("Latency. Each region drains its own queue, so one slow region can't hold the rest back. "
                            "We tested it with a replay.")
    assert "Source" not in first.answer  # muted asides are not what you'd say
    assert first.cues[0] == "Latency."
    assert cards[1].answer == "Unit tests locally, then a replay of a day's traffic."  # the first answer is kept


def test_sheet_cards_use_practised_answers_then_drafts_with_their_stories():
    s = sheet(practised=[{"question": "Tell me about yourself.", "improved": "I build queues. I like it."}],
              drafted=[{"question": "A time you cut latency?", "probes": "", "kind": "need", "no_story": False,
                        "stories": [{"id": "queue-split", "title": "Split the job queue"}],
                        "outline": ["One queue per region", "Replay tested"], "angle": ""},
                       {"question": "Kubernetes at scale?", "probes": "", "kind": "need", "no_story": True,
                        "stories": [], "outline": [], "angle": "Say what's closest."},
                       {"question": "Tell me about yourself.", "probes": "", "kind": "need", "no_story": False,
                        "stories": [], "outline": ["A drafted version"], "angle": ""}])
    cards = drill.from_sheet(s, [STORY])
    assert [c.question for c in cards] == ["Tell me about yourself.", "A time you cut latency?"]
    assert cards[0].answer == "I build queues. I like it."
    assert cards[1].cues == ("One queue per region", "Replay tested")
    assert cards[1].answer == ("One queue per region. Replay tested. Split one job queue into one per region. "
                               "The hard part: Two regions shared a worker pool. Late jobs went from 40 a day to 3.")


def test_a_sheet_without_answers_gives_no_cards():
    assert drill.from_sheet(sheet(expect=["Why this company?"]), []) == []


def test_segments_ask_hold_then_answer_in_two_voices():
    cards = [drill.Card("Why <queues>?", "Latency.", ("Latency.",)), drill.Card("Tested?", "Yes.", ("Yes.",))]
    segs = drill.segments(cards, "Initech", pause=60)
    assert len(segs) == 1 + 3 * 2
    q, hold, answer = segs[1:4]
    assert (q.voice, q.line) == (drill.INTERVIEWER, "Why <queues>?")
    assert "Why &lt;queues&gt;?" in q.html and "<queues>" not in q.html
    assert (hold.voice, hold.line, hold.hold) == ("", "", 60)
    assert "Answer out loud" in hold.html and "60 seconds" in hold.html
    assert (answer.voice, answer.line) == (drill.ANSWERER, "Latency.")
    assert "<li>Latency.</li>" in answer.html
    assert f"--a:{drill.THEMES[1][0]}" in q.html and f"--a:{drill.THEMES[2][0]}" in segs[4].html  # own colours


def test_no_pause_is_a_quick_review():
    segs = drill.segments([drill.Card("Q?", "A.", ("A.",))], "T", pause=0)
    assert [s.voice for s in segs] == [drill.INTERVIEWER, drill.INTERVIEWER, drill.ANSWERER]
    assert "quick review" in segs[0].line


class FakeTTS:
    def __init__(self):
        self.voice, self.said = "", []

    def synthesize(self, text, out_path):
        self.said.append((self.voice, text))
        return 1.0


def test_voices_switch_on_each_lines_tag():
    tts = FakeTTS()
    voices = drill.Voices(tts)
    voices.synthesize("[am_michael] Why queues?", "a.wav")
    voices.synthesize("[af_heart] Latency.", "b.wav")
    assert tts.said == [("am_michael", "Why queues?"), ("af_heart", "Latency.")]


@pytest.fixture
def fake_slidecast(monkeypatch):
    """A stand-in slidecast that records what the reel is given instead of making a video."""
    made = {}

    class Reel:
        def __init__(self, **kw):
            made["reel"], made["slides"] = kw, []

        def add(self, html, narration="", **kw):
            made["slides"].append((html, narration, kw))

        def render(self, out):
            for _, narration, _ in made["slides"]:
                if narration:
                    made["reel"]["tts"].synthesize(narration, "x.wav")
            made["out"] = out

    mod = types.ModuleType("slidecast")
    mod.__spec__ = importlib.machinery.ModuleSpec("slidecast", None)
    mod.Reel, mod.MLXKokoroTTS = Reel, FakeTTS
    monkeypatch.setitem(sys.modules, "slidecast", mod)
    return made


def test_render_sends_tagged_lines_and_silent_holds(fake_slidecast, tmp_path):
    tts = FakeTTS()
    segs = drill.segments([drill.Card("Q?", "A.", ("A.",))], "T", pause=70)
    out = drill.render(segs, tmp_path / "prep" / "drill.mp4", tts=tts, renderer=object())
    slides = fake_slidecast["slides"]
    assert [n for _, n, _ in slides] == [f"[{drill.INTERVIEWER}] {segs[0].line}", f"[{drill.INTERVIEWER}] Q?", "",
                                         f"[{drill.ANSWERER}] A."]
    assert slides[2][2] == {"min_duration": 70}
    assert tts.said[-2:] == [(drill.INTERVIEWER, "Q?"), (drill.ANSWERER, "A.")]
    assert out == fake_slidecast["out"] and out.parent.is_dir()


def test_render_without_slidecast_says_how_to_get_it(monkeypatch, tmp_path):
    monkeypatch.setattr(drill.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(SystemExit, match=r"jobwatch\[video\]"):
        drill.render([], tmp_path / "x.mp4")


def test_cli_drills_a_hand_written_sheet(watchlist, tmp_path, monkeypatch):
    page = tmp_path / "sheet.html"
    page.write_text(PAGE)
    got = {}
    monkeypatch.setattr(drill, "render", lambda segs, out: got.update(segs=segs, out=out) or out)
    cli.main(["--config", str(watchlist), "prep", str(page), "--drill", str(tmp_path / "d.mp4"), "--pause", "65"])
    assert got["out"] == tmp_path / "d.mp4"
    assert len(got["segs"]) == 1 + 3 * 2 and got["segs"][2].hold == 65
    cli.main(["--config", str(watchlist), "prep", str(page), "--drill", str(tmp_path / "d.mp4"), "--no-pause"])
    assert len(got["segs"]) == 1 + 2 * 2


def test_cli_drill_with_no_answers_says_what_to_do(watchlist, tmp_path, monkeypatch):
    page = tmp_path / "empty.html"
    page.write_text("<html><body><p>No tables.</p></body></html>")
    with pytest.raises(SystemExit, match="--draft"):
        cli.main(["--config", str(watchlist), "prep", str(page), "--drill", str(tmp_path / "d.mp4")])
