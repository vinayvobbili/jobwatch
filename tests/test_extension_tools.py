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

live_check = pytest.importorskip("live_check")  # imports the harness, which needs nothing installed to import


def test_the_store_zip_holds_only_what_the_browser_loads(tmp_path):
    target = package.build(tmp_path, expected_version=package.package_version())
    assert target.name == f"jobwatch-extension-{package.package_version()}.zip"
    names = set(zipfile.ZipFile(target).namelist())
    assert {"manifest.json", "background.js", "logic.js", "page.js", "panel.js", "popup.html", "options.html",
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


def test_the_committed_icons_are_the_ones_the_tool_draws():
    for size in make_icons.SIZES:
        png = (EXT / "icons" / f"icon{size}.png").read_bytes()
        assert struct.unpack(">II", png[16:24]) == (size, size)
        assert png == make_icons.render_png(size)
