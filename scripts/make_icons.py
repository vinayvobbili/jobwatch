"""The app's PNG icons, rendered from the SVGs in jobwatch/static (the page's manifest lists them).

    python scripts/make_icons.py          # after changing icon-app.svg or icon-maskable.svg

Chrome installs the page as an app from the manifest's PNGs (macOS's dock and app switcher, Windows' taskbar);
Safari's "Add to Dock" and iOS read apple-touch-icon.png. Needs Playwright's Chromium (`playwright install chromium`).
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

STATIC = Path(__file__).resolve().parent.parent / "jobwatch" / "static"
# (source, size, output)
ICONS = [
    ("icon-app.svg", 192, "icon-192.png"),
    ("icon-app.svg", 512, "icon-512.png"),
    ("icon-maskable.svg", 512, "icon-maskable-512.png"),
    ("icon-maskable.svg", 180, "apple-touch-icon.png"),  # iOS rounds the corners itself
]


def render(page, svg: Path, size: int, out: Path):
    page.set_viewport_size({"width": size, "height": size})
    page.set_content(f'<html><body style="margin:0;background:transparent">'
                     f'<img src="data:image/svg+xml;base64,{_b64(svg)}" width="{size}" height="{size}" '
                     f'style="display:block"></body></html>')
    page.wait_for_load_state("load")
    page.screenshot(path=out, omit_background=True, clip={"x": 0, "y": 0, "width": size, "height": size})


def _b64(path: Path) -> str:
    import base64
    return base64.b64encode(path.read_bytes()).decode()


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for src, size, name in ICONS:
            render(page, STATIC / src, size, STATIC / name)
            print(f"{name}: {size}x{size} from {src}")
        browser.close()


if __name__ == "__main__":
    main()
