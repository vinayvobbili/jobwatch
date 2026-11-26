"""chrome-extension/tools/paste_block.py: one block of CHROMEWEBSTORE.md onto the clipboard (a fake one here)."""

import io
import sys
from pathlib import Path

import pytest

EXT = Path(__file__).resolve().parent.parent / "chrome-extension"
sys.path.insert(0, str(EXT / "tools"))
import paste_block  # noqa: E402

DOC = """# Store listing: Example

## Store Listing

### Single purpose

Not a paste block: it sits outside the paste section.

## Paste blocks for 1.0.0

Intro text that belongs to no block.

### Single purpose

Help with forms.

Second paragraph.

### Justification: activeTab

Reads the form.

### Justification: storage

Keeps the address.

### Justification: scripting

Injects the filler.

### Host permission justification (the dashboard field; 1,000 characters at most)

The dashboard has one box. Paste this; the longer blocks below are for a reviewer.

Local app (http://127.0.0.1/*): only the app on this computer.

LinkedIn and Indeed (https://www.linkedin.com/*): job lists only.

Ladders (theladders.com): no host access.

### Justification: host permissions (http://127.0.0.1/*)

The long wording.

### Data use: data types to tick

Tick: Website content.

## Permissions Justification (working notes)

### Single purpose

Also not a paste block.

## Test Instructions (for the reviewer)

1. Install it.
2. Run it.

## Version History
"""


class Clipboard:
    def __init__(self):
        self.copies = []

    def __call__(self, text):
        self.copies.append(text)


@pytest.fixture
def doc(tmp_path):
    path = tmp_path / "CHROMEWEBSTORE.md"
    path.write_text(DOC, encoding="utf-8")
    return path


def run(doc, *argv, clipboard=None):
    out = io.StringIO()
    code = paste_block.main(list(argv), clipboard=clipboard or Clipboard(), doc=doc, out=out)
    return code, out.getvalue()


def test_list_names_each_block_with_its_length_and_marks_the_ticks(doc):
    _, out = run(doc, "--list")
    assert "Single purpose" in out and "Justification: activeTab" in out and "test-instructions" in out
    assert "Also not a paste block" not in out and "Intro text" not in out
    assert out.count("(read, not pasted)") == 1
    assert "Data use: data types to tick  (read, not pasted)" in out
    assert f"{len('Reads the form.'):>6,}  Justification: activeTab" in out


def test_a_name_copies_the_blocks_trimmed_body_and_says_what_it_copied(doc):
    clip = Clipboard()
    _, out = run(doc, "single", clipboard=clip)
    assert clip.copies == ["Help with forms.\n\nSecond paragraph."]
    assert "Copied Single purpose (35 characters)" in out


def test_the_justification_lead_is_optional_and_case_does_not_matter(doc):
    for name in ("activetab", "ACTIVETAB", "Justification: activeTab", "justification: active"):
        clip = Clipboard()
        run(doc, name, clipboard=clip)
        assert clip.copies == ["Reads the form."], name


def test_an_exact_name_beats_a_longer_one_that_starts_with_it(doc):
    clip = Clipboard()
    run(doc, "host permissions", clipboard=clip)
    assert clip.copies == ["The long wording."]
    run(doc, "host permission justification", clipboard=clip)
    assert clip.copies[-1].startswith("Local app")


def test_the_host_block_is_only_its_three_paragraphs(doc):
    clip = Clipboard()
    run(doc, "host permission j", clipboard=clip)
    assert clip.copies == [
        "Local app (http://127.0.0.1/*): only the app on this computer.\n\n"
        "LinkedIn and Indeed (https://www.linkedin.com/*): job lists only.\n\n"
        "Ladders (theladders.com): no host access."
    ]


def test_the_host_block_over_1000_characters_is_refused(doc):
    doc.write_text(DOC.replace("job lists only.", "job lists only. " + "x" * 1000), encoding="utf-8")
    clip = Clipboard()
    with pytest.raises(SystemExit, match="over the dashboard's 1,000"):
        run(doc, "host permission justification", clipboard=clip)
    assert clip.copies == []


def test_the_host_block_without_a_paragraph_is_an_error(doc):
    doc.write_text(DOC.replace("Ladders (theladders.com): no host access.", ""), encoding="utf-8")
    with pytest.raises(SystemExit, match="Ladders"):
        run(doc, "--list")


def test_test_instructions_copies_that_sections_body(doc):
    clip = Clipboard()
    run(doc, "test-instructions", clipboard=clip)
    assert clip.copies == ["1. Install it.\n2. Run it."]


def test_a_block_of_ticks_is_not_copied(doc):
    clip = Clipboard()
    _, out = run(doc, "data use: data", clipboard=clip)
    assert clip.copies == []
    assert "(read, not pasted)" in out and "nothing was copied" in out


def test_an_unknown_name_lists_the_choices(doc):
    clip = Clipboard()
    with pytest.raises(SystemExit) as err:
        run(doc, "nope", clipboard=clip)
    assert "'nope' is not a block" in str(err.value)
    assert "Justification: storage" in str(err.value) and "test-instructions" in str(err.value)
    assert clip.copies == []


def test_an_ambiguous_prefix_lists_only_the_matches(doc):
    with pytest.raises(SystemExit) as err:
        run(doc, "host")
    message = str(err.value)
    assert "matches several blocks" in message
    assert "Host permission justification" in message and "Justification: host permissions" in message
    assert "storage" not in message


def test_a_document_with_no_paste_section_is_an_error(doc):
    doc.write_text("# Nothing\n\n## Store Listing\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="no '## Paste blocks for"):
        run(doc, "--list")


def test_pbcopy_pipes_the_text_to_the_command(monkeypatch):
    seen = {}

    def fake_run(cmd, input, check):
        seen.update(cmd=cmd, input=input, check=check)

    monkeypatch.setattr(paste_block.subprocess, "run", fake_run)
    paste_block.pbcopy("héllo")
    assert seen == {"cmd": ["pbcopy"], "input": "héllo".encode(), "check": True}


def test_every_dashboard_block_of_the_real_file_resolves_and_the_host_box_fits():
    blocks = paste_block.load_blocks(paste_block.STORE_DOC.read_text(encoding="utf-8"))
    for name in ("single", "activeTab", "scripting", "storage", "sidePanel", "tabs",
                 "host permission justification", "host permissions", "content script", "test-instructions"):
        block = paste_block.find_block(blocks, name)
        assert block.text and not block.read_only, name
    host = paste_block.find_block(blocks, "host permission justification")
    assert host.text.startswith("Local app") and "Ladders" in host.text
    assert len(host.text) <= paste_block.HOST_LIMIT
    ticks = [b for b in blocks if b.read_only]
    assert len(ticks) == 2
    for block in ticks:
        assert "nothing was copied" in paste_block.copy_block(block, clipboard=pytest.fail)
