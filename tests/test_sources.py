import pytest

from jobwatch import sources
from tests.conftest import ASHBY, GREENHOUSE, LEVER, FakeWeb


def test_greenhouse():
    jobs = sources.parse_greenhouse(GREENHOUSE, "acme")
    j = jobs[0]
    assert (j.key, j.title, j.company_name) == ("greenhouse:acme:101", "Senior Software Engineer, Platform", "Acme")
    assert j.locations == ["Austin, TX", "Remote-Friendly, United States", "Austin, Texas, United States"]
    assert j.remote is True
    assert (j.salary_min, j.salary_max, j.currency) == (180_000, 240_000, "USD")
    assert "- Distributed systems" in j.description
    assert j.age_days() == 3
    assert jobs[1].remote is None and jobs[1].salary_min is None


def test_lever():
    jobs = sources.parse_lever(LEVER, "globex")
    j = jobs[0]
    assert j.key == "lever:globex:aaaa-1111"
    assert (j.salary_min, j.salary_max) == (150_000, 210_000)
    assert j.remote is True
    assert "You will:\n- Ship LLM features" in j.description and "Benefits." in j.description
    assert j.age_days() == 10
    # An hourly range is not an annual salary.
    assert jobs[1].salary_min is None


def test_ashby_skips_unlisted_and_reads_structured_pay():
    jobs = sources.parse_ashby(ASHBY, "initech")
    assert [j.id for j in jobs] == ["c1"]
    j = jobs[0]
    assert j.locations == ["Denver, CO, United States", "Remote"]
    assert j.remote is None  # isRemote is true for this hybrid role; workplaceType decides
    assert (j.salary_min, j.salary_max) == (230_000, 300_000)


def test_fetch_calls_the_board_api():
    web = FakeWeb()
    assert len(sources.fetch("lever", "globex", web)) == 2
    assert web.calls == ["https://api.lever.co/v0/postings/globex?mode=json"]


@pytest.mark.parametrize("url, expected", [
    ("https://job-boards.greenhouse.io/anthropic/jobs/4461450008", ("greenhouse", "anthropic")),
    ("https://boards.greenhouse.io/embed/job_board?for=stripe", ("greenhouse", "stripe")),
    ("jobs.lever.co/globex/4f1c2a9e/apply?source=LinkedIn", ("lever", "globex")),
    ("https://jobs.ashbyhq.com/openai/8fb1615c/application", ("ashby", "openai")),
    ("https://api.ashbyhq.com/posting-api/job-board/openai", ("ashby", "openai")),
    ("https://boards-api.greenhouse.io/v1/boards/acme/jobs", ("greenhouse", "acme")),
    ("https://careers.example.com/jobs/1", None),
    ("https://jobs.lever.co/", None),
])
def test_detect(url, expected):
    assert sources.detect(url) == expected


def test_board_names():
    assert sources.board_names("Scale AI") == ["scaleai", "scale-ai", "scale"]
    assert sources.board_names("Stripe") == ["stripe"]


def test_probe_tries_every_source_and_reports_open_roles():
    web = FakeWeb()
    [(source, board, jobs)] = sources.probe("Globex", web)
    assert (source, board, len(jobs)) == ("lever", "globex", 2)
    assert sources.probe("Nobody", web) == []
    by_link = sources.probe("https://jobs.lever.co/globex/aaaa-1111", web)
    assert [(s, b) for s, b, _ in by_link] == [("lever", "globex")]


def test_probe_ignores_empty_boards():
    web = FakeWeb({"https://api.lever.co/v0/postings/ghost?mode=json": []})
    assert sources.probe("ghost", web) == []


def _http_error(code, retry_after=None):
    import email.message
    import urllib.error

    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://x.test/api", code, "slow down", headers, None)


def test_a_rate_limited_board_is_asked_again(monkeypatch):
    import io

    replies = [_http_error(429, "5"), _http_error(503), io.BytesIO(b'{"ok": true}')]

    def urlopen(req, timeout):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    waits = []
    monkeypatch.setattr(sources.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(sources.time, "sleep", waits.append)
    assert sources.get_json("https://x.test/api") == {"ok": True}
    assert waits == [5.0, 4]  # the server's Retry-After, then backing off


def test_a_board_that_stays_rate_limited_fails(monkeypatch):
    def urlopen(req, timeout):
        raise _http_error(429, "999")

    waits = []
    monkeypatch.setattr(sources.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(sources.time, "sleep", waits.append)
    with pytest.raises(sources.SourceError, match="HTTP 429"):
        sources.get_json("https://x.test/api")
    assert waits == [sources.MAX_WAIT] * sources.RETRIES
