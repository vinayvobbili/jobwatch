"""Job-alert emails: parsed per sender, links cleaned, followed only where robots.txt allows, matched to the
company's own board, deduped against what's tracked, and into the digest. No network: boards are canned (the
`web` fixture) and every page jobwatch reads comes from `Pages`."""

import io
import json
import re
import subprocess
from datetime import date
from pathlib import Path

import pytest

from jobwatch import alerts, cli, config, sources
from jobwatch.store import Store
from jobwatch.watch import build_digest, fetch_all

FIXTURES = Path(__file__).parent / "fixtures" / "alerts"
PLACEHOLDERS = re.compile(r"TOKEN|TRACKING|VIEWER-ID|ALERT-ID|PREFERENCE-ID|MESSAGE-ID|SIGNATURE|REF-ID|MID-|EMAIL-ID|"
                          r"utm_|trk|gh_src|awstrack|google\.com/url", re.I)

ROBOTS = {
    "https://www.linkedin.com/robots.txt": "User-agent: Googlebot\nAllow: /\n\nUser-agent: *\nDisallow: /\n",
    "https://www.indeed.com/robots.txt": "User-agent: *\nAllow: /jobs\nDisallow: /viewjob\nDisallow: /rc/\n",
    "https://builtin.com/robots.txt": "User-agent: *\nDisallow: /search/\nDisallow: /*?ni=5\n",
}


def posting_page(title, company, description, **extra):
    data = {"@context": "https://schema.org", "@type": "JobPosting", "title": title, "description": description,
            "hiringOrganization": {"@type": "Organization", "name": company}, **extra}
    # Built In writes the script's type with its plus sign escaped, as here.
    return (f'<html><head><script type="application/ld&#x2B;json">{json.dumps({"@graph": [data]})}</script></head>'
            f"<body><h1>{title}</h1></body></html>")


PAGES = {
    "https://builtin.com/job/staff-ai-engineer/9000001": posting_page(
        "Staff AI Engineer", "Initech", "<p>Agents, RAG and evaluation.</p>"),
    "https://builtin.com/job/senior-data-engineer/9000002": posting_page(
        "Senior Data Engineer", "Hooli", "<p>Spark pipelines in <b>Python</b>.</p>", datePosted="2026-10-06",
        baseSalary={"@type": "MonetaryAmount", "currency": "USD",
                    "value": {"minValue": 160000, "maxValue": 200000, "unitText": "YEAR"}},
        jobLocation={"@type": "Place", "address": {"addressLocality": "Denver", "addressRegion": "CO"}}),
    # A job site whose page links to the company's own posting (jobs.example.net has no robots.txt: all allowed)
    "https://jobs.example.net/job/12345": '<a href="https://jobs.lever.co/globex/aaaa-1111?lever-source=digest">'
                                         "Apply on the company's site</a>",
}


class Pages:
    """Stands in for sources.get_text when following alert links: robots.txt files and job pages."""

    def __init__(self, pages=None):
        self.pages = {**ROBOTS, **PAGES, **(pages or {})}
        self.calls: list[str] = []

    def __call__(self, url, timeout=30):
        self.calls.append(url)
        if url not in self.pages:
            raise sources.NotFound(url)
        return self.pages[url]


def emails(*names):
    return alerts.read([str(FIXTURES / n) for n in names])


def take(watchlist, names, **kw):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    pages = kw.pop("page", None) or Pages()
    return cfg, store, alerts.intake(cfg, store, emails(*names), page=pages, **kw), pages


def by_title(r):
    return {f.alert.title + " @ " + f.alert.company: f for f in r.found}


# -- Links

def test_links_lose_their_tracking():
    assert alerts.clean_link("https://www.linkedin.com/comm/jobs/view/4100000001/?trackingId=X&refId=Y&otpToken=Z") \
        == "https://www.linkedin.com/jobs/view/4100000001/"
    assert alerts.clean_link("https://www.indeed.com/rc/clk/dl?jk=0a1b2c3d&from=ja&tk=T&alid=A") \
        == "https://www.indeed.com/viewjob?jk=0a1b2c3d"
    assert alerts.clean_link("https://x1.r.us-west-2.awstrack.me/L0/https:%2F%2Fbuiltin.com%2Fjob%2Fstaff%2F9%3Fi=V"
                             "%26utm_source=ses/1/M/S=0") == "https://builtin.com/job/staff/9"
    assert alerts.clean_link("https://job-boards.greenhouse.io/acme/jobs/101?gh_src=abc&utm_medium=email") \
        == "https://job-boards.greenhouse.io/acme/jobs/101"
    assert alerts.clean_link("https://boards.greenhouse.io/embed/job_app?for=acme&gh_jid=101&utm_source=x") \
        == "https://boards.greenhouse.io/embed/job_app?for=acme&gh_jid=101"  # the job's own id stays
    assert alerts.clean_link("https://www.google.com/url?q=https%3A%2F%2Fjobs.lever.co%2Fglobex%2Faaaa-1111%3F"
                             "lever-source%3Dx&sa=D") == "https://jobs.lever.co/globex/aaaa-1111"
    assert alerts.clean_link("https://eur01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fjobs.example.net"
                             "%2Fjob%2F1%3Fref%3Dmail&data=X") == "https://jobs.example.net/job/1"


def test_which_links_are_jobs():
    assert alerts.job_link("https://www.linkedin.com/comm/jobs/view/4100000001/?trk=x")[0] == "linkedin"
    assert alerts.job_link("https://jobs.lever.co/globex/aaaa-1111")[0] == "ats"
    assert alerts.job_link("https://acme.wd5.myworkdayjobs.com/External/job/Austin/Engineer_R123")[0] == "ats"
    assert alerts.job_link("https://jobs.example.net/job/12345")[0] == "other"
    for not_a_job in ("https://jobs.lever.co/globex", "https://www.indeed.com/jobs?q=Python",
                      "https://www.linkedin.com/comm/jobs/search-results/?keywords=x", "mailto:you@example.com",
                      "https://www.indeed.com/pagead/clk/dl?mo=r&ad=SPONSORED", "https://jobs.example.org/preferences"):
        assert alerts.job_link(not_a_job) is None, not_a_job


# -- Parsing each sender

def test_linkedin_alert():
    found = alerts.parse(emails("linkedin.eml")[0])
    assert [(a.title, a.company, a.location, a.pay) for a in found] == [
        ("Senior Software Engineer, Platform", "Acme Inc.", "Austin, TX (Remote)", "$180K - $240K"),
        ("Field Engineer", "Umbrella LLC", "United States (Remote)", ""),
        ("Account Executive", "Acme Inc.", "London, United Kingdom (On-site)", ""),
    ]
    assert found[0].url == "https://www.linkedin.com/jobs/view/4100000001/"
    assert {a.via for a in found} == {"linkedin-alert"} and {a.site for a in found} == {"linkedin"}


def test_linkedin_alert_as_plain_text():
    _, text = alerts.bodies(emails("linkedin.eml")[0])
    cards = alerts.text_cards(text)
    assert [alerts.parse_linkedin(c).company for c in cards] == ["Acme Inc.", "Umbrella LLC", "Acme Inc."]
    assert alerts.parse_linkedin(cards[1]).location == "United States"


def test_builtin_alert():
    found = alerts.parse(emails("builtin.eml")[0])
    assert [(a.title, a.company, a.location, a.pay, a.url) for a in found] == [
        ("Staff AI Engineer", "Initech", "Remote - United States", "$230,000-$300,000",
         "https://builtin.com/job/staff-ai-engineer/9000001"),
        ("Senior Data Engineer", "Hooli", "Denver, CO", "", "https://builtin.com/job/senior-data-engineer/9000002"),
    ]
    assert found[0].via == "builtin-alert"


def test_indeed_alert_html_and_text():
    found = alerts.parse(emails("indeed.eml")[0])
    assert [(a.title, a.company, a.location, a.pay) for a in found] == [
        ("Machine Learning Engineer", "Globex", "Remote", ""),
        ("Python Developer (Contract)", "Vandelay Industries", "Austin, TX", "$60 - $70 an hour"),
        ("Account Executive", "Acme", "London", "$90,000 - $120,000 a year"),
    ]  # the sponsored listing has no job id: left out
    assert found[0].url == "https://www.indeed.com/viewjob?jk=0a1b2c3d4e5f6a7b"
    _, text = alerts.bodies(emails("indeed.eml")[0])
    assert [(c.lines[0], alerts.parse_indeed(c).company, alerts.parse_indeed(c).location)
            for c in alerts.text_cards(text)] == [("Machine Learning Engineer", "Globex", "Remote"),
                                                  ("Python Developer (Contract)", "Vandelay Industries", "Austin, TX"),
                                                  ("Account Executive", "Acme", "London")]


def test_other_senders_use_the_generic_parser():
    found = alerts.parse(emails("other.eml")[0])
    assert [(a.title, a.company, a.location, a.pay, a.site, a.url) for a in found] == [
        ("Senior Software Engineer, Platform", "Acme", "Remote", "", "ats",
         "https://job-boards.greenhouse.io/acme/jobs/101"),
        ("Machine Learning Engineer", "Globex", "Remote (United States)", "$150,000 - $210,000", "other",
         "https://jobs.example.net/job/12345"),
    ]
    assert found[0].via == "example-alert"


def test_no_tracking_survives_in_any_link():
    for msg in emails("linkedin.eml", "builtin.eml", "indeed.eml", "other.eml"):
        for a in alerts.parse(msg):
            assert not PLACEHOLDERS.search(a.url), a.url


def test_a_body_without_headers_is_read_by_its_links():
    """What an assistant may pass: just the HTML body. LinkedIn's links pick LinkedIn's parser."""
    markup, _ = alerts.bodies(emails("linkedin.eml")[0])
    msg = alerts.message(markup)
    assert alerts.sender(msg) == "" and [a.via for a in alerts.parse(msg)] == ["linkedin-alert"] * 3
    raw = (FIXTURES / "indeed.eml").read_text()
    assert [a.company for a in alerts.parse(alerts.message(raw))][:1] == ["Globex"]  # a raw message, as a string


def test_reading_files_folders_mbox_and_stdin(tmp_path):
    assert len(alerts.read([str(FIXTURES)])) == 4
    mbox = b"".join(b"From MAILER-DAEMON Thu Oct  8 00:00:00 2026\n" + (FIXTURES / n).read_bytes() + b"\n"
                    for n in ("linkedin.eml", "indeed.eml"))
    (tmp_path / "alerts.mbox").write_bytes(mbox)
    assert [alerts.sender(m) for m in alerts.read([str(tmp_path / "alerts.mbox")])] == [
        "jobalerts-noreply@linkedin.com", "donotreply@jobalert.indeed.com"]
    assert len(alerts.read(["-"], io.BytesIO(mbox))) == 2
    assert len(alerts.read(["-"], io.BytesIO((FIXTURES / "builtin.eml").read_bytes()))) == 1
    with pytest.raises(alerts.AlertError, match="no such file"):
        alerts.read([str(tmp_path / "missing.eml")])


# -- robots.txt

def test_robots_rules():
    text = ("User-agent: Googlebot\nDisallow:\n\nUser-agent: *\nUser-agent: OtherBot\nDisallow: /private\n"
            "Allow: /private/open\nDisallow: /*?ni=5\nDisallow: /*.pdf$\n# comment\nSitemap: https://x/s.xml\n")
    rules = alerts.robots_rules(text)
    assert rules == [(False, "/private"), (True, "/private/open"), (False, "/*?ni=5"), (False, "/*.pdf$")]
    allows = lambda path: alerts.robots_allows(rules, "https://example.com" + path)  # noqa: E731
    assert allows("/job/1") and allows("/private/open/2") and allows("/a.pdf?x=1") and allows("/")
    assert not allows("/private/x") and not allows("/jobs?ni=5") and not allows("/a.pdf")
    assert alerts.robots_rules("User-agent: jobwatch\nDisallow: /x\n\nUser-agent: *\nDisallow: /\n") == [
        (False, "/x")]  # a group naming jobwatch comes first
    assert alerts.robots_allows([(False, "/p"), (True, "/p")], "https://example.com/p")  # a tie: Allow


def test_robots_per_site(monkeypatch):
    def page(url):
        if "broken" in url:
            raise sources.SourceError("HTTP 500")
        if "none" in url:
            raise sources.NotFound(url)
        return "User-agent: *\nDisallow: /\n"
    robots = alerts.Robots(page)
    assert not robots.allowed("https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/1")
    assert robots.allowed("https://none.example.com/job/1")       # no robots.txt: allowed
    assert not robots.allowed("https://broken.example.com/job/1")  # can't tell: not read


# -- Taking them in

def test_alerts_become_tracked_jobs(web, watchlist):
    _, store, r, pages = take(watchlist, ["linkedin.eml", "builtin.eml", "indeed.eml"])
    jobs = by_title(r)
    sse = jobs["Senior Software Engineer, Platform @ Acme Inc."]
    assert (sse.how, sse.result, sse.key) == ("board", "new", "greenhouse:acme:101")  # where the application goes
    assert (jobs["Staff AI Engineer @ Initech"].how, jobs["Staff AI Engineer @ Initech"].key) == ("board",
                                                                                                 "ashby:initech:c1")
    assert jobs["Machine Learning Engineer @ Globex"].key == "lever:globex:aaaa-1111"
    hooli = jobs["Senior Data Engineer @ Hooli"]  # no board found: what the job site's page says
    assert hooli.how == "page" and hooli.key == "manual:hooli:senior-data-engineer"
    job, rec = store.find(hooli.key)
    assert job.description == "Spark pipelines in Python." and job.pay() == "$160K–$200K" and job.posted
    assert rec["status"] == "new" and rec["via"] == "builtin-alert"
    umbrella = jobs["Field Engineer @ Umbrella LLC"]
    assert umbrella.how == "email" and store.find(umbrella.key)[0].locations == ["United States (Remote)"]
    assert any("robots.txt doesn't allow" in n for n in umbrella.notes)
    # Filtered out on what the email says: kept (so it's known next time), never followed
    contract = jobs["Python Developer (Contract) @ Vandelay Industries"]
    assert contract.reason and contract.how == "email" and contract.result == "new"
    assert jobs["Account Executive @ Acme Inc."].reason == "location"
    assert jobs["Account Executive @ Acme"].result == "duplicate"  # in LinkedIn's alert first, then Indeed's
    # Robots first: LinkedIn and Indeed postings are never read, Built In's pages are
    assert not [u for u in pages.calls if "linkedin.com/jobs" in u or "indeed.com/viewjob" in u]
    assert "https://builtin.com/job/staff-ai-engineer/9000001" in pages.calls
    _, rec = store.find("greenhouse:acme:101")
    assert rec["via"] == "linkedin-alert" and "From a LinkedIn job alert: https://www.linkedin.com/jobs/view/" \
        "4100000001/" in rec["note"]
    assert (r.count(result="new"), r.count(result="duplicate"), r.count(result="known")) == (7, 1, 0)


def test_new_alert_jobs_are_in_the_digest(web, watchlist):
    cfg, store, _, _ = take(watchlist, ["linkedin.eml", "builtin.eml", "indeed.eml"])
    d = build_digest(cfg, store)
    keys = {e.job.key for e in d.entries}
    assert {"greenhouse:acme:101", "ashby:initech:c1", "lever:globex:aaaa-1111", "manual:hooli:senior-data-engineer",
            "manual:umbrella-llc:field-engineer"} == keys
    assert d.rejected == {"title": 1, "location": 1}
    from jobwatch import report
    assert "`greenhouse:acme:101` (via linkedin-alert)" in report.to_markdown(d)
    assert {j["key"]: j["via"] for j in json.loads(report.to_json(d))["jobs"]}["ashby:initech:c1"] == "builtin-alert"


def test_jobs_already_tracked_are_left_alone(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    fetch_all(cfg, store)  # the watched boards first: Acme's two roles are known
    store.set_status(["greenhouse:acme:101"], "queued")
    pages = Pages()
    r = alerts.intake(cfg, store, emails("linkedin.eml"), page=pages)
    jobs = by_title(r)
    assert jobs["Senior Software Engineer, Platform @ Acme Inc."].result == "known"
    assert jobs["Account Executive @ Acme Inc."].key == "greenhouse:acme:102"  # the same job seen on its board
    assert store.find("greenhouse:acme:101")[1]["status"] == "queued" and not store.find(
        "greenhouse:acme:101")[1]["via"]
    again = alerts.intake(cfg, store, emails("linkedin.eml"), page=pages)
    assert {f.result for f in again.found} == {"known"}


def test_a_direct_board_link_and_a_page_that_links_to_the_board(web, watchlist):
    cfg, store, r, pages = take(watchlist, ["other.eml"])
    jobs = by_title(r)
    assert (jobs["Senior Software Engineer, Platform @ Acme"].how,
            jobs["Senior Software Engineer, Platform @ Acme"].key) == ("posting", "greenhouse:acme:101")
    globex = jobs["Machine Learning Engineer @ Globex"]
    assert (globex.how, globex.key) == ("posting", "lever:globex:aaaa-1111")
    assert store.find(globex.key)[1]["via"] == "example-alert"
    # The same jobs from LinkedIn and Indeed later: already tracked from their boards
    later = alerts.intake(cfg, store, emails("linkedin.eml", "indeed.eml"), page=pages)
    assert by_title(later)["Senior Software Engineer, Platform @ Acme Inc."].result == "known"
    assert by_title(later)["Machine Learning Engineer @ Globex"].result == "known"


def test_dry_run_records_nothing(web, watchlist):
    _, store, r, _ = take(watchlist, ["linkedin.eml", "builtin.eml", "indeed.eml"], dry_run=True)
    assert r.count(result="new") == 7 and r.dry_run
    assert store.jobs(include_closed=True) == []
    assert alerts.summary(r).startswith("Dry run: nothing recorded. Read 3 email(s): 8 job(s)")


def test_no_follow_reads_nothing(web, watchlist):
    _, store, r, pages = take(watchlist, ["linkedin.eml", "builtin.eml", "indeed.eml"], follow=False)
    assert pages.calls == [] and web.calls == []
    assert {f.how for f in r.found} == {"email"}
    assert store.find("manual:acme-inc:senior-software-engineer-platform")[0].pay() == "$180K–$240K"


def test_summary_and_json(web, watchlist):
    _, _, r, _ = take(watchlist, ["linkedin.eml", "builtin.eml", "indeed.eml"])
    text = alerts.summary(r)
    assert "Read 3 email(s): 8 job(s), 0 already tracked, 1 repeated, 7 new." in text
    assert "5 pass your filters and are in the digest." in text
    assert "greenhouse:acme:101  Acme: Senior Software Engineer, Platform  (found on the company's board; via " \
           "linkedin-alert)" in text
    assert "Vandelay" not in text and "Vandelay" in alerts.summary(r, every=True)
    d = alerts.to_dict(r)
    assert (d["new"], d["new_passing_filters"], d["repeated"]) == (7, 5, 1)


# -- The command and the MCP tool

def test_cli(web, watchlist, capsys, monkeypatch):
    cli.main(["-c", str(watchlist), "alerts", str(FIXTURES / "linkedin.eml"), "--no-follow"])
    out = capsys.readouterr().out
    assert "Read 1 email(s): 3 job(s), 0 already tracked, 0 repeated, 3 new." in out
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO((FIXTURES / "linkedin.eml").read_bytes())))
    cli.main(["-c", str(watchlist), "alerts", "-", "--no-follow", "--format", "json"])
    assert json.loads(capsys.readouterr().out)["known"] == 3
    with pytest.raises(SystemExit, match="give the alert emails"):
        cli.main(["-c", str(watchlist), "alerts"])
    with pytest.raises(SystemExit, match=r"alerts\.imap"):
        cli.main(["-c", str(watchlist), "alerts", "--imap"])


def test_mcp_tool(web, watchlist, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    raw = [(FIXTURES / n).read_text() for n in ("linkedin.eml", "indeed.eml")]
    out = mcp.import_job_alerts(raw, follow_links=False)
    assert (out["emails"], out["new"], out["repeated"]) == (2, 5, 1)
    assert out["found"][0]["link"] == "https://www.linkedin.com/jobs/view/4100000001/"
    assert mcp.import_job_alerts(raw, follow_links=False)["known"] == 5


# -- IMAP, optional

IMAP_WATCHLIST = "\nalerts:\n  imap:\n    host: imap.example.com\n    user: you@example.com\n"


class FakeIMAP:
    """Stands in for imaplib.IMAP4_SSL; the last one made is `FakeIMAP.last`."""

    last = None

    def __init__(self, host, port, ssl_context=None):
        self.host, self.port, self.calls = host, port, []
        FakeIMAP.last = self

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def select(self, folder, readonly=False):
        self.calls.append(("select", folder, readonly))
        return "OK", [b"2"]

    def search(self, charset, *criteria):
        self.calls.append(("search", *criteria))
        return "OK", [b"1 2" if "linkedin" in criteria[-1] else b"2"]

    def fetch(self, i, what):
        self.calls.append(("fetch", i, what))
        name = {b"1": "linkedin.eml", b"2": "indeed.eml"}[i]
        return "OK", [(b"1 (BODY[] {100}", (FIXTURES / name).read_bytes()), b")"]

    def logout(self):
        self.calls.append(("logout",))


def test_imap_settings(tmp_path, watchlist):
    for extra, error in (("    password: hunter2\n", "doesn't take a password"),
                         ("", "needs password_env .* or keychain"),
                         ("    password_env: X\n    color: blue\n", "unknown alerts.imap setting")):
        path = tmp_path / "w.yaml"
        path.write_text(watchlist.read_text() + IMAP_WATCHLIST + extra)
        with pytest.raises(config.ConfigError, match=error):
            config.load(path)
    path.write_text(watchlist.read_text() + IMAP_WATCHLIST + "    password_env: JOBWATCH_IMAP_PASSWORD\n")
    cfg = config.load(path)
    assert cfg.imap.host == "imap.example.com" and cfg.imap.senders == config.ALERT_SENDERS
    assert config.load(watchlist).imap is None  # off unless set


def test_imap_reads_without_marking_anything(tmp_path, watchlist, web, capsys, monkeypatch):
    path = tmp_path / "w.yaml"
    path.write_text(watchlist.read_text() + IMAP_WATCHLIST + "    password_env: JOBWATCH_IMAP_PASSWORD\n")
    monkeypatch.setenv("JOBWATCH_IMAP_PASSWORD", "not-a-real-password")
    monkeypatch.setattr(alerts.imaplib, "IMAP4_SSL", FakeIMAP)
    msgs = alerts.imap_messages(config.load(path).imap, today=date(2026, 10, 8))
    assert [alerts.sender(m) for m in msgs] == ["jobalerts-noreply@linkedin.com", "donotreply@jobalert.indeed.com"]
    calls = FakeIMAP.last.calls
    assert ("login", "you@example.com", "not-a-real-password") in calls and calls[-1] == ("logout",)
    assert ("select", '"INBOX"', True) in calls  # read-only
    assert {c[2] for c in calls if c[0] == "fetch"} == {"(BODY.PEEK[])"}  # PEEK: nothing marked read
    assert ("search", "SINCE", "05-Oct-2026", "FROM", '"jobalerts-noreply@linkedin.com"') in calls
    cli.main(["-c", str(path), "alerts", "--imap", "--no-follow"])
    out = capsys.readouterr()
    assert "Read 2 email(s)" in out.out and "not-a-real-password" not in out.out + out.err


def test_imap_password_from_the_keychain(monkeypatch):
    settings = config.Imap(host="imap.example.com", user="you@example.com", keychain="jobwatch-imap")
    seen = []

    def run(args, **kw):
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="from-keychain\n", stderr="")
    monkeypatch.setattr(alerts.subprocess, "run", run)
    assert alerts.imap_password(settings) == "from-keychain"
    assert seen == [["security", "find-generic-password", "-s", "jobwatch-imap", "-a", "you@example.com", "-w"]]
    monkeypatch.setattr(alerts.subprocess, "run", lambda args, **kw: subprocess.CompletedProcess(args, 44, "", ""))
    with pytest.raises(alerts.AlertError, match="no password in the keychain item 'jobwatch-imap'"):
        alerts.imap_password(settings)
    with pytest.raises(alerts.AlertError, match="set the environment variable NOPE"):
        alerts.imap_password(config.Imap(host="h", user="u", password_env="NOPE"))


# -- The fixtures themselves

def test_fixtures_hold_no_personal_data():
    """Sample alerts are made up: example.com addresses, placeholder tokens, made-up companies."""
    for f in FIXTURES.iterdir():
        text = f.read_text()
        addresses = set(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text))
        assert addresses <= {"you@example.com", "jobalerts-noreply@linkedin.com", "support@builtin.com",
                             "donotreply@jobalert.indeed.com", "digest@jobs.example.org", "alert-0001@example.com",
                             "alert-0002@example.com", "alert-0003@example.com", "alert-0004@example.com"}, f
        # No real tracking tokens: long opaque runs of letters and digits
        assert not re.search(r"(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{20,}", text), f
