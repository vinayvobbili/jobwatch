"""Command-line interface: `jobwatch <command>`."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from . import __version__, alerts, chat, config, dupes, learn, levels, prep, report, sources
from .config import ConfigError
from .score import ScoringUnavailable, resume_id
from .store import STAGES, STATUSES, Store
from .watch import (
    build_digest,
    check_postings,
    fetch_all,
    load_contacts,
    queue,
    save_job,
    score_entries,
    set_link,
    unscored,
    unscored_reasons,
    watched_name,
)


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
            print(f"{query}: no Greenhouse, Lever, Ashby, Workday, Eightfold, Rippling, SmartRecruiters or Avature "
                  "board found. Give the link to their careers page or a job on it, to look for a board linked "
                  "there; or the company may use another system.")
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


def cmd_score(args, cfg, store):
    """Score Today's unscored jobs now, most relevant first and one at a time, so stopping keeps what's done.
    `jobwatch ui` does the same in the background."""
    if not (cfg.resume and cfg.resume.is_file()):
        raise ConfigError("set `resume:` in the watchlist to a resume file to score fit")
    todo = unscored(cfg, store)
    todo = todo[:args.limit] if args.limit else todo
    if not todo:
        print("Every job on Today has a fit score.")
        return
    scored, failed = 0, {}
    for i, e in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {e.job.display_company}: {e.job.title}", file=sys.stderr)
        n, errors = score_entries(cfg, store, [e], progress=lambda m: None)
        scored += n
        failed.update(errors)
        if n:
            fit = e.fit
            print(f"  {fit['score']:.0f}/100, must-haves {fit['must_haves_met']}/{fit['must_haves_total']}",
                  file=sys.stderr)
    print(f"Scored {scored} of {len(todo)} jobs." + (f" {len(failed)} failed:" if failed else ""))
    for key, err in failed.items():
        print(f"  {key}: {err}")


def cmd_unscored(args, cfg, store):
    """Today's jobs with no fit score, and why: in the background scorer's line (and where), no posting text to
    score, the same role scored before this posting came in, no resume. Failures and the job being scored
    right now are what the page itself knows: see Today there."""
    why = unscored_reasons(cfg, store)
    if not why:
        print("Every job on Today has a fit score.")
        return
    for key, w in why.items():
        job, _ = store.find(key)
        print(f"{job.display_company}: {job.title}\n  {w['text']}\n  {key}")
    counts: dict[str, int] = {}
    for w in why.values():
        counts[w["code"]] = counts.get(w["code"], 0) + 1
    print(f"\n{len(why)} without a score: " + ", ".join(f"{n} {code.replace('_', ' ')}" for code, n in counts.items()))


def cmd_show(args, cfg, store):
    job, rec = store.find(args.key)
    status = rec["status"] + (f" ({rec['note']})" if rec.get("note") else "")
    closed = f", closed {rec['closed'][:10]}" if rec["closed"] else ""
    via = f" (via {rec['via']})" if rec.get("via") else ""
    print(f"{job.to_text()}\n---\n{job.key}: {status}, first seen {rec['first_seen'][:10]}{via}{closed}")
    if job.link_note:
        print(f"Link: {job.link_note}")
    if same := dupes.check(store, job.key):
        print(f"Check: {same.line}")
    if (contacts := load_contacts(cfg)) and (known := contacts.at(job.display_company, job.company)):
        print(f"You know: {report.people(known, most=10)}")
    if home := store.candidate_home(job):
        print(f"Your applications there (sign in): {home}")
    if cfg.resume and cfg.resume.is_file() and (fit := store.score(job.key, resume_id(cfg.resume))):
        print("\n".join(report.fit_lines(fit)))
    if (pay := levels.for_one_job(cfg, store, job)) is not None:
        print("\n".join(report.pay_lines(pay, job)))


def cmd_mark(args, cfg, store):
    if not hasattr(args, "keys"):  # `mark [STATUS] KEY...` or `mark KEY... STATUS`; without one, each keeps its own
        what = args.what
        status, *keys = (what if what[0] in STATUSES else (what[-1], *what[:-1]) if what[-1] in STATUSES
                         else (None, *what))
        if not keys:
            raise ValueError("which job? give its key, posting id or company")
        args.status, args.keys = status, keys
    keys = [store.find(k)[0].key for k in args.keys]
    if args.status:
        store.set_status(keys, args.status, args.note, on=getattr(args, "on", None))
    else:
        for k in keys:
            store.track(k, note=args.note, applied=getattr(args, "on", None))
    if text := getattr(args, "text", None):
        text = sys.stdin.read() if str(text) == "-" else text.read_text()
        for k in keys:
            store.set_description(k, text)
    for k in keys:
        store.track(k, next_step=getattr(args, "next", None), follow_up=getattr(args, "follow_up", None))
        if getattr(args, "url", None) is not None:
            print(f"  {k}: {set_link(store, k, args.url)}")
        if getattr(args, "add_note", None):
            store.add_note(k, args.add_note)
        print(f"{k}: {args.status or store.find(k)[1]['status']}")
        if args.status == "queued" and (same := dupes.check(store, k)):  # queued all the same: the person decides
            print(f"  Check: {same.line}")
        _attach(store.package(k), getattr(args, "attach", None) or [])


def _attach(pkg, files: list[Path], kind: str | None = None):
    for f in files:
        name = pkg.attach(f.name, f.expanduser().read_bytes(), kind)
        print(f"  kept {f.name} as {pkg.dir / name}")


def _pairs(d: dict, prefix: str = "") -> list[dict]:
    out = []
    for q, a in d.items():
        if isinstance(a, dict):  # a form's sections: {"Links": {"LinkedIn": ...}} -> "Links / LinkedIn"
            out += _pairs(a, f"{prefix}{q} / ")
        else:
            text = "" if a is None else ("Yes" if a else "No") if isinstance(a, bool) else str(a)  # YAML: no -> False
            out.append({"question": f"{prefix}{q}", "answer": text})
    return out


def _answers(path: Path) -> list[dict]:
    """A YAML or JSON file of form answers: {question: answer, ...} (sections nested or not) or
    [{question, answer}, ...]."""
    raw = yaml.safe_load(path.expanduser().read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return _pairs(raw)
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
                         location=args.location or "", boards=cfg.boards)
    store.track(job.key, next_step=args.next, follow_up=args.follow_up)
    if args.add_note:
        store.add_note(job.key, args.add_note)
    how = "read from the link" if read else "with the posting's text" if text.strip() else ""
    print(f"{job.key}: {args.status}" + (f" ({job.display_company}, {job.title}; {how})" if how else ""))
    if same := dupes.check(store, job.key):
        print(f"  Check: {same.line}")


def cmd_dupes(args, cfg, store):
    """Pairs of tracked jobs that are (maybe) the same opening, where you acted on one: read-only."""
    print(dupes.pairs_text(dupes.pairs(store, strong_only=args.strong)))


def cmd_alerts(args, cfg, store):
    if not (args.emails or args.imap):
        raise ValueError("give the alert emails: .eml or .mbox files, a folder of them, or - to read stdin; or "
                         "--imap to read them from the mailbox set in alerts.imap")
    msgs = alerts.read(args.emails, sys.stdin) if args.emails else []
    if args.imap:
        if not cfg.imap:
            raise ConfigError("--imap reads the mailbox set in alerts.imap in the watchlist, and there's none: "
                              "see the README's job-alert emails section")
        msgs += alerts.imap_messages(cfg.imap)
    r = alerts.intake(cfg, store, msgs, follow=not args.no_follow, dry_run=args.dry_run)
    if args.format == "json":
        print(json.dumps(alerts.to_dict(r), indent=2, ensure_ascii=False))
    else:
        print(alerts.summary(r, every=args.all))


def cmd_applications(args, cfg, store):
    rows = store.applications()
    if args.due:
        rows = [r for r in rows if report.due(r[1])]
    _write(report.applications_markdown(rows, homes={j.key: store.candidate_home(j) for j, _ in rows}), args.out)


def cmd_ask(args, cfg, store):
    info, pieces = chat.start(cfg, store, chat.clean([{"role": "user", "content": " ".join(args.question)}]),
                              args.job)
    print(f"({info['label']}: {info['model']})", file=sys.stderr)
    for piece in pieces:
        if isinstance(piece, dict):  # what it's waiting for, or what the model reports at the end
            print(f"({piece['status']}…)" if "status" in piece else "\n(" + chat.stats_line(piece) + ")",
                  file=sys.stderr)
            continue
        sys.stdout.write(piece)
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
    _write(report.queue_markdown(queue(cfg, store, pay_budget=levels.QUEUE)), args.out)


def cmd_check(args, cfg, store):
    checks = check_postings(store, tuple(args.status or ("queued", "applied", "screening", "interviewing")),
                            watched=cfg.boards)
    order = {"closed": 0, "reopened": 1, "unknown": 2, "open": 3}
    for c in sorted(checks, key=lambda c: order[c.result]):
        if c.result != "open" or args.all:
            print(f"{c.result:8}  {c.job.key}  {c.job.display_company}: {c.job.title}"
                  + (f"  ({c.detail})" if c.detail else ""))
    counts = {r: sum(c.result == r for c in checks) for r in order}
    print(", ".join(f"{n} {r}" for r, n in counts.items() if n) or "nothing to check", file=sys.stderr)


def cmd_ui(args):
    from .web import serve

    server = serve(config.locate(args.config), port=args.port, open_browser=not args.no_browser)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def cmd_mcp(args):
    try:
        from . import mcp_server
    except ImportError as e:
        if e.name != "mcp" and not str(e.name).startswith("mcp."):
            raise
        raise SystemExit("jobwatch: the MCP server needs the mcp package: pip install 'jobwatch[mcp]'") from None
    if args.config:
        os.environ["JOBWATCH_CONFIG"] = str(args.config)
    mcp_server.main()


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
                                 "Ashby, Workable, Workday, Eightfold, Jibe, Rippling, Google Careers, Amazon, "
                                 "Oracle Recruiting Cloud, SmartRecruiters, Avature) and get a ranked digest of new "
                                 "matches.")
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

    p = sub.add_parser("score", help="score Today's unscored jobs against your resume, most relevant first")
    p.add_argument("--limit", type=int, default=None, metavar="N", help="stop after N jobs")
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("unscored", help="Today's jobs with no fit score yet, and why (in line, no posting text...)")
    p.set_defaults(func=cmd_unscored)

    p = sub.add_parser("show", help="a job's full posting text")
    p.add_argument("key", help="job key, its posting id, or its company")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("mark", help="record that you queued, applied to or skipped jobs, or how an application "
                       "is going (screening, interviewing, offer, rejected, withdrawn); without a status, each job "
                       "keeps its own and only the rest changes")
    p.add_argument("what", nargs="+", metavar="[STATUS] KEY", help="the job: its key, its posting id, or its "
                   "company when that names one job (the one you queued or applied to there); and the status, "
                   f"before or after it: {', '.join(STATUSES)}")
    _tracking(p)
    p.add_argument("--url", metavar="LINK", help="the link for a job you added by hand: its posting, or the "
                   "company's careers site once the posting is gone")
    p.add_argument("--text", type=Path, metavar="FILE", help="the posting's text for a job you added by hand (found "
                   "later, or from a copy once the posting is gone), to score and prep it (- reads stdin)")
    p.add_argument("--attach", type=Path, action="append", metavar="FILE",
                   help="keep a copy of what you sent (the resume, a cover letter); repeat for more")
    p.set_defaults(func=cmd_mark)

    p = sub.add_parser("add", help="add a job found elsewhere (LinkedIn, a referral, a recruiter): `add <link>` "
                       "reads the posting from Greenhouse, Lever, Ashby, Workable, Workday, Rippling, Google "
                       "Careers, amazon.jobs, Oracle Recruiting Cloud, SmartRecruiters or Avature; `add <company> "
                       "<title>` for anything else, a LinkedIn link included (--url; LinkedIn's robots.txt doesn't "
                       "allow reading it, so jobwatch looks for the job on the company's own board). "
                       "--status queued to consider it, else it's an application")
    p.add_argument("job", nargs="+", metavar="LINK | COMPANY TITLE")
    p.add_argument("--url", help="link to the posting, with a company and title")
    p.add_argument("--company", help="with a link: the company's name, when the board doesn't give it (Workday)")
    p.add_argument("--text", type=Path, metavar="FILE", help="the posting's text, to score it (- reads stdin)")
    p.add_argument("--status", choices=("queued", *STAGES), default="applied")
    p.add_argument("--location")
    _tracking(p)
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("alerts", help="track the jobs in job-alert emails (LinkedIn, Built In, Indeed and others): "
                       "each is looked for on the company's own board and goes into the digest like any other new "
                       "job. Pages are read only where robots.txt allows; jobwatch never asks for your mail "
                       "password", description="Track the jobs in job-alert emails. Give saved emails (.eml), an "
                       "mbox export, a folder of them, or - to read one email (or an mbox) from stdin. Each job "
                       "whose title, place and pay pass your filters is looked for on the company's own board "
                       "(a link to a supported board is read from there); job sites' pages are read only when "
                       "their robots.txt allows (LinkedIn's and Indeed's don't, so the email's details are used). "
                       "Jobs already tracked are left alone. --imap reads the last few days' alerts from the "
                       "mailbox set in alerts.imap (off unless set; the password comes from an environment variable "
                       "or the macOS keychain, never the watchlist).")
    p.add_argument("emails", nargs="*", metavar="FILE | FOLDER | -", help=".eml or .mbox files, folders of them, "
                   "or - for stdin")
    p.add_argument("--imap", action="store_true", help="also read the last few days' alerts from the mailbox set in "
                   "alerts.imap (read-only: nothing is marked read, moved or deleted)")
    p.add_argument("--dry-run", action="store_true", help="show what would be tracked, and record nothing")
    p.add_argument("--no-follow", action="store_true", help="read no links: track each job as the email has it")
    p.add_argument("--all", action="store_true", help="list every new job, also the ones your filters leave out")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_alerts)

    p = sub.add_parser("applications", aliases=["apps"],help="where each application stands, follow-ups first")
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

    p = sub.add_parser("check", help="check that queued jobs and open applications are still posted, and record "
                       "the ones that closed (or came back)")
    p.add_argument("--status", choices=STATUSES, action="append", help="only jobs with this status (repeatable)")
    p.add_argument("--all", action="store_true", help="also list the ones still open")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("ui", help="open jobwatch in your browser (setup, digest, queue, applied)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    p.set_defaults(func=cmd_ui, needs_config=False)

    p = sub.add_parser("mcp", help="run the MCP server (the same as `jobwatch-mcp`) for Claude or another assistant")
    p.set_defaults(func=cmd_mcp, needs_config=False)

    p = sub.add_parser("service", help="keep `jobwatch ui` running: start it at login, restart it if it stops "
                                       "(macOS)")
    p.add_argument("action", choices=["install", "uninstall", "status"])
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_service, needs_config=False)

    p = sub.add_parser("list", help="jobs by status, e.g. `jobwatch list --status applied`")
    p.add_argument("--status", choices=STATUSES, action="append")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("dupes", help="jobs tracked twice: pairs that are the same opening (a shared req or posting "
                       "id) or maybe the same (the same title), where you queued, applied to or skipped one. "
                       "Read-only: nothing is changed")
    p.add_argument("--strong", action="store_true", help="only the same opening, not the same title alone")
    p.set_defaults(func=cmd_dupes, read_only=True)
    return ap


def main(argv: list[str] | None = None):
    args = build_parser().parse_args(argv)
    try:
        if getattr(args, "needs_config", True) is False:
            return args.func(args)
        cfg = config.load(args.config)
        read_only = getattr(args, "read_only", False)  # opened without changing the file at all
        if read_only and not Path(cfg.state).expanduser().is_file():
            raise ValueError(f"no jobs tracked yet: {cfg.state} doesn't exist")
        store = Store(cfg.state, read_only=read_only)
        try:
            args.func(args, cfg, store)
        finally:
            store.close()
    except (ConfigError, ScoringUnavailable, chat.ChatUnavailable, KeyError, ValueError, sources.SourceError,
            alerts.AlertError) as e:
        raise SystemExit(f"jobwatch: {e.args[0] if isinstance(e, KeyError) else e}") from None


if __name__ == "__main__":
    main()
