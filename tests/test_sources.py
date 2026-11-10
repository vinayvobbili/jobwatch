import pytest

from jobwatch import cli, sources
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
    # An hourly wage ($60–$80) is kept as the year's pay it comes to, 2,080 hours a year.
    assert (jobs[1].salary_min, jobs[1].salary_max) == (124_800, 166_400)


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
    ("https://job-boards.greenhouse.io/initech/jobs/4000000001", ("greenhouse", "initech")),
    ("https://boards.greenhouse.io/embed/job_board?for=stripe", ("greenhouse", "stripe")),
    ("jobs.lever.co/globex/4f1c2a9e/apply?source=LinkedIn", ("lever", "globex")),
    ("https://jobs.ashbyhq.com/hooli/8fb1615c/application", ("ashby", "hooli")),
    ("https://api.ashbyhq.com/posting-api/job-board/hooli", ("ashby", "hooli")),
    ("https://boards-api.greenhouse.io/v1/boards/acme/jobs", ("greenhouse", "acme")),
    ("https://my.greenhouse.io/jobs/initech/4000000001", ("greenhouse", "initech")),
    ("https://my.greenhouse.io/dashboard", None),
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


def test_a_lookup_by_name_does_not_wait_out_a_rate_limited_guess(monkeypatch):
    # `find` guesses dozens of boards; waiting each 429 out (5 tries, up to 30 s apiece) ran one past ten minutes
    def urlopen(req, timeout):
        raise _http_error(429, "999")

    waits = []
    monkeypatch.setattr(sources.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(sources.time, "sleep", waits.append)
    guess = sources._impatient(lambda: sources.get_json("https://x.test/api"))
    with pytest.raises(sources.SourceError, match="HTTP 429"):
        guess()
    assert waits == [sources.PROBE_WAIT] * sources.PROBE_RETRIES
    waits.clear()
    with pytest.raises(sources.SourceError):  # outside a lookup, a board is as patient as before
        sources.get_json("https://x.test/api")
    assert len(waits) == sources.RETRIES


def test_probe_guesses_are_impatient(web, monkeypatch):
    seen = []
    monkeypatch.setattr(sources, "_peek", lambda *a, **k: seen.append(sources._patience.get()) or [])
    sources.probe("Initech Labs")
    assert seen and set(seen) == {(sources.PROBE_RETRIES, sources.PROBE_WAIT)}


def test_a_source_that_said_slow_down_is_named_not_taken_for_a_no(web, monkeypatch, capsys):
    def peek(source, board, get=None):
        if source == "workable":
            raise sources.SourceError(f"https://apply.workable.com/api/v1/widget/accounts/{board}: HTTP 429")
        return []
    monkeypatch.setattr(sources, "_peek", peek)
    limited = set()
    assert sources.probe("Initech Labs", limited=limited) == [] and limited == {"workable"}
    assert sources.slow_down(set()) == ""
    cli.main(["find", "Initech Labs"])
    assert "Workable, Workday" in (out := capsys.readouterr().out) and "workable said to slow down (HTTP 429)" in out


@pytest.mark.parametrize("url, expected", [
    ("https://jobs.lever.co/initech/6f1b2c", "https://jobs.lever.co/initech/6f1b2c/apply"),
    ("https://jobs.lever.co/initech/6f1b2c/?lever-source=x", "https://jobs.lever.co/initech/6f1b2c/apply"),
    ("https://jobs.lever.co/initech/6f1b2c/apply", "https://jobs.lever.co/initech/6f1b2c/apply"),
    ("https://jobs.ashbyhq.com/initech/4f1c9a", "https://jobs.ashbyhq.com/initech/4f1c9a/application"),
    ("https://jobs.ashbyhq.com/initech/4f1c9a/application", "https://jobs.ashbyhq.com/initech/4f1c9a/application"),
    ("https://job-boards.greenhouse.io/initech/jobs/4001", "https://job-boards.greenhouse.io/initech/jobs/4001"),
    ("https://careers.globex.example/jobs?gh_jid=7", "https://careers.globex.example/jobs?gh_jid=7"),
    ("", ""),
])
def test_the_apply_button_opens_the_form(url, expected):
    assert sources.apply_url(url) == expected


def test_times_with_a_colonless_offset():
    t = sources._time("2026-09-29T21:03:00+0000")  # Jibe; Python 3.10's fromisoformat needs "+00:00"
    assert (t.year, t.hour, t.utcoffset().total_seconds()) == (2026, 21, 0)
    assert sources._time("2026-09-29T21:03:00-0500").utcoffset().total_seconds() == -5 * 3600
