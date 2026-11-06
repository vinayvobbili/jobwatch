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


def test_cards_come_through_from_the_sheet(sheet):
    out = rehearse.write(sheet)
    data = _cards(out.read_text(encoding="utf-8"))
    assert data["title"] == "Initech: interview prep"
    assert [c["q"] for c in data["cards"]] == ["Why one queue per region?", "What did Globex change?"]
    assert data["cards"][0]["a"].startswith("Latency. Each region")


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


def test_page_has_no_network_or_cloud_speech(sheet):
    page = rehearse.write(sheet).read_text(encoding="utf-8")
    assert "SpeechRecognition" not in page
    assert not re.search(r"https?://|fetch\(|XMLHttpRequest", page)


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


def test_command_opens_the_page_by_default(sheet, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    out = tmp_path / "page.html"
    cli.main(["rehearse", str(sheet), "-o", str(out)])
    assert opened == [out.resolve().as_uri()]


def test_command_reports_a_bad_sheet(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: None)
    with pytest.raises(SystemExit, match="no such prep sheet"):
        cli.main(["rehearse", str(tmp_path / "nope.html"), "--no-open"])
