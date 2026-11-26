"""scripts/time_mark.py: times POST /api/mark on a made-up state file."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "time_mark.py"


@pytest.fixture
def timing():
    spec = importlib.util.spec_from_file_location("time_mark", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_it_times_each_button_on_a_small_made_up_state(timing, capsys):
    assert timing.main(["--jobs", "60", "--acted", "30"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split("  ")[0].strip() for line in lines] == [
        "Queue", "Skip", "I applied", "Remove from queue", "Undo (back to new)"]
    assert all("s  (60 jobs, 30 acted on)" in line for line in lines)


def test_profile_lists_where_the_time_went(timing, capsys):
    assert timing.main(["--jobs", "60", "--acted", "30", "--profile"]) == 0
    assert "post_mark" in capsys.readouterr().out
