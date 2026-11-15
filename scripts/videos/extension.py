"""The extension's scenes: Chrome's side panel docked beside a page, as it sits in the browser.

Automation can't click the toolbar button that opens the real side panel, so the panel's own page is framed on the
right of the tab (the same code and the same stand-in jobwatch as chrome-extension/tools), pinned to that tab. The
cursor is the recorder's, over both. The forms and the LinkedIn list are the demo pages in chrome-extension/demo,
served under the boards' addresses; every name in them is made up.
"""

from __future__ import annotations

PANEL_WIDTH = 440
FORM_URL = ("job-boards.greenhouse.io", "/initech/jobs/4001")
LIST_URL = ("www.linkedin.com", "/jobs/collections/recommended")


def form_url(demo) -> str:
    return demo.stack.url(*FORM_URL)


def list_url(demo) -> str:
    return demo.stack.url(*LIST_URL)


def dock(rec, demo):
    """Frame the side panel on the right of the page, as Chrome docks it; returns its frame locator."""
    stack = demo.stack
    helper = demo.extra.get("helper")
    if helper is None:  # an extension page, to ask Chrome for this tab's id
        helper = demo.extra["helper"] = stack.extension_page("options.html")
    import harness  # chrome-extension/tools, on the path since demo_running(extension=True)

    page = rec.page
    tab = harness.tab_id_for(helper, page.url)
    src = f"chrome-extension://{stack.extension_id}/sidepanel.html?tab={tab}"
    page.evaluate("""([src, w]) => {
        document.documentElement.style.cssText += "margin-right:" + w + "px";
        const f = document.createElement("iframe");
        f.id = "jw-panel"; f.src = src;
        f.style.cssText = "position:fixed;top:0;right:0;width:" + w + "px;height:100vh;border:0;" +
          "background:#fff;box-shadow:-8px 0 30px rgba(20,18,43,.18);z-index:2147483000";
        document.body.appendChild(f);
    }""", [src, PANEL_WIDTH])
    return panel(rec)


def panel(rec):
    return rec.page.frame_locator("#jw-panel")
