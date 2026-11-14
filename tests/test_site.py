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
