"""The demo video's problem scene (chrome-extension/tools/problem_scene.py): its page and keyframe tracks."""

import importlib.util
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "chrome-extension" / "tools"


def load():
    sys.path.insert(0, str(TOOLS))
    try:
        spec = importlib.util.spec_from_file_location("problem_scene_under_test", TOOLS / "problem_scene.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(TOOLS))


def test_the_page_has_four_made_up_forms_with_the_same_questions():
    scene = load()
    html = scene.problem_html("body {{ margin: 0 }}", 1280, 800)
    for company in ("Initech", "Globex", "Umbrella", "Hooli"):
        assert f"<b>{company}</b>" in html
    for question, _start, _end in scene.QUESTIONS:
        assert html.count(f"<label>{question}</label>") == 4


def test_every_track_stays_inside_the_clock_and_ends_on_it():
    scene = load()
    css = scene.scene_css()
    for rule in re.findall(r"@keyframes \w+ \{(.*?)\} \}", css, flags=re.S):
        percents = [float(p) for p in re.findall(r"([\d.]+)% \{", rule)]
        assert percents == sorted(percents) and percents[0] == 0 and percents[-1] == 100


def test_counters_run_from_one_to_forty_and_zero_to_twenty_hours():
    scene = load()
    apps = scene.counter_track("apps", scene.COUNT, 1, 40, "")
    hours = scene.counter_track("hours", scene.CLOCK, 0, 20, " hours")
    assert 'content: "1";' in apps and 'content: "40";' in apps
    assert 'content: "0 hours";' in hours and 'content: "20 hours";' in hours


def test_the_typing_is_deleted_and_started_over():
    scene = load()
    for line in scene.TYPE_RUNS:
        widths = [chars for _t, chars in line]
        assert max(widths) > 0 and 0 in widths[widths.index(max(widths)):]  # typed, then emptied
        assert widths[-1] > 0  # and started again
