"""The extension's packaging and icon tools (chrome-extension/tools)."""

import json
import struct
import sys
import zipfile
from pathlib import Path

import pytest

EXT = Path(__file__).resolve().parent.parent / "chrome-extension"
sys.path.insert(0, str(EXT / "tools"))
import make_icons  # noqa: E402
import package  # noqa: E402
import store_assets  # noqa: E402

live_check = pytest.importorskip("live_check")  # imports the harness, which needs nothing installed to import


def test_the_store_zip_holds_only_what_the_browser_loads(tmp_path):
    target = package.build(tmp_path, expected_version=package.package_version())
    assert target.name == f"jobwatch-extension-{package.package_version()}.zip"
    names = set(zipfile.ZipFile(target).namelist())
    assert {"manifest.json", "background.js", "logic.js", "page.js", "sidepanel.js", "sidepanel.html",
            "options.html",
            "icons/icon128.png", "THIRD_PARTY_NOTICES"} <= names
    assert not any(n.startswith(("demo/", "tools/")) or n.endswith(".md") for n in names)


def test_the_zip_refuses_a_version_that_is_not_the_packages(tmp_path):
    with pytest.raises(SystemExit, match="bump them together"):
        package.build(tmp_path, expected_version="9.9.9")


def test_the_manifest_version_follows_the_package():
    assert json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))["version"] == package.package_version()


def test_the_live_check_prints_a_line_per_field():
    reply = {"ok": True, "info": {"title": "Platform Engineer", "company": "Initech"}, "items": [
        {"question": "First name", "kind": "text", "source": "details", "value": "Jordan", "checked": True},
        {"question": "What are your salary expectations?", "kind": "text", "source": "details", "value": "180K"},
        {"question": "Gender", "kind": "select", "source": "details", "value": "Decline to answer",
         "options": ["Male", "Female", "Decline"], "filled": True},
        {"question": "How did you hear about us? " * 5, "kind": "textarea", "source": "none", "value": ""},
    ]}
    out = live_check.report("https://jobs.example.com/apply", reply).splitlines()
    assert out[1] == "  Platform Engineer at Initech: 4 fields (3 details, 1 none)"
    assert out[2].startswith("  [x] details  text") and out[2].endswith("Jordan")
    assert out[3].startswith("  [ ] details")
    assert out[4].endswith("Decline to answer [3 options] (already filled)")
    assert "…" in out[5]
    assert live_check.report("u", {"ok": False, "error": "No form fields"}) == "u\n  could not scan: No form fields"


def test_the_store_composition_makes_screenshots_of_the_size_the_store_requires(tmp_path):
    """The compose step on blank images, in a plain Chromium (no extension); skips without Playwright."""
    sync_api = pytest.importorskip("playwright.sync_api")
    blank = tmp_path / "blank.png"
    blank.write_bytes((EXT / "icons" / "icon128.png").read_bytes())
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # no Chromium installed
            pytest.skip(f"Chromium unavailable: {exc}")
        try:
            context = browser.new_context()
            two = store_assets.compose(context, "Title", "Subtitle", [blank, blank], tmp_path / "two.png")
            one = store_assets.compose(context, "Title", "Subtitle", [blank], tmp_path / "one.png")
            small = store_assets.render(context, store_assets.promo_small_html(blank), store_assets.PROMO,
                                        tmp_path / "small.png")
            marquee = store_assets.render(context, store_assets.promo_marquee_html(blank, blank),
                                          store_assets.MARQUEE, tmp_path / "marquee.png")
        finally:
            browser.close()
    for path, size in [(two, store_assets.SCREEN), (one, store_assets.SCREEN), (small, store_assets.PROMO),
                       (marquee, store_assets.MARQUEE)]:
        assert struct.unpack(">II", path.read_bytes()[16:24]) == size


def test_the_caption_band_leaves_the_rest_of_the_screenshot_to_the_capture():
    assert store_assets.FORM_W + store_assets.PANEL_W == store_assets.SCREEN[0]
    assert store_assets.CAPTION_H + store_assets.BODY_H == store_assets.SCREEN[1]
    assert "split" in store_assets.stage_html("t", "s", [EXT / "icons" / "icon16.png"] * 2)


def test_the_live_check_samples_one_form_per_kind_of_board():
    from jobwatch.models import Job

    jobs = [Job("greenhouse", "initech", "1", "SRE", "https://job-boards.greenhouse.io/initech/jobs/1"),
            Job("greenhouse", "globex", "2", "SRE", "https://careers.globex.example/jobs?gh_jid=2"),
            Job("greenhouse", "initech", "3", "Older", "https://job-boards.greenhouse.io/initech/jobs/3"),
            Job("lever", "umbrella", "4", "SRE", "https://jobs.lever.co/umbrella/4"),
            Job("ashby", "hooli", "5", "SRE", "https://jobs.ashbyhq.com/hooli/5"),
            Job("workday", "acme", "6", "SRE", "https://acme.wd5.myworkdayjobs.com/x/job/6")]
    assert live_check.samples(jobs) == {
        "greenhouse": "https://job-boards.greenhouse.io/initech/jobs/1",
        "greenhouse embedded": "https://careers.globex.example/jobs?gh_jid=2",
        "lever": "https://jobs.lever.co/umbrella/4/apply",
        "ashby": "https://jobs.ashbyhq.com/hooli/5/application",
    }


def test_the_committed_icons_are_the_ones_the_tool_draws():
    for size in make_icons.SIZES:
        png = (EXT / "icons" / f"icon{size}.png").read_bytes()
        assert struct.unpack(">II", png[16:24]) == (size, size)
        assert png == make_icons.render_png(size)
