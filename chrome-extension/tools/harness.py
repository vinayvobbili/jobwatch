"""Run the extension for real: a fake jobwatch, the demo forms and Chromium with the extension loaded.

Used by the end-to-end test (tests/test_extension_e2e.py). Needs Playwright with Chromium installed.
The demo forms are served under the addresses of the boards they imitate (jobs.lever.co and so on, mapped to
this computer inside the browser only), so the extension's per-system code sees what it would see for real.
"""

from __future__ import annotations

import functools
import json
import re
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fake_server import TOKEN, State, fake_jobwatch

EXTENSION_DIR = Path(__file__).resolve().parents[1]
DEMO_DIR = EXTENSION_DIR / "demo"

HOSTS = ("job-boards.greenhouse.io", "boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com",
         "careers.initech.example")
TLS_HOSTS = ("jobs.ashbyhq.com",)
ROUTES = [
    (r"^/initech/jobs/\d+$", "greenhouse.html"),
    (r"^/embed/job_app$", "greenhouse.html"),
    (r"^/[^/]+/[^/]+/apply$", "lever.html"),
    (r"^/[^/]+/[^/]+/thanks$", "lever-thanks.html"),
    (r"^/[^/]+/[^/]+/application$", "ashby.html"),
    (r"^/careers$", "greenhouse-embed.html"),
]


class BrowserUnavailable(RuntimeError):
    """Playwright's Chromium isn't installed (run `playwright install chromium`)."""


@dataclass
class Stack:
    api_url: str
    site_port: int
    tls_port: int
    server: State
    context: object  # playwright BrowserContext
    extension_id: str

    def url(self, host: str, path: str) -> str:
        if host in TLS_HOSTS:
            return f"https://{host}:{self.tls_port}{path}"
        return f"http://{host}:{self.site_port}{path}"

    def extension_page(self, name: str = "options.html"):
        page = self.context.new_page()
        page.goto(f"chrome-extension://{self.extension_id}/{name}")
        return page


@contextmanager
def demo_site() -> Iterator[tuple[int, int]]:
    """Serve demo/ with the routes of the boards it imitates. Yields (http port, https port).

    Chromium only reaches ashbyhq.com over https (it is on the HSTS preload list), so that host gets a
    self-signed certificate, which the browser is told to accept.
    """
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def translate_path(self, path):
            clean = path.split("?")[0].split("#")[0]
            for pattern, name in ROUTES:
                if re.match(pattern, clean):
                    return str(DEMO_DIR / name)
            return super().translate_path(path)

    handler = functools.partial(Handler, directory=str(DEMO_DIR))
    plain = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    secure = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    with tempfile.TemporaryDirectory() as tmp:
        cert, key = Path(tmp) / "cert.pem", Path(tmp) / "key.pem"
        try:
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj",
                            "/CN=jobs.ashbyhq.com", "-keyout", str(key), "-out", str(cert)],
                           check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise BrowserUnavailable(f"openssl is needed for the Ashby demo: {exc}") from exc
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        secure.socket = context.wrap_socket(secure.socket, server_side=True)
        for server in (plain, secure):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            yield plain.server_address[1], secure.server_address[1]
        finally:
            plain.shutdown()
            secure.shutdown()


@contextmanager
def browser_with_extension(playwright, headless: bool = True, map_hosts: bool = True) -> Iterator[tuple]:
    """Chromium with the extension loaded. Yields (context, extension_id).

    activeTab is granted by a person clicking the toolbar button, which automation can't do, so the loaded
    copy gets host access instead. Nothing else about it differs from what ships. `map_hosts` sends the
    boards' addresses to the demo site; live_check.py turns it off to reach the real boards.
    """
    with tempfile.TemporaryDirectory() as tmp:
        ext = Path(tmp) / "jobwatch-extension"
        shutil.copytree(EXTENSION_DIR, ext, ignore=shutil.ignore_patterns("demo", "tools", "__pycache__"))
        manifest = json.loads((ext / "manifest.json").read_text())
        manifest["host_permissions"] = ["<all_urls>"]
        (ext / "manifest.json").write_text(json.dumps(manifest))
        args = [f"--disable-extensions-except={ext}", f"--load-extension={ext}"]
        if map_hosts:
            rules = ", ".join(f"MAP {h} 127.0.0.1" for h in HOSTS)
            args += [f"--host-resolver-rules={rules}", "--ignore-certificate-errors"]
        try:
            context = playwright.chromium.launch_persistent_context(
                str(Path(tmp) / "profile"), channel="chromium", headless=headless, args=args)
        except Exception as exc:  # playwright raises its own Error for a missing binary
            raise BrowserUnavailable(f"Chromium unavailable: {exc}") from exc
        try:
            deadline = time.time() + 30
            while not context.service_workers and time.time() < deadline:
                try:
                    context.wait_for_event("serviceworker", timeout=1000)
                except Exception:  # not yet; the check above decides
                    pass
            if not context.service_workers:
                raise BrowserUnavailable("the extension's service worker never started")
            yield context, context.service_workers[0].url.split("/")[2]
        finally:
            context.close()


@contextmanager
def demo_stack(playwright, headless: bool = True, token: str = TOKEN) -> Iterator[Stack]:
    """Everything at once, with the extension already paired to the fake jobwatch."""
    with fake_jobwatch() as (api_url, server), demo_site() as (port, tls_port), \
            browser_with_extension(playwright, headless) as (context, ext_id):
        stack = Stack(api_url=api_url, site_port=port, tls_port=tls_port, server=server, context=context,
                      extension_id=ext_id)
        pair(stack, api_url, token)
        yield stack


def pair(stack: Stack, api_url: str, token: str) -> None:
    page = stack.extension_page()
    page.evaluate("(s) => chrome.storage.local.set({settings: s})", {"serverUrl": api_url, "token": token})
    page.close()


# --- driving it as the toolbar popup does ---------------------------------------------------------


def tab_id_for(ext_page, url: str) -> int:
    return ext_page.evaluate(
        "async (url) => (await chrome.tabs.query({})).find((t) => t.url && t.url.startsWith(url)).id", url)


def open_panel(ext_page, tab_id: int) -> dict:
    """What the popup's "Fill this application" button sends."""
    return ext_page.evaluate("(tabId) => chrome.runtime.sendMessage({type: 'open', tabId})", tab_id)


def wait_until(test, timeout: float = 10, what: str = "condition"):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = test()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {what}")
