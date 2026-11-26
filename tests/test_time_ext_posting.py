"""scripts/time_ext_posting.py: times POST /ext/posting on a made-up state file."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "time_ext_posting.py"


@pytest.fixture
def timing():
    spec = importlib.util.spec_from_file_location("time_ext_posting", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_it_times_each_request_on_a_small_made_up_state(timing, capsys):
    assert timing.main(["--jobs", "30"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split("  ")[0].strip() for line in lines] == [
        "first read, page open", "read again, page open", "read again, page closed"]
    assert all("s  (30 jobs)" in line for line in lines)


def test_profile_lists_where_the_time_went(timing, capsys):
    assert timing.main(["--jobs", "30", "--profile"]) == 0
    assert "ext_posting" in capsys.readouterr().out
