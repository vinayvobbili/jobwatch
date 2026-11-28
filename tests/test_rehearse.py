"""Rehearsal pages: the cards a hand-written prep sheet gives, the page built from them, and the command."""

import json
import re
import shutil
import subprocess

import pytest

from jobwatch import cli, drill, rehearse

SHEET = """<!doctype html><html><head><title>Initech: interview prep</title></head><body>
<table><tr><th>Question</th><th>Answer (say this)</th></tr>
<tr><td>Why one queue per region?</td><td>"Latency. Each region drains its own queue. A slow region can't hold
the rest back."</td></tr>
<tr><td>What did <b>Globex</b> change?</td>
<td>"We cut the backlog from 40 hours to 6 &lt;/script&gt;&lt;b&gt;bold&lt;/b&gt;."</td></tr>
</table></body></html>"""


def _cards(page: str) -> dict:
    """The JSON the page embeds, read back the way the browser would."""
    return json.loads(re.search(r"const DATA = (.*?);\nconst TITLE", page, re.S).group(1))


@pytest.fixture
def sheet(tmp_path):
    path = tmp_path / "initech-sheet.html"
    path.write_text(SHEET, encoding="utf-8")
    return path


def test_a_picture_in_the_sheet_is_found_beside_it_from_any_working_folder(tmp_path, monkeypatch):
    folder = tmp_path / "prep"
    folder.mkdir()
    (folder / "board.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    page = folder / "umbrella-sheet.html"
    page.write_text(SHEET.replace("</table>", '<tr><td>Draw it.</td><td><img src="board.png"> "Boxes."</td></tr>'
                                              "</table>"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    out = rehearse.write(page)
    assert out == folder / "umbrella-sheet-rehearse.html" and out.is_file()


def test_cards_come_through_from_the_sheet(sheet):
    out = rehearse.write(sheet)
    data = _cards(out.read_text(encoding="utf-8"))
    assert data["title"] == "Initech: interview prep"
    assert [c["q"] for c in data["cards"]] == ["Why one queue per region?", "What did Globex change?"]
    assert data["cards"][0]["a"].startswith("Latency. Each region")


def test_page_says_it_is_a_rehearse_page_for_the_interviews_tab(sheet):
    from jobwatch import interviews
    out = rehearse.write(sheet)
    assert interviews.sheet_role(out) == "rehearse"


def test_page_reads_only_the_card_fields_it_is_given(sheet):
    """The page once read c.answer from cards that carry only q and a, so showing an answer threw."""
    keys = set(_cards(rehearse.write(sheet).read_text(encoding="utf-8"))["cards"][0])
    used = set(re.findall(r"\bc\.([a-z]\w*)", rehearse.TEMPLATE.read_text(encoding="utf-8")))
    assert used and used <= keys


def test_unsafe_text_cannot_close_the_script_tag():
    cards = [drill.Card("Q </script><script>alert(1)</script>?", "A <!-- x --> & <b>y</b>.")]
    page = rehearse.build("Title </script> & <i>", cards)
    assert page.count("</script>") == 1   # the template's own closing tag, and no more
    assert "<!--" not in page.split("const DATA")[1].split("const TITLE")[0]
    assert "<title>Rehearse: Title &lt;/script&gt; &amp; &lt;i&gt;</title>" in page
    data = _cards(page)
    assert data["cards"][0]["q"] == "Q </script><script>alert(1)</script>?"
    assert data["title"] == "Title </script> & <i>"


def test_card_text_that_looks_like_a_placeholder_stays_as_is():
    page = rehearse.build("Initech", [drill.Card("What is __SECONDS__?", "__TITLE__ __CARDS__.")])
    assert _cards(page)["cards"][0] == {"q": "What is __SECONDS__?", "a": "__TITLE__ __CARDS__."}


def test_page_talks_only_to_jobwatch_ui_and_never_to_cloud_speech(sheet):
    page = rehearse.write(sheet, ui="http://jobwatch.localhost:9911/").read_text(encoding="utf-8")
    assert "SpeechRecognition" not in page and "XMLHttpRequest" not in page
    assert re.findall(r"https?://[^\s\"'<`]+", page) == ["http://jobwatch.localhost:9911"]
    assert 'const UI = "http://jobwatch.localhost:9911";' in page
    assert re.findall(r"fetch\(([^,)]*)", page) == ["UI + \"/rehearse/status\"", "UI + path"]
    assert set(re.findall(r'post\("(/rehearse/\w+)', page)) == {"/rehearse/transcribe", "/rehearse/feedback"}


def test_page_has_theme_and_width_controls_and_respects_reduced_motion():
    page = rehearse.build("Initech", [drill.Card("Why?", "Because. Latency.")])
    for group, choices in (("theme", ["system", "light", "dark"]), ("width", ["standard", "wide", "full"])):
        seg = re.search(rf'<div class="seg" id="{group}"[^>]*>(.*?)</div>', page).group(1)
        assert re.findall(r'data-v="(\w+)"', seg) == choices   # System first
    assert ':root[data-theme="dark"]' in page and "prefers-color-scheme: dark" in page
    assert "prefers-reduced-motion: reduce" in page
    assert 'id="progress"' in page and 'class="title" id="sheet"' in page


def test_page_script_parses(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node isn't installed")
    page = rehearse.build("Initech", [drill.Card("Why?", "Because. Latency.")])
    script = tmp_path / "page.js"
    script.write_text(re.search(r"<script>(.*)</script>", page, re.S).group(1), encoding="utf-8")
    done = subprocess.run([node, "--check", str(script)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_output_path(sheet, tmp_path):
    assert rehearse.write(sheet) == sheet.with_name("initech-sheet-rehearse.html")
    elsewhere = tmp_path / "out" / "mine.html"
    elsewhere.parent.mkdir()
    assert rehearse.write(sheet, elsewhere) == elsewhere
    assert elsewhere.is_file()


def test_sheet_without_answers_is_an_error(tmp_path):
    empty = tmp_path / "empty.html"
    empty.write_text("<html><body><p>Nothing here.</p></body></html>", encoding="utf-8")
    with pytest.raises(ValueError, match="no questions"):
        rehearse.write(empty)
    with pytest.raises(ValueError, match="no such prep sheet"):
        rehearse.write(tmp_path / "missing.html")


def test_command_no_open_writes_without_a_browser(sheet, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    cli.main(["rehearse", str(sheet), "--no-open"])
    assert opened == []
    assert sheet.with_name("initech-sheet-rehearse.html").is_file()
    assert "wrote" in capsys.readouterr().err


@pytest.fixture
def opened(monkeypatch):
    urls = []
    monkeypatch.setattr(cli.webbrowser, "open", urls.append)
    return urls


def at_terminal(monkeypatch, yes):
    monkeypatch.setattr(cli, "_at_a_terminal", lambda: yes)


def test_command_opens_the_page_at_a_terminal(sheet, tmp_path, opened, monkeypatch):
    at_terminal(monkeypatch, True)
    out = tmp_path / "page.html"
    cli.main(["rehearse", str(sheet), "-o", str(out)])
    assert opened == [out.resolve().as_uri()]


def test_command_does_not_open_the_page_when_not_at_a_terminal(sheet, tmp_path, opened, monkeypatch):
    at_terminal(monkeypatch, False)
    out = tmp_path / "page.html"
    cli.main(["rehearse", str(sheet), "-o", str(out)])
    assert opened == [] and out.is_file()


def test_command_open_flag_forces_the_browser_without_a_terminal(sheet, tmp_path, opened, monkeypatch):
    at_terminal(monkeypatch, False)
    out = tmp_path / "page.html"
    cli.main(["rehearse", str(sheet), "-o", str(out), "--open"])
    assert opened == [out.resolve().as_uri()]


def test_command_no_open_suppresses_the_browser_even_at_a_terminal(sheet, tmp_path, opened, monkeypatch):
    at_terminal(monkeypatch, True)
    cli.main(["rehearse", str(sheet), "-o", str(tmp_path / "page.html"), "--no-open"])
    assert opened == []


@pytest.mark.parametrize("stdin, stdout, expected", [(True, True, True), (True, False, False),
                                                     (False, True, False), (False, False, False)])
def test_a_terminal_needs_both_stdin_and_stdout_to_be_ttys(monkeypatch, stdin, stdout, expected):
    class Stream:
        def __init__(self, tty):
            self.tty = tty

        def isatty(self):
            return self.tty

    monkeypatch.setattr(cli.sys, "stdin", Stream(stdin))
    monkeypatch.setattr(cli.sys, "stdout", Stream(stdout))
    assert cli._at_a_terminal() is expected


def test_command_points_the_mic_at_another_ui(sheet, monkeypatch):
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: None)
    cli.main(["rehearse", str(sheet), "--no-open", "--ui", "http://127.0.0.1:9000"])
    page = sheet.with_name("initech-sheet-rehearse.html").read_text(encoding="utf-8")
    assert 'const UI = "http://127.0.0.1:9000";' in page


def test_command_reports_a_bad_sheet(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: None)
    with pytest.raises(SystemExit, match="no such prep sheet"):
        cli.main(["rehearse", str(tmp_path / "nope.html"), "--no-open"])
