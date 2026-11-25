"""Filling in the posting text of jobs that came from an alert or a list with none (filltext.py): the company's
board first, then the job's own link, then a LinkedIn or Indeed page read in the person's browser (here, a fake
reader). Every page and company is made up."""

import pytest

from jobwatch import alerts, config, filltext
from jobwatch.store import Store, closed_state

from .test_alerts import emailed, posting_of, umbrella_board

LINKEDIN_PAGE = """Initech

Platform Engineer

United States · 1 week ago · 45 people clicked apply

$100K/yr - $150K/yr
Remote

Not currently accepting applications

Show match details

About the job

We are hiring a Platform Engineer to run the services behind Initech's reports. You will build Rust and Python
tools, own on-call for the data platform, and work with the support team on the hardest customer cases.

Qualifications

5+ years building production services. Strong communication skills for diverse audiences.

… more

Benefits found in job post

401(k)

Set alert for similar jobs

More jobs

Platform Engineer

Globex
"""

INDEED_PAGE = """Skip to main content
Platform Engineer
Initech
Remote
$100 - $150 an hour
Apply with Indeed
Job details
Full job description

About Initech

Initech builds reporting tools for banks. This role designs and runs the platform behind them: Rust services,
Python tooling, observability and the on-call rotation for the data platform, with the support team.

Pay: $100.00 - $150.00 per hour

Report job
Senior Engineer jobs in Remote
Hiring Lab
"""

SIGN_IN = "Sign in to see who you already know at Initech\n\nJoin now\n\nSign in\n"
CAPTCHA = "Just a moment...\n\nVerify you are human by completing the action below.\n"


def test_a_linkedin_page_gives_its_description_and_that_it_is_closed():
    read = filltext.posting_from_page("linkedin", LINKEDIN_PAGE)
    assert read.text.startswith("We are hiring a Platform Engineer") and read.text.endswith("diverse audiences.")
    assert "Benefits found" not in read.text and "More jobs" not in read.text
    assert read.closed


def test_an_indeed_page_gives_its_description():
    read = filltext.posting_from_page("indeed", INDEED_PAGE)
    assert read.text.startswith("About Initech") and read.text.endswith("per hour")
    assert "Report job" not in read.text and not read.closed


@pytest.mark.parametrize("page, why", [(SIGN_IN, "asks to sign in"), (CAPTCHA, "captcha"),
                                       ("Some other page about nothing in particular.", "no posting text")])
def test_a_page_with_no_posting_says_why(page, why):
    with pytest.raises(filltext.PageError, match=why):
        filltext.posting_from_page("linkedin", page)


def test_which_links_only_a_browser_can_read():
    assert filltext.browser_site("https://www.linkedin.com/jobs/view/4000000001/") == "linkedin"
    assert filltext.browser_site("https://www.indeed.com/viewjob?jk=abc123") == "indeed"
    assert filltext.browser_site("https://www.linkedin.com/jobs/search/?keywords=x") == ""
    assert filltext.browser_site("https://jobs.lever.co/globex/aaaa-1111") == ""
    assert filltext.browser_site("") == ""


def test_the_reason_says_what_is_in_the_way():
    store_job = alerts.email_job(alerts.Alert("Platform Engineer", "Initech", "", url="https://www.linkedin.com/jobs/view/1/",
                                              site="linkedin", via="linkedin-alert"))
    assert filltext.no_text_why(store_job) == (
        "no_text", "No posting text: LinkedIn blocks automatic reading; open it and press Read posting")
    store_job.url = "https://www.indeed.com/viewjob?jk=abc123"
    assert "Indeed blocks automatic reading" in filltext.no_text_why(store_job)[1]
    store_job.url = ""
    assert filltext.no_text_why(store_job)[1].startswith("No posting text: add a link")


def test_the_companys_board_is_the_first_source(web, watchlist):
    umbrella_board(web, posting_of(7, "Platform Engineer"))
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    key = emailed(store)
    store.note_unwatched("umbrella", "Umbrella", key, "greenhouse:umbrellacorp", "posting")
    seen = []
    out = filltext.fill_text(cfg, store, read_browser=lambda url: seen.append(url) or LINKEDIN_PAGE)
    assert [(o.job.key, o.how) for o in out] == [(key, "board")]
    assert "Rust services" in store.find(key)[0].description
    assert seen == []  # the browser isn't asked for what a board has


def test_a_linkedin_job_with_no_board_is_read_in_the_browser(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    key = emailed(store, "Initech", "Platform Engineer")
    asked = []
    dry = filltext.fill_text(cfg, store, read_browser=lambda url: asked.append(url) or LINKEDIN_PAGE, dry_run=True)
    assert dry[0].how == "browser" and store.find(key)[0].description == ""
    out = filltext.fill_text(cfg, store, read_browser=lambda url: asked.append(url) or LINKEDIN_PAGE)
    job, rec = store.find(key)
    assert out[0].how == "browser" and job.description.startswith("We are hiring a Platform Engineer")
    assert "in the person's own browser" in rec["note"] and "not accepting applications" in rec["note"]
    assert rec["status"] == "new" and asked[-1] == "https://www.linkedin.com/jobs/view/1/"
    assert filltext.textless(store) == []


def test_without_a_reader_the_linkedin_job_waits_for_the_browser(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    key = emailed(store, "Initech", "Platform Engineer")
    (o,) = filltext.fill_text(cfg, store)
    assert o.how == "needs_browser" and store.find(key)[0].description == ""
    assert "needs the browser" in filltext.summary([o]) and "0 filled in; 1 on LinkedIn" in filltext.summary([o])
    # a wall is not text: the job waits, with what the page said
    (o,) = filltext.fill_text(cfg, store, read_browser=lambda url: SIGN_IN)
    assert o.how == "needs_browser" and "asks to sign in" in o.note and store.find(key)[0].description == ""


def test_a_link_to_a_readable_posting_fills_the_job(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    key = store.add("Globex", "Staff Engineer", url="https://jobs.lever.co/globex/aaaa-1111",
                    status="queued").key
    (o,) = filltext.fill_text(cfg, store)
    assert o.how == "link" and "Train machine learning models" in store.find(key)[0].description


def test_a_job_with_no_link_has_no_source(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    store.add("Initech", "Platform Engineer", status="queued")
    (o,) = filltext.fill_text(cfg, store)
    assert o.how == "none" and "add the posting's link or text" in o.note


def test_only_new_shown_and_queued_jobs_without_text_are_looked_at(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    skipped = emailed(store, "Initech", "Platform Engineer")
    store.set_status([skipped], "skipped")
    assert filltext.fill_text(cfg, store) == []
    assert "has its posting text" in filltext.summary([])


REAL_SHAPE = """Initech

Staff Engineer, Security Operations

United States · 1 month ago · 34 people clicked apply

Promoted by hirer · Responses managed off LinkedIn

$150K/yr - $190K/yr
Remote
Full-time

 No longer accepting applications.

Use AI to assess how you fit

About the job

For our client, Initech, we are looking for a Staff Engineer to own security operations tooling. You will build
detections in Python, run the incident tooling, and work with the platform team on the hardest cases every week.

Set alert for similar jobs
"""


def test_the_closed_line_of_a_real_banner_is_read():
    """The banner's line comes after the pay chips with the icon's text around it; a trailing dot or a stray space
    doesn't hide it, and Indeed's own wording counts too."""
    assert filltext.posting_from_page("linkedin", REAL_SHAPE).closed
    expired = INDEED_PAGE.replace("Job details\n", "Job details\nThis job has expired on Indeed\n")
    assert filltext.posting_from_page("indeed", expired).closed
    assert not filltext.posting_from_page("indeed", INDEED_PAGE).closed
    # the same words inside the description are not the banner
    inside = REAL_SHAPE.replace(" No longer accepting applications.", "").replace(
        "About the job\n\n", "About the job\n\nNo longer accepting applications\n\n")
    assert not filltext.posting_from_page("linkedin", inside).closed


def test_saving_a_closed_page_marks_the_job_closed(watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    key = emailed(store, "Initech", "Platform Engineer")
    filltext.save_page_posting(store, key, filltext.posting_from_page("linkedin", LINKEDIN_PAGE))
    rec = store.find(key)[1]
    assert closed_state(rec) == "closed" and "LinkedIn says it is not accepting applications" in rec["note"]


def test_saving_a_page_the_browser_read(watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    key = emailed(store, "Initech", "Platform Engineer", via="indeed-alert")
    filltext.save_page_posting(store, key, filltext.posting_from_page("indeed", INDEED_PAGE))
    job, rec = store.find(key)
    assert job.description.startswith("About Initech") and "Indeed page" in rec["note"]
    assert "not accepting" not in rec["note"]


def test_the_command_lists_saves_and_refuses(web, watchlist, tmp_path, capsys):
    from jobwatch import cli

    cfg = config.load(watchlist)
    store = Store(cfg.state)
    key = emailed(store, "Initech", "Platform Engineer")
    store.close()
    c = ["-c", str(watchlist)]
    cli.main([*c, "fill-text", "--open"])
    assert "https://www.linkedin.com/jobs/view/1/" in capsys.readouterr().out
    wall = tmp_path / "wall.txt"
    wall.write_text(SIGN_IN, encoding="utf-8")
    with pytest.raises(SystemExit, match="asks to sign in"):
        cli.main([*c, "fill-text", "--set", key, "--page-text", str(wall)])
    page = tmp_path / "page.txt"
    page.write_text(LINKEDIN_PAGE, encoding="utf-8")
    cli.main([*c, "fill-text", "--set", key, "--page-text", str(page)])
    assert "not accepting applications" in capsys.readouterr().out
    store = Store(cfg.state)
    assert store.find(key)[0].description.startswith("We are hiring")
    cli.main([*c, "fill-text", "--open"])
    assert "No job is waiting" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="--page-text"):
        cli.main([*c, "fill-text", "--set", key])


def test_open_lists_the_links_one_to_a_line():
    store_job = alerts.email_job(alerts.Alert("Platform Engineer", "Initech", "", url="https://www.linkedin.com/jobs/view/1/",
                                              site="linkedin", via="linkedin-alert"))
    text = filltext.open_list([store_job])
    assert text.splitlines()[1] == "  https://www.linkedin.com/jobs/view/1/"
    assert "No job is waiting" in filltext.open_list([])
