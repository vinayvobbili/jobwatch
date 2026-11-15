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


def test_install_line_lists_the_options_before_running_jobwatch():
    sub = re.search(r'<p class="sub">(.*?)</p>', PAGE.split('<div class="cta">')[1], re.S).group(1)
    assert sub.index("pipx install jobwatch") < sub.index("pip install jobwatch") < sub.index("Then run")
    assert "Or <code>" not in sub
    assert ('target="_blank" rel="noopener" href="https://pipx.pypa.io/stable/how-to/install-pipx.html">'
            'Setup guide</a>') in sub
    assert "New to Python?" in sub


def test_readme_has_the_uv_line():
    assert "https://docs.astral.sh/uv/getting-started/installation/" in README
    assert "`uv tool install jobwatch`" in README


def test_title_and_link_preview():
    title = "jobwatch | Your job hunt shouldn't be a full-time job"
    desc = ("Free and open source. Watches the job boards you pick, ranks new roles against your resume, "
            "tracks your applications and fills the forms. Runs on your own computer.")
    assert f"<title>{title}</title>" in PAGE
    assert f'<meta name="description" content="{desc}">' in PAGE
    assert f'<meta property="og:description" content="{desc}">' in PAGE
    assert f'<meta property="og:title" content="{title}">' in PAGE
    for tag in ('property="og:type" content="website"', 'name="twitter:card" content="summary_large_image"',
                'property="og:url" content="https://vinayvobbili.github.io/jobwatch/"',
                'property="og:image" content="https://vinayvobbili.github.io/jobwatch/og.jpg"'):
        assert f"<meta {tag}>" in PAGE, tag
    og = (ROOT / "site" / "og.jpg").read_bytes()
    assert og[:2] == b"\xff\xd8"


def test_display_settings_live_in_a_gear_popover():
    header = PAGE.split("<header>")[1].split("</header>")[0]
    gear = re.search(r'<button class="gear"[^>]*>', header).group(0)
    assert 'aria-label="Display settings"' in gear and 'aria-expanded="false"' in gear
    pop = header.split('id="pop"')[1]
    assert pop.index('id="theme"') < pop.index('id="width"')
    assert pop.index('data-v="system"') < pop.index('data-v="light"') < pop.index('data-v="dark"')
    for want in ('"jw-theme"', '"jw-width"', "root.dataset.width", "root.dataset.theme", '"Escape"',
                 'closest(".settings")'):
        assert want in PAGE, want
    assert ".gear:focus-visible" in PAGE


def test_private_tile_and_demo_data_caption():
    assert '<a class="tile" href="#private"><b>Private</b><span>nothing leaves your computer</span></a>' in PAGE
    assert "made from made-up data" not in PAGE
    assert "The whole app in a minute and a half.</p>" in PAGE
    # once under the tour, once under the tutorials
    assert PAGE.count("Demo data: the companies and jobs shown are invented.") == 2


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


def test_local_model_table_is_in_a_closed_details_that_a_hash_opens():
    box = PAGE.split('<details class="models-box" id="local-models">')[1].split("</details>")[0]
    assert "<summary>" in box and '<table class="models">' in box
    assert "open" not in PAGE.split('id="local-models"')[0].rsplit("<details", 1)[-1]  # closed by default
    assert 'location.hash === "#local-models"' in PAGE and "box.open = true" in PAGE


def test_join_in_links_and_lazy_giscus_comments():
    join = PAGE.split('id="join"')[1].split("</section>")[0]
    for href in ("https://github.com/vinayvobbili/jobwatch", "https://github.com/vinayvobbili/jobwatch/issues",
                 "https://ko-fi.com/vinayvobbili"):
        assert f'href="{href}"' in join
    assert 'id="comments"' in join
    script = PAGE.split("// comments (giscus")[1].split('document.getElementById("copy")')[0]
    assert 'src = "https://giscus.app/client.js"' in script
    assert "IntersectionObserver" in script  # client.js loads only when the section scrolls into view
    for want in ('repo: "vinayvobbili/vinayvobbili.github.io"', '"repo-id": "R_kgDOSZD6Ig"',
                 'category: "Announcements"', '"category-id": "DIC_kwDOSZD6Is4C-p2b"',
                 'mapping: "specific"', 'term: "jobwatch"', 'strict: "0"', 'loading: "lazy"'):
        assert want in script, want
    assert "setConfig" in script  # follows the System / Light / Dark switch
    assert "giscus.app/client.js" not in PAGE.split("<script>")[0]  # not a static script tag
