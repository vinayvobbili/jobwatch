"""The page's gloss layer (a top-edge highlight and sheen on the chrome, a hover sweep, a coloured shiny scrollbar):
its tokens exist in both themes, motion off means static gloss only, and white text on a filled surface keeps 4.5:1."""

import re
from importlib import resources

import pytest


def _read(name: str) -> str:
    return resources.files("jobwatch").joinpath(f"static/{name}").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css() -> str:
    page = _read("index.html")
    return re.search(r"<style>(.*?)</style>", page, re.S).group(1)


def _rule(css: str, selector: str, after: str = "") -> str:
    """The body of the first rule whose selector is exactly `selector`, searching from the text `after`."""
    start = css.index(after) if after else 0
    m = re.compile(r"(?:^|[{}\n])\s*" + re.escape(selector) + r"\s*\{([^{}]*)\}", re.S).search(css, start)
    assert m, f"no rule {selector}"
    return m.group(1)


GLOSS = "/* GLOSS."
TOKENS = ("--gloss-edge", "--gloss-edge-panel", "--gloss-sheen", "--gloss-sheen-panel", "--gloss-sheen-chip",
          "--gloss-sweep", "--gloss-ms", "--sb-track", "--sb-thumb", "--sb-thumb-hover", "--sb-sheen", "--sb-edge",
          "--sb-glow", "--sb-solid-thumb", "--sb-solid-track")


def test_gloss_tokens_sit_on_root_for_the_light_theme(css):
    root = _rule(css, ":root", GLOSS)
    for token in TOKENS:
        assert f"{token}:" in root, token
    assert "inset 0 1px 0 rgba(255, 255, 255, .25)" in root  # the top-edge highlight


def test_gloss_tokens_that_depend_on_the_theme_have_a_dark_value(css):
    dark = _rule(css, ':root[data-theme="dark"]', GLOSS)
    for token in ("--gloss-edge-panel", "--gloss-sheen-panel", "--gloss-sheen-chip", "--shadow", "--shadow-hover",
                  "--sb-track", "--sb-thumb", "--sb-thumb-hover", "--sb-edge", "--sb-solid-thumb", "--sb-solid-track"):
        assert f"{token}:" in dark, token


def test_the_gloss_goes_on_the_chrome_and_the_tables_cells_stay_flat(css):
    gloss = css[css.index(GLOSS):]
    for selector in (".card", ".dialog", ".stat:not(.lead)", "button.primary", ".chip:not(.gap)", ".badge.new", ".ring",
                     "button.btn.btn-close", "nav button.on"):
        assert selector in gloss, selector
    assert not re.search(r"table[^{]*\b(td|th)\b[^{]*\{[^}]*gloss", gloss), "a table cell got gloss"
    assert "@media screen" in gloss  # the print rules keep their flat dialogs


def test_the_sweep_runs_once_per_hover_and_stops_when_motion_is_reduced(css):
    gloss = css[css.index(GLOSS):]
    assert re.search(r":hover::after \{[^}]*transform: translateX\(130%\);"
                     r" transition: transform var\(--gloss-ms\)", gloss)
    assert re.search(r"--gloss-ms: [67]\d\dms", gloss)  # 600 to 800ms
    reduced = re.search(r"@media screen and \(prefers-reduced-motion: reduce\) \{(.*?)\n\}", gloss, re.S).group(1)
    assert "::after" in reduced and "display: none" in reduced


def test_scrollbar_rules_cover_track_thumb_hover_and_corner_in_both_themes(css):
    gloss = css[css.index(GLOSS):]
    # thick: 18px on the page and panes, 14px inside dialogs, tables and the sidebar, never widened on hover
    assert "::-webkit-scrollbar { width: 18px; height: 18px; }" in gloss
    narrow = _rule(gloss, ".overlay::-webkit-scrollbar, .dialog *::-webkit-scrollbar, .table-wrap::-webkit-scrollbar,\n"
                          "  .layout > aside::-webkit-scrollbar")
    assert "width: 14px; height: 14px" in narrow
    assert "scrollbar-gutter: stable" in _rule(gloss, "html")
    thumb = _rule(gloss, "::-webkit-scrollbar-thumb")
    assert "var(--sb-thumb)" in thumb and "var(--sb-sheen)" in thumb and "border-radius: 999px" in thumb
    assert "border: 3px solid transparent" in thumb and "background-clip: padding-box" in thumb
    assert "min-height: 40px" in thumb and "min-width: 40px" in thumb
    assert "999px" in _rule(gloss, "::-webkit-scrollbar-track")
    for state in (":hover", ":active"):
        assert not re.search(r"width|height|border", _rule(gloss, f"::-webkit-scrollbar-thumb{state}"))
    assert "var(--sb-thumb-hover)" in _rule(gloss, "::-webkit-scrollbar-thumb:hover")
    assert "transparent" in _rule(gloss, "::-webkit-scrollbar-corner")
    # indigo, then violet, then teal, brighter on hover, in light and in dark
    light = _rule(css, ":root", GLOSS)
    dark = _rule(css, ':root[data-theme="dark"]', GLOSS)
    for theme in (light, dark):
        thumb_value = re.search(r"--sb-thumb: ([^;]*);", theme).group(1)
        hover_value = re.search(r"--sb-thumb-hover: ([^;]*);", theme).group(1)
        assert re.findall(r"#[0-9a-f]{6}", thumb_value) != re.findall(r"#[0-9a-f]{6}", hover_value)
        assert len(re.findall(r"#[0-9a-f]{6}", thumb_value)) == 3
    # Firefox: the colour pair, and only where ::-webkit-scrollbar isn't known (Chrome drops the rules above otherwise)
    assert ("@supports not selector(::-webkit-scrollbar) { * { scrollbar-width: auto; "
            "scrollbar-color: var(--sb-solid-thumb) var(--sb-solid-track); } }") in gloss
    assert "scrollbar-width: auto" in _rule(gloss, ".layout > aside")  # the old `thin` would switch the rules off


def test_no_later_rule_turns_the_webkit_scrollbar_off_by_setting_scrollbar_width_thin(css):
    """Chrome ignores ::-webkit-scrollbar on an element that sets scrollbar-width or scrollbar-color."""
    for m in re.finditer(r"([^{}]+)\{[^{}]*scrollbar-(width|color): ([^;}]+)", css):
        selector, value = m.group(1).strip().splitlines()[-1], m.group(3).strip()
        assert value in {"none", "auto"} or (selector == "*" and "scrollbar-color" in m.group(0)) \
            or selector == ".layout > aside", (selector, value)


def _luminance(rgb):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    return .2126 * r + .7152 * g + .0722 * b


def _over(top, alpha, base):
    return tuple(alpha * t + (1 - alpha) * b for t, b in zip(top, base, strict=True))


def _hex(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def test_white_text_on_a_glossy_filled_surface_keeps_four_and_a_half_to_one(css):
    """--grad (what filled buttons, badges and tiles carry white text on), deepened by --gloss-shade, with the white
    lift --gloss-lift the sheen holds to where the text sits."""
    gloss_root = _rule(css, ":root", GLOSS)
    lift = float(re.search(r"--gloss-lift: ([.\d]+)", gloss_root).group(1))
    r, g, b, a = (float(x) for x in re.search(r"--gloss-shade: rgba\(([\d.]+), ([\d.]+), ([\d.]+), ([\d.]+)\)",
                                               gloss_root).groups())
    stops = re.search(r"--grad: linear-gradient\(135deg, (#[0-9a-f]{6}), (#[0-9a-f]{6})\)", css).groups()
    for stop in stops:
        shaded = _over((r, g, b), a, _hex(stop))
        lifted = _over((255, 255, 255), lift, shaded)
        ratio = 1.05 / (_luminance(lifted) + .05)
        assert ratio >= 4.5, (stop, round(ratio, 2))


def test_the_sheen_lift_where_text_sits_is_the_token(css):
    sheen = re.search(r"--gloss-sheen: ([^;]*);", css).group(1)
    assert "rgba(255, 255, 255, var(--gloss-lift)) 30%" in sheen
    assert "rgba(255, 255, 255, 0) 46%" in sheen and "rgba(255, 255, 255, 0) 54%" in sheen  # nothing across the middle


def test_the_prep_sheet_page_gets_the_scrollbar_and_the_top_edge_too():
    page = _read("rehearse.html")
    assert "::-webkit-scrollbar { width: 18px; height: 18px; }" in page
    assert "scrollbar-gutter: stable" in page and "min-height: 40px" in page
    assert "::-webkit-scrollbar-thumb:hover" in page and "::-webkit-scrollbar-corner" in page
    assert "@supports not selector(::-webkit-scrollbar) { * { scrollbar-width: auto;" in page
    assert "--gloss-edge" in page
