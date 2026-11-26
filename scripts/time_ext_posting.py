#!/usr/bin/env python3
"""Time POST /ext/posting on a made-up state file of N jobs, without a browser, and say where the time goes.

    scripts/time_ext_posting.py [--jobs 50000] [--profile]

Seeds a throwaway watchlist with N board jobs (Initech, Globex and Umbrella, in invented towns) plus one job from
a LinkedIn alert with no text, then answers what the extension's Read posting sends for it, as App.ext_posting
does. Prints how long each of those requests took; --profile adds the functions the time went in. Nothing real is
read or written: the files are in a temporary folder and no network is used.
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
TOWNS = ("Springfield", "Shelbyville", "Ogdenville", "Capital City")
LINKEDIN_ID = "4000000001"
POSTING = "Build and run machine learning services. " * 150  # a posting's text, about 6 KB


def seed(path: Path, jobs: int):
    """A watchlist at `path` and, next to it, a state file with `jobs` board jobs and one alert job."""
    path.write_text("companies:\n  - greenhouse:initech\nstate: state.db\ncache: cache\nfetch_every: off\n"
                    "keywords:\n  Python: 2\n")
    store = Store(config.load(path).state)
    try:
        with store.db:
            for i in range(jobs):
                job = Job(source="greenhouse", company=COMPANIES[i % 3], id=str(i), title=f"Engineer {i}",
                          url=f"https://boards.example/{i}", locations=[TOWNS[i % 4]], description=POSTING)
                store.db.execute("INSERT INTO jobs (key, source, company, data, first_seen, last_seen) VALUES "
                                 "(?, ?, ?, ?, ?, ?)", (job.key, job.source, job.company, json.dumps(job.to_dict()),
                                                        f"2026-01-{i % 28 + 1:02d}", "2026-11-25"))
        return store.add("Globex", "Machine Learning Engineer", status="queued", note="From a LinkedIn job alert",
                         url=f"https://www.linkedin.com/jobs/view/{LINKEDIN_ID}/").key
    finally:
        store.close()


def requests(key: str) -> list[tuple[str, dict]]:
    """The bodies the extension sends: the first read of an alert job, then the page read again, open this time."""
    body = {"linkedin": LINKEDIN_ID, "company": "Globex", "title": "Machine Learning Engineer", "text": POSTING,
            "closed": False}
    return [("first read, page open", body), ("read again, page open", body), ("read again, page closed",
                                                                              {**body, "closed": True})]


def timed(app: App, body: dict) -> float:
    start = time.perf_counter()
    app.ext_posting(body)
    return time.perf_counter() - start


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jobs", type=int, default=50_000, help="board jobs in the made-up state file")
    ap.add_argument("--profile", action="store_true", help="also list the functions the time went in")
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "jobwatch.yaml"
        key = seed(path, args.jobs)
        app = App(path)
        for label, body in requests(key):
            took = timed(app, body)
            print(f"{label:26} {took:6.2f}s  ({args.jobs} jobs)")
        if args.profile:
            prof = cProfile.Profile()
            prof.runcall(app.ext_posting, requests(key)[1][1])
            pstats.Stats(prof).sort_stats("cumulative").print_stats(12)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
