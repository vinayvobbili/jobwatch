#!/usr/bin/env python3
"""Time POST /api/mark (Queue, Skip, I applied, Remove, Undo) on a made-up state file of N jobs, and say where the
time goes.

    scripts/time_mark.py [--jobs 50000] [--acted 400] [--profile]

Seeds a throwaway watchlist with N board jobs (Initech, Globex and Umbrella, in invented towns), ACTED of them already
queued, applied or skipped (what the duplicate check reads). Then answers what the page's buttons send, as
App.post_mark does. Prints how long each took; --profile adds the functions the time went in. Nothing real is read or
written: the files are in a temporary folder.
"""

import argparse
import cProfile
import json
import pstats
import tempfile
import time
from pathlib import Path

from jobwatch import config
from jobwatch.models import Job
from jobwatch.store import Store
from jobwatch.web import App

COMPANIES = ("initech", "globex", "umbrella")
BOARDS = 100  # companies the jobs are spread over: initech0, globex1, umbrella2, initech3...
TOWNS = ("Springfield", "Shelbyville", "Ogdenville", "Capital City")
POSTING = "Build and run machine learning services. " * 150  # a posting's text, about 6 KB
ACTED_STATUSES = ("queued", "applied", "skipped")


def board(i: int) -> str:
    return f"{COMPANIES[i % 3]}{i % BOARDS}"


def seed(path: Path, jobs: int, acted: int) -> dict[str, str]:
    """A watchlist at `path` and, next to it, a state file; returns the keys to press each button on."""
    path.write_text("companies:\n  - greenhouse:initech\nstate: state.db\ncache: cache\nfetch_every: off\n"
                    "keywords:\n  Python: 2\n")
    store = Store(config.load(path).state)
    try:
        with store.db:
            for i in range(jobs):
                job = Job(source="greenhouse", company=board(i), id=str(i), title=f"Engineer {i}",
                          url=f"https://boards.example/{i}", locations=[TOWNS[i % 4]], description=POSTING)
                status = ACTED_STATUSES[i % 3] if i < acted else "new"
                store.db.execute("INSERT INTO jobs (key, source, company, data, first_seen, last_seen, status, "
                                 "status_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                 (job.key, job.source, job.company, json.dumps(job.to_dict()),
                                  f"2026-01-{i % 28 + 1:02d}", "2026-11-25", status, "2026-11-01"))
        fresh = [f"greenhouse:{board(i)}:{i}" for i in range(acted, acted + 4)]
        return dict(zip(("queue", "skip", "applied", "remove"), fresh, strict=True))
    finally:
        store.close()


def presses(keys: dict[str, str]) -> list[tuple[str, dict]]:
    """What each button sends, in the order a person might press them."""
    return [("Queue", {"keys": [keys["queue"]], "status": "queued"}),
            ("Skip", {"keys": [keys["skip"]], "status": "skipped"}),
            ("I applied", {"keys": [keys["applied"]], "status": "applied"}),
            ("Remove from queue", {"keys": [keys["remove"]], "status": "shown"}),
            ("Undo (back to new)", {"keys": [keys["queue"]], "status": "new"})]


def timed(app: App, body: dict) -> float:
    start = time.perf_counter()
    app.post_mark(body)
    return time.perf_counter() - start


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jobs", type=int, default=50_000, help="board jobs in the made-up state file")
    ap.add_argument("--acted", type=int, default=400, help="of them, jobs already queued, applied or skipped")
    ap.add_argument("--profile", action="store_true", help="also list the functions the time went in")
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "jobwatch.yaml"
        keys = seed(path, args.jobs, min(args.acted, args.jobs - 6))
        app = App(path)
        for label, body in presses(keys):
            print(f"{label:22} {timed(app, body):6.2f}s  ({args.jobs} jobs, {args.acted} acted on)")
        if args.profile:
            prof = cProfile.Profile()
            prof.runcall(app.post_mark, {"keys": [keys["queue"]], "status": "queued"})
            pstats.Stats(prof).sort_stats("cumulative").print_stats(14)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
