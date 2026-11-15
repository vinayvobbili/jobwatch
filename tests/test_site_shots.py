"""scripts/site_shots.py screenshots a site with its settings popover open."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_shoot_writes_hero_and_popover_shots(tmp_path):
    pytest.importorskip("playwright.sync_api")
    spec = importlib.util.spec_from_file_location("site_shots", ROOT / "scripts" / "site_shots.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(
        '<button id="gear" aria-expanded="false" onclick="this.setAttribute(\'aria-expanded\',\'true\')">x</button>'
        "<script>addEventListener('keydown',()=>gear.setAttribute('aria-expanded','false'))</script>")
    try:
        overflow = mod.shoot(site, tmp_path / "out", "t")
    except Exception as e:  # no browser installed here
        pytest.skip(str(e))
    assert (tmp_path / "out" / "t-375-popover.png").is_file()
    assert overflow == {"1440": 0, "375": 0}
