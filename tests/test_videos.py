"""The videos' stories (scripts/videos): every video fits its length, shows the UI rather than a terminal, and keeps
to invented figures. Nothing here opens a browser."""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("playwright")
pytest.importorskip("slidecast")

VIDEOS = Path(__file__).resolve().parents[1] / "scripts" / "videos"


@pytest.fixture(scope="module")
def stories():
    sys.path.insert(0, str(VIDEOS))
    try:
        loaded = {}
        for name in ("common", "cards", "stories", "tutorials"):
            spec = importlib.util.spec_from_file_location(name, VIDEOS / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            loaded[name] = module
        yield loaded
    finally:
        sys.path.remove(str(VIDEOS))
        for name in ("common", "cards", "stories", "tutorials", "extension"):
            sys.modules.pop(name, None)


def all_videos(stories):
    return {**stories["stories"].VIDEOS, **stories["tutorials"].TUTORIALS}


def estimated_length(stories, video) -> float:
    """Title card, problem, tagline, each scene held for its voice, and the closing card."""
    say = stories["common"].seconds_to_say
    scenes = sum((s.seconds if s.html else max(s.min_seconds, say(s.say))) + 0.3 for s in video.scenes)
    return 3.0 + max(7.0, say(video.problem_say)) + say(stories["common"].TAGLINE) + scenes + 4.0


def test_the_capture_has_the_frames_aspect_ratio_and_is_recorded_at_the_viewport_size(stories):
    """Playwright never scales a recording up: recording at the frame's size left the page in a grey frame."""
    common = stories["common"]
    view, frame, record = common.VIEW["viewport"], common.VIDEO_SIZE, common.RECORD_SIZE
    assert record == view
    assert view["width"] * frame["height"] == view["height"] * frame["width"]


def test_the_tour_and_the_seven_tutorials_are_here(stories):
    assert list(all_videos(stories)) == [
        "jobwatch-demo", "jobwatch-01-getting-started", "jobwatch-02-daily-routine", "jobwatch-03-where-the-ai-runs",
        "jobwatch-04-applying", "jobwatch-05-tracking", "jobwatch-06-interview-prep", "jobwatch-07-comps-and-contacts"]


def test_every_video_fits_its_length(stories):
    for name, video in all_videos(stories).items():
        limit = 100 if name == "jobwatch-demo" else 120
        assert estimated_length(stories, video) <= limit, name
        assert video.max_seconds <= limit


def test_the_tour_is_about_a_minute_and_a_half(stories):
    assert 75 <= estimated_length(stories, stories["stories"].VIDEOS["jobwatch-demo"]) <= 100


def test_scenes_show_the_ui_not_a_terminal(stories):
    for name, video in all_videos(stories).items():
        cards = [s for s in video.scenes if s.html]
        assert all(s.html is stories["stories"].INSTALL for s in cards), name  # the one command: pipx install
        assert len(cards) <= 1
        for scene in video.scenes:
            assert not re.search(r"\bjobwatch (ui|add|prep|comp|stories|alerts|inbox)\b|\bterminal\b|\bcommand",
                                 scene.say)


def test_the_tour_shows_the_current_features(stories):
    tour = stories["stories"].VIDEOS["jobwatch-demo"]
    said = " ".join(s.say for s in tour.scenes).lower()
    for word in ("no score", "no pay clue", "pay unknown", "queue", "extension", "linkedin", "same list", "coverage",
                 "already had", "follow up", "prep sheet", "side by side"):
        assert word in said, word
    assert tour.extension and tour.demo == "more"


def test_no_real_pay_figure_is_written_in_the_story_files(stories):
    forbidden = re.compile(r"\b(200|185|225|240|250)\s?K\b|\b(200|185|225|240|250),?000\b")
    for name in ("common", "cards", "stories", "tutorials", "extension", "build"):
        text = (VIDEOS / f"{name}.py").read_text(encoding="utf-8")
        assert not forbidden.search(text), name
    assert not forbidden.search((VIDEOS.parent / "demo" / "seed.py").read_text(encoding="utf-8").split("BOARDS")[0])


def test_publish_puts_each_video_where_the_site_and_docs_read_it(tmp_path):
    spec = importlib.util.spec_from_file_location("publish", VIDEOS / "publish.py")
    publish = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publish)
    assert [p.relative_to(tmp_path).as_posix() for p in publish.targets("jobwatch-demo", tmp_path)] == [
        "docs/jobwatch-demo.mp4", "site/jobwatch-demo.mp4"]
    assert [p.relative_to(tmp_path).as_posix() for p in publish.targets("jobwatch-04-applying", tmp_path)] == [
        "docs/tutorials/jobwatch-04-applying.mp4", "site/tutorials/jobwatch-04-applying.mp4"]
    for name in ("jobwatch-02-x", "jobwatch-01-x", "jobwatch-demo"):
        (tmp_path / name).mkdir()
        (tmp_path / name / f"{name}.mp4").write_bytes(b"")
    assert publish.tutorial_names(tmp_path) == ["jobwatch-01-x", "jobwatch-02-x"]


def test_the_cards_hold_the_title_and_the_problem(stories):
    cards = stories["cards"]
    title = cards.title_card("Getting started")
    assert "Getting started" in title and "job" in title and "background-clip: text" in title
    problem = cards.problem_scene(["One", "Two", "Three"], 9.0)
    assert problem.count('class="line"') == 3 and "animation-delay" in problem
