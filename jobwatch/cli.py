"""Command-line interface: `jobwatch <command>`."""

from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from . import __version__, chat, config, learn, prep, report, sources
from .config import ConfigError
from .score import ScoringUnavailable
from .store import STAGES, STATUSES, Store
from .watch import build_digest, fetch_all, load_contacts, queue, save_job, watched_name


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
            print(f"{query}: no Greenhouse, Lever, Ashby, Workday or Eightfold board found. Paste a job link "
                  "from their careers page to check, or the company may use another system.")
        for source, board, jobs in hits:
            name = next((j.company_name for j in jobs if j.company_name), "")
            print(f"{query}: {source}:{board}  ({sources.open_roles(jobs)} open roles{', ' + name if name else ''})  "
                  f"{sources.careers_url(source, board)}\n    e.g. {jobs[0].title}")


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
    if home := store.candidate_home(job):
        print(f"Your applications there (sign in): {home}")


def cmd_mark(args, cfg, store):
    keys = [store.find(k)[0].key for k in args.keys]
    store.set_status(keys, args.status, args.note, on=getattr(args, "on", None))
    for k in keys:
        store.track(k, next_step=getattr(args, "next", None), follow_up=getattr(args, "follow_up", None))
        if getattr(args, "add_note", None):
            store.add_note(k, args.add_note)
        print(f"{k}: {args.status}")
        _attach(store.package(k), getattr(args, "attach", None) or [])


def _attach(pkg, files: list[Path], kind: str | None = None):
    for f in files:
        name = pkg.attach(f.name, f.expanduser().read_bytes(), kind)
        print(f"  kept {f.name} as {pkg.dir / name}")


def _answers(path: Path) -> list[dict]:
    """A YAML or JSON file of form answers: {question: answer, ...} or [{question, answer}, ...]."""
    raw = yaml.safe_load(path.expanduser().read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return [{"question": str(q), "answer": "" if a is None else str(a)} for q, a in raw.items()]
    if isinstance(raw, list):
        return raw
    raise ValueError(f"{path}: expected question: answer pairs, or a list of {{question, answer}}")


def cmd_attach(args, cfg, store):
    pkg = store.package(args.key)
    _attach(pkg, args.files, args.kind)
    pkg.write(answers=_answers(args.answers) if args.answers else None,
              note=args.message.expanduser().read_text(encoding="utf-8") if args.message else None)
    cmd_package(args, cfg, store)


def cmd_package(args, cfg, store):
    pkg = store.package(args.key)
    d = pkg.data()
    print(pkg.context() or "Nothing kept yet. Add what you sent with `jobwatch attach`.")
    if d["posting_saved"]:
        print(f"\nPosting as it read on {d['posting_saved']}: {pkg.dir / 'posting.md'}")
    print(f"Folder: {pkg.dir}")


def cmd_add(args, cfg, store):
    link, company, title = args.url or "", "", ""
    if len(args.job) == 1 and re.match(r"(?:https?://)?[\w-]+(?:\.[\w-]+)+/", args.job[0]):
        link, company = args.job[0], args.company or watched_name(cfg, args.job[0])
    elif len(args.job) == 2:
        company, title = args.job
    else:
        raise ValueError("give a link to the posting, or the company and the job title")
    text = "" if not args.text else sys.stdin.read() if str(args.text) == "-" else args.text.read_text()
    job, read = save_job(store, link, company, title, text, status=args.status, note=args.note, applied=args.on,
                         location=args.location or "")
    store.track(job.key, next_step=args.next, follow_up=args.follow_up)
    if args.add_note:
        store.add_note(job.key, args.add_note)
    how = "read from the link" if read else "with the posting's text" if text.strip() else ""
    print(f"{job.key}: {args.status}" + (f" ({job.display_company}, {job.title}; {how})" if how else ""))


def cmd_applications(args, cfg, store):
    rows = store.applications()
    if args.due:
        rows = [r for r in rows if report.due(r[1])]
    _write(report.applications_markdown(rows, homes={j.key: store.candidate_home(j) for j, _ in rows}), args.out)


def cmd_ask(args, cfg, store):
    info, pieces = chat.start(cfg, store, chat.clean([{"role": "user", "content": " ".join(args.question)}]),
                              args.job)
    print(f"({info['label']}: {info['model']})", file=sys.stderr)
    for text in pieces:
        sys.stdout.write(text)
        sys.stdout.flush()
    sys.stdout.write("\n")


def cmd_prep(args, cfg, store):
    _write(prep.markdown(prep.build(cfg, store, args.key)), args.out)


def cmd_skills(args, cfg, store):
    _write(learn.markdown(learn.gather(cfg, store, args.timeline), include_covered=args.all), args.out)


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


def cmd_service(args):
    from . import service

    try:
        if args.action == "install":
            url = service.install(config.locate(args.config), args.port)
            print(f"jobwatch ui now starts when you log in and restarts if it stops: {url}\n"
                  f"Log: {service.log_path()}. Undo with `jobwatch service uninstall`.")
        elif args.action == "uninstall":
            print("Removed: jobwatch ui no longer starts at login." if service.uninstall() else "Not installed.")
        else:
            s = service.status()
            if not s["installed"]:
                print("Not installed. `jobwatch service install` starts jobwatch ui at login.")
            else:
                state = f"running (pid {s['pid']})" if s["running"] else "installed, not running: see the log"
                print(f"{state}\n{s['url'] or ''}\nLog: {s['log']}")
    except service.ServiceError as e:
        raise SystemExit(f"jobwatch: {e}") from None


def cmd_list(args, cfg, store):
    rows = store.jobs(tuple(args.status) if args.status else None, include_closed=True)
    for job, rec in rows:
        closed = " [closed]" if rec["closed"] else ""
        note = f"  ({rec['note']})" if rec.get("note") else ""
        print(f"{rec['status']:8} {(rec['status_at'] or rec['first_seen'])[:10]}  {job.display_company}: "
              f"{job.title}{closed}{note}  `{job.key}`")
    if not rows:
        print("no jobs")


def _tracking(p: argparse.ArgumentParser):
    p.add_argument("--note", help="replaces the note")
    p.add_argument("--add-note", metavar="TEXT", help="adds a dated line to the note, keeping what's there")
    p.add_argument("--on", metavar="DAY", help="the day you applied, if not today (YYYY-MM-DD)")
    p.add_argument("--next", metavar="STEP", help="what happens next, e.g. 'check in with the recruiter'")
    p.add_argument("--follow-up", metavar="DAY", help="when to act on it: YYYY-MM-DD, tomorrow or +N days")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="jobwatch", description="Watch company job boards (Greenhouse, Lever, "
                                 "Ashby, Workable, Workday, Eightfold) and get a ranked digest of new matches.")
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

    p = sub.add_parser("mark", help="record that you queued, applied to or skipped jobs, or how an application "
                       "is going (screening, interviewing, offer, rejected, withdrawn)")
    p.add_argument("status", choices=STATUSES)
    p.add_argument("keys", nargs="+")
    _tracking(p)
    p.add_argument("--attach", type=Path, action="append", metavar="FILE",
                   help="keep a copy of what you sent (the resume, a cover letter); repeat for more")
    p.set_defaults(func=cmd_mark)

    p = sub.add_parser("add", help="add a job found elsewhere (LinkedIn, a referral, a recruiter): `add <link>` "
                       "reads the posting from Greenhouse, Lever, Ashby, Workable or Workday; `add <company> "
                       "<title>` for anything else. --status queued to consider it, else it's an application")
    p.add_argument("job", nargs="+", metavar="LINK | COMPANY TITLE")
    p.add_argument("--url", help="link to the posting, with a company and title")
    p.add_argument("--company", help="with a link: the company's name, when the board doesn't give it (Workday)")
    p.add_argument("--text", type=Path, metavar="FILE", help="the posting's text, to score it (- reads stdin)")
    p.add_argument("--status", choices=("queued", *STAGES), default="applied")
    p.add_argument("--location")
    _tracking(p)
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("applications", aliases=["apps"], help="where each application stands, follow-ups first")
    p.add_argument("--due", action="store_true", help="only applications to follow up on now")
    p.add_argument("-o", "--out", type=Path)
    p.set_defaults(func=cmd_applications)

    p = sub.add_parser("attach", help="keep what you sent with an application: the resume, a cover letter, the "
                                      "form's answers (copies, so later edits don't change them)")
    p.add_argument("key")
    p.add_argument("files", nargs="*", type=Path)
    p.add_argument("--kind", choices=["resume", "letter", "other"], help="default: guessed from the file name")
    p.add_argument("--answers", type=Path, metavar="FILE", help="YAML or JSON: question: answer pairs")
    p.add_argument("--message", type=Path, metavar="FILE", help="a cover letter or message you pasted in, as text")
    p.set_defaults(func=cmd_attach)

    p = sub.add_parser("package", help="what you sent with an application")
    p.add_argument("key")
    p.set_defaults(func=cmd_package)

    p = sub.add_parser("ask", help="ask about today's jobs and your applications, or one job (--job), with the "
                                   "model set in scoring.backend")
    p.add_argument("question", nargs="+")
    p.add_argument("--job", metavar="KEY", help="ask about this job (its key, or the end of it)")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("prep", help="a prep sheet for a recruiter call or interview: their asks next to your "
                                    "resume lines, gaps to be honest about, what you sent, questions to expect")
    p.add_argument("key")
    p.add_argument("-o", "--out", type=Path)
    p.set_defaults(func=cmd_prep)

    p = sub.add_parser("skills", help="skills your matching jobs ask for that your resume doesn't show, and "
                                      "courses and certifications to learn them")
    p.add_argument("--timeline", choices=config.TIMELINES,
                   help="how soon: week, month, quarter (default, or learning.timeline) or any")
    p.add_argument("--all", action="store_true", help="also skills your resume already shows")
    p.add_argument("-o", "--out", type=Path)
    p.set_defaults(func=cmd_skills)

    p = sub.add_parser("queue", help="jobs to apply to next: `queue <key>...` adds, `queue` lists")
    p.add_argument("keys", nargs="*")
    p.add_argument("--note", help="e.g. 'ask Ana for a referral first'")
    p.add_argument("-o", "--out", type=Path)
    p.set_defaults(func=cmd_queue)

    p = sub.add_parser("ui", help="open jobwatch in your browser (setup, digest, queue, applied)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    p.set_defaults(func=cmd_ui, needs_config=False)

    p = sub.add_parser("service", help="keep `jobwatch ui` running: start it at login, restart it if it stops "
                                       "(macOS)")
    p.add_argument("action", choices=["install", "uninstall", "status"])
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_service, needs_config=False)

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
    except (ConfigError, ScoringUnavailable, chat.ChatUnavailable, KeyError, ValueError, sources.SourceError) as e:
        raise SystemExit(f"jobwatch: {e.args[0] if isinstance(e, KeyError) else e}") from None


if __name__ == "__main__":
    main()
