"""scripts/check: its option parsing. Every case here stops before it installs or runs anything."""

import subprocess
from pathlib import Path

import pytest

CHECK = Path(__file__).parents[1] / "scripts" / "check"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(CHECK), *args], capture_output=True, text=True, timeout=30)


def test_help_describes_the_python_option():
    for flag in ("--help", "-h"):
        r = run(flag)
        assert r.returncode == 0 and "--python VERSION" in r.stdout and "repeat" in r.stdout


@pytest.mark.parametrize("args, message", [
    (["--python"], "needs a version"),
    (["--python", "3.11", "--python"], "needs a version"),
    (["--python", "latest"], "isn't a Python version"),
    (["--python=3.11.4"], "isn't a Python version"),
    (["--python=; echo hi"], "isn't a Python version"),
    (["--fast"], "unknown option '--fast'"),
])
def test_bad_options_are_refused_before_anything_runs(args, message):
    r = run(*args)
    assert r.returncode == 2 and message in r.stderr and "== Python" not in r.stdout
