"""The pay chips are links to where their figures can be checked, in a real browser: on a Today card and in the Details
dialog the Posted chip is the posting's own link, the Levels chip the Levels.fyi page jobwatch stored and read, the
Glassdoor chip a Glassdoor search; Recruiter is a plain chip (from your notes); no chip is ever an empty or "#" link,
a click on a chip's link stays out of the card, and drawing the links sends nothing to any outside site. The pages are
made up (tests/fixtures/levels) and no outside site is reached. Skipped where Playwright or its browser isn't
installed."""

# ruff: noqa: F811  (a test's `page` argument is the fixture imported from test_browser)
import pytest

from jobwatch import config
from jobwatch.store import Store

from .test_browser import browser, jobs, page, sync_api, watchlist  # noqa: F401 (fixtures)
from .test_levels import SE
from .test_levels import page as levels_page

ACME = "greenhouse:acme:101"
POSTING = "https://job-boards.greenhouse.io/acme/jobs/101"
LEVELS_PAGE = SE.format("acme")  # the page behind the Levels chip; the store keeps what it read at this address + .md


@pytest.fixture
def paid(jobs, watchlist):
    """Acme's job with Levels.fyi lookups on and its two pages already stored (so nothing is fetched), and a Glassdoor
    figure and a recruiter's base typed in."""
    watchlist.write_text(watchlist.read_text() + "pay: {levels: true, years: 20}\n")
    store = Store(config.load(watchlist).state)
    store.save_pay_page(LEVELS_PAGE + ".md", levels_page("acme-software-engineer"))
    store.save_pay_page(LEVELS_PAGE + "/levels/a3.md", levels_page("acme-software-engineer-a3"))
    store.set_comp(ACME, glassdoor="170-210K", base="165-195K")
    store.close()


@pytest.fixture
def quiet(page):
    """Any request the page makes to a site other than the jobwatch server is recorded and refused."""
    page.outside = []

    def refuse(route):
        page.outside.append(route.request.url)
        route.abort()
    page.route(lambda url: not url.startswith("http://127.0.0.1"), refuse)
    return page


def show(page, tab="today"):
    page.goto(page.url.split("#")[0] + "#" + tab)
    page.reload()
    page.wait_for_load_state("networkidle")


def acme_card(page):
    card = page.locator(".card.job", has=page.locator("b.co", has_text="Acme")).first
    sync_api.expect(card).to_be_visible()
    sync_api.expect(card.locator(".psrcs a.psrc[data-src=levels]")).to_be_visible(timeout=15000)
    return card


def check_links(chips):
    by = {a.get_attribute("data-src"): a for a in chips.locator("a.psrc").all()}
    assert set(by) == {"posted", "levels", "glassdoor"}
    for src, a in by.items():
        assert a.get_attribute("target") == "_blank" and a.get_attribute("rel") == "noopener noreferrer", src
        assert a.get_attribute("title").startswith("Open "), src
        assert a.locator("svg.ico").count() == 1, src  # the external-link icon
    assert by["posted"].get_attribute("href") == POSTING
    assert by["posted"].get_attribute("title") == "Open the posting to verify: the posting's own range"
    assert by["levels"].get_attribute("href") == LEVELS_PAGE  # the page it was read from, not a site-wide link
    assert by["levels"].get_attribute("title").startswith("Open Levels.fyi to verify: A3 median $160K base")
    assert by["glassdoor"].get_attribute("href").startswith(
        "https://www.glassdoor.com/Search/results.htm?keyword=Acme%20Senior%20Software%20Engineer")
    assert "Glassdoor salary search" in by["glassdoor"].get_attribute("title")
    # from your notes: a plain chip with the words on hover, never a link
    recruiter = chips.locator(".psrc-recruiter")
    sync_api.expect(recruiter).to_have_count(1)
    assert recruiter.evaluate("e => e.tagName") == "SPAN"
    assert recruiter.get_attribute("title").startswith("From your notes")
    assert chips.locator('a[href=""], a[href="#"], a:not([href])').count() == 0  # never an empty or "#" link


def test_the_chips_on_a_today_card_are_links_to_their_sources(paid, quiet):
    show(quiet)
    check_links(acme_card(quiet).locator(".psrcs"))
    assert quiet.errors == []


def test_the_details_dialog_has_the_same_links_and_a_sources_line(paid, quiet):
    show(quiet)
    acme_card(quiet).get_by_role("button", name="Details", exact=True).click()
    dialog = quiet.locator("#dialog")
    sync_api.expect(dialog.locator(".psrcs a.psrc[data-src=levels]")).to_be_visible(timeout=15000)
    check_links(dialog.locator(".psrcs"))
    sources = dialog.locator(".paysrcs")
    sync_api.expect(sources).to_contain_text("Sources:")
    assert [a.get_attribute("href") for a in sources.locator("a").all()][1] == LEVELS_PAGE
    assert quiet.errors == []


def test_a_click_on_a_chip_link_stays_out_of_the_card_and_nothing_goes_out_when_links_are_drawn(paid, quiet):
    show(quiet)
    card = acme_card(quiet)
    for a in card.locator("a.psrc").all():  # stop the new tab: the test never visits an outside site
        a.evaluate("e => e.addEventListener('click', ev => ev.preventDefault())")
    card.locator("a.psrc[data-src=posted]").click()
    assert quiet.locator("#overlay").evaluate("e => getComputedStyle(e).display") == "none"  # no Details dialog
    assert quiet.outside == []  # drawing the links, and clicking one here, reached no outside site
    assert quiet.errors == []


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_a_linked_chip_underlines_on_hover_in_both_themes(paid, quiet, theme, tmp_path):
    """The chip keeps its look and shows it is a link on hover; set JOBWATCH_SHOTS=<folder> to also save a picture of
    the chips in each theme there."""
    import os
    show(quiet)
    quiet.evaluate("t => document.documentElement.dataset.theme = t", theme)
    chips = acme_card(quiet).locator(".psrcs")
    link, plain = chips.locator("a.psrc[data-src=levels]"), chips.locator(".psrc-recruiter")
    assert link.evaluate("e => getComputedStyle(e).textDecorationLine") == "none"
    assert link.evaluate("e => getComputedStyle(e).cursor") == "pointer"
    assert plain.evaluate("e => getComputedStyle(e).cursor") != "pointer"
    link.hover()
    assert link.evaluate("e => getComputedStyle(e).textDecorationLine") == "underline"
    if shots := os.environ.get("JOBWATCH_SHOTS"):
        os.makedirs(shots, exist_ok=True)
        quiet.locator(".card.job", has=quiet.locator("b.co", has_text="Acme")).first.screenshot(
            path=os.path.join(shots, f"pay-links-{theme}.png"))


def test_a_job_added_by_hand_has_a_plain_posted_chip_with_no_link(watchlist, quiet):
    store = Store(config.load(watchlist).state)
    store.add("Initech", "Field Engineer", status="queued", description="Annual Salary: $150,000 - $190,000")
    store.close()
    show(quiet, "queue")
    chips = quiet.locator(".card.job", has=quiet.locator("b.co", has_text="Initech")).first.locator(".psrcs")
    sync_api.expect(chips.locator(".psrc-posted")).to_have_count(1, timeout=15000)
    assert chips.locator(".psrc-posted").evaluate("e => e.tagName") == "SPAN"
    assert chips.locator("a").count() == 0  # nothing known to link to: no link, not even an empty one
    assert quiet.outside == [] and quiet.errors == []
