import json

import pytest
import yaml

from jobwatch import autofill, chat, config
from jobwatch.store import Store
from jobwatch.web import App

from .conftest import TOKEN, request

FORM = "https://jobs.ashbyhq.com/initech/c1/application"


@pytest.fixture
def app(watchlist, web):
    raw = yaml.safe_load(watchlist.read_text())
    (watchlist.parent / "resume.txt").write_text("Jordan Rivera. Platform engineer. Python, Kubernetes.")
    raw.update(resume="resume.txt", pay={"target": 180000, "target_max": 200000},
               applicant={"first_name": "Jordan", "last_name": "Rivera", "email": "jordan@example.com",
                          "work_authorized": True, "needs_sponsorship": False})
    watchlist.write_text(yaml.safe_dump(raw))
    app = App(watchlist)
    app.post_fetch({})
    return app


def _store(app) -> Store:
    return Store(config.load(app.path).state)


def test_applicant_section(watchlist):
    cfg = config.load(watchlist)
    assert cfg.applicant.email == "" and cfg.applicant.gender == "decline"
    raw = yaml.safe_load(watchlist.read_text())
    raw["applicant"] = {"email": "jordan@example.com", "relocate": True, "notice_period": 2}
    watchlist.write_text(yaml.safe_dump(raw))
    a = config.load(watchlist).applicant
    assert (a.email, a.relocate, a.notice_period) == ("jordan@example.com", "yes", "2")
    for bad, match in (({"relocate": "maybe"}, "yes or no"), ({"shoe_size": "9"}, "unknown applicant"),
                       ({"email": ["a", "b"]}, "is text")):
        raw["applicant"] = bad
        watchlist.write_text(yaml.safe_dump(raw))
        with pytest.raises(config.ConfigError, match=match):
            config.load(watchlist)


def test_token_is_kept_until_renewed(tmp_path):
    state = tmp_path / "data" / "state.db"
    first = autofill.token(state)
    assert autofill.token(state) == first and len(first) > 20
    assert (tmp_path / "data" / "extension-token").stat().st_mode & 0o077 == 0  # only you can read it
    assert autofill.token(state, renew=True) != first


def test_context_for_an_application_page(app):
    earlier = app.post_add({"company": "Globex", "title": "SRE", "applied_at": "2026-09-14"})["key"]
    store = _store(app)
    try:
        store.package(earlier).write(answers=[{"question": "Notice period?", "answer": "Two weeks."}])
        got = autofill.context(config.load(app.path), store, FORM)
    finally:
        store.close()
    assert got["job"]["key"] == "ashby:initech:c1" and got["job"]["company"] == "Initech"
    a = got["applicant"]
    assert (a["first_name"], a["work_authorized"], a["needs_sponsorship"]) == ("Jordan", "yes", "no")
    assert a["salary"] == "180000-200000" and a["veteran"] == "decline"
    assert got["resume"] == {"name": "resume.txt", "type": "text/plain"}
    assert [(x["question"], x["answer"], x["company"]) for x in got["answers"]] == [
        ("Notice period?", "Two weeks.", "Globex")]


def test_a_page_jobwatch_doesnt_know(app):
    got = app.ext_context("https://careers.umbrella.example/jobs/42/apply")
    assert got["job"] is None and got["resume"]["name"] == "resume.txt"


def test_a_job_added_by_hand_is_found_by_its_link(app):
    app.post_add({"company": "Umbrella", "title": "Platform Engineer", "status": "queued",
                  "url": "https://careers.umbrella.example/jobs/42"})
    for page in ("https://careers.umbrella.example/jobs/42/apply", "https://careers.umbrella.example/jobs/42?src=x"):
        assert app.ext_context(page)["job"]["company"] == "Umbrella"


def test_submitted_records_the_application(app):
    sent = [{"question": "Why Initech?", "answer": "The platform work."}]
    got = app.ext_submitted({"url": FORM, "answers": sent, "resume": "resume.txt"})
    assert got == {"key": "ashby:initech:c1", "status": "applied", "added": False}
    store = _store(app)
    try:
        data = store.package("ashby:initech:c1").data()
        _, rec = store.find("ashby:initech:c1")
    finally:
        store.close()
    assert data["answers"] == sent and [f["kind"] for f in data["files"]] == ["resume"]
    assert rec["applied_at"]
    # Sent again (a second submit, the page reloaded): one copy of the resume, and the stage is kept.
    app.post_track({"key": "c1", "status": "screening"})
    assert app.ext_submitted({"url": FORM, "resume": "resume.txt"})["status"] == "screening"
    store = _store(app)
    try:
        assert len(store.package("ashby:initech:c1").data()["files"]) == 1
    finally:
        store.close()


def test_submitted_adds_a_page_it_doesnt_know(app):
    got = app.ext_submitted({"url": "https://careers.umbrella.example/jobs/42", "company": "Umbrella",
                             "title": "Platform Engineer"})
    assert got["added"] and got["status"] == "applied"
    with pytest.raises(ValueError, match="company and the job title"):
        app.ext_submitted({"url": "https://careers.globex.example/jobs/7"})


def test_draft(app, monkeypatch):
    seen = {}

    def reply(backend, system, messages, model="", max_tokens=0):
        seen.update(system=system, messages=messages)
        yield "I build platforms "
        yield "that teams trust."
        yield {"output_tokens": 9}

    monkeypatch.setattr(chat, "check", lambda *a: None)
    monkeypatch.setattr(chat, "reply", reply)
    got = app.ext_draft({"url": FORM, "question": "  Why do you want this role? ", "words": 80})
    assert got["answer"] == "I build platforms that teams trust."
    assert "about 80 words" in seen["system"] and "Staff Data Engineer" in seen["system"]
    assert "Kubernetes" in seen["system"] and seen["messages"][0]["content"].endswith("Why do you want this role?")
    with pytest.raises(ValueError, match="send the question"):
        app.ext_draft({"url": FORM, "question": " "})


def test_draft_says_what_to_set_up(app, monkeypatch):
    def unavailable(*a):
        raise chat.ChatUnavailable("Add an Anthropic API key in Settings > AI")
    monkeypatch.setattr(chat, "check", unavailable)
    with pytest.raises(ValueError, match="API key"):
        app.ext_draft({"url": FORM, "question": "Why us?"})


def test_extension_calls_need_its_token(server, watchlist):
    status, data = request(server, "GET", "/api/extension", headers={"X-Jobwatch-Token": TOKEN})
    token = json.loads(data)["token"]
    ok = {"X-Jobwatch-Extension": token}
    assert request(server, "GET", "/ext/ping")[0] == 403
    assert request(server, "GET", "/ext/ping", headers={"X-Jobwatch-Extension": "wrong"})[0] == 403
    status, data = request(server, "GET", "/ext/ping", headers=ok)
    assert status == 200 and json.loads(data)["ok"]
    # A web page calling the local server sends its own Origin: refused even with the token.
    assert request(server, "GET", "/ext/ping", headers={**ok, "Origin": "https://evil.example"})[0] == 403
    assert request(server, "GET", "/ext/ping", headers={**ok, "Origin": "chrome-extension://abc"})[0] == 200
    # The page's token isn't the extension's, and the other way round.
    assert request(server, "GET", "/ext/ping", headers={"X-Jobwatch-Extension": TOKEN})[0] == 403
    assert request(server, "GET", "/api/settings", headers={"X-Jobwatch-Token": token})[0] == 403
    status, data = request(server, "GET", f"/ext/resume?url={FORM}", headers=ok)
    assert status == 404 and "no resume" in json.loads(data)["error"]
    new = json.loads(request(server, "POST", "/api/extension/token", {}, headers={"X-Jobwatch-Token": TOKEN})[1])
    assert request(server, "GET", "/ext/ping", headers=ok)[0] == 403
    assert request(server, "GET", "/ext/ping", headers={"X-Jobwatch-Extension": new["token"]})[0] == 200


def test_extension_resume_is_the_file(server, watchlist):
    raw = yaml.safe_load(watchlist.read_text())
    (watchlist.parent / "resume.pdf").write_bytes(b"%PDF-1.4 fake")
    raw["resume"] = "resume.pdf"
    watchlist.write_text(yaml.safe_dump(raw))
    token = json.loads(request(server, "GET", "/api/extension", headers={"X-Jobwatch-Token": TOKEN})[1])["token"]
    status, body, headers = request(server, "GET", f"/ext/resume?url={FORM}",
                                    headers={"X-Jobwatch-Extension": token}, with_headers=True)
    assert status == 200 and body == b"%PDF-1.4 fake"
    assert headers["Content-Type"] == "application/pdf" and "resume.pdf" in headers["Content-Disposition"]
