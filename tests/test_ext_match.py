"""Which job a browser tab is for (autofill.match), and the extension's context, ATS check, cover letter and draft on
that job: the job's own board page, a LinkedIn or Indeed page of a job that came from an alert, and the company's own
careers page for such a job (another host than the one jobwatch keeps). The model is faked; nothing leaves the test."""

import json
from urllib.parse import quote

import pytest
import yaml

from jobwatch import autofill, chat, config, cover
from jobwatch.store import Store
from jobwatch.web import App

from .conftest import TOKEN, request

LEVER = "lever:globex:aaaa-1111"  # Globex, Machine Learning Engineer (its board's job, from the fake Lever)
ASHBY = "ashby:initech:c1"        # Initech, Staff Data Engineer
LI_BOARD = "https://www.linkedin.com/jobs/view/4000000001/"  # the LinkedIn listing of the Globex job
LI_ONLY = "https://www.linkedin.com/jobs/view/4000000002/"   # a LinkedIn job with no board behind it: Umbrella
INDEED_KEY = "0000000000000001"
INDEED = f"https://www.indeed.com/viewjob?jk={INDEED_KEY}"
GLOBEX_SITE = "https://careers.globex.example/openings/machine-learning/apply"
POSTING = "Run the platform on Kubernetes with Python and Terraform.\n\nRequirements:\n- 5+ years of Python\n"


@pytest.fixture
def app(watchlist, web):
    raw = yaml.safe_load(watchlist.read_text())
    (watchlist.parent / "resume.txt").write_text("Jordan Rivera. Platform engineer. Python, Kubernetes, Terraform, "
                                                 "machine learning platforms.")
    raw.update(resume="resume.txt")
    watchlist.write_text(yaml.safe_dump(raw))
    app = App(watchlist)
    app.post_fetch({})
    return app


@pytest.fixture
def ctx(app):
    """(cfg, store) with the jobs an alert leaves: the Globex job matched to its board (the alert's link only in its
    note), an Umbrella job kept at its LinkedIn link, and an Indeed job at Hooli kept at its Indeed link."""
    cfg = config.load(app.path)
    store = Store(cfg.state)
    store.set_status([LEVER], "queued", None)
    store.add_note(LEVER, f"From a LinkedIn job alert: {LI_BOARD}")
    store.add("Umbrella", "Platform Engineer", url=LI_ONLY, status="queued", description=POSTING)
    store.add("Hooli", "Site Reliability Engineer", url=INDEED, status="queued", description=POSTING)
    yield cfg, store
    store.close()


def how(store, url, company="", title=""):
    got = autofill.match(store, url, company, title)
    return got and (got[0].key, got[2])


# --- the job's own board page ------------------------------------------------------------------------


@pytest.mark.parametrize("page", ["https://jobs.ashbyhq.com/initech/c1", "https://jobs.ashbyhq.com/initech/c1/application",
                                  "https://jobs.ashbyhq.com/initech/c1/application?utm_source=linkedin"])
def test_the_jobs_own_board_page_matches_by_its_posting_id(ctx, page):
    assert how(ctx[1], page) == (ASHBY, "board")


def test_a_lever_form_matches_too(ctx):
    assert how(ctx[1], "https://jobs.lever.co/globex/aaaa-1111/apply") == (LEVER, "board")


# --- LinkedIn and Indeed pages of a job that came from an alert --------------------------------------------


@pytest.mark.parametrize("page", [
    LI_BOARD, LI_BOARD.rstrip("/"), LI_BOARD + "?trackingId=abc",
    "https://www.linkedin.com/jobs/view/machine-learning-engineer-at-globex-4000000001/",
    "https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4000000001"])
def test_a_linkedin_page_finds_the_job_by_its_id_even_when_its_board_link_is_kept(ctx, page):
    """The alert's job was matched to the company's board, so its link is the board's: the LinkedIn id is only in
    its note."""
    assert how(ctx[1], page) == (LEVER, "linkedin")


@pytest.mark.parametrize("page, by", [
    (LI_ONLY, "link"), ("https://www.linkedin.com/jobs/view/umbrella-4000000002", "linkedin"),
    ("https://www.linkedin.com/jobs/search/?currentJobId=4000000002&keywords=x", "linkedin")])
def test_a_linkedin_page_finds_a_job_kept_at_its_linkedin_link(ctx, page, by):
    assert how(ctx[1], page) == ("manual:umbrella:platform-engineer", by)


def test_an_indeed_page_finds_the_job_by_its_key(ctx):
    store = ctx[1]
    assert how(store, INDEED) == ("manual:hooli:site-reliability-engineer", "link")
    assert how(store, f"https://www.indeed.com/jobs?q=sre&vjk={INDEED_KEY}") == (
        "manual:hooli:site-reliability-engineer", "indeed")


def test_another_linkedin_job_is_not_this_one(ctx):
    assert how(ctx[1], "https://www.linkedin.com/jobs/view/4000000099/", "Globex", "Machine Learning Engineer") is None


def test_a_closed_job_is_not_found_by_its_id(ctx):
    store = ctx[1]
    store.db.execute("UPDATE jobs SET closed='2026-11-01' WHERE key=?", (LEVER,))
    assert how(store, LI_BOARD) is None


# --- the company's own application page for a job found on LinkedIn or Indeed ------------------------------


def test_the_companys_own_page_is_not_known_by_its_address_alone(ctx):
    """Its host is nothing jobwatch keeps for the job, and the address names no job: this is what the extension had
    before it sent the page's company and title."""
    assert how(ctx[1], GLOBEX_SITE) is None


def test_the_companys_own_page_matches_by_company_and_title_when_one_open_job_fits(ctx):
    store = ctx[1]
    assert how(store, GLOBEX_SITE, "Globex", "Machine Learning Engineer") == (LEVER, "name")
    assert how(store, GLOBEX_SITE, "Globex, Inc.", "Machine Learning Engineer (Remote - US)") == (LEVER, "name")
    assert how(store, GLOBEX_SITE, "globex", "machine  learning engineer") == (LEVER, "name")


@pytest.mark.parametrize("company, title", [
    ("Globex", "Staff Machine Learning Engineer"),   # another title, not a near one
    ("Globex", "Machine Learning"),
    ("Initech", "Machine Learning Engineer"),         # another company
    ("", "Machine Learning Engineer"), ("Globex", ""), ("", "")])
def test_a_page_that_names_another_job_or_nothing_matches_nothing(ctx, company, title):
    assert how(ctx[1], GLOBEX_SITE, company, title) is None


def test_two_open_jobs_with_that_company_and_title_are_never_guessed_between(ctx):
    store = ctx[1]
    store.add("Globex", "Machine Learning Engineer", url="https://www.linkedin.com/jobs/view/4000000007/",
              status="queued")
    assert how(store, GLOBEX_SITE, "Globex", "Machine Learning Engineer") is None
    # the second is closed: one open job fits again
    store.db.execute("UPDATE jobs SET closed='2026-11-01' WHERE key LIKE 'manual:globex:%'")
    assert how(store, GLOBEX_SITE, "Globex", "Machine Learning Engineer") == (LEVER, "name")


def test_a_page_on_a_supported_board_with_another_posting_id_is_another_posting(ctx):
    """A Lever job of Globex's with this title is tracked; another Lever posting id is a different opening."""
    assert how(ctx[1], "https://jobs.lever.co/globex/ffff-9999/apply", "Globex", "Machine Learning Engineer") is None


def test_linkedin_and_indeed_pages_are_never_matched_by_what_their_title_says(ctx):
    for page in ("https://www.linkedin.com/jobs/view/4000000099/", "https://www.indeed.com/viewjob?jk=ffffffffffffffff"):
        assert how(ctx[1], page, "Globex", "Machine Learning Engineer") is None


def test_the_links_the_other_matches_used_still_win_over_a_name(ctx):
    store = ctx[1]
    store.add("Globex", "Machine Learning Engineer", url=GLOBEX_SITE, status="queued")  # kept at its own page
    assert how(store, GLOBEX_SITE, "Globex", "Machine Learning Engineer")[1] == "link"


# --- what the extension asks for on the matched job ---------------------------------------------------------


def test_context_names_the_job_and_how_it_was_told(app, ctx):
    cfg, store = ctx
    got = autofill.context(cfg, store, GLOBEX_SITE, "Globex", "Machine Learning Engineer")
    assert got["job"]["key"] == LEVER and got["job"]["matched_by"] == "name" and got["job"]["company"] == "globex"
    assert autofill.context(cfg, store, GLOBEX_SITE)["job"] is None
    assert autofill.context(cfg, store, LI_BOARD)["job"]["matched_by"] == "linkedin"
    board = autofill.context(cfg, store, "https://jobs.ashbyhq.com/initech/c1/application")
    assert board["job"]["matched_by"] == "board"


def test_the_ats_check_runs_on_the_job_a_company_page_matches(app, ctx):
    cfg, store = ctx
    got = autofill.ats_check(cfg, store, GLOBEX_SITE, "Globex", "Machine Learning Engineer")
    assert got["key"] == LEVER and got["matched_by"] == "name" and got["file"] == "resume.txt"
    assert got["tailored"] is False and got["score"] is not None
    assert [f["term"] for f in got["found"]] == ["Machine learning"]
    assert [m["term"] for m in got["missing"]] == ["LLMs and generative AI"] and got["score"] == 50
    assert autofill.ats_check(cfg, store, LI_BOARD)["key"] == LEVER
    with pytest.raises(KeyError, match="doesn't track this job"):
        autofill.ats_check(cfg, store, GLOBEX_SITE)


def test_the_ats_check_says_to_save_the_posting_when_the_job_has_no_text(app, ctx):
    cfg, store = ctx
    store.add("Initech", "Support Engineer", url="https://careers.initech.example/support", status="queued")
    with pytest.raises(ValueError, match="Save this posting to jobwatch"):
        autofill.ats_check(cfg, store, "https://careers.initech.example/support")


@pytest.fixture
def model(monkeypatch):
    seen = {"said": "Hello Globex team,\n\nI ran Kubernetes and Terraform platforms. " + "Plain words fill it. " * 30}

    def fake(backend, system, messages, model="", max_tokens=0):
        seen.update(backend=backend, prompt="\n".join([system, *(m["content"] for m in messages)]))
        yield seen["said"]
        yield {"output_tokens": 9}

    monkeypatch.setattr(chat, "check", lambda *a: None)
    monkeypatch.setattr(chat, "reply", fake)
    return seen


def test_the_cover_letter_is_drafted_for_the_matched_job_and_kept_with_it(app, ctx, model):
    cfg, store = ctx
    got = autofill.cover_letter(cfg, store, GLOBEX_SITE, "Globex", "Machine Learning Engineer")
    assert got["key"] == LEVER and got["matched_by"] == "name" and got["drafted"] and got["version"] == 1
    assert got["letter"].startswith("Hello Globex team,") and got["local"] is True and model["backend"] == "local"
    assert "Train machine learning models in Python" in model["prompt"]  # that job's posting
    assert [v["version"] for v in cover.versions(store, LEVER)] == [1]  # kept, as the card's button keeps it
    again = autofill.cover_letter(cfg, store, LI_BOARD, tone="warm", emphasis="my platform work")
    assert again["version"] == 2 and again["tone"] == "warm"
    with pytest.raises(KeyError, match="doesn't track this job"):
        autofill.cover_letter(cfg, store, GLOBEX_SITE)
    with pytest.raises(ValueError, match="tone must be one of"):
        autofill.cover_letter(cfg, store, LI_BOARD, tone="rude")


def test_a_cover_letter_without_a_model_comes_back_with_the_why_and_no_version(app, ctx, monkeypatch):
    cfg, store = ctx

    def unavailable(*a):
        raise chat.ChatUnavailable("the local model isn't running: start it with `local-llm`")
    monkeypatch.setattr(chat, "check", unavailable)
    got = autofill.cover_letter(cfg, store, LI_BOARD)
    assert got["drafted"] is False and got["letter"] == "" and "local model isn't running" in got["warnings"][0]
    assert cover.versions(store, LEVER) == []


def test_a_drafted_answer_uses_the_matched_jobs_posting(app, ctx, model):
    cfg, store = ctx
    got = autofill.draft(cfg, store, GLOBEX_SITE, "Why Globex?", company="Globex", title="Machine Learning Engineer")
    assert got["answer"].startswith("Hello Globex team") and "Train machine learning models" in model["prompt"]
    autofill.draft(cfg, store, GLOBEX_SITE, "Why Globex?")  # no name sent: the page is no job, so no posting
    assert "Train machine learning models" not in model["prompt"]


def test_the_resume_and_tailoring_follow_the_same_match(app, ctx, monkeypatch):
    cfg, store = ctx
    assert autofill.resume_file(cfg, store, GLOBEX_SITE, "Globex", "Machine Learning Engineer")[2] == "resume.txt"
    store.package(LEVER).attach("Jordan_Rivera_Globex.pdf", b"%PDF-1 tailored", "resume")
    named = (GLOBEX_SITE, "Globex", "Machine Learning Engineer")
    assert autofill.context(cfg, store, *named)["resume"]["tailored"] is True
    assert autofill.resume_file(cfg, store, *named)[2] == "Jordan_Rivera_Globex.pdf"
    assert autofill.context(cfg, store, GLOBEX_SITE)["resume"]["tailored"] is False  # no name sent: the default one


# --- over HTTP, with the extension's token ------------------------------------------------------------------


def test_the_endpoints_take_the_pages_company_and_title_and_want_the_token(server, watchlist, model):
    page = {"X-Jobwatch-Token": TOKEN}
    (watchlist.parent / "resume.txt").write_text("Jordan Rivera. Platform engineer. Python, Kubernetes, Terraform.")
    watchlist.write_text(watchlist.read_text() + "resume: resume.txt\n")
    request(server, "POST", "/api/fetch", {}, headers=page)
    store = Store(config.load(watchlist).state)
    store.set_status([LEVER], "queued", None)
    store.close()
    ok = {"X-Jobwatch-Extension": json.loads(request(server, "GET", "/api/extension", headers=page)[1])["token"]}
    body = {"url": GLOBEX_SITE, "company": "Globex", "title": "Machine Learning Engineer"}
    assert "ats" in json.loads(request(server, "GET", "/ext/ping", headers=ok)[1])["features"]
    assert "cover" in json.loads(request(server, "GET", "/ext/ping", headers=ok)[1])["features"]
    for path in ("/ext/ats", "/ext/cover"):
        assert request(server, "POST", path, body)[0] == 403
        assert request(server, "POST", path, body, headers={"X-Jobwatch-Extension": "wrong"})[0] == 403
    status, data = request(server, "GET", f"/ext/context?url={quote(GLOBEX_SITE, safe='')}&company=Globex&title="
                           f"{quote('Machine Learning Engineer')}", headers=ok)
    assert status == 200 and json.loads(data)["job"]["matched_by"] == "name"
    status, data = request(server, "POST", "/ext/ats", body, headers=ok)
    assert status == 200 and json.loads(data)["key"] == LEVER and json.loads(data)["matched_by"] == "name"
    status, data = request(server, "POST", "/ext/cover", body, headers=ok)
    assert status == 200 and json.loads(data)["drafted"] is True and json.loads(data)["version"] == 1
    status, data = request(server, "POST", "/ext/ats", {"url": GLOBEX_SITE}, headers=ok)
    assert status == 404 and "doesn't track this job" in json.loads(data)["error"]
    assert request(server, "POST", "/ext/cover", {"url": "", "tone": "rude"}, headers=ok)[0] == 404
