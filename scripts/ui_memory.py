#!/usr/bin/env python3
"""Measure the memory of `jobwatch ui`: resident size at startup and after each round of page loads.

    scripts/ui_memory.py CONFIG.yaml                  # 3 rounds of the Today page's requests
    scripts/ui_memory.py CONFIG.yaml --rounds 10 --paths /api/digest /api/queue

It works on a copy of the config's database (in a temp folder) with the schedule off, so the real one isn't
touched ("New" jobs are marked shown by Today). Prints the RSS in MB, from `ps`, after each round. Run it from the
checkout's virtualenv.
"""

from __future__ import annotations

import argparse
import http.client
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

TODAY = ["/api/settings", "/api/digest", "/api/queue", "/api/pace", "/api/applications"]
TOKEN = "memory-probe"


def rss_mb() -> float:
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True, text=True).stdout
    return int(out.strip() or 0) / 1024


def peak_mb() -> float:
    """The most the process has held (ru_maxrss: bytes on macOS, kilobytes on Linux)."""
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024 if sys.platform == "darwin" else 1024)


def probe_config(config: Path, folder: Path) -> Path:
    """A copy of the watchlist whose database is a copy too, with the schedule off."""
    from jobwatch import config as cfgmod
    state = cfgmod.load(config).state
    shutil.copy(state, folder / "state.db")
    text = re.sub(r"(?m)^(state|fetch_every):.*\n", "", config.read_text(encoding="utf-8"))
    path = folder / "jobwatch.yaml"
    path.write_text(text + f"\nstate: {folder / 'state.db'}\nfetch_every: off\n", encoding="utf-8")
    return path


def get(port: int, path: str) -> int:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=300)
    conn.request("GET", path, headers={"Host": f"127.0.0.1:{port}", "X-Jobwatch-Token": TOKEN})
    r = conn.getresponse()
    n = len(r.read())
    conn.close()
    return n if r.status == 200 else -r.status


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("config", type=Path)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--paths", nargs="+", default=TODAY)
    args = ap.parse_args(argv)
    from jobwatch.web import serve
    with tempfile.TemporaryDirectory() as tmp:
        srv = serve(probe_config(args.config.expanduser(), Path(tmp)), port=0, open_browser=False, token=TOKEN)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]
        print(f"startup: {rss_mb():.0f} MB")
        for i in range(1, args.rounds + 1):
            t0 = time.time()
            sizes = {p: get(port, p) for p in args.paths}
            print(f"round {i}: {rss_mb():.0f} MB, peak {peak_mb():.0f} MB  ({time.time() - t0:.1f}s; bytes {sizes})")
        srv.app.refresher.stop(10)
        srv.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
