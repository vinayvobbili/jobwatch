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


def test_board_variants():
    assert sources.board_variants("Initech") == ["initechinc", "initechhq", "initechlabs", "initechai", "initech.ai",
                                                 "initechsecurity"]  # "Initech" finds the board "Initech Security" has
    assert "initechsecurity" not in sources.board_variants("Initech Security")
    assert "umbrella.ai" in sources.board_variants("Umbrella AI")
    assert "hooliinc" in sources.board_variants("Hooli Corp")
    assert "hoolicorpinc" in sources.board_variants("Hooli Corp")
    assert sources.board_variants("") == []


def test_probe_finds_a_board_named_with_a_company_suffix():
    gh = {"https://boards-api.greenhouse.io/v1/boards/globexinc/jobs?content=true": GREENHOUSE}
    ash = {"https://api.ashbyhq.com/posting-api/job-board/initechlabs?includeCompensation=true": ASHBY}
    dotted = {"https://api.ashbyhq.com/posting-api/job-board/umbrella.ai?includeCompensation=true": ASHBY}
    [(source, board, _)] = sources.probe("Globex", FakeWeb(gh))
    assert (source, board) == ("greenhouse", "globexinc")
    [(source, board, _)] = sources.probe("Initech", FakeWeb(ash))
    assert (source, board) == ("ashby", "initechlabs")
    [(source, board, _)] = sources.probe("Umbrella", FakeWeb(dotted))
    assert (source, board) == ("ashby", "umbrella.ai")


def test_probe_finds_a_board_under_the_brand_a_legal_name_goes_by(monkeypatch):
    monkeypatch.setitem(sources._BRANDS, "hooliparent", ["hooli"])
    web = FakeWeb({"https://api.lever.co/v0/postings/hooli?mode=json": LEVER})
    [(source, board, _)] = sources.probe("Hooliparent", web)
    assert (source, board) == ("lever", "hooli")


def test_probe_leaves_workable_out_of_suffix_guesses():
    web = FakeWeb({})
    sources.probe("Globex", web)
    assert not any("workable" in c and "globexinc" in c for c in web.calls)
    assert any("greenhouse" in c and "globexinc" in c for c in web.calls)


def test_board_long_shots():
    assert sources.board_long_shots("Initech") == ["initech-ai", "initechcareers", "initech-com"]
    assert sources.board_long_shots("GlobexAI") == ["globex-ai", "globexaicareers", "globexai-com"]
    assert sources.board_long_shots("8AI") == ["eightai", "eight-ai", "8aicareers", "8ai-com"]
    assert sources.board_long_shots("Umbrella AI")[0] == "umbrellaaicareers"  # umbrella-ai is a board name already
    assert sources.board_long_shots("") == []


def test_probe_finds_a_long_shot_board_name_only_where_a_guess_is_cheap():
    ash = "https://api.ashbyhq.com/posting-api/job-board/{}?includeCompensation=true"
    web = FakeWeb({ash.format("eightai"): ASHBY})
    [(source, board, _)] = sources.probe("8AI", web)
    assert (source, board) == ("ashby", "eightai")
    web = FakeWeb({ash.format("hooli-com"): ASHBY})
    [(source, board, _)] = sources.probe("Hooli", web)
    assert (source, board) == ("ashby", "hooli-com")
    long_shots = [c for c in web.calls if "hoolicareers" in c]
    assert long_shots and all(any(h in c for h in ("greenhouse", "lever", "ashby", "gem", "recruitee"))
                              for c in long_shots)


def test_careers_hosts():
    assert sources.careers_hosts("Initech Labs") == ["initechlabs.com", "initechlabs.ai", "initechlabs.io"]
    assert sources.careers_hosts("globex.dev") == ["globex.dev", "globexdev.com", "globexdev.ai", "globexdev.io"]
    assert sources.careers_hosts("") == []


def test_probe_reads_the_companys_own_careers_page_when_no_board_name_fits():
    from tests.test_comeet import PAGE as COMEET

    web = FakeWeb({
        "https://hooli.com/robots.txt": sources.SourceError("hooli.com: no such host"),  # no site there
        "https://hooli.ai/robots.txt": "User-agent: *\nDisallow: /careers\n",
        "https://hooli.ai/careers": '<a href="https://jobs.ashbyhq.com/hooli-xyz">never read</a>',
        "https://hooli.ai/jobs": '<a href="https://jobs.lever.co/hooli-old">gone</a><iframe src="https://www.comeet'
                                 '.com/jobs/hooli/12.345/careers/A1.B23"></iframe>',
        "https://www.comeet.com/jobs/hooli/12.345": COMEET,
    })
    [(source, board, jobs)] = sources.probe("Hooli", web)
    assert (source, board, len(jobs)) == ("comeet", "hooli/12.345", 2)
    assert not any(c.startswith("https://hooli.com/") and "robots" not in c for c in web.calls)
    assert "https://hooli.ai/careers" not in web.calls  # robots.txt closes it
    assert not any("workable" in c for c in web.calls)  # found: Workable isn't guessed


def test_a_workable_board_linked_from_the_careers_page_is_the_one_workable_guess():
    web = FakeWeb({"https://initech.com/careers": '<a href="https://apply.workable.com/initech-co/">Jobs</a>'})
    assert sources.probe("Initech", web) == []
    assert [c for c in web.calls if "workable" in c] == [
        "https://apply.workable.com/api/v1/widget/accounts/initech-co?details=true"]


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
    seen = {}

    def peek(source, *args, **kwargs):
        seen.setdefault(source, set()).add(sources._patience.get())
        return []
    monkeypatch.setattr(sources, "_peek", peek)
    sources.probe("Initech Labs")
    assert seen.pop("workable") == {(0, 0)}  # its turns are the waiting: a 429 there isn't asked again
    assert seen and set().union(*seen.values()) == {(sources.PROBE_RETRIES, sources.PROBE_WAIT)}


def test_a_source_that_said_slow_down_is_named_not_taken_for_a_no(web, monkeypatch, capsys):
    def peek(source, board, get=None):
        if source == "workable":
            raise sources.SourceError(f"https://apply.workable.com/api/v1/widget/accounts/{board}: HTTP 429")
        return []
    monkeypatch.setattr(sources, "_peek", peek)
    limited, untested = set(), set()
    assert sources.probe("Initech Labs", limited=limited, untested=untested) == []
    assert untested == {"workable"} and limited == set()  # Workable is paused by its turns, not left out
    assert sources.untested_note(set()) == "" and sources.untested_note({"gem", "icims"}) == \
        "untested (Gem, iCIMS rate-limited)"
    cli.main(["find", "Initech Labs"])  # Workable is still paused: untested again, with no request
    out = capsys.readouterr().out
    assert out.startswith("Initech Labs: untested (Workable rate-limited): no board found on the others")
    monkeypatch.setattr(sources, "_peek", lambda *a, **k: [])
    monkeypatch.setattr(sources, "WORKABLE_TURNS", sources._Turns(gap=0, pause=60, most=30))
    cli.main(["find", "Initech Labs"])
    out = capsys.readouterr().out
    assert "no Greenhouse, Lever, Ashby, Workable" in out and "untested" not in out


def test_workable_is_guessed_last_and_once():
    web = FakeWeb({})
    assert sources.probe("Initech Labs", web) == []
    workable = [u for u in web.calls if "workable" in u]
    assert workable == ["https://apply.workable.com/api/v1/widget/accounts/initechlabs?details=true"]
    assert web.calls[-1] == workable[0]  # after every other guess and the careers page
    web = FakeWeb()
    assert sources.probe("Globex", web)  # a board elsewhere: Workable isn't asked
    assert not any("workable" in u for u in web.calls)


def test_workable_guesses_take_turns_and_pause_after_a_429(monkeypatch):
    clock, slept = [100.0], []
    monkeypatch.setattr(sources.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(sources.time, "sleep", slept.append)
    turns = sources._Turns(gap=2, pause=60, most=30)
    assert turns.take() and turns.take() and slept == [2]  # the second waits its turn
    turns.answered(refused=True)
    assert not turns.take()  # paused: a minute off, too long to wait for
    clock[0] += 61
    assert turns.take()
    turns.answered(refused=True)  # again: twice as long
    clock[0] += 61
    assert not turns.take()
    clock[0] += 60
    assert turns.take()
    turns.answered(refused=False)
    assert turns.strikes == 0


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
