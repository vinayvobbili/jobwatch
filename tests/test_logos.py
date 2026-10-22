"""Company logos (logos.py): the company's site from its jobs, the icon from the site, and the page's /logo/ route."""

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from jobwatch import logos, sources
from jobwatch.alerts import Robots
from jobwatch.models import Job
from jobwatch.store import Store

from .conftest import TOKEN, FakeWeb, request

PNG = b"\x89PNG\r\n\x1a\n" + bytes(40)
ICO = b"\x00\x00\x01\x00" + bytes(40)


def job(company="Acme", board="acme", url="https://boards.greenhouse.io/acme/jobs/1", text=""):
    return Job(source="greenhouse", company=board, id="1", title="Engineer", url=url, company_name=company,
               description=text)


class Bytes(FakeWeb):
    """get_bytes: serves bytes, 404s everything else."""


def finder(pages: dict, files: dict):
    get = FakeWeb({"https://acme.com/robots.txt": "", **pages})
    return dict(get=get, get_bytes=Bytes(files), robots=Robots(get)), get


def test_the_site_is_one_the_jobs_point_to_whose_name_is_the_company():
    jobs = [job(text="See https://www.acme.com/about and careers.acme.com, or eeoc.gov and https://linkedin.com/x"),
            job(url="https://careers.acme.com/jobs/2")]
    assert logos.sites(jobs) == [("acme.com", False)]
    assert logos.sites([job(company="Globex", board="globex", text="globexcorp.com")]) == [
        ("globexcorp.com", False), ("globex.com", True)]
    # A Workday board's name isn't a name to guess a domain from
    wd = job(company="Initech", board="initech.wd1/InitechCareers")
    assert logos.sites([wd]) == [("initech.com", True)]
    assert logos.site_of("www.acme.co.uk") == "acme.co.uk" and logos.site_of("jobs.eu.acme.com") == "acme.com"


def test_icons_biggest_first_then_the_favicon():
    html = ('<link rel="icon" href="/f-16.png" sizes="16x16"><link rel=apple-touch-icon href="/touch.png">'
            '<link rel="shortcut icon" href="https://cdn.acme.com/f.svg"><link rel="mask-icon" href="/m.svg">'
            '<link rel="stylesheet" href="/s.css"><link rel="icon" href="data:image/png;base64,xx">')
    assert logos.icons(html, "https://acme.com/") == [
        "https://cdn.acme.com/f.svg", "https://acme.com/touch.png", "https://acme.com/f-16.png",
        "https://acme.com/favicon.ico"]


def test_only_an_image_is_kept_by_its_bytes():
    assert logos.image_type(PNG) == "image/png" and logos.image_type(ICO) == "image/x-icon"
    assert logos.image_type(b'<?xml version="1.0"?>\n<svg xmlns="x"></svg>') == "image/svg+xml"
    assert logos.image_type(b"<!doctype html><html>not found</html>") is None


def test_find_takes_the_first_icon_that_is_an_image():
    kw, _ = finder({"https://acme.com/": '<link rel="icon" href="/a.png" sizes="64x64">'},
                   {"https://acme.com/a.png": b"<html>oops</html>", "https://acme.com/favicon.ico": ICO})
    assert logos.find([job(text="acme.com")], **kw) == ("acme.com", "image/x-icon", ICO)


def test_a_guessed_domain_must_name_the_company_and_robots_is_obeyed():
    kw, _ = finder({"https://acme.com/": "<title>Domain for sale</title>"}, {"https://acme.com/favicon.ico": ICO})
    assert logos.find([job()], **kw) == ("", "", b"")
    kw, _ = finder({"https://acme.com/": "<title>Acme | Rockets</title>"}, {"https://acme.com/favicon.ico": ICO})
    assert logos.find([job()], **kw)[0] == "acme.com"
    kw, get = finder({"https://acme.com/robots.txt": "User-agent: *\nDisallow: /\n"},
                     {"https://acme.com/favicon.ico": ICO})
    assert logos.find([job(text="acme.com")], **kw) == ("", "", b"")
    assert get.calls == ["https://acme.com/robots.txt"]


def test_a_site_that_refuses_finds_nothing():
    kw, _ = finder({"https://acme.com/": sources.Refused("HTTP 403")}, {})
    assert logos.find([job(text="acme.com")], **kw) == ("", "", b"")


def test_look_up_keeps_what_it_found_and_waits_before_asking_again(tmp_path, monkeypatch):
    monkeypatch.setattr(logos, "PAUSE", 0)
    store = Store(tmp_path / "state.db")
    kw, get = finder({"https://acme.com/": "Acme"}, {"https://acme.com/favicon.ico": PNG})
    assert logos.look_up(store, ["Acme", "Acme, Inc.", "Nobody"], [job(text="acme.com")], **kw) == ["acme"]
    site, ctype, body, _ = store.logo("acme")
    assert (site, ctype, body) == ("acme.com", "image/png", PNG) and store.logo("nobody") is None
    asked = len(get.calls)
    assert logos.look_up(store, ["Acme"], [job()], **kw) == [] and len(get.calls) == asked
    store.save_logo("globex", "", "", b"")
    later = datetime.now(timezone.utc) + logos.MISSING + timedelta(hours=1)
    assert not logos.due(store.logo("globex")) and logos.due(store.logo("globex"), later)
    assert not logos.due(store.logo("acme"), later) and logos.due(None)
    store.close()


def test_the_page_shows_a_kept_logo_and_asks_for_one_it_lacks(server, watchlist, monkeypatch):
    monkeypatch.setattr(sources, "get_bytes", Bytes({}))
    store = Store(watchlist.parent / "state.db")
    store.save_logo("acme", "acme.com", "image/png", PNG)
    store.close()
    status, body, headers = request(server, "GET", f"/logo/{TOKEN}/{quote('Acme, Inc.')}", with_headers=True)
    assert (status, body, headers["Content-Type"]) == (200, PNG, "image/png")
    assert headers["Content-Security-Policy"] == "sandbox" and "max-age" in headers["Cache-Control"]
    assert request(server, "GET", f"/logo/{TOKEN}/Globex")[0] == 404
    assert request(server, "GET", f"/logo/wrong/{quote('Acme')}")[0] == 403
    page = request(server, "GET", "/")[1].decode()
    assert "/logo/${TOKEN}/${encodeURIComponent(name)}" in page and 'el.classList.add("logo")' in page
