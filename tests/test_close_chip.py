"""The Close chip every dialog shares (.btn-close) must stand out from the dialog in both themes: its text meets 4.5:1
against its own surface and its edge and X 3:1, computed from the page's CSS variables (the --close-* tokens over the
theme's --panel-solid, which is what a dialog and its header are painted with)."""

import re
from importlib import resources

import pytest

PAGE = resources.files("jobwatch").joinpath("static/index.html").read_text(encoding="utf-8")


def tokens(selector: str) -> dict[str, str]:
    """The --name: value pairs of the first CSS rule for this selector."""
    block = re.search(rf"^{re.escape(selector)}\s*\{{(.*?)\}}", PAGE, re.S | re.M)
    assert block, f"no {selector} rule in the page"
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", block.group(1)))


def rgba(value: str) -> tuple[float, float, float, float]:
    value = value.strip()
    if m := re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", value, re.I):
        h = m.group(1)
        h = "".join(c * 2 for c in h) if len(h) == 3 else h
        return (*(int(h[i:i + 2], 16) for i in (0, 2, 4)), 1.0)
    m = re.fullmatch(r"rgba?\(\s*(\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\s*\)", value)
    assert m, f"can't read the colour {value!r}"
    return (float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4) or 1))


def over(top: tuple, below: tuple) -> tuple:
    """top painted over an opaque colour."""
    a = top[3]
    return (*(top[i] * a + below[i] * (1 - a) for i in range(3)), 1.0)


def luminance(c: tuple) -> float:
    def lin(v: float) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2])


def contrast(a: tuple, b: tuple) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("theme, selector", [("light", ":root"), ("dark", ':root[data-theme="dark"]')])
def test_the_close_chip_stands_out_from_its_dialog(theme, selector):
    t = {**tokens(":root"), **tokens(selector)}  # the dark block overrides the light tokens it names
    dialog = rgba(t["--panel-solid"])
    surface = over(rgba(t["--close-bg"]), dialog)
    assert contrast(rgba(t["--close-fg"]), surface) >= 4.5, f"{theme}: the word Close"
    assert contrast(rgba(t["--close-x"]), surface) >= 3, f"{theme}: the X"
    assert contrast(rgba(t["--close-edge"]), dialog) >= 3, f"{theme}: the edge"
    assert contrast(surface, dialog) >= 1.1, f"{theme}: the chip's own surface is lighter or darker than the dialog"


def test_the_chip_is_big_enough_and_reads_its_colours_from_the_tokens():
    rule = re.search(r"^button\.btn\.btn-close \{(.*?)\}", PAGE, re.S | re.M).group(1)
    assert "min-height: 36px" in rule and "font-size: 14px" in rule
    for token in ("--close-bg", "--close-fg", "--close-edge"):
        assert f"var({token})" in rule
    assert re.search(r"button\.btn\.btn-close \.ico \{[^}]*var\(--close-x\)", PAGE)
    assert re.search(r"button\.btn\.btn-close:hover \{[^}]*box-shadow", PAGE)  # a glow ring on hover...
    assert re.search(r"button\.btn\.btn-close:focus-visible \{[^}]*box-shadow", PAGE)  # ...and on focus
    assert re.search(r"button\.btn\.btn-close\.icon-only \{ width: 36px; height: 36px", PAGE)
