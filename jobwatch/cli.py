"""Command-line interface: `jobwatch <command>`."""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import __version__, config, report, sources
from .config import ConfigError
from .score import ScoringUnavailable
from .store import STATUSES, Store
from .watch import build_digest, fetch_all, load_contacts, queue


def _write(text: str, out: Path | None):
    if out:
        out.write_text(text, encoding="utf-8")
        print(f"Wrote {out}", file=sys.stderr)
    else:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")


def cmd_init(args):
    path = Path(args.path)
    if path.exists() and not args.force:
        raise SystemExit(f"{path} exists (use --force to overwrite)")
    path.write_text(config.EXAMPLE)
    print(f"Wrote {path}. Add companies with `jobwatch find \"Company\"`, then run `jobwatch run`.")


def cmd_find(args):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(sources.probe, args.company))
    for query, hits in zip(args.company, results, strict=True):
        if not hits:
            print(f"{query}: no Greenhouse, Lever or Ashby board found. Paste a job link from their careers "
                  "page to check, or the company may use another system.")
        for source, board, jobs in hits:
            name = next((j.company_name for j in jobs if j.company_name), "")
            print(f"{query}: {source}:{board}  ({len(jobs)} open roles{', ' + name if name else ''})  "
                  f"{sources.SOURCES[source].careers.format(board=board)}\n    e.g. {jobs[0].title}")


def _digest(args, cfg, store):
    d = build_digest(cfg, store, include_seen=args.all, score_top=args.score, limit=args.limit)
    text = report.to_json(d) if args.format == "json" else report.to_markdown(d)
    if not args.peek:
        store.set_status([k for e in d.entries for k in e.keys], "shown")
    return text


def cmd_fetch(args, cfg, store):
    print(report.fetch_summary(fetch_all(cfg, store)))


def cmd_digest(args, cfg, store):
    _write(_digest(args, cfg, store), args.out)


def cmd_run(args, cfg, store):
    print(report.fetch_summary(fetch_all(cfg, store)), file=sys.stderr)
    _write(_digest(args, cfg, store), args.out)


def cmd_show(args, cfg, store):
    job, rec = store.find(args.key)
    status = rec["status"] + (f" ({rec['note']})" if rec.get("note") else "")
    closed = f", closed {rec['closed'][:10]}" if rec["closed"] else ""
    print(f"{job.to_text()}\n---\n{job.key}: {status}, first seen {rec['first_seen'][:10]}{closed}")
    if (contacts := load_contacts(cfg)) and (known := contacts.at(job.display_company, job.company)):
        print(f"You know: {report.people(known, most=10)}")


def cmd_mark(args, cfg, store):
    keys = [store.find(k)[0].key for k in args.keys]
    store.set_status(keys, args.status, args.note)
    for k in keys:
        print(f"{k}: {args.status}")


def cmd_queue(args, cfg, store):
    if args.keys:
        args.status = "queued"
        return cmd_mark(args, cfg, store)
    _write(report.queue_markdown(queue(cfg, store)), args.out)


def cmd_ui(args):
    from .web import serve

    server = serve(config.locate(args.config), port=args.port, open_browser=not args.no_browser)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def cmd_list(args, cfg, store):
    rows = store.jobs(tuple(args.status) if args.status else None, include_closed=True)
    for job, rec in rows:
        closed = " [closed]" if rec["closed"] else ""
        note = f"  ({rec['note']})" if rec.get("note") else ""
        print(f"{rec['status']:8} {(rec['status_at'] or rec['first_seen'])[:10]}  {job.display_company}: "
              f"{job.title}{closed}{note}  `{job.key}`")
    if not rows:
        print("no jobs")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="jobwatch", description="Watch company job boards (Greenhouse, Lever, "
                                 "Ashby) and get a ranked digest of new matches.")
    ap.add_argument("--version", action="version", version=f"jobwatch {__version__}")
    ap.add_argument("-c", "--config", help="watchlist file (default: ./jobwatch.yaml, $JOBWATCH_CONFIG, "
                    "~/.config/jobwatch/config.yaml)")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="write an example watchlist")
    p.add_argument("path", nargs="?", default="jobwatch.yaml")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init, needs_config=False)

    p = sub.add_parser("find", help="find a company's job board (by name, or a job/careers link)")
    p.add_argument("company", nargs="+")
    p.set_defaults(func=cmd_find, needs_config=False)

    p = sub.add_parser("fetch", help="check every board and record new roles")
    p.set_defaults(func=cmd_fetch)

    for name, func, help_ in (("digest", cmd_digest, "ranked list of new matching jobs"),
                              ("run", cmd_run, "fetch, then digest (for a daily schedule)")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--score", type=int, default=None, metavar="N",
                       help="score the N most relevant unscored jobs with shortlist-ai (default: config)")
        p.add_argument("--all", action="store_true", help="include jobs already shown in an earlier digest")
        p.add_argument("--peek", action="store_true", help="don't mark the listed jobs as shown")
        p.add_argument("--limit", type=int, default=None)
        p.add_argument("--format", choices=["md", "json"], default="md")
        p.add_argument("-o", "--out", type=Path)
        p.set_defaults(func=func)

    p = sub.add_parser("show", help="a job's full posting text")
    p.add_argument("key", help="job key, or its posting id")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("mark", help="record that you queued, applied to or skipped jobs")
    p.add_argument("status", choices=STATUSES)
    p.add_argument("keys", nargs="+")
    p.add_argument("--note")
    p.set_defaults(func=cmd_mark)

    p = sub.add_parser("queue", help="jobs to apply to next: `queue <key>...` adds, `queue` lists")
    p.add_argument("keys", nargs="*")
    p.add_argument("--note", help="e.g. 'ask Ana for a referral first'")
    p.add_argument("-o", "--out", type=Path)
    p.set_defaults(func=cmd_queue)

    p = sub.add_parser("ui", help="open jobwatch in your browser (setup, digest, queue, applied)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    p.set_defaults(func=cmd_ui, needs_config=False)

    p = sub.add_parser("list", help="jobs by status, e.g. `jobwatch list --status applied`")
    p.add_argument("--status", choices=STATUSES, action="append")
    p.set_defaults(func=cmd_list)
    return ap


def main(argv: list[str] | None = None):
    args = build_parser().parse_args(argv)
    try:
        if getattr(args, "needs_config", True) is False:
            return args.func(args)
        cfg = config.load(args.config)
        store = Store(cfg.state)
        try:
            args.func(args, cfg, store)
        finally:
            store.close()
    except (ConfigError, ScoringUnavailable, KeyError, sources.SourceError) as e:
        raise SystemExit(f"jobwatch: {e.args[0] if isinstance(e, KeyError) else e}") from None


if __name__ == "__main__":
    main()
