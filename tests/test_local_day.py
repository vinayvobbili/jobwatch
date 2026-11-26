"""A stamp the store wrote in UTC shows on its day on this computer: a posting found closed at 10:13 PM Eastern on
Nov 25 (03:13 UTC on Nov 26) read "closed Nov 26", because the page cut the stamp to its first ten characters.
Python's local_day and the page's localDay turn a stamp into its local day; a plain day passes through; both are
checked here with the clock set to Eastern, in node and in a real browser."""

# ruff: noqa: F811  (a test's `browser` argument is the fixture imported from test_browser)
import json
import os
import shutil
import subprocess
import time

import pytest

from jobwatch import closed_notice, company, config
from jobwatch.localday import local_day
from jobwatch.store import Store

from .test_browser import browser, sync_api, watchlist  # noqa: F401 (fixtures)
from .test_page_js import page_function

EVENING = "2026-11-26T03:13:00+00:00"  # 10:13 PM Eastern on Nov 25
AFTERNOON = "2026-11-26T15:00:00+00:00"  # 10 AM Eastern on Nov 26
needs_tzset = pytest.mark.skipif(not hasattr(time, "tzset"), reason="needs time.tzset")
needs_node = pytest.mark.skipif(not shutil.which("node"), reason="needs node")


@pytest.fixture
def eastern():
    before = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    time.tzset()
    yield
    if before is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = before
    time.tzset()


@needs_tzset
def test_a_utc_evening_stamp_is_the_day_before_in_eastern_time(eastern):
    assert local_day(EVENING) == "2026-11-25"
    assert local_day("2026-11-26T03:13:00.123456+00:00") == "2026-11-25"
    assert local_day("2026-11-26T03:13:00Z") == "2026-11-25"


@needs_tzset
def test_a_utc_daytime_stamp_stays_on_its_day(eastern):
    assert local_day(AFTERNOON) == "2026-11-26"


@needs_tzset
def test_a_plain_day_and_unreadable_values_are_handled(eastern):
    assert local_day("2026-11-26") == "2026-11-26"
    assert local_day("") == local_day(None) == local_day("  ") == ""
    assert local_day("not a day") == local_day("2026-13-45") == ""


@needs_tzset
def test_the_closed_notice_and_company_page_days_are_local(eastern):
    assert closed_notice.local_day(EVENING) == "2026-11-25"
    assert closed_notice.local_day(None) is None
    assert company._day(EVENING) == "2026-11-25"
    assert company._day(None) is None


@needs_node
def test_the_pages_local_day_in_eastern_time(tmp_path):
    js = tmp_path / "day.js"
    js.write_text(page_function("localDay") + f"""
console.log(JSON.stringify([localDay("{EVENING}"), localDay("{AFTERNOON}"), localDay("2026-11-26"),
  localDay(""), localDay(null), localDay(undefined), localDay("not a day")]));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True, env={**os.environ, "TZ": "America/New_York"})
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ["2026-11-25", "2026-11-26", "2026-11-26", "", "", "", ""]


@pytest.fixture
def ny_page(browser, server):
    """The Queue tab, in a browser whose clock is Eastern."""
    ctx = browser.new_context(timezone_id="America/New_York")
    page = ctx.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.base = f"http://127.0.0.1:{server}/"
    yield page
    ctx.close()


def test_a_posting_found_closed_in_the_evening_shows_that_evenings_day(watchlist, ny_page):
    store = Store(config.load(watchlist).state)
    try:
        job = store.add("Initech", "Principal Architect", status="queued", description="Design systems. " * 30)
        store.set_closed(job.key, True)
        with store.db:
            store.db.execute("UPDATE jobs SET closed=? WHERE key=?", (EVENING, job.key))
        store.confirm_closed([job.key])
    finally:
        store.close()
    ny_page.goto(ny_page.base + "#queue")
    ny_page.wait_for_load_state("networkidle")
    badge = ny_page.locator(f'[id="job-{job.key}"] .badge.closed')
    sync_api.expect(badge).to_have_text("closed Nov 25")
    assert ny_page.errors == []
