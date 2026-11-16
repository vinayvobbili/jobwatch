"""Check the hero's install notes and uv command card at 1280, 820 and 390px, in light and dark, for both systems.

    python scripts/uv_layout.py SITE_DIR [OUT_DIR]

Prints each note paragraph's lines (a line that is a single word is flagged WIDOW) and, per width, scheme and system,
whether the page scrolls sideways and whether the Copy buttons share one column and one width. The exit code is 1 on
any problem. With OUT_DIR it also writes a crop of the uv card per case. It also checks the closing "Ready to try it?"
section: no one-word line, and the Install button scrolls the card into view below the sticky header (with OUT_DIR, a
crop of the section per width and scheme). Needs playwright.
"""

import functools
import http.server
import sys
import threading
from pathlib import Path

WIDTHS = (1280, 820, 390)

LINES = """() => [...document.querySelectorAll('.hero .sub')].map(p => {
  const lines = []; let top = null;
  const walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
  for (let n; (n = walker.nextNode());) {
    for (const m of n.textContent.matchAll(/\\S+/g)) {
      const r = document.createRange(); r.setStart(n, m.index); r.setEnd(n, m.index + m[0].length);
      const y = Math.round(r.getBoundingClientRect().top);
      if (top === null || Math.abs(y - top) > 6) { lines.push([]); top = y; }
      lines[lines.length - 1].push(m[0]);
    }
  }
  return lines.map(l => l.join(' '));
})"""

TABLE = """() => {
  const panel = [...document.querySelectorAll('.uvpanel[data-os]')].find(p => !p.hidden);
  const b = [...panel.querySelectorAll('.uvrow button')].map(x => x.getBoundingClientRect());
  const card = panel.getBoundingClientRect();
  const spread = xs => Math.round(Math.max(...xs) - Math.min(...xs));
  return {pageOverflow: document.documentElement.scrollWidth - innerWidth, buttonLefts: spread(b.map(r => r.left)),
          buttonWidths: spread(b.map(r => r.width)),
          cardHeight: Math.round(card.height),
          cardInsideViewport: card.left >= 0 && card.right <= innerWidth,
          scrollingCommands: [...panel.querySelectorAll('.uvrow code')]
            .filter(c => c.scrollWidth > c.clientWidth).length};
}"""


CLOSING = """() => {
  const sec = document.querySelector('#get-started');
  const sub = sec.querySelector('.sub'); const lines = new Set();
  const range = document.createRange(); range.selectNodeContents(sub);
  [...range.getClientRects()].forEach(r => lines.add(Math.round(r.top)));
  const btn = sec.querySelector('.btn.primary');
  return {commands: sec.querySelectorAll('code').length, subLines: lines.size, buttonColor: getComputedStyle(btn).color,
          buttonText: btn.textContent, pageOverflow: document.documentElement.scrollWidth - innerWidth};
}"""

LANDING = """() => {
  const card = document.querySelector('#install-card').getBoundingClientRect();
  const bar = document.querySelector('header').getBoundingClientRect();
  return {cardBelowHeader: card.top >= bar.bottom - 1, cardTop: Math.round(card.top)};
}"""


def check(site: Path, out: Path | None = None) -> bool:
    from playwright.sync_api import sync_playwright

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/index.html"
    bad = False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for width in WIDTHS:
                page = browser.new_page(viewport={"width": width, "height": 900})
                page.goto(url)
                page.wait_for_timeout(900)
                for lines in page.evaluate(LINES):
                    widow = any(len(line.split()) == 1 for line in lines)
                    bad |= widow
                    print(width, "WIDOW" if widow else "ok", " / ".join(lines))
                for scheme in ("light", "dark"):
                    page.emulate_media(color_scheme=scheme)
                    for os_name in ("unix", "win"):
                        page.click(f'.uv .seg button[data-os="{os_name}"]')
                        m = page.evaluate(TABLE)
                        print(width, scheme, os_name, m)
                        bad |= (m["pageOverflow"] > 0 or m["buttonLefts"] > 1 or m["buttonWidths"] > 1
                                or not m["cardInsideViewport"])
                        if out:
                            out.mkdir(parents=True, exist_ok=True)
                            shot = out / f"uv-{scheme}-{width}-{os_name}.png"
                            page.locator("#install-card").screenshot(path=str(shot))
                for scheme in ("light", "dark"):
                    page.emulate_media(color_scheme=scheme)
                    closing = page.evaluate(CLOSING)
                    print(width, scheme, "closing", closing)
                    bad |= closing["commands"] > 0 or closing["subLines"] > 2 or closing["pageOverflow"] > 0
                    if out:
                        page.locator("#get-started").screenshot(path=str(out / f"closing-{scheme}-{width}.png"))
                page.evaluate("scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(300)
                page.click("#get-started .btn.primary")
                page.wait_for_timeout(1500)
                landing = page.evaluate(LANDING)
                print(width, "landing", landing)
                bad |= not landing["cardBelowHeader"]
                page.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    return bad


if __name__ == "__main__":
    sys.exit(1 if check(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else None) else 0)
