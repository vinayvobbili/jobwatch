"""config.save keeps a hand-written watchlist's comments: a setting saved from the page, the MCP server or the
command line changes that value and leaves every comment, and every other line, as it was."""

import difflib
import os
import re
import shutil
from pathlib import Path

import pytest
import yaml

from jobwatch import config

HAND_WRITTEN = """\
# Dana's watchlist: robotics, remote or Denver.
companies:
  - greenhouse:acme      # applied 10/2, waiting
  # the two below came from a friend's list
  - lever:globex
  - {source: ashby, board: initech, name: Initech}
filters:
  locations: [remote, Denver]
  max_age_days: 30       # older posts are usually filled
scoring:
  backend: local
  auto: false  # paused for the Initech take-home; back on after Friday
  top: 3
state: state.db
cache: cache
"""


# The layout jobwatch's own saves had (list dashes level with their key), with a comment added by hand since.
SAVED_BY_JOBWATCH = """\
# jobwatch watchlist, saved by jobwatch. Docs: https://github.com/vinayvobbili/jobwatch
companies:
- greenhouse:acme
- source: ashby
  board: initech
  name: Initech
scoring:
  backend: local
  fallback:
  - claude
  auto: false  # off until the Globex onsite is done
state: state.db
cache: cache
"""


def hand_written(tmp_path, text=HAND_WRITTEN):
    path = tmp_path / "jobwatch.yaml"
    path.write_text(text)
    return path


def comments(text):
    return [line[line.index("#"):] for line in text.splitlines() if "#" in line]


def test_saving_a_setting_keeps_every_comment(tmp_path):
    path = hand_written(tmp_path)
    cfg = config.save(path, {"scoring": {"backend": "local", "auto": True, "top": 3}})
    text = path.read_text()
    assert cfg.auto_score is True
    assert re.search(r"\n  auto: true +# paused for the Initech take-home; back on after Friday\n", text)  # same column
    assert comments(text) == comments(HAND_WRITTEN)


def test_only_the_changed_line_changes(tmp_path):
    path = hand_written(tmp_path)
    config.save(path, {"filters": {"locations": ["remote", "Denver"], "max_age_days": 14}})
    changed = [(a, b) for a, b in zip(HAND_WRITTEN.splitlines(), path.read_text().splitlines(), strict=True)
               if a != b]
    assert changed == [("  max_age_days: 30       # older posts are usually filled",
                        "  max_age_days: 14       # older posts are usually filled")]


def test_saving_the_same_values_leaves_the_file_as_it_was(tmp_path):
    path = hand_written(tmp_path)
    config.save(path, {"scoring": {"backend": "local", "auto": False, "top": 3}})
    assert path.read_text() == HAND_WRITTEN


def test_a_file_jobwatch_saved_keeps_its_layout(tmp_path):
    path = hand_written(tmp_path, SAVED_BY_JOBWATCH)
    config.save(path, {"scoring": {"backend": "local", "fallback": ["claude"], "auto": True}})
    assert path.read_text() == SAVED_BY_JOBWATCH.replace("auto: false ", "auto: true  ")


def test_boards_added_and_removed_keep_the_comments_on_the_rest(tmp_path):
    path = hand_written(tmp_path)
    config.add_board(path, "greenhouse:umbrella")
    assert "  - greenhouse:acme      # applied 10/2, waiting\n" in path.read_text()
    config.remove_board(path, "lever:globex")
    text = path.read_text()
    assert "  - greenhouse:acme      # applied 10/2, waiting\n" in text
    assert "lever:globex" not in text and "greenhouse:umbrella" in text
    assert [b.board for b in config.load(path).boards] == ["acme", "initech", "umbrella"]
    assert "# Dana's watchlist: robotics, remote or Denver." in text


def test_a_setting_cleared_is_taken_out(tmp_path):
    path = hand_written(tmp_path)
    config.save(path, {"scoring": None})
    text = path.read_text()
    assert "scoring" not in text and "backend: local" not in text
    assert "# older posts are usually filled" in text


def test_a_prompt_of_several_lines_is_written_as_a_block(tmp_path):
    path = hand_written(tmp_path)
    config.save(path, {"chat": {"prompt": "Today is {today}. Be brief.\n{context}"}})
    assert "prompt: |" in path.read_text()
    assert config.load(path).chat.prompt == "Today is {today}. Be brief.\n{context}"


@pytest.mark.skipif(not os.environ.get("JOBWATCH_REAL_WATCHLIST"), reason="set JOBWATCH_REAL_WATCHLIST to a watchlist")
def test_your_own_watchlist_saved_unchanged_stays_byte_for_byte(tmp_path):
    """Opt-in, against a copy of a real watchlist: every top-level setting saved as it is changes nothing."""
    real = Path(os.environ["JOBWATCH_REAL_WATCHLIST"]).expanduser()
    path = tmp_path / real.name
    shutil.copy(real, path)
    before = path.read_text()
    raw = yaml.safe_load(before)
    config.save(path, {key: raw[key] for key in raw if key in config.SETTINGS})
    changed = list(difflib.unified_diff(before.splitlines(), path.read_text().splitlines(), lineterm="", n=1))
    assert not changed, "\n".join(changed[:40])


def test_a_value_wrapped_over_two_lines_stays_wrapped_when_another_setting_changes(tmp_path):
    wrapped = ("filters:\n  exclude_text:\n"
               "  - \\b(must|required to) be an? (citizen|resident of Freedonia)\\b(?![^.]{0,40}\\b(permanent\n"
               "    resident|work permit))\n")
    path = hand_written(tmp_path, SAVED_BY_JOBWATCH + wrapped)
    config.save(path, {"scoring": {"backend": "local", "fallback": ["claude"], "auto": True}})
    assert path.read_text().endswith(wrapped)
    assert config.load(path).filters.exclude_text[0].endswith("(permanent resident|work permit))")


def test_a_new_file_starts_with_the_header(tmp_path):
    path = tmp_path / "new" / "jobwatch.yaml"
    config.save(path, {"companies": ["greenhouse:acme"]})
    assert path.read_text().startswith("# jobwatch watchlist, saved by jobwatch.")
    assert [b.board for b in config.load(path).boards] == ["acme"]
