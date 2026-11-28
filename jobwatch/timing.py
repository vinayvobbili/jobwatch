"""`jobwatch timing`: how long each tab of the page takes to load, from the API calls the tab makes.

The calls are the page's own (see TABS), timed N times each, and listed slowest first. They go to a running page
(`--url`, the token read from the page it serves) or, without one, to the page's server started here on a free port
over the watchlist's store: the same requests, with no background work (no board checks, no scoring). Today
marks the jobs it lists as seen, so point `-c` at a copy of the store to leave the real one alone.
"""

from __future__ import annotations

import dataclasses
import gzip as gzip_mod
import http.client
import json
import re
import sqlite3
import statistics
import threading
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import APP_HOST

# The calls each tab makes when it opens, all at once: the page's own paths. {company} is a company with a tracked
# job (see pick_company); a tab that needs one is left out when there is none.
TABS: dict[str, tuple[str, ...]] = {
    "Page": ("/",),
    "Today": ("/api/digest?part=list", "/api/digest?part=extra", "/api/hidden"),
    "Queue": ("/api/queue?part=list", "/api/queue?part=extra", "/api/pace", "/api/snoozed"),
    "Counts": ("/api/counts",),
    "Applications": ("/api/applications",),
    "Interviews": ("/api/interviews",),
    "Company": ("/api/company?q={company}",),
    "Comps": ("/api/comps?stages=screening,interviewing,offer",),
    "Referrals": ("/api/referrals",),
    "Skills": ("/api/skills",),
    "Activity": ("/api/activity-logs", "/api/activity?kind=boards"),
    "Settings": ("/api/settings", "/api/suggestions"),
}

# What a tab waits on before its first real data is on screen (it draws its head and placeholders at once, at 0 ms,
# and fills the rest in as each call lands). The calls go out together, so the slowest of these decides. A tab not
# listed waits on all of its calls; Settings waits on none (it draws from the settings the page already has).
FIRST_DATA: dict[str, tuple[str, ...]] = {
    "Today": ("/api/digest?part=list",),
    "Queue": ("/api/queue?part=list",),
    "Settings": (),
}

# The one-call forms Today and the Queue used before they were split in two, for `--combined`: they wait on everything.
ONE_CALL: dict[str, tuple[str, ...]] = {"Today (one call)": ("/api/digest",), "Queue (one call)": ("/api/queue",)}

Get = Callable[[str], tuple[int, int]]   # path -> (HTTP status, bytes received)


@dataclass
class Timing:
    tab: str
    path: str
    ms: list[float] = field(default_factory=list)
    kb: float = 0.0
    error: str = ""

    @property
    def median(self) -> float:
        return statistics.median(self.ms) if self.ms else 0.0

    def to_dict(self) -> dict:
        return {"tab": self.tab, "path": self.path, "runs": [round(m) for m in self.ms],
                "median_ms": round(self.median), "max_ms": round(max(self.ms, default=0)), "kb": round(self.kb),
                "error": self.error}


def calls(tabs: list[str] | None = None, company: str = "", combined: bool = False) -> list[tuple[str, str]]:
    """(tab, path) for the tabs named (all by default; case doesn't matter), a company's page only with a company.
    `combined` adds the one-call forms of Today and the Queue (ONE_CALL), named for the tab they stand in for."""
    wanted = {t.lower() for t in tabs or ()}
    unknown = wanted - {t.lower() for t in TABS}
    if unknown:
        raise ValueError(f"no tab named {', '.join(sorted(unknown))}; the tabs are {', '.join(TABS)}")
    out = []
    for tab, paths in {**TABS, **(ONE_CALL if combined else {})}.items():
        if wanted and tab.split(" (")[0].lower() not in wanted:
            continue
        for path in paths:
            if "{company}" in path:
                if not company:
                    continue
                path = path.format(company=urllib.parse.quote(company))
            out.append((tab, path))
    return out


def measure(get: Get, wanted: list[tuple[str, str]], runs: int = 3, clock: Callable[[], float] = time.perf_counter
            ) -> list[Timing]:
    """Each call `runs` times (the first one is the cold one), slowest median first. A call that fails stops
    being repeated and says why."""
    out = []
    for tab, path in wanted:
        t = Timing(tab, path)
        for _ in range(runs):
            start = clock()
            try:
                status, size = get(path)
            except Exception as e:  # a refused connection, a timeout
                t.error = f"{type(e).__name__}: {e}"
                break
            t.ms.append((clock() - start) * 1000)
            t.kb = size / 1024
            if status >= 400:
                t.error = f"HTTP {status}"
                break
        out.append(t)
    return sorted(out, key=lambda t: -t.median)


def waits(rows: list[Timing]) -> list[dict]:
    """Per tab, slowest first: when its first real data can be on screen (the slowest of the calls it waits on, see
    FIRST_DATA; its head and placeholders are there at 0), and when its last part has landed (the slowest call)."""
    by_tab: dict[str, list[Timing]] = {}
    for t in rows:
        by_tab.setdefault(t.tab, []).append(t)
    out = []
    for tab, ts in by_tab.items():
        gate = FIRST_DATA.get(tab, tuple(t.path for t in ts))
        gating = [t for t in ts if t.path in gate]
        out.append({"tab": tab, "first_data_ms": round(max((t.median for t in gating), default=0.0)),
                    "complete_ms": round(max(t.median for t in ts)), "waits_on": [t.path for t in gating]})
    return sorted(out, key=lambda w: (-w["first_data_ms"], -w["complete_ms"]))


def render(rows: list[Timing]) -> str:
    """The ranked list, one call a line, then what each tab waits on before its first data (see waits)."""
    lines = [f"{'ms (median)':>11}  {'KB':>6}  {'runs (ms)':<22}  tab: call"]
    for t in rows:
        lines.append(f"{t.median:>11.0f}  {t.kb:>6.0f}  {' '.join(f'{m:.0f}' for m in t.ms):<22}  {t.tab}: {t.path}"
                     + (f"  ({t.error})" if t.error else ""))
    lines += ["", "each tab draws its head and placeholders at 0 ms; its first data waits on:",
              f"{'first data':>10}  {'complete':>8}  tab: waits on"]
    for w in waits(rows):
        waits_on = ", ".join(w["waits_on"]) or "nothing"
        lines.append(f"{w['first_data_ms']:>10}  {w['complete_ms']:>8}  {w['tab']}: {waits_on}")
    return "\n".join(lines)


def to_json(rows: list[Timing]) -> str:
    return json.dumps({"calls": [t.to_dict() for t in rows], "tabs": waits(rows)}, indent=2)


class Client:
    """A page at host:port: the Host header it expects, the token, and gzip as a browser asks for it."""

    def __init__(self, host: str, port: int, token: str = "", gzip: bool = True, timeout: float = 900):
        self.host, self.port, self.token, self.gzip, self.timeout = host, port, token, gzip, timeout

    def fetch(self, path: str) -> tuple[int, bytes, str]:
        """(status, the body as sent on the wire, its Content-Encoding)."""
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            conn.request("GET", path, headers={"Host": f"{APP_HOST}:{self.port}", "X-Jobwatch-Token": self.token,
                                               **({"Accept-Encoding": "gzip"} if self.gzip else {})})
            r = conn.getresponse()
            return r.status, r.read(), r.getheader("Content-Encoding", "")
        finally:
            conn.close()

    def get(self, path: str) -> tuple[int, int]:
        """(status, bytes on the wire)."""
        status, body, _ = self.fetch(path)
        return status, len(body)

    def json(self, path: str):
        status, body, encoding = self.fetch(path)
        if status >= 400:
            raise ValueError(f"HTTP {status}")
        return json.loads(gzip_mod.decompress(body) if encoding == "gzip" else body)


def page_token(host: str, port: int) -> str:
    """The token a running page embeds in its HTML."""
    page = Client(host, port, gzip=False).fetch("/")[1].decode("utf-8", "replace")
    if not (m := re.search(r'const TOKEN = "([^"]+)"', page)):
        raise ValueError(f"nothing at {host}:{port} is a jobwatch page (no token in it)")
    return m.group(1)


def pick_company(client: Client) -> str:
    """A company to open the Company tab on: the first one with an application, else the first on the queue."""
    for path, rows_of in (("/api/applications", lambda d: d["applications"]), ("/api/queue", lambda d: d)):
        try:
            if rows := rows_of(client.json(path)):
                return rows[0]["company"]
        except (OSError, ValueError, KeyError):
            continue
    return ""


def profile(app, path: str, top: int = 12) -> str:
    """Where one GET handler spends its time: the `top` functions by cumulative time (names and counts only), run
    in this thread so the profiler sees it. For finding what makes a call slow, not for timing it."""
    import cProfile
    import io
    import pstats
    from urllib.parse import parse_qs, urlsplit

    from .web import ROUTES

    url = urlsplit(path)
    route = ROUTES[("GET", url.path)]
    prof = cProfile.Profile()
    prof.enable()
    try:
        route(app, parse_qs(url.query))
    finally:
        prof.disable()
    out = io.StringIO()
    stats = pstats.Stats(prof, stream=out)
    stats.sort_stats("cumulative").print_stats(top)
    # the work that waits or computes in the function itself (a subprocess, a query), and what called the worst of it
    stats.sort_stats("tottime").print_stats(5)
    worst = stats.fcn_list[0]
    named = re.escape(worst[2])
    stats.print_callers(named if worst[0] == "~" else f"{re.escape(worst[0])}.*{named}")
    return out.getvalue()


def copy_store(source: Path, dest: Path) -> Path:
    """A consistent copy of a state database (SQLite's own backup, the source opened read-only), so timing a real
    store changes nothing in it."""
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return dest


def serve_here(config_path: Path, store_copy: Path | None = None, port: int = 0):
    """The page's server over this watchlist on a free port (or `port`), with none of the background work;
    (server, token). With `store_copy` (see copy_store) the watchlist is read as it is but its store is that copy."""
    from .web import App, _Server, make_handler

    class CopyApp(App):
        def _cfg(self):
            return dataclasses.replace(super()._cfg(), state=store_copy)

    token = "timing-token"
    port_ref = [0]
    app = (CopyApp if store_copy else App)(config_path, background=False)
    server = _Server(("127.0.0.1", port), make_handler(app, token, port_ref))
    port_ref[0] = server.server_address[1]
    server.app = app
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, token


# What a page opening on Today asks for, in order, and what each step is called in the cold-start report.
COLD_STEPS = (("page first byte", "/"), ("first API answer", "/api/settings"),
              ("Today's list (first data)", "/api/digest?part=list"))


def cold_start(config_path: Path, store_copy: Path | None = None, clock: Callable[[], float] = time.perf_counter
               ) -> dict[str, float]:
    """The first seconds of a page opening on a freshly started server, in ms from the server's creation: it is
    listening, the page's HTML has its first byte, the API answers (settings), Today's first data is here (see
    COLD_STEPS). Then the store's indexes are built (`indexes built`, as the page does after its first answers) and
    a lookup by status (/api/counts) is timed before and after, to show what they save. Over `store_copy` the way
    `jobwatch timing --copy` does."""
    begin = clock()
    server, token = serve_here(config_path, store_copy)
    out = {"listening": (clock() - begin) * 1000}
    try:
        client = Client("127.0.0.1", server.server_address[1], token)
        for name, path in COLD_STEPS:
            client.get(path)
            out[name] = (clock() - begin) * 1000
        start = clock()
        client.get("/api/counts")
        out["by-status lookup before indexes"] = (clock() - start) * 1000
        start = clock()
        server.app.warm()
        out["indexes built"] = (clock() - start) * 1000
        start = clock()
        client.get("/api/counts")
        out["by-status lookup after indexes"] = (clock() - start) * 1000
    finally:
        server.shutdown()
        server.server_close()
    return out


def render_cold(steps: dict[str, float]) -> str:
    rows = (f"{ms:>10.0f}  {name}" for name, ms in steps.items())
    return "cold start, ms from the server starting:\n" + "\n".join(rows)
