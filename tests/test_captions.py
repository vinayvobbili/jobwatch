"""scripts/videos/captions.py: WebVTT captions from a video's narration and its segments' lengths.
No ffmpeg, no browser."""

import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "videos" / "captions.py"


@pytest.fixture(scope="module")
def captions():
    spec = importlib.util.spec_from_file_location("captions_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass
class Scene:
    say: str


@dataclass
class Video:
    problem_say: str
    scenes: list


def test_the_reel_says_the_problem_the_tagline_and_each_scene_between_two_silent_cards(captions):
    video = Video("The problem.", [Scene("One."), Scene("Two.")])
    assert captions.narrations(video, "The tagline.") == ["", "The problem.", "The tagline.", "One.", "Two.", ""]


def test_a_short_sentence_is_one_cue_and_a_long_one_is_cut_at_its_commas(captions):
    assert captions.split_text("Press Queue. Then apply.") == ["Press Queue.", "Then apply."]
    long = ("On a LinkedIn list, it shows your coverage: how many of those jobs jobwatch already had, "
            "and which are new.")
    cues = captions.split_text(long)
    assert len(cues) > 1 and all(len(c) <= captions.MAX_CHARS for c in cues)
    assert " ".join(cues) == long


def test_a_long_run_without_commas_is_cut_at_spaces(captions):
    text = " ".join(["word"] * 60) + "."
    cues = captions.split_text(text)
    assert len(cues) > 1 and all(len(c) <= captions.MAX_CHARS for c in cues)
    assert " ".join(cues) == text


def test_cues_share_the_spoken_time_by_their_letters_and_run_end_to_end(captions):
    cues = captions.cues_for("Aaa. Bbbbbbb.", 10.0, 6.0)
    assert [(round(a, 2), round(b, 2), t) for a, b, t in cues] == [(10.0, 12.0, "Aaa."), (12.0, 16.0, "Bbbbbbb.")]


def test_timestamps_have_hours_minutes_seconds_and_milliseconds(captions):
    assert captions.timestamp(0) == "00:00:00.000"
    assert captions.timestamp(75.5) == "00:01:15.500"
    assert captions.timestamp(3661.0049) == "01:01:01.005"


def test_captions_start_each_line_with_its_segment_and_skip_the_silent_cards(captions):
    text = captions.captions(["", "Hello there.", "Bye."], [3.0, 5.0, 2.0], [0.0, 4.0, 1.0])
    assert text == ("WEBVTT\n\n"
                    "00:00:03.000 --> 00:00:07.000\nHello there.\n\n"
                    "00:00:08.000 --> 00:00:09.000\nBye.\n")


def test_a_spoken_line_longer_than_its_segment_is_cut_at_the_segment(captions):
    text = captions.captions(["Long line."], [2.0], [9.0])
    assert "00:00:00.000 --> 00:00:02.000" in text


def test_mismatched_lengths_are_an_error(captions):
    with pytest.raises(ValueError, match="2 narrations, 1 segments"):
        captions.captions(["a", "b"], [1.0], [1.0, 1.0])


def test_every_video_on_the_site_has_well_formed_captions_that_stay_within_the_video():
    site = SCRIPT.parents[2] / "site"
    page = (site / "index.html").read_text(encoding="utf-8")
    for src in re.findall(r'<track kind="captions"[^>]* src="([^"]+)"', page):
        vtt = (site / src).read_text(encoding="utf-8")
        assert vtt.startswith("WEBVTT\n\n"), src
        spans = re.findall(r"^(\d\d):(\d\d):(\d\d)\.(\d{3}) --> (\d\d):(\d\d):(\d\d)\.(\d{3})$", vtt, re.M)
        assert spans, src
        last = 0.0
        for g in spans:
            a = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000
            b = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 1000
            assert last <= a < b, (src, g)
            last = b
