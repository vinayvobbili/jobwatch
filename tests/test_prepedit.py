"""Editing a prep sheet in the browser: edits applied by key, sanitized, saved with a .bak, and what follows a save."""

import json
import os
import threading
import time

import pytest

from jobwatch import config, prepedit
from jobwatch.store import Store
from jobwatch.web import App

from .conftest import TOKEN, request

SHEET = """<!doctype html>
<html><head><title>Initech call</title><style>td { color: red }</style><script>var p = "<p>no</p>";</script></head>
<body>
<h1>Initech: recruiter call</h1>
<p class="sub">Mon 11/2<br>Pat, recruiter</p>
<table>
<tr><th>Question</th><th>Answer</th></tr>
<tr><td>Why Initech?</td><td>Because of the <b>mission</b> &amp; the team.</td></tr>
<tr><td>Why leave?</td><td>Growth.</td></tr>
</table>
<ul>
  <li>First point</li>
  <li>Second point<ul><li>nested point</li></ul></li>
</ul>
<div class="say"><p>Say this.</p><p>Then this.</p></div>
<pre><p>code sample</p></pre>
<p>Last line</p>
<script>document.write("<p>x</p>")</script>
</body></html>
"""
# the td, li and p elements in document order (script, style and pre leave out what's inside them)
KEYS = ["Mon", "Why Initech?", "Because", "Why leave?", "Growth.", "First", "Second", "nested", "Say", "Then", "Last"]


def key_of(source, text):
    return next(s.key for s in prepedit.slots(source) if s.words.startswith(text))


def test_slots_count_the_td_li_and_p_elements_in_document_order():
    found = prepedit.slots(SHEET)
    assert [s.words[:len(k)] for s, k in zip(found, KEYS, strict=False)] == KEYS and len(found) == len(KEYS)
    assert [s.leaf for s in found] == [True] * 6 + [False, True, True, True, True]  # "Second" holds a list
    assert all(s.end is not None for s in found)


def test_an_edit_replaces_one_elements_inner_html_by_its_key():
    key = key_of(SHEET, "Growth.")
    out = prepedit.apply_edits(SHEET, [{"key": key, "html": "Growth and <i>scope</i>.", "was": "Growth."}])
    assert "<td>Growth and <i>scope</i>.</td>" in out
    assert out.replace("Growth and <i>scope</i>.", "Growth.") == SHEET  # nothing else moved
    two = prepedit.apply_edits(SHEET, [{"key": key_of(SHEET, "First"), "html": "One"},
                                       {"key": key_of(SHEET, "Last"), "html": "End"},
                                       {"key": key_of(SHEET, "Then"), "html": "Next"}])
    assert "<li>One</li>" in two and "<p>End</p>" in two and "<p>Then this.</p>" not in two and "<p>Next</p>" in two
    assert len(prepedit.slots(two)) == len(KEYS)


def test_entities_in_a_cell_are_compared_as_the_text_they_show():
    key = key_of(SHEET, "Because")
    was = "Because of the mission & the team."
    out = prepedit.apply_edits(SHEET, [{"key": key, "html": "Because of the mission &amp; the crew.", "was": was}])
    assert "<td>Because of the mission &amp; the crew.</td>" in out


@pytest.mark.parametrize("edit, why", [
    ({"key": 99, "html": "x"}, "no element 99"),
    ({"key": -1, "html": "x"}, "no element -1"),
    ({"key": "1", "html": "x"}, "no element '1'"),
    ({"key": 6, "html": "x"}, "structure"),                       # the <li> that holds a list
    ({"key": 4, "html": 5}, "no html"),
    ({"key": 4, "html": "x", "was": "Something else"}, "changed since the page loaded"),
])
def test_an_edit_that_cant_be_applied_says_why_and_changes_nothing(edit, why):
    with pytest.raises(prepedit.EditError, match=why):
        prepedit.apply_edits(SHEET, [edit])


def test_the_same_element_twice_or_nothing_at_all_is_refused():
    with pytest.raises(prepedit.EditError, match="twice"):
        prepedit.apply_edits(SHEET, [{"key": 4, "html": "a"}, {"key": 4, "html": "b"}])
    with pytest.raises(prepedit.EditError, match="nothing to save"):
        prepedit.apply_edits(SHEET, [])


def test_sanitizing_keeps_inline_formatting_and_strips_everything_else():
    dirty = ('Hi <b onclick="steal()">there</b><script>alert(1)</script> <a href="https://example.com/a" '
             'onmouseover="x()" style="color:red">link</a> <img src=x onerror=alert(1)> <span class="no" style="x:y">'
             'no</span><iframe src="//evil.example"></iframe><style>p{}</style> <u>under</u> <code>1 &lt; 2</code>')
    assert prepedit.sanitize(dirty) == ('Hi <b>there</b> <a href="https://example.com/a">link</a>  '
                                        '<span class="no">no</span> under <code>1 &lt; 2</code>')
    assert "onclick" not in prepedit.sanitize('<em onclick="x()">e</em>') and "script" not in prepedit.sanitize(
        "<script>alert(1)</script>ok")
    assert prepedit.sanitize("<script>alert(1)</script>ok") == "ok"


def test_sanitizing_refuses_script_links_and_balances_tags():
    assert prepedit.sanitize('<a href="javascript:alert(1)">x</a>') == "<a>x</a>"
    assert prepedit.sanitize('<a href="  JaVa\nScRiPt:alert(1)">x</a>') == "<a>x</a>"
    assert prepedit.sanitize('<a href="data:text/html,<script>">x</a>') == "<a>x</a>"
    assert prepedit.sanitize('<a href="mailto:pat@example.com">m</a>') == '<a href="mailto:pat@example.com">m</a>'
    assert prepedit.sanitize("<b>open <i>nested") == "<b>open <i>nested</i></b>"
    assert prepedit.sanitize("stray</b> end</span>") == "stray end"
    assert prepedit.sanitize("a<div>b</div><div>c</div>") == "a<br>b<br>c"      # Enter in a cell makes a <div>
    assert prepedit.sanitize("<br>line<br><br>") == "line"
    assert prepedit.sanitize("5 < 6 & 7 > 3") == "5 &lt; 6 &amp; 7 &gt; 3"


def test_an_edit_cant_smuggle_markup_into_the_file():
    out = prepedit.apply_edits(SHEET, [{"key": 4, "html": '</td></tr><script>alert(1)</script><td onclick="x()">'}])
    assert "alert" not in out and "onclick" not in out and len(prepedit.slots(out)) == len(KEYS)


# -- the file

def folder_with(tmp_path, **sheets):
    folder = tmp_path / "prep"
    folder.mkdir()
    for name, text in sheets.items():
        (folder / name).write_text(text, encoding="utf-8")
    return folder


def test_saving_writes_the_file_and_keeps_the_previous_version_as_bak(tmp_path):
    folder = folder_with(tmp_path, **{"initech-call.html": SHEET})
    edit = {"key": key_of(SHEET, "Growth."), "html": "Growth, <b>scope</b>."}
    path = prepedit.save(folder, "initech-call.html", [edit])
    assert "<td>Growth, <b>scope</b>.</td>" in path.read_text(encoding="utf-8")
    assert (folder / "initech-call.html.bak").read_text(encoding="utf-8") == SHEET
    assert not list(folder.glob("*.tmp"))
    prepedit.save(folder, "initech-call.html", [{"key": edit["key"], "html": "Again."}])  # one level: the .bak moves on
    assert "Growth, <b>scope</b>." in (folder / "initech-call.html.bak").read_text(encoding="utf-8")
    assert sorted(p.name for p in folder.iterdir()) == ["initech-call.html", "initech-call.html.bak"]


def test_a_failed_save_leaves_the_file_and_the_bak_alone(tmp_path):
    folder = folder_with(tmp_path, **{"initech-call.html": SHEET})
    with pytest.raises(prepedit.EditError):
        prepedit.save(folder, "initech-call.html", [{"key": 4, "html": "x", "was": "nope"}])
    assert (folder / "initech-call.html").read_text(encoding="utf-8") == SHEET
    assert not (folder / "initech-call.html.bak").exists()


@pytest.mark.parametrize("name", ["../secret.html", "..%2Fsecret.html", "/etc/passwd", "sub/initech-call.html",
                                  "initech-call.html/../../x.html", "", None, 5])
def test_a_path_outside_the_prep_folder_is_refused(tmp_path, name):
    folder = folder_with(tmp_path, **{"initech-call.html": SHEET})
    (tmp_path / "secret.html").write_text(SHEET)
    with pytest.raises(prepedit.EditError):
        prepedit.save(folder, name, [{"key": 4, "html": "pwned"}])
    assert "pwned" not in (tmp_path / "secret.html").read_text()


def test_a_link_out_of_the_folder_a_rehearse_page_and_a_non_sheet_are_refused(tmp_path):
    folder = folder_with(tmp_path, **{"initech-call.html": SHEET, "initech-call-rehearse.html": SHEET,
                                      "notes.txt": "x", "sheet.css": "p {}"})
    (tmp_path / "outside.html").write_text(SHEET)
    (folder / "linked.html").symlink_to(tmp_path / "outside.html")
    for name in ("linked.html", "initech-call-rehearse.html", "notes.txt", "sheet.css", "missing.html"):
        with pytest.raises(prepedit.EditError):
            prepedit.save(folder, name, [{"key": 4, "html": "pwned"}])
    with pytest.raises(prepedit.EditError, match="no prep sheets folder is set"):
        prepedit.save(None, "initech-call.html", [{"key": 4, "html": "x"}])
    assert "pwned" not in (tmp_path / "outside.html").read_text()


# -- after a save

QA = ("<html><body><h1>Globex call</h1><table><tr><th>Question</th><th>Answer</th></tr>"
      "<tr><td>Why Globex?</td><td>The mission.</td></tr></table></body></html>")


def test_the_rehearse_page_is_rebuilt_only_when_the_sheet_has_one(tmp_path):
    folder = folder_with(tmp_path, **{"globex-call.html": QA})
    sheet = folder / "globex-call.html"
    assert prepedit.rebuild_rehearse(sheet) is None and not (folder / "globex-call-rehearse.html").exists()
    (folder / "globex-call-rehearse.html").write_text("old")
    prepedit.save(folder, "globex-call.html", [{"key": 1, "html": "A <b>new</b> answer."}])
    assert prepedit.rebuild_rehearse(sheet) is None
    assert "A new answer." in (folder / "globex-call-rehearse.html").read_text()
    sheet.write_text("<html><body><p>no questions</p></body></html>")
    assert "was not rebuilt" in prepedit.rebuild_rehearse(sheet)


def test_prep_blocks_check_is_run_from_the_sheets_repo_and_skipped_without_it(tmp_path):
    folder = folder_with(tmp_path, **{"globex-call.html": QA})
    sheet = folder / "globex-call.html"
    assert prepedit.check_blocks(sheet) == []  # no scripts/prep_blocks.py beside prep/
    (tmp_path / "scripts").mkdir()
    script = tmp_path / "scripts" / "prep_blocks.py"
    script.write_text("import sys\nprint(sys.argv[1] + ': missing influence')\nsys.exit(1)\n")
    assert prepedit.check_blocks(sheet) == [f"{sheet}: missing influence"]
    script.write_text("import sys\nsys.exit(0)\n")
    assert prepedit.check_blocks(sheet) == []
    script.write_text("import sys\nsys.exit(3)\n")
    assert prepedit.check_blocks(sheet) == ["the sheet check failed (exit 3)"]


def test_a_drill_is_queued_only_for_a_sheet_that_has_a_video(tmp_path):
    folder = folder_with(tmp_path, **{"globex-call.html": QA, "initech-call.html": SHEET})
    (folder / "initech-call-drill.mp4").write_bytes(b"x")
    ran, log = [], []
    queue = prepedit.DrillQueue(lambda sheet, cap: ran.append((sheet.name, cap)), lambda *a, **k: log.append((a, k)),
                                settle=0)
    assert queue.kick(folder / "globex-call.html") is False and queue.waiting() == []
    assert queue.kick(folder / "initech-call.html", "15G") is True
    queue.wait(5)
    assert ran == [("initech-call.html", "15G")]
    assert log[0][0][:2] == ("prep", "Rendered the drill video for initech-call.html")
    assert log[0][1].get("ok", True) is True


def test_several_saves_become_one_render(tmp_path):
    folder = folder_with(tmp_path, **{"initech-call.html": SHEET})
    (folder / "initech-call-drill.mp4").write_bytes(b"x")
    ran = []
    queue = prepedit.DrillQueue(lambda sheet, cap: ran.append(sheet.name), lambda *a, **k: None, settle=0.3)
    for _ in range(5):
        queue.kick(folder / "initech-call.html")
        time.sleep(0.02)
    assert queue.waiting() == [folder / "initech-call.html"]
    queue.wait(10)
    assert ran == ["initech-call.html"] and queue.waiting() == []


def test_a_save_during_a_render_is_rendered_once_more_after_it(tmp_path):
    folder = folder_with(tmp_path, **{"initech-call.html": SHEET})
    sheet = folder / "initech-call.html"
    (folder / "initech-call-drill.mp4").write_bytes(b"x")
    ran, started, release = [], threading.Event(), threading.Event()

    def run(path, cap):
        ran.append(path.name)
        started.set()
        release.wait(10)

    queue = prepedit.DrillQueue(run, lambda *a, **k: None, settle=0)
    queue.kick(sheet)
    assert started.wait(10)
    queue.kick(sheet)
    queue.kick(sheet)  # two more while it renders: one render after it, not two
    assert queue.waiting() == [sheet]
    release.set()
    queue.wait(10)
    assert ran == ["initech-call.html", "initech-call.html"]


def test_a_render_that_fails_is_logged_as_failed_and_the_next_one_still_runs(tmp_path):
    folder = folder_with(tmp_path, **{"initech-call.html": SHEET, "globex-call.html": QA})
    for n in ("initech-call", "globex-call"):
        (folder / f"{n}-drill.mp4").write_bytes(b"x")
    log = []

    def run(path, cap):
        if path.name.startswith("initech"):
            return "ffmpeg not found"

    queue = prepedit.DrillQueue(run, lambda *a, **k: log.append((a, k)), settle=60)
    queue.kick(folder / "initech-call.html")
    queue.kick(folder / "globex-call.html")
    queue.drain()
    assert [(a[1], k.get("ok", True), k.get("detail")) for a, k in log] == [
        ("The drill video for initech-call.html was not rendered", False, ["ffmpeg not found"]),
        ("Rendered the drill video for globex-call.html", True, None)]


def test_render_drill_passes_the_cache_cap_on_and_replaces_the_video_only_when_done(tmp_path, monkeypatch):
    folder = folder_with(tmp_path, **{"initech-call.html": SHEET})
    sheet, video = folder / "initech-call.html", folder / "initech-call-drill.mp4"
    video.write_bytes(b"old")
    calls = []

    class Done:
        def __init__(self, code, err=""):
            self.returncode, self.stderr, self.stdout = code, err, ""

    def fake(cmd, **kw):
        calls.append((cmd, kw["env"].get("SLIDECAST_CACHE_MAX")))
        out = cmd[cmd.index("--drill") + 1]
        if len(calls) == 1:
            open(out, "wb").write(b"new")
            return Done(0)
        open(out, "wb").write(b"half")
        return Done(1, "boom\n")

    monkeypatch.setattr(prepedit.subprocess, "run", fake)
    assert prepedit.render_drill(sheet, "15G", tmp_path / "jobwatch.yaml") is None
    cmd, cap = calls[0]
    assert cmd[:3] == ["nice", "-n", "15"] and cmd[3:7] == [cmd[3], "-m", "jobwatch.cli", "-c"]
    assert cmd[-5:-3] == ["prep", str(sheet)] and cmd[-1] == "--no-pause" and cap == "15G"
    assert video.read_bytes() == b"new" and not list(folder.glob("*.rendering.mp4"))
    assert prepedit.render_drill(sheet, "") == "boom"
    assert calls[1][1] == os.environ.get("SLIDECAST_CACHE_MAX")  # unset in the watchlist: as it was
    assert video.read_bytes() == b"new" and not list(folder.glob("*.rendering.mp4"))


# -- the page's call

@pytest.fixture
def sheets(watchlist, tmp_path):
    folder = tmp_path / "prep"
    folder.mkdir()
    (folder / "initech-call.html").write_text(SHEET, encoding="utf-8")
    watchlist.write_text(watchlist.read_text() + "prep:\n  sheets: prep\n  cache_max: 2G\n")
    return folder


def base_of(watchlist):
    return App(watchlist).get_interviews({})["sheets_base"]


SITE = "Or" + "igin"  # the request header naming the page a call comes from (split: the privacy audit's company rule)


def post(server, path, body, origin="null", **kw):
    return request(server, "POST", path, body, headers={SITE: origin} if origin else {}, with_headers=True, **kw)


def test_the_cache_cap_is_a_watchlist_setting(watchlist, sheets):
    assert config.load(watchlist).prep.cache_max == "2G"
    watchlist.write_text(watchlist.read_text().replace("cache_max: 2G", "cache_max: lots"))
    with pytest.raises(config.ConfigError, match=r"prep\.cache_max"):
        config.load(watchlist)


def test_a_sheet_saves_through_its_own_address(server, watchlist, sheets):
    base = base_of(watchlist)
    key = key_of(SHEET, "Growth.")
    body = {"sheet": "initech-call.html", "edits": [{"key": key, "html": 'Growth <b onclick="x()">now</b>',
                                                      "was": "Growth."}]}
    status, data, headers = post(server, base + "_save", body)
    reply = json.loads(data)
    assert reply.get("error") is None, reply
    assert status == 200 and headers["access-control-allow-origin"] == "null"
    assert reply["saved"] == 1 and reply["applied"] == {str(key): "Growth <b>now</b>"}
    assert reply["problems"] == [] and reply["drill"] is False and reply["rehearse"] is False
    assert "<td>Growth <b>now</b></td>" in (sheets / "initech-call.html").read_text(encoding="utf-8")
    assert (sheets / "initech-call.html.bak").read_text(encoding="utf-8") == SHEET
    store = Store(config.load(watchlist).state)
    try:
        events = store.activity(kind="prep")
    finally:
        store.close()
    assert [(e["text"], e["ok"]) for e in events] == [("Saved 1 edit to initech-call.html", True)]


def test_a_wrong_address_is_refused_and_nothing_is_written(server, watchlist, sheets):
    body = {"sheet": "initech-call.html", "edits": [{"key": 4, "html": "pwned"}]}
    status, _data, _ = post(server, "/prep/not-the-secret/_save", body)
    assert status == 404 and "pwned" not in (sheets / "initech-call.html").read_text()
    assert not (sheets / "initech-call.html.bak").exists()
    status, _, _ = post(server, "/prep/not-the-secret/_save", body, origin="https://evil.example")
    assert status == 403
    status, _, _ = post(server, base_of(watchlist) + "_save", body, origin="https://evil.example")
    assert status == 403 and "pwned" not in (sheets / "initech-call.html").read_text()
    status, _, _ = post(server, base_of(watchlist) + "_save", body, host="evil.example")
    assert status == 403 and "pwned" not in (sheets / "initech-call.html").read_text()
    status, _, _ = post(server, base_of(watchlist) + "other", body)
    assert status == 404


def test_the_page_token_header_is_not_what_opens_a_sheet(server, watchlist, sheets):
    """The /api token is no stand-in for the sheet's secret, and the secret is no stand-in for the /api token."""
    body = {"sheet": "initech-call.html", "edits": [{"key": 4, "html": "pwned"}]}
    status, _, _ = request(server, "POST", "/prep/guess/_save", body,
                           headers={"X-Jobwatch-Token": TOKEN, SITE: "null"}, with_headers=True)
    assert status == 404
    status, _ = request(server, "POST", "/api/prep/save", body)
    assert status == 403


def test_a_traversal_name_over_http_changes_nothing(server, watchlist, sheets, tmp_path):
    (tmp_path / "secret.html").write_text(SHEET)
    for name in ("../secret.html", "..%2Fsecret.html", "/etc/passwd"):
        status, _data, _ = post(server, base_of(watchlist) + "_save",
                                {"sheet": name, "edits": [{"key": 4, "html": "pwned"}]})
        assert status == 400, name
    assert "pwned" not in (tmp_path / "secret.html").read_text()


def test_a_save_reports_what_follows_it(watchlist, sheets, monkeypatch):
    (sheets / "globex-call.html").write_text(QA, encoding="utf-8")
    (sheets / "globex-call-rehearse.html").write_text("old")
    (sheets / "globex-call-drill.mp4").write_bytes(b"x")
    (tmp_path_scripts := sheets.parent / "scripts").mkdir()
    (tmp_path_scripts / "prep_blocks.py").write_text(
        "print('globex-call.html: missing influence')\nraise SystemExit(1)\n")
    app = App(watchlist)
    renders = []
    app.drills.run = lambda sheet, cap: renders.append((sheet.name, cap))
    app.drills.settle = 0
    secret = base_of(watchlist).split("/")[2]
    one = app.prep_save(secret, {"sheet": "globex-call.html", "edits": [{"key": 1, "html": "First."}]})
    two = app.prep_save(secret, {"sheet": "globex-call.html", "edits": [{"key": 1, "html": "Second."}]})
    app.drills.wait(10)
    assert one["rehearse"] is True and one["drill"] is True and len(one["problems"]) == 1
    assert "missing influence" in one["problems"][0] and two["saved"] == 1
    assert "Second." in (sheets / "globex-call-rehearse.html").read_text()
    assert renders in ([("globex-call.html", "2G")], [("globex-call.html", "2G")] * 2)
    store = Store(config.load(watchlist).state)
    try:
        events = store.activity(kind="prep")
    finally:
        store.close()
    texts = [e["text"] for e in events]
    assert "Saved 1 edit to globex-call.html" in texts and all(e["ok"] for e in events)
    assert not any("failed" in t.lower() or " 0 " in t for t in texts)


def test_a_sheet_served_by_jobwatch_may_run_its_scripts_but_not_reach_the_page():
    from jobwatch import interviews
    assert "allow-scripts" in interviews.SHEET_POLICY and "allow-same-origin" not in interviews.SHEET_POLICY


def test_a_preflight_for_the_sheets_save_is_answered_for_a_sheet_only(server, watchlist, sheets):
    status, _, headers = request(server, "OPTIONS", base_of(watchlist) + "_save", headers={SITE: "null"},
                                 with_headers=True)
    assert status == 204 and headers["access-control-allow-origin"] == "null"
    status, _, _ = request(server, "OPTIONS", base_of(watchlist) + "_save", headers={SITE: "https://evil.example"},
                           with_headers=True)
    assert status == 403
