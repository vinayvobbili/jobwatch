"""`jobwatch timing`: how long each tab of the page takes to load, from the API calls the tab makes.

The calls are the page's own (see TABS), timed N times each, and listed slowest first. They go to a running page
(`--url`, the token read from the page it serves) or, without one, to the page's server started here on a free port
over the watchlist's store: the same requests, with no background work (no board checks, no scoring). Today
marks the jobs it lists as seen, so point `-c` at a copy of the store to leave the real one alone.
"""

from __future__ import annotations

import gzip as gzip_mod
import http.client
import json
import re
import statistics
import threading
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import APP_HOST

# The calls each tab's first draw makes, in the order it makes them: the page's own paths. {company} is a company
# with a tracked job (see pick_company); a tab that needs one is left out when there is none.
TABS: dict[str, tuple[str, ...]] = {
    "Page": ("/",),
    "Today": ("/api/digest", "/api/hidden"),
    "Queue": ("/api/queue", "/api/pace", "/api/snoozed"),
    "Counts": ("/api/counts",),
    "Applications": ("/api/applications", "/api/calendar"),
    "Interviews": ("/api/interviews",),
    "Company": ("/api/company?q={company}",),
    "Comps": ("/api/comps?stages=screening,interviewing,offer",),
    "Referrals": ("/api/referrals",),
    "Skills": ("/api/skills",),
    "Activity": ("/api/activity-logs", "/api/activity?kind=boards"),
    "Settings": ("/api/settings", "/api/suggestions"),
}

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


def calls(tabs: list[str] | None = None, company: str = "") -> list[tuple[str, str]]:
    """(tab, path) for the tabs named (all by default; case doesn't matter), a company's page only with a company."""
    wanted = {t.lower() for t in tabs or ()}
    unknown = wanted - {t.lower() for t in TABS}
    if unknown:
        raise ValueError(f"no tab named {', '.join(sorted(unknown))}; the tabs are {', '.join(TABS)}")
    out = []
    for tab, paths in TABS.items():
        if wanted and tab.lower() not in wanted:
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


def render(rows: list[Timing]) -> str:
    """The ranked list, one call a line, with the tabs' totals (the median of each of their calls added up) under it."""
    lines = [f"{'ms (median)':>11}  {'KB':>6}  {'runs (ms)':<22}  tab: call"]
    for t in rows:
        lines.append(f"{t.median:>11.0f}  {t.kb:>6.0f}  {' '.join(f'{m:.0f}' for m in t.ms):<22}  {t.tab}: {t.path}"
                     + (f"  ({t.error})" if t.error else ""))
    totals: dict[str, float] = {}
    for t in rows:
        totals[t.tab] = totals.get(t.tab, 0.0) + t.median
    lines.append("")
    lines.append("tab totals: " + ", ".join(f"{tab} {ms / 1000:.1f}s" for tab, ms in
                                            sorted(totals.items(), key=lambda kv: -kv[1])))
    return "\n".join(lines)


def to_json(rows: list[Timing]) -> str:
    return json.dumps({"calls": [t.to_dict() for t in rows]}, indent=2)


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


def serve_here(config_path: Path):
    """The page's server over this watchlist on a free port, with none of the background work; (server, token)."""
    from .web import App, _Server, make_handler

    token = "timing-token"
    port_ref = [0]
    server = _Server(("127.0.0.1", 0), make_handler(App(config_path, background=False), token, port_ref))
    port_ref[0] = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, token
