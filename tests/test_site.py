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
    cmd = re.search(r"(?:^|`)(pipx install jobwatch)\b", README, re.M).group(1)
    assert PAGE.count(f'<code class="cmd">{cmd}</code>') == 1  # the hero's line, the page's only install card


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


def test_install_notes_cover_every_system_uv_and_claude_desktop():
    notes = PAGE.split('<div class="uv" id="install-card" tabindex="-1">')[1].split('<div class="tiles">')[0]
    assert ('<p class="sub">Works on Mac, Windows and Linux. Run <code>jobwatch</code> and your page opens '
            'in the browser.</p>') in notes
    assert ('<p class="sub pipx">Already have Python? <code class="cmd">pipx install jobwatch</code>'
            '<button type="button" aria-live="polite">Copy</button> works too.</p>') in notes
    assert "uv brings Python" not in PAGE and "No Python?" not in PAGE
    assert PAGE.count("getting-started/installation/") == 2  # "Install uv" links the docs, once per system
    desktop = notes
    assert ('Use Claude Desktop? <a target="_blank" rel="noopener" '
            'href="https://github.com/vinayvobbili/jobwatch/releases/latest/download/jobwatch.mcpb">'
            'Download the extension</a>, open it and press Install.') in desktop
    assert "MIT licensed" not in PAGE  # the license is named in the footer only
    assert "jobwatch is open source under the MIT license." in PAGE.split("<footer")[1]
    assert "pipx.pypa.io" not in PAGE


def test_uv_commands_have_a_system_switch_that_starts_on_the_visitors_system():
    uv = PAGE.split('<div class="uv" id="install-card" tabindex="-1">')[1].split('<p class="sub">Works on')[0]
    hero = PAGE.split('<div class="hero">')[1]
    assert hero.index('class="uv"') < hero.index('<p class="sub">Works on') < hero.index('<div class="tiles">')
    # two panels, one per system, each with the install line and its alternative, then the shared next steps
    assert "<code>curl -LsSf https://astral.sh/uv/install.sh | sh</code>" in uv
    assert "<code>brew install uv</code>" in uv
    assert '<code>powershell -c "irm https://astral.sh/uv/install.ps1 | iex"</code>' in uv
    assert "<code>winget install astral-sh.uv</code>" in uv
    # each system is one card with labelled rows: install, its alternative, then the two shared next steps
    order = ["brew install uv", "uv tool install jobwatch", "powershell -c"]
    assert uv.index(order[0]) < uv.index(order[1]) < uv.index(order[2]) < uv.rindex("<code>jobwatch</code>")
    assert uv.count('<div class="uvpanel"') == 2 and uv.count("uv tool install jobwatch") == 2
    labels = re.findall(r'<span class="or">(?:<a [^>]*>)?([^<]+)(?:</a>)?</span>', uv)
    assert labels == ["Install uv", "or", "Then", "Then run"] * 2
    assert "var(--grad) border-box" in PAGE.split(".uvpanel {")[1].split("}")[0]  # the glow border the old box had
    # label, command, Copy: the same columns on every row
    assert "grid-template-columns: 5.2em minmax(0, 1fr) 4.6em" in PAGE
    # a copy button on every command, in the hero's style, and a keyboard-reachable switch
    assert uv.count("<code>") == 8 and uv.count("<button type=\"button\" aria-live=\"polite\">Copy</button>") == 8
    seg = re.search(r'<div class="seg" role="group" aria-label="Your system" hidden>(.*?)</div>', uv, re.S).group(1)
    assert re.findall(r'<button type="button" data-os="(\w+)" aria-pressed="(\w+)">([^<]+)</button>', seg) == [
        ("unix", "true", "Mac / Linux"), ("win", "false", "Windows")]
    # no script: the switch stays hidden and both systems show, each under its name
    assert '<span class="os">Mac / Linux</span>' in uv and '<span class="os">Windows</span>' in uv
    assert ".uv.js .os { display: none; }" in PAGE
    script = PAGE.split("// the uv commands show")[1].split('document.querySelectorAll(".uvrow')[0]
    assert "osSwitch.hidden = false" in script and "navigator.platform || navigator.userAgent" in script
    assert "put(" not in script and "localStorage" not in script  # nothing is remembered
    assert '".uvrow button, .pipx button"' in PAGE
    assert 'querySelectorAll(".uv").forEach' in PAGE  # the (one) card switches on its own


def test_gear_popover_options_have_icons_and_keep_their_labels_and_state():
    pop = PAGE.split('id="pop"')[1].split("</header>")[0]
    buttons = re.findall(r'<button data-v="(\w+)" aria-pressed="(\w+)"><svg class="ic" viewBox="0 0 24 24" '
                         r'aria-hidden="true">.*?</svg>(\w+)</button>', pop)
    assert buttons == [("system", "true", "System"), ("light", "false", "Light"), ("dark", "false", "Dark"),
                       ("standard", "true", "Standard"), ("wide", "false", "Wide"), ("full", "false", "Full")]
    assert '.pop .seg button[aria-pressed="true"] .ic { color: var(--accent-2); }' in PAGE
    assert "prefers-reduced-motion" in PAGE  # the hover wiggle stands down


def test_hero_notes_balance_their_lines_so_no_word_is_left_alone():
    assert re.search(r"\.sub \{[^}]*text-wrap: balance;", PAGE)


def test_install_card_exists_once_in_the_hero_and_the_closing_section_points_up_to_it():
    # one card, in the hero: the closing section has no commands, only a button that scrolls up to the card
    assert PAGE.count('class="uv" ') == 1 and PAGE.count("curl -LsSf https://astral.sh/uv/install.sh") == 1
    assert PAGE.count('class="uvrow"') == 8 and PAGE.count("pipx install jobwatch") == 1
    hero = PAGE.split('<div class="hero">')[1].split('<div class="tiles">')[0]
    assert '<div class="uv" id="install-card" tabindex="-1">' in hero
    closing = PAGE.index('<section class="again" id="get-started">')
    assert PAGE.index('id="private"') < closing < PAGE.index("<h2>Read more")
    again = PAGE.split('<section class="again" id="get-started">')[1].split("</section>")[0]
    assert "<h2>Ready to try it?</h2>" in again
    assert "Install takes about a minute and works on Mac, Windows and Linux." in again
    assert '<a class="btn primary" href="#install-card">Install jobwatch</a>' in again
    assert '<a class="btn" href="#setup">Watch the setup video</a>' in again
    assert "<code" not in again and "<pre" not in again  # no install commands down here
    assert 'id="setup"' in PAGE  # the link's target: the set-up tutorial video
    assert re.search(r"\.uv \{[^}]*scroll-margin-top: \d+px", PAGE)  # the sticky header doesn't cover the card
    assert 'class="install"' not in PAGE
    ids = re.findall(r' id="([^"]+)"', PAGE)
    assert "uv" not in ids and len(set(ids)) == len(ids)  # no duplicate ids


def test_readme_has_the_uv_line():
    assert "https://docs.astral.sh/uv/getting-started/installation/" in README
    get_started = README.split("## Get started")[1]
    assert get_started.index("uv tool install jobwatch") < get_started.index("pipx install jobwatch")


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
    assert '<a class="tile" href="#private"><b>Private</b><span>your data stays on your computer</span></a>' in PAGE
    assert "made from made-up data" not in PAGE
    assert "The whole app in under two minutes.</p>" in PAGE
    # once under the tour, once under the tutorials
    assert PAGE.count("Demo data: the companies and jobs shown are invented.") == 2


def test_hero_has_the_pipx_install_and_no_chrome_button_but_step_3_says_the_app_comes_first():
    hero = PAGE.split('<div class="hero">')[1].split('<div class="tiles">')[0]
    assert 'class="cmd"' in hero and "Add to Chrome" not in PAGE and 'id="add-chrome"' not in PAGE
    assert "chromewebstore" not in hero
    step = PAGE.split('<article class="step" id="apply">')[1].split("</article>")[0]
    assert "The extension works with the jobwatch app on your computer; install the app first." in step
    assert ">Chrome extension</a>" in step and "chromewebstore.google.com" in step


def test_tutorials_section_serves_local_videos_lazily_with_captions_and_a_name():
    cards = re.findall(r'<video controls preload="none" playsinline poster="([^"]+)" src="([^"]+)"', PAGE)
    assert len(cards) == 8  # seven tutorials and the whole-app tour
    assert PAGE.count('class="step"') == 6
    for poster, src in cards:
        assert (ROOT / "site" / poster).is_file(), poster
        assert (ROOT / "site" / src).is_file(), src
        assert "user-attachments" not in src
    for _, src in cards:
        assert "autoplay" not in src
    videos = re.findall(r"<video\b[^>]*>.*?</video>", PAGE)
    assert len(videos) == 8
    for video, (_, src) in zip(videos, cards, strict=True):
        vtt = src.removesuffix(".mp4") + ".vtt"
        assert re.search(r'aria-label="Video: [^"]+"', video), video
        assert f'<track kind="captions" srclang="en" label="English" src="{vtt}">' in video
        assert " default" not in video  # captions are on request, never forced
        assert (ROOT / "site" / vtt).read_text(encoding="utf-8").startswith("WEBVTT"), vtt


def test_hero_says_who_it_is_for_in_plain_words():
    hero = PAGE.split('<div class="hero">')[1].split('<div class="cta">')[0]
    assert ("For anyone applying to lots of companies: jobwatch checks the companies' own job pages for you every "
            "day, ranks the new openings against your resume, and keeps track of every application. It helps fill "
            'forms, and you always press Submit.<span class="free">Free, and it runs on your own '
            'computer.</span>') in hero
    # "job" in the text color, "watch" in the gradient, read as one word; the nav brand matches
    assert '<h1 aria-label="jobwatch">job<span class="grad">watch</span></h1>' in hero
    assert '<span aria-label="jobwatch" role="img">job<b>watch</b></span>' in PAGE
    tiles = re.findall(r'<a class="tile" href="#\w+"><b>(.*?)</b><span>(.*?)</span></a>', PAGE)
    assert tiles[:2] == [("Company job pages", "checked daily, straight from the source"),
                         ("Fit score", "how well each job matches your resume, 0 to 100")]
    for jargon in ("Ashby", "Boards</b>"):
        assert jargon not in PAGE.split('<div class="tiles">')[1].split("</div>")[0]


def test_tiles_keep_white_text_readable():
    assert "#ec4899" not in PAGE and "#0ea5b7" not in PAGE  # their white text was under 4.5:1
    assert "#db2777" in PAGE and "#0e7490" in PAGE


def test_the_problem_comes_right_after_the_hero_and_the_overview_before_the_demo():
    pain = re.findall(r"<p>(.*?)</p>", PAGE.split('<div class="pain">')[1].split("</div>")[0])
    assert pain == ["Twelve boards, checked by hand.", "Forty tabs and a stale spreadsheet.",
                    "The same form, again and again."]
    label = re.search(r'<p class="pain-label">(.*?)The old way</p>', PAGE, re.S)
    assert label and '<svg class="ic"' in label.group(1) and 'aria-hidden="true"' in label.group(1)
    assert PAGE.index('The old way</p>') < PAGE.index('<div class="pain">')
    assert "var(--panel)" not in re.search(r"\.pain p \{.*?\}", PAGE, re.S).group(0)  # lines, not cards
    order = [PAGE.index(m) for m in ('<div class="hero">', '<div class="pain">', "<h2>What jobwatch does for you</h2>",
                                     "<h2>See it work</h2>", "<h2>How it works</h2>", "<h2>Private by design</h2>",
                                     '<section class="again"', "<h2>Read more</h2>", 'id="join"')]
    assert order == sorted(order)


def test_steps_and_cards_use_plain_words():
    step = lambda name: PAGE.split(f'<article class="step" id="{name}">')[1].split("</article>")[0]  # noqa: E731
    assert "It opens in your browser and asks four quick things" in step("setup")
    assert "Then you land on Today, your daily list of new matches." in step("setup")
    assert "Status emails from companies become suggested updates you confirm with one click" in step("track")
    assert "Status emails update it" not in PAGE
    assert "a mock interview, and a practice video to rehearse with." in step("prep")
    assert "<h3>Compare and ask</h3>" in step("extras") and "Extras" not in PAGE
    assert "so you know whom to ask for a referral." in step("extras")
    assert '<p class="lead">Six parts, each with a short video.</p>' in PAGE
    cards = PAGE.split("<h2>What jobwatch does for you</h2>")[1].split("</section>")[0]
    assert "Hacker News' monthly hiring thread and investor job boards" in cards
    assert "with the posted pay range when there is one. It reads only what sites allow." in cards
    for jargon in ("robots.txt", "real pay ranges", "VC portfolio", "HN's Who is hiring", "drill video"):
        assert jargon not in PAGE, jargon
    assert "<h3>Works with your AI assistant</h3>" in cards
    assert "the standard way to plug tools into AI chat" in cards and "An MCP server for" not in PAGE


def test_privacy_caption_and_local_model_notes_avoid_jargon():
    cap = re.search(r'<p class="cap">(.*?)</p>', PAGE).group(1)
    assert cap == ("Where the AI runs: Claude's API, Google's Antigravity (with your own subscription) or a model on "
                   "your own computer; a backup if one runs out; and exactly what leaves your computer.")
    assert ("<summary><span>Want the AI to run on your own computer? Pick a model by how much memory (RAM) you "
            "have.</span>") in PAGE
    assert "We tested only the 16 GB row: it matched 28 of 29 hand-checked scores, at about 27 seconds a job." in PAGE


def test_read_more_pills_are_in_reading_order_with_plain_names():
    links = PAGE.split("<h2>Read more</h2>")[1].split("</section>")[0]
    names = re.findall(r"<a [^>]*>(.*?)</a>", links)
    assert names == ["The guide", "Applying", "Tracking", "Interview prep", "The jobwatch page (dashboard)",
                     "Use it from Claude (MCP)", "GitHub", "PyPI", "MCP Registry entry"]
    # jobwatch's own entry, not the registry's home page
    assert "registry.modelcontextprotocol.io/v0.1/servers/io.github.vinayvobbili%2Fjobwatch/versions/latest" in links
    server = (ROOT / "server.json").read_text(encoding="utf-8")
    assert '"name": "io.github.vinayvobbili/jobwatch"' in server


def test_join_in_cards_name_no_price_and_do_not_guilt():
    join = PAGE.split('id="join"')[1].split("</section>")[0]
    assert "<h3>Buy me a coffee</h3><p>If it landed you an interview, a coffee says thanks.</p>" in join
    assert "$1" not in PAGE
    assert "jobwatch collects no usage data, so a star is how I know it helped." in join


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
    script = PAGE.split("// comments (giscus")[1].split('document.querySelectorAll(".install button")')[0]
    assert 'src = "https://giscus.app/client.js"' in script
    assert "IntersectionObserver" in script  # client.js loads only when the section scrolls into view
    for want in ('repo: "vinayvobbili/vinayvobbili.github.io"', '"repo-id": "R_kgDOSZD6Ig"',
                 'category: "Announcements"', '"category-id": "DIC_kwDOSZD6Is4C-p2b"',
                 'mapping: "specific"', 'term: "jobwatch"', 'strict: "0"', 'loading: "lazy"'):
        assert want in script, want
    assert "setConfig" in script  # follows the System / Light / Dark switch
    assert "giscus.app/client.js" not in PAGE.split("<script>")[0]  # not a static script tag
