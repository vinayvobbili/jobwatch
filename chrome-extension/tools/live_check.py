"""See what the extension makes of a real application form, without touching it.

    python chrome-extension/tools/live_check.py https://job-boards.greenhouse.io/<board>/jobs/<id> [more links]

Opens each link in Chromium with the extension loaded and paired to the fake jobwatch (made-up details and
answers, see fake_server.py), scans the form as "Fill this application" does, and prints one line per field:
the question, what kind of control it is, where the value would come from, the value, and whether it starts
ticked. It never fills a field and never presses a button, so nothing reaches the employer. Use it when a board
changes its markup, or before adding a system to page.js's ADAPTERS. Needs Playwright with Chromium.
"""

from __future__ import annotations

import argparse
import sys

from fake_server import TOKEN, fake_jobwatch
from harness import Stack, browser_with_extension, open_panel, pair, tab_id_for

WIDTH = 60


def row(item: dict) -> str:
    """One plan row as a line: tick, source, kind, question, value."""
    tick = "x" if item.get("checked") else " "
    filled = " (already filled)" if item.get("filled") else ""
    question = " ".join(str(item.get("question") or "?").split())
    question = question if len(question) <= WIDTH else question[: WIDTH - 1] + "…"
    value = " ".join(str(item.get("value") or "").split())[:40]
    options = f" [{len(item['options'])} options]" if item.get("options") else ""
    source, kind = item.get("source", "none"), item.get("kind", "")
    return f"[{tick}] {source:<8} {kind:<10} {question:<{WIDTH}} {value}{options}{filled}"


def report(url: str, reply: dict) -> str:
    if not reply.get("ok"):
        return f"{url}\n  could not scan: {reply.get('error')}"
    info = reply.get("info") or {}
    items = reply.get("items") or []
    sources: dict[str, int] = {}
    for it in items:
        sources[it.get("source", "none")] = sources.get(it.get("source", "none"), 0) + 1
    counts = ", ".join(f"{n} {s}" for s, n in sorted(sources.items()))
    lines = [url, f"  {info.get('title') or '?'} at {info.get('company') or '?'}: {len(items)} fields ({counts})"]
    lines += [f"  {row(it)}" for it in items]
    return "\n".join(lines)


def scan(stack: Stack, url: str) -> dict:
    page = stack.context.new_page()
    try:
        page.goto(url, wait_until="networkidle", timeout=45000)
        ext = stack.extension_page()
        try:
            tab = tab_id_for(ext, page.url)
            opened = open_panel(ext, tab)
            if not opened.get("ok"):
                return opened
            return ext.evaluate("(tabId) => chrome.runtime.sendMessage({type: 'analyze', tabId})", tab)
        finally:
            ext.close()
    finally:
        page.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("urls", nargs="+", help="application form links (the page with the form on it)")
    parser.add_argument("--show", action="store_true", help="show the browser window")
    args = parser.parse_args(argv)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw, fake_jobwatch() as (api_url, server), \
            browser_with_extension(pw, headless=not args.show, map_hosts=False) as (context, ext_id):
        stack = Stack(api_url=api_url, site_port=0, tls_port=0, server=server, context=context, extension_id=ext_id)
        server.know_every_page = True
        pair(stack, api_url, TOKEN)
        for url in args.urls:
            print(report(url, scan(stack, url)), end="\n\n")
        if server.submitted:  # can't happen: nothing is filled or pressed
            print("warning: something was recorded as submitted", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
