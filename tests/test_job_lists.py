"""The job list extractor (chrome-extension/job-lists.js), run in Chromium against made-up LinkedIn and Indeed list
pages (tests/fixtures/lists), and the copy jobwatch ships for `import-list --script`.

The browser tests are skipped unless Playwright and its Chromium are installed:

    pip install playwright && playwright install chromium
"""
# ruff: noqa: E501  (cards' text as the site writes it)

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from jobwatch import joblist

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "chrome-extension" / "job-lists.js"
FIXTURES = Path(__file__).parent / "fixtures" / "lists"


def test_jobwatch_ships_the_extensions_extractor():
    assert joblist.script() == SCRIPT.read_text(encoding="utf-8")


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_a_linkedin_cards_text_reads_as_a_record(tmp_path):
    js = tmp_path / "case.js"
    js.write_text(f"""const L = require({json.dumps(str(SCRIPT))});
console.log(JSON.stringify([
  L.parseLinkedIn("Senior Platform Engineer  (Verified job)\\nSenior Platform Engineer \\n\\nInitech\\n\\nBoulder, CO (Remote)\\n\\nPosted 9 minutes ago\\n9 minutes ago\\n\\n · \\n\\nBe an early applicant\\n\\n · \\n\\nEasy Apply", "4100000001"),
  L.parseLinkedIn("Platform Engineer (Verified job)\\nPlatform Engineer \\n\\nGlobex\\n\\nBoulder, CO\\n\\n$120K/yr - $180K/yr\\n\\n401(k) benefit\\n\\n1 connection works here\\n\\nSaved", "4100000002"),
  L.parseLinkedIn("", "4100000003"),
]));""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    first, second, empty = json.loads(r.stdout)
    assert first == {"source": "linkedin", "id": "4100000001", "title": "Senior Platform Engineer",
                     "company": "Initech", "location": "Boulder, CO (Remote)", "pay": "", "posted": "9 minutes ago"}
    assert second["pay"] == "$120K/yr - $180K/yr" and second["location"] == "Boulder, CO" and not second["posted"]
    assert empty is None


@pytest.fixture(scope="module")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as pw:
        try:
            b = pw.chromium.launch()
        except Exception as e:  # no Chromium downloaded
            pytest.skip(f"no Chromium for Playwright: {e}")
        yield b
        b.close()


def open_list(browser, name: str):
    page = browser.new_page()
    page.goto((FIXTURES / name).as_uri())
    page.add_script_tag(path=str(SCRIPT))
    return page


def test_linkedin_every_page_is_read_scrolled_to_its_end_and_each_job_once(browser):
    page = open_list(browser, "linkedin_list.html")
    try:
        assert len(page.evaluate("JWList.readList(document)")) == 3  # before scrolling, as LinkedIn renders it
        got = page.evaluate("JWList.readAll({maxPages: 5})")
        assert [r["id"] for r in got] == [f"410000000{i}" for i in range(1, 7)]
        first = got[0]
        assert first == {"source": "linkedin", "id": "4100000001", "title": "Senior Platform Engineer",
                         "company": "Initech", "location": "Boulder, CO (Hybrid)", "pay": "$120K/yr - $180K/yr",
                         "posted": "9 minutes ago"}
        assert got[1]["title"] == "Security Automation Engineer" and got[1]["company"] == "Globex Corporation"
        assert got[3]["posted"] == "2 days ago" and got[4]["pay"] == "$120K/yr"
        assert page.evaluate("JWList.lastRun") == {"pages": 2, "jobs": 6, "nextUrl": None}
    finally:
        page.close()


def test_linkedin_the_page_cap_stops_the_paging(browser):
    page = open_list(browser, "linkedin_list.html")
    try:
        got = page.evaluate("JWList.readAll({maxPages: 1})")
        assert len(got) == 5 and page.evaluate("JWList.lastRun.pages") == 1
    finally:
        page.close()


def test_indeed_cards_read_with_missing_fields_and_next_is_a_link(browser):
    page = open_list(browser, "indeed_list.html")
    try:
        got = page.evaluate("JWList.readPage({source: 'indeed'})")
        assert [r["id"] for r in got] == [f"a1b2c3d4e5f6000{i}" for i in range(1, 5)]
        assert got[0] == {"source": "indeed", "id": "a1b2c3d4e5f60001", "title": "Senior Platform Engineer",
                          "company": "Initech", "location": "Boulder, CO 80301", "pay": "$120,000 - $180,000 a year",
                          "posted": "3 days ago"}
        assert got[1]["title"] == "Security Engineer" and got[1]["posted"].lower() == "just posted"
        assert got[2] == {"source": "indeed", "id": "a1b2c3d4e5f60003", "title": "Data Analyst",
                          "company": "Umbrella Corp", "location": "", "pay": "", "posted": ""}
        assert got[3]["company"] == "Hooli" and got[3]["pay"] == "$60 an hour"
        nxt = page.evaluate("JWList.next({source: 'indeed'})")
        assert nxt.endswith("/jobs?q=engineer&l=Boulder%2C+CO&start=10")
        # readAll stops where a page has to be loaded, and says where
        page.evaluate("JWList.readAll({source: 'indeed'})")
        assert page.evaluate("JWList.lastRun.nextUrl") == nxt
    finally:
        page.close()
