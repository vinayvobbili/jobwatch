import json

import pytest

from jobwatch import chat, cli, sources
from jobwatch.package import MANIFEST, POSTING, Package, kind_of
from jobwatch.web import App

from .conftest import TOKEN, request


@pytest.fixture
def pkg(tmp_path):
    return Package(tmp_path / "packages", "ashby:initech:c1")


def test_files_are_copies_kept_once_under_safe_names(pkg):
    assert pkg.attach("Jane Doe Resume.pdf", b"%PDF-1") == "Jane_Doe_Resume.pdf"
    assert pkg.attach("../elsewhere/Jane Doe Resume.pdf", b"%PDF-1") == "Jane_Doe_Resume.pdf"  # same bytes: once
    assert pkg.attach("Jane Doe Resume.pdf", b"%PDF-2") == "Jane_Doe_Resume-2.pdf"  # a rebuilt one: both kept
    assert pkg.attach("notes", b"x", kind="other") == "notes"
    assert pkg.dir.name == "ashby_initech_c1" and (pkg.dir / "Jane_Doe_Resume.pdf").read_bytes() == b"%PDF-1"
    assert [f["kind"] for f in pkg.data()["files"]] == ["other", "resume", "resume"]
    assert pkg.resume().name == "Jane_Doe_Resume-2.pdf"  # the latest resume
    for bad in (b"", b"x" * (20 * 1024 * 1024 + 1)):
        with pytest.raises(ValueError):
            pkg.attach("a.pdf", bad)
    with pytest.raises(ValueError, match="kind"):
        pkg.attach("a.pdf", b"x", kind="photo")


def test_kind_from_the_name():
    assert [kind_of(n) for n in ("Resume_Acme.pdf", "my-cv.docx", "Cover Letter.pdf", "portfolio.pdf")] == \
        ["resume", "resume", "letter", "other"]


def test_only_listed_files_can_be_read_or_removed(pkg):
    pkg.attach("resume.pdf", b"%PDF")
    for name in ("../state.db", MANIFEST, "missing.pdf"):
        with pytest.raises(KeyError):
            pkg.path(name)
    pkg.remove("resume.pdf")
    assert pkg.data()["files"] == [] and not (pkg.dir / "resume.pdf").exists()
    assert [p.name.endswith("-resume.pdf") for p in (pkg.dir / ".removed").iterdir()] == [True]  # moved, not deleted


def test_answers_and_note(pkg):
    assert pkg.context() == "" and pkg.summary() == {"files": 0, "answers": 0, "note": False}
    pkg.write(answers=[{"question": "Why us?", "answer": " The product. "}, {"question": " ", "answer": ""}],
              note="Hi, I'm applying for...")
    pkg.write(note=None)  # None leaves it
    d = pkg.data()
    assert d["answers"] == [{"question": "Why us?", "answer": "The product."}]
    assert d["note"] == "Hi, I'm applying for..."
    assert "Q: Why us?\nA: The product." in pkg.context() and "Cover letter or message:" in pkg.context()
    with pytest.raises(ValueError):
        pkg.write(answers="Why us? The product.")


def test_applying_saves_the_posting_as_it_read_then(tmp_path, web):
    from jobwatch.store import Store

    store = Store(tmp_path / "state.db")
    board = sources.fetch("ashby", "initech")
    store.sync("ashby", "initech", board)
    store.set_status([board[0].key], "applied")
    saved = (store.package(board[0].key).dir / POSTING).read_text()
    board[0].description = "Edited after you applied."
    store.sync("ashby", "initech", board)
    store.set_status([board[0].key], "interviewing")
    assert (store.package(board[0].key).dir / POSTING).read_text() == saved  # the first save stands
    assert "Edited" not in saved and store.package(board[0].key).data()["posting_saved"]
    store.close()


def test_the_page_attaches_shows_and_serves_files(server):
    ok = {"X-Jobwatch-Token": TOKEN}
    request(server, "POST", "/api/fetch", {}, headers=ok)
    request(server, "POST", "/api/mark", {"keys": ["c1"], "status": "applied"}, headers=ok)
    status, data = request(server, "POST", "/api/package/file?key=c1&name=Resume%20Acme.pdf", None,
                           headers={**ok, "Content-Length": "4"}, raw=b"%PDF")
    assert status == 200 and json.loads(data)["files"][0]["name"] == "Resume_Acme.pdf"
    request(server, "POST", "/api/package/file?key=c1&name=page.html", None, headers=ok, raw=b"<script>x</script>")
    request(server, "POST", "/api/package", {"key": "c1", "answers": [{"question": "Salary?", "answer": "Open"}]},
            headers=ok)
    job = json.loads(request(server, "GET", "/api/job?key=c1", headers=ok)[1])
    assert [f["name"] for f in job["package"]["files"]] == ["page.html", "Resume_Acme.pdf"]
    assert job["package"]["answers"][0]["answer"] == "Open" and job["package"]["posting_saved"]
    apps = json.loads(request(server, "GET", "/api/applications", headers=ok)[1])["applications"]
    assert apps[0]["package"] == {"files": 2, "answers": 1, "note": False}

    status, body, headers = request(server, "GET", "/api/package/file?key=c1&name=Resume_Acme.pdf", headers=ok,
                                    with_headers=True)
    assert status == 200 and body == b"%PDF" and headers["Content-Type"] == "application/pdf"
    assert headers["Content-Disposition"].startswith("inline") and headers["Content-Security-Policy"] == "sandbox"
    status, _, headers = request(server, "GET", "/api/package/file?key=c1&name=page.html", headers=ok,
                                 with_headers=True)
    assert headers["Content-Type"] == "application/octet-stream"  # never served as a page
    assert headers["Content-Disposition"].startswith("attachment")
    assert request(server, "GET", "/api/package/file?key=c1&name=Resume_Acme.pdf")[0] == 403  # no token
    assert request(server, "GET", "/api/package/file?key=c1&name=..%2Fstate.db", headers=ok)[0] == 404
    status, data = request(server, "POST", "/api/package/remove", {"key": "c1", "name": "page.html"}, headers=ok)
    assert [f["name"] for f in json.loads(data)["files"]] == ["Resume_Acme.pdf"]


def test_chat_about_a_job_reads_what_was_sent(watchlist, web, monkeypatch):
    seen = {}
    monkeypatch.setattr(chat, "check", lambda backend: None)
    monkeypatch.setattr(chat, "reply", lambda backend, system, messages: seen.update(system=system) or iter(["ok"]))
    app = App(watchlist)
    app.post_fetch({})
    (watchlist.parent / "general.md").write_text("General resume.")
    app.post_settings({"resume": "general.md"})
    ask = {"key": "c1", "messages": [{"role": "user", "content": "Prep me"}]}
    app.chat(ask)
    assert "General resume." in seen["system"]
    app.attach("c1", "resume-initech.md", "", b"Tailored for Initech.")
    app.post_package({"key": "c1", "answers": [{"question": "Why Initech?", "answer": "Their RAG work."}]})
    app.chat(ask)
    assert "resume the user sent for this job (resume-initech.md)" in seen["system"]
    assert "Tailored for Initech." in seen["system"] and "General resume." not in seen["system"]
    assert "Q: Why Initech?\nA: Their RAG work." in seen["system"]


def test_command_line(watchlist, web, tmp_path, capsys):
    cv, answers, letter = tmp_path / "cv.pdf", tmp_path / "answers.yaml", tmp_path / "letter.txt"
    cv.write_bytes(b"%PDF")
    answers.write_text("Why us?: Your agents platform\nSalary expectation: 200000\n")
    letter.write_text("Dear team,")
    cli.main(["-c", str(watchlist), "fetch"])
    cli.main(["-c", str(watchlist), "mark", "applied", "c1", "--attach", str(cv)])
    cli.main(["-c", str(watchlist), "attach", "c1", "--answers", str(answers), "--message", str(letter)])
    out = capsys.readouterr().out
    assert "kept cv.pdf" in out and "Q: Salary expectation\nA: 200000" in out and "Dear team," in out
    assert "Files: cv.pdf (resume" in out and "Posting as it read on" in out
    cli.main(["-c", str(watchlist), "package", "aaaa-1111"])
    assert "Nothing kept yet" in capsys.readouterr().out


def test_mcp_tools(watchlist, web, tmp_path, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    cli.main(["-c", str(watchlist), "fetch"])
    cv = tmp_path / "Resume.pdf"
    cv.write_bytes(b"%PDF")
    saved = mcp.save_application_package("c1", files=[str(cv)], answers=[{"question": "Q", "answer": "A"}])
    assert saved["files"][0]["name"] == "Resume.pdf" and mcp.application_package("c1")["answers"] == saved["answers"]


def test_mcp_job_details_and_notes(watchlist, web, monkeypatch, capsys):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    cli.main(["-c", str(watchlist), "fetch"])
    d = mcp.job_details("aaaa-1111")
    assert d["company"] == "globex" and d["fit"] is None and "linkedin.com" in d["find_referral"]
    assert any(g["id"] == "ml" for g in d["skill_gaps"]) and d["package"]["files"] == []
    assert mcp.mark_job("aaaa-1111", "applied", note="Recruiter Ana.").endswith(": applied")
    assert mcp.mark_job("aaaa-1111", add_note="she replied: onsite only", follow_up="").endswith(": applied")
    note = mcp.job_details("aaaa-1111")["note"]
    assert note.startswith("Recruiter Ana. 20") and note.endswith(": she replied: onsite only")
    cli.main(["-c", str(watchlist), "mark", "withdrawn", "aaaa-1111", "--add-note", "dropped"])
    assert mcp.job_details("aaaa-1111")["note"].startswith("Recruiter Ana.")
