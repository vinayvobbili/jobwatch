"""The landing page (site/index.html) says what the README and the Web Store listing say."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
STORE = (ROOT / "chrome-extension" / "CHROMEWEBSTORE.md").read_text(encoding="utf-8")


def test_web_store_item_id_matches_listing():
    item = re.search(r"item ID `([a-p]{32})`", STORE).group(1)
    assert f"https://chromewebstore.google.com/detail/jobwatch-application-fill/{item}" in PAGE


def test_install_command_matches_readme():
    cmd = re.search(r"^(pipx install jobwatch)\b", README, re.M).group(1)
    assert f'<code id="cmd">{cmd}</code>' in PAGE


def test_page_is_self_contained():
    assert not re.search(r"<script[^>]+src=", PAGE)
    assert "const YOUTUBE_ID = " in PAGE
    for asset in re.findall(r'(?:src|href|poster)="([\w.-]+\.(?:svg|png|gif|mp4))"', PAGE):
        assert (ROOT / "site" / asset).is_file(), asset


def test_external_links_open_in_a_new_tab():
    anchors = re.findall(r"<a\b[^>]*>", PAGE)
    external = [a for a in anchors if 'href="http' in a]
    assert external
    for a in external:
        assert 'target="_blank"' in a and 'rel="noopener"' in a, a


def test_stat_tiles_link_to_page_sections():
    tiles = re.findall(r'<a class="tile" href="#(\w+)"', PAGE)
    assert len(tiles) == 4
    for anchor in tiles:
        assert f'id="{anchor}"' in PAGE, anchor


def test_hero_leads_with_the_pipx_install():
    hero = PAGE.split('<div class="cta">')[1]
    assert hero.index('id="cmd"') < hero.index('id="add-chrome"')


def test_tutorials_section_serves_local_videos_lazily():
    cards = re.findall(r'<video controls preload="none" playsinline poster="([^"]+)" src="([^"]+)"', PAGE)
    assert len(cards) == 8  # seven tutorials and the whole-app tour
    assert PAGE.count('class="step"') == 6
    for poster, src in cards:
        assert (ROOT / "site" / poster).is_file(), poster
        assert (ROOT / "site" / src).is_file(), src
        assert "user-attachments" not in src
    for _, src in cards:
        assert "autoplay" not in src
