import http.client
import json
import threading

import pytest
import yaml

from jobwatch import config
from jobwatch.web import ApiError, App, serve

TOKEN = "test-token"


@pytest.fixture
def app(watchlist):
    return App(watchlist)


def test_first_run_has_no_watchlist_until_saved(tmp_path, web):
    app = App(tmp_path / "new" / "config.yaml")
    assert app.get_settings({})["exists"] is False
    with pytest.raises(ApiError, match="No watchlist yet"):
        app.get_digest({})
    hits = app.post_find({"company": "Initech"})
    assert hits[0]["source"] == "ashby" and hits[0]["sample_titles"] == ["Staff AI Engineer"]
    app.post_settings({"companies": [{"source": "ashby", "board": "initech", "name": "Initech"}],
                       "filters": {"locations": ["remote", "Denver"]}, "keywords": {"RAG": 3}})
    s = app.get_settings({})
    assert s["exists"] and s["companies"] == [{"source": "ashby", "board": "initech", "name": "Initech"}]
    assert app.post_fetch({})["new"] == 1  # the unlisted role is skipped


def test_save_keeps_other_keys_and_a_backup(app, watchlist):
    before = watchlist.read_text()
    app.post_settings({"filters": {"titles": ["engineer"]}})
    raw = yaml.safe_load(watchlist.read_text())
    assert raw["filters"] == {"titles": ["engineer"]} and raw["state"] == "state.db" and len(raw["companies"]) == 3
    assert (watchlist.parent / "jobwatch.yaml.bak").read_text() == before


def test_a_bad_setting_leaves_the_file_alone(app, watchlist):
    before = watchlist.read_text()
    with pytest.raises(config.ConfigError, match="min_pay"):
        app.post_settings({"filters": {"min_pay": 1}})
    assert watchlist.read_text() == before
    assert not list(watchlist.parent.glob("*.new"))


def test_digest_marks_new_jobs_seen_and_queue_flow(app, web):
    app.post_fetch({})
    first = app.get_digest({})
    assert [j["status"] for j in first["jobs"]] == ["new"] * 3
    assert {j["status"] for j in app.get_digest({})["jobs"]} == {"shown"}
    app.post_mark({"keys": ["c1"], "status": "queued", "note": "referral first"})
    queued = app.get_queue({})
    assert [(j["key"], j["note"]) for j in queued] == [("ashby:initech:c1", "referral first")]
    assert "ashby:initech:c1" not in [j["key"] for j in app.get_digest({})["jobs"]]
    app.post_mark({"keys": ["c1"], "status": "applied"})
    assert [j["title"] for j in app.get_jobs({"status": ["applied"]})] == ["Staff AI Engineer"]
    assert app.get_job({"key": ["c1"]})["text"].startswith("# Staff AI Engineer")
    with pytest.raises(ApiError):
        app.post_mark({"keys": ["c1"], "status": "bogus"})


def test_score_needs_a_resume(app, web):
    app.post_fetch({})
    with pytest.raises(ApiError, match="Add your resume"):
        app.post_score({"key": "c1"})


def test_uploads(app, watchlist, web):
    csv = ("Notes:\n\nFirst Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
           "Ana,Li,,,Initech,Engineer,x\n")
    assert app.upload("connections", "Connections.csv", csv.encode()) == {"connections": "Connections.csv",
                                                                          "people": 1}
    assert app.upload("resume", "My CV.PDF", b"%PDF-1.4") == {"resume": "resume.pdf"}
    cfg = config.load(watchlist)
    assert cfg.resume == watchlist.parent / "resume.pdf" and cfg.connections.is_file()
    app.post_fetch({})
    assert app.get_digest({})["jobs"][0]["contacts"][0]["name"] == "Ana Li"
    with pytest.raises(ApiError, match=r"\.csv"):
        app.upload("connections", "c.xlsx", b"x")
    with pytest.raises(ApiError, match=r"Connections\.csv"):
        app.upload("connections", "c.csv", b"a,b\n")
    with pytest.raises(ApiError):
        app.upload("state", "state.db", b"x")


@pytest.fixture
def server(watchlist, web):
    srv = serve(watchlist, port=0, open_browser=False, token=TOKEN)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def request(port, method, path, body=None, headers=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Host": host or f"127.0.0.1:{port}", **(headers or {})}
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
    r = conn.getresponse()
    data = r.read()
    conn.close()
    return r.status, data


def test_page_carries_the_token(server):
    status, html = request(server, "GET", "/")
    assert status == 200 and f'const TOKEN = "{TOKEN}"' in html.decode()


def test_api_requires_the_token_and_a_local_host(server):
    ok = {"X-Jobwatch-Token": TOKEN}
    assert request(server, "GET", "/api/settings")[0] == 403
    assert request(server, "GET", "/api/settings", headers={"X-Jobwatch-Token": "wrong"})[0] == 403
    # DNS rebinding: right port, someone else's name.
    assert request(server, "GET", "/api/settings", headers=ok, host=f"evil.example:{server}")[0] == 403
    assert request(server, "GET", "/", host=f"evil.example:{server}")[0] == 403
    status, data = request(server, "GET", "/api/settings", headers=ok)
    assert status == 200 and len(json.loads(data)["companies"]) == 3
    status, data = request(server, "POST", "/api/fetch", {}, headers=ok, host=f"localhost:{server}")
    assert status == 200 and json.loads(data)["new"] == 5


def test_api_errors_are_json(server):
    ok = {"X-Jobwatch-Token": TOKEN}
    status, data = request(server, "GET", "/api/job?key=nope", headers=ok)
    assert status == 404 and "no job matches" in json.loads(data)["error"]
    assert request(server, "GET", "/api/nothing", headers=ok)[0] == 404
    assert request(server, "POST", "/api/mark", [], headers=ok)[0] == 400
