"""Command-line interface: `jobwatch <command>`."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import (
    __version__,
    advice,
    alerts,
    answers,
    chat,
    company,
    config,
    drill,
    dupes,
    ics,
    inbox,
    learn,
    levels,
    logos,
    mock,
    prep,
    profile,
    quiet,
    referrals,
    report,
    sources,
    stories,
    storyfind,
    suggest,
)
from .config import BACKENDS, ConfigError, duration
from .filters import KINDS, rejection
from .score import ScoringUnavailable, check_prompts, prompt_info, resume_id, scorer_label
from .store import STAGES, STATUSES, Store
from .watch import (
    MANY_ROLES,
    build_digest,
    check_postings,
    compare_picks,
    compare_scores,
    fetch_all,
    hidden,
    load_contacts,
    pace,
    queue,
    rescore_line,
    save_job,
    scorable,
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
            print(f"{query}: no Greenhouse, Lever, Ashby, Workday, Eightfold, Rippling, SmartRecruiters, Avature, "
                  "iCIMS or Jobvite board found. Give the link to their careers page or a job on it, to look for a "
                  "board linked there; or the company may use another system.")
        for source, board, jobs in hits:
            if not jobs:
                print(f"{query}: {source}:{board}  (no open roles listed)  {sources.careers_url(source, board)}\n"
                      "    The site may send visitors to the company's own careers site: give a link to that careers "
                      "page or a job on it.")
                continue
            name = next((j.company_name for j in jobs if j.company_name), "")
            print(f"{query}: {source}:{board}  ({sources.open_roles(jobs)} open roles{', ' + name if name else ''})  "
                  f"{sources.careers_url(source, board)}\n    e.g. {jobs[0].title}")
            if args.roles:
                _roles(source, board, jobs, args.roles)


def _roles(source: str, board: str, sample: list, text: str):
    """`find --roles`: the board's open roles with the text in the title, with place, pay and posted day."""
    try:
        found = sources.roles_matching(source, board, text, sample)
    except sources.SourceError as e:
        print(f"    roles: {e}")
        return
    if not found:
        print(f"    No open role with {text!r} in its title.")
    for j in found:
        facts = [x for x in ("; ".join(j.places), j.pay(), f"posted {j.posted:%Y-%m-%d}" if j.posted else "") if x]
        print(f"    {j.title}  ({' · '.join(facts)})  {j.url}" if facts else f"    {j.title}  {j.url}")


def _digest(args, cfg, store):
    # The top display.today unless --all or --limit says otherwise; the rest stay new for the next digest.
    limit = args.limit if args.limit is not None else None if args.all else cfg.today or None
    d = build_digest(cfg, store, include_seen=args.all, score_top=args.score, limit=limit)
    text = report.to_json(d) if args.format == "json" else report.to_markdown(
        d, more="`jobwatch digest --all`", pace=pace(cfg, store))
    if not args.peek:
        store.set_status([k for e in d.entries for k in e.keys], "shown")
    return text


def cmd_fetch(args, cfg, store):
    print(report.fetch_summary(fetch_all(cfg, store, reread=tuple(args.reread))))


def cmd_digest(args, cfg, store):
    _write(_digest(args, cfg, store), args.out)


def cmd_run(args, cfg, store):
    print(report.fetch_summary(fetch_all(cfg, store)), file=sys.stderr)
    _write(_digest(args, cfg, store), args.out)


def cmd_score(args, cfg, store):
    """Score Today's unscored jobs now, most relevant first and one at a time, so stopping keeps what's done.
    `jobwatch ui` does the same in the background. --show-prompts prints the prompts it sends instead."""
    if args.show_prompts:
        info = prompt_info(cfg.prompts)
        if info["note"]:
            print(info["note"], file=sys.stderr)
        for p in info["prompts"]:
            print(f"== {p['name']}{' (edited)' if p['edited'] else ''}: {p['about']}\n{p['text']}\n")
        return
    if not (cfg.resume and cfg.resume.is_file()):
        raise ConfigError("set `resume:` in the watchlist to a resume file to score fit")
    if args.backend or args.model:  # this run only; the watchlist keeps its own
        backend = args.backend or cfg.backend
        cfg = replace(cfg, backend=backend, score_fallback="" if cfg.score_fallback == backend else cfg.score_fallback,
                      score_model=args.model if args.model else "" if args.backend else cfg.score_model)
    if args.batch_api and cfg.backend != "claude":
        raise ConfigError(f"--batch-api is for Claude (scoring.backend: claude, or --backend claude), "
                          f"not {cfg.backend}")
    if args.compare:
        return _compare(args, cfg, store)
    if args.keep_old is not None:
        n, scorer = store.keep_old_scores(resume_id(cfg.resume, cfg.prompts), args.keep_old)
        print(f"Kept {n} score{'s' * (n != 1)} from scorer {scorer} as current." if n else
              f"No scores from scorer {scorer} to keep." if scorer else
              "No scores from an earlier scorer to keep.")
        return
    cfg = replace(cfg, score_daily=0)  # scoring.daily holds back the page's background scoring, not what's asked for
    if args.rescore is not None:
        cfg = replace(cfg, score_fallback="")  # the fallback would only put one stand-in score for another
        todo = rescore_line(cfg, store, args.rescore)
        if not todo:
            model = f" ({cfg.score_model})" if cfg.score_model else ""
            print(f"Every scored job on Today was scored by {cfg.backend}{model}.")
            return
    elif args.incomplete or args.redo_kept:
        rid = resume_id(cfg.resume, cfg.prompts)
        dropped = set(store.drop_incomplete_scores(rid) if args.incomplete else store.drop_kept_scores(rid))
        what = "left requirements unjudged" if args.incomplete else "were kept from an earlier scorer"
        todo = [e for e in unscored(cfg, store) if e.job.key in dropped]
        print(f"{len(dropped)} score{'s' * (len(dropped) != 1)} {what}; scoring {len(todo)} of them again (the "
              f"rest aren't on Today or queued: their old score shows until they're scored)." if dropped else
              f"No score {what}.", file=sys.stderr)
        if not todo:
            return
    else:
        todo = unscored(cfg, store)
    todo = todo[:args.limit] if args.limit else todo
    if not todo:
        print("Every job on Today has a fit score.")
        return
    # Groups of scoring.workers jobs scored at once (Claude), so stopping keeps every group done; --batch-api sends
    # them all, half price, and a stopped run collects its batch next time.
    size = len(todo) if args.batch_api else 1 if cfg.backend == "local" else cfg.score_workers
    if args.batch_api:
        print(f"Scoring {len(todo)} jobs through Claude's Message Batches API (half price; each batch takes minutes, "
              "at most a day). Stopping is safe: the next run collects what was sent.", file=sys.stderr)
    scored, failed, done = 0, {}, 0
    for start in range(0, len(todo), size):
        group = todo[start:start + size]
        before = {e.job.key: e.fit["score"] for e in group} if args.rescore is not None else {}
        for i, e in enumerate(group, start + 1):
            if not args.batch_api:
                print(f"[{i}/{len(todo)}] {e.job.display_company}: {e.job.title}", file=sys.stderr)
        n, errors = score_entries(cfg, store, group, batch=args.batch_api,
                                  progress=(lambda m: print(f"  {m}", file=sys.stderr)) if args.batch_api
                                  else (lambda m: None))
        scored += n
        failed.update(errors)
        for e in group:
            done += 1
            if e.job.key in errors:
                continue
            was = before.get(e.job.key)
            fit = e.fit
            print(f"  {f'[{done}/{len(todo)}] {e.job.display_company}: {e.job.title}: ' if size > 1 else ''}"
                  f"{f'{was:.0f} -> ' if was is not None else ''}{fit['score']:.0f}/100, must-haves "
                  f"{fit['must_haves_met']}/{fit['must_haves_total']}"
                  + (f" (by {cfg.score_fallback}: {fit['fallback']})" if fit.get("fallback") else ""), file=sys.stderr)
    print(f"Scored {scored} of {len(todo)} jobs." + (f" {len(failed)} failed:" if failed else ""))
    for key, err in failed.items():
        print(f"  {key}: {err}")


def _compare(args, cfg, store):
    """score --compare N: N already-scored jobs (--stored-by: only ones that backend scored), from the lowest score
    to the highest, scored again with --backend/--model (and --prompts, edited prompts to try) and shown next to
    the stored score. Nothing is stored."""
    prompts = None
    if args.prompts:
        tried = yaml.safe_load(args.prompts.read_text(encoding="utf-8")) or {}
        if not isinstance(tried, dict):
            raise ConfigError(f"{args.prompts}: edited prompts by name (see --show-prompts), got {tried!r:.80}")
        prompts = {**cfg.prompts, **{str(k): str(v) for k, v in tried.items()}}
        if problem := check_prompts(prompts):
            raise ConfigError(f"{args.prompts}: {problem}")
    picks = compare_picks(cfg, store, args.compare, by=args.stored_by or "")
    if not picks:
        print("No job has a fit score for this resume yet" + (f" made by {args.stored_by}" if args.stored_by else "")
              + ": score some first.")
        return
    print(f"Scoring {len(picks)} jobs again with {cfg.backend}{f' ({cfg.score_model})' if cfg.score_model else ''}"
          + (f" and the prompts in {args.prompts}" if prompts else "")
          + (" (paid API calls)" if cfg.backend == "claude" else "") + "; nothing is saved.", file=sys.stderr)
    results, errors = compare_scores(cfg, picks, cfg.backend, cfg.score_model, prompts=prompts,
                                     progress=lambda m: print(f"  {m}", file=sys.stderr), batch=args.batch_api)
    cut, diffs, flips = cfg.filters.min_fit or 0, [], 0
    print(f"{'stored':>6} {'new':>4} {'diff':>5}  job")
    for job, old in picks:
        new = results.get(job.key)
        if not new:
            print(f"{old['score']:6.0f}  {'-':>3} {'':>5}  {job.display_company}: {job.title}  "
                  f"({errors.get(job.key, 'failed')})")
            continue
        diff = new["score"] - old["score"]
        diffs.append(diff)
        crossed = cut and (old["score"] >= cut) != (new["score"] >= cut)
        flips += bool(crossed)
        print(f"{old['score']:6.0f} {new['score']:4.0f} {diff:+5.0f}  {job.display_company}: {job.title}"
              + (f"  <- other side of min_fit {cut}" if crossed else ""))
    by = {scorer_label(f["scored_by"]) for _, f in picks if f.get("scored_by")}
    print(f"\nStored scores by: {', '.join(sorted(by)) or 'the scorer before scores were labelled'}; new by: "
          f"{scorer_label(next(iter(results.values()))['scored_by']) if results else cfg.backend}")
    if diffs:
        print(f"{len(diffs)} compared: mean difference {sum(diffs) / len(diffs):+.1f}, mean size "
              f"{sum(map(abs, diffs)) / len(diffs):.1f}, largest {max(diffs, key=abs):+.0f}"
              + (f", {flips} on the other side of min_fit {cut}" if cut else ""))


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
    print(f"Source: {report.found_on(job, rec.get('via'))}")
    if job.link_note:
        print(f"Link: {job.link_note}")
    if same := dupes.check(store, job.key):
        print(f"Check: {same.line}")
    if (contacts := load_contacts(cfg)) and (known := contacts.at(job.display_company, job.company)):
        print(f"You know: {report.people(known, most=10)}")
    if home := store.candidate_home(job):
        print(f"Your applications there (sign in): {home}")
    fit = (store.score(job.key, resume_id(cfg.resume, cfg.prompts))
           if scorable(job) and cfg.resume and cfg.resume.is_file() else None)
    # Why a job that came in isn't on Today: the first filter it fails.
    if hidden := rejection(job, cfg.filters, fit):
        kind, why = hidden
        why = {"title": "the title matches none of your titles",
               "location": "the location matches none of your places"}.get(why, why)
        print(f"Hidden from Today by your {kind} filter: {why}")
    if not scorable(job):
        print(f"{MANY_ROLES[1]}.")
    elif fit:
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


def cmd_advice(args, cfg, store):
    """How the queue-or-skip suggestions fall across Today's jobs, by rule: read-only."""
    s = advice.summary(cfg, store, build_digest(cfg, store, include_seen=True, score_top=0).entries)
    print(json.dumps(s, indent=2) if args.format == "json" else advice.summary_text(s))


def cmd_hidden(args, cfg, store):
    """What the filters hide from Today, by filter; with a filter's name, its jobs and why: read-only."""
    since = None
    if args.since:
        if not (ago := duration(args.since)):
            raise SystemExit(f"jobwatch: --since looks like 6h, 90m or 1d, got {args.since!r}")
        since = datetime.now(timezone.utc) - ago
    h = hidden(cfg, store, args.kind or "", args.limit, since, args.source or "")
    if args.format == "json":
        print(json.dumps(h, indent=2, ensure_ascii=False))
        return
    print(f"{h['total']} job(s) hidden" + (f" in the last {args.since}" if since else "") + ": "
          + (", ".join(f"{k} {n}" for k, n in h["by"].items()) or "none"))
    for j in h["jobs"]:
        print(f"  {j['company']}: {j['title']}  ({j['kind'] + ': ' if since else ''}{j['why']})  `{j['key']}`")
    if h["more"]:
        print(f"  ...and {h['more']} more (--limit)")


def cmd_logos(args, cfg, store):
    """Look up company logos for the page (logos.py): the companies named, or every one with an open job."""
    jobs = [j for j, _ in store.jobs(include_closed=True)]
    names = args.name or list(dict.fromkeys(j.display_company for j, _ in store.jobs()))
    if args.again:
        for n in names:
            store.db.execute("DELETE FROM logos WHERE company=?", (logos.key(n),))
        store.db.commit()
    found = set(logos.look_up(store, names, jobs))
    for n in dict.fromkeys(names):
        kept = store.logo(logos.key(n))
        line = f"{kept[0]} ({kept[1]}, {len(kept[2]):,} bytes)" if kept and kept[2] else "none found"
        print(f"  {n}: {line}" + ("  (new)" if logos.key(n) in found else ""))


def cmd_company(args, cfg, store):
    """Everything tracked at one company, whatever status its jobs are in: read-only."""
    name = " ".join(args.name)
    v = company.view(cfg, store, name, every=True if args.all else None)
    if args.format == "json":
        print(json.dumps(v, indent=2, ensure_ascii=False))
    else:
        print(company.text(v, name))


def cmd_search(args, cfg, store):
    """Tracked jobs of any status with the text in their note, next step, source, title or company: read-only."""
    text = " ".join(args.text)
    found = company.mentions(store, text)
    print(json.dumps(found, indent=2, ensure_ascii=False) if args.format == "json" else
          company.mentions_text(found, text))


def cmd_answers(args, cfg, store):
    """Form answers saved in earlier applications' packages, for questions with the words given: read-only."""
    query = " ".join(args.query)
    found = answers.find(store, query)
    print(json.dumps(found, indent=2, ensure_ascii=False) if args.format == "json" else answers.text(found, query))


def cmd_profile(args):
    """The roles in a LinkedIn experience page's text that you saved: parsed, never fetched."""
    text = sys.stdin.read() if args.file == "-" else Path(args.file).expanduser().read_text()
    if not (found := profile.roles(text)):
        raise ValueError("no roles found (is this the text of the /details/experience/ page?)")
    print(profile.render(found, args.format))


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


def cmd_inbox(args, cfg, store):
    if not args.emails:
        raise ValueError("give the emails about your applications: .eml or .mbox files, a folder of them, or - to "
                         "read stdin")
    asking = args.apply and not args.yes
    if asking and "-" in args.emails:
        raise ValueError("stdin has the emails, so there's nowhere to ask: save them to files, or give --yes")
    r = inbox.propose(store, alerts.read(args.emails, sys.stdin))
    if args.format == "json":
        print(json.dumps(inbox.to_dict(r), indent=2, ensure_ascii=False))
    else:
        print(inbox.summary(r))
    if not (args.apply or args.yes):
        if r.proposals and args.format == "text":
            print("\nNothing is recorded. --apply asks about each one; --yes records them all.")
        return
    for p in r.proposals:
        if args.yes or input(f"\nRecord this for {p.key}? [y/N] ").strip().lower() in ("y", "yes"):
            print(f"  {inbox.apply(store, p)}")


def cmd_suggest(args, cfg, store):
    for which in args.add or []:
        cfg, s = suggest.accept(cfg, store, which)
        print(f"Watching {s.name}: {s.entry} is on {cfg.path} now (the old file is kept as {cfg.path.name}.bak). "
              "`jobwatch fetch` checks it with the rest.")
    for which in args.dismiss or []:
        print(f"{suggest.dismiss(store, which).name} won't be suggested again.")
    if args.add or args.dismiss:
        return
    if args.rescan:
        n = suggest.rescan(cfg, store)
        if args.format != "json":
            print(f"Rescanned the HN posts already kept: {n} compan{'y' if n == 1 else 'ies'} noted.\n")
    found = suggest.suggestions(cfg, store, limit=args.limit, look=not args.no_lookup)
    if args.format == "json":
        print(json.dumps([s.to_dict() for s in found], indent=2, ensure_ascii=False))
    else:
        print(suggest.text(found))


def cmd_applications(args, cfg, store):
    rows = store.applications()
    found = quiet.find(rows, cfg.quiet, known=load_contacts(cfg))
    rows, more = quiet.order(rows, found), ""
    if args.due:
        rows = [r for r in rows if report.due(r[1])]
        stale = [r for r in rows if found.get(r[0].key, {}).get("long")]
        rows = [r for r in rows if r not in stale]
        more = f"{len(stale)} more due, quiet for {cfg.quiet.long}+ days: `jobwatch quiet`." if stale else ""
    _write(report.applications_markdown(rows, homes={j.key: store.candidate_home(j) for j, _ in rows},
                                        quiet=found, more=more), args.out)


def cmd_quiet(args, cfg, store):
    rows = store.applications()
    _write(report.quiet_markdown(rows, quiet.find(rows, cfg.quiet, known=load_contacts(cfg))), args.out)


def cmd_snooze(args, cfg, store):
    for k in args.keys:
        print(f"{k}: follow up {store.snooze(k, args.days)}")


def cmd_calendar(args, cfg, store):
    feed = ics.calendar(store.applications(), remind=cfg.calendar.remind)
    if args.out:
        args.out.write_bytes(feed.encode())  # bytes: the lines end in CRLF whatever the platform
        print(f"Wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(feed)


def _stream(pieces) -> dict:
    """Print a reply as it's written (what the model reports goes to stderr); returns the dicts it yielded."""
    got = {}
    for piece in pieces:
        if isinstance(piece, dict):  # what it's waiting for, or what the model reports at the end
            got.update(piece)
            if "status" in piece or "output_tokens" in piece:
                print(f"({piece['status']}…)" if "status" in piece else "\n(" + chat.stats_line(piece) + ")",
                      file=sys.stderr)
            continue
        sys.stdout.write(piece)
        sys.stdout.flush()
    sys.stdout.write("\n")
    return got


def cmd_mock(args, cfg, store):
    """A mock interview for one job: a question, your answer, feedback; skip, repeat and quit work at any prompt."""
    session = mock.start(cfg, store, args.job)
    print(f"({session.where['label']}: {session.where['model']})", file=sys.stderr)
    print(f"Mock interview: {len(session.questions)} questions. Type your answer, or skip, repeat, quit.\n")
    answered, skipped, kept = 0, 0, []
    for n, item in enumerate(session.questions, 1):
        answer = "repeat"
        while answer.lower() == "repeat" or not answer:  # a blank line isn't an answer: ask again
            if answer:
                print(f"Question {n} of {len(session.questions)}: {item['question']}")
            try:
                answer = input("> ").strip()
            except EOFError:
                answer = "quit"
        if answer.lower() == "quit":
            break
        if answer.lower() == "skip":
            skipped += 1
            print()
            continue
        answered += 1
        print()
        got = _stream(mock.feedback(session, item["question"], answer))
        if got.get("note"):
            print(f"({got['note']})")
        if got.get("improved"):
            try:
                keep = input("\nSave the tightened answer to the prep sheet? [y/N] ").strip().lower() == "y"
            except EOFError:
                keep = False
            if keep:
                mock.save(store, session.key, item["question"], answer, got["improved"])
                kept.append(item["question"])
        print()
    print(f"Done: {answered} answered, {skipped} skipped, {len(kept)} saved."
          + (f" See them with: jobwatch prep {args.job}" if kept else ""))


def _say(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return "quit"


def cmd_story(args, cfg, store):
    """Find a story: pick one of the prep sheet's gaps (or type your own), answer the model's questions, and save
    the story it proposes once you've checked it. quit ends it at any prompt."""
    gap = " ".join(args.question)
    if not gap:
        found = storyfind.gaps(prep.build(cfg, store, args.job))
        print("What should the story show?" if found else storyfind.NOTHING)
        for n, g in enumerate(found, 1):
            print(f"  {n}. {g['ask']} ({g['why']})")
        pick = _say("Pick a number, or type your own: " if found else "Type what it should show: ")
        if pick.lower() in ("quit", ""):
            return
        gap = found[int(pick) - 1]["ask"] if pick.isdigit() and 1 <= int(pick) <= len(found) else pick
    session = storyfind.start(cfg, store, args.job, gap)
    print(f"({session.where['label']}: {session.where['model']})", file=sys.stderr)
    print(f"Finding a story for: {session.gap}\nAnswer each question; quit ends it. Nothing is saved unless you "
          "say yes.\n")
    def kept(pieces, reply: list[str]):  # the reply's text, kept for the next turn as it's printed
        for p in pieces:
            if isinstance(p, str):
                reply.append(p)
            yield p
    messages: list[dict] = []
    while True:
        reply: list[str] = []
        got = _stream(kept(storyfind.talk(session, messages), reply))
        messages.append({"role": "assistant", "content": "".join(reply)})
        if got.get("note"):
            print(f"({got['note']})")
        if got.get("story"):
            if _say("\nSave this story to your story file? [y/N] ").lower() == "y":
                saved, path = storyfind.save(cfg, got["story"])
                return print(f"Saved {saved.id} to {path}. Drafted answers use it from now on: "
                             f"jobwatch prep {args.job} --draft")
        answer = _say("\n> ")
        while not answer:
            answer = _say("> ")
        if answer.lower() == "quit":
            return print("Nothing saved.")
        messages.append({"role": "user", "content": answer})
        print()


def cmd_stories(args, cfg, store):
    """Check the story file the way drafting reads it (after editing it by hand), and list its stories."""
    if not cfg.stories:
        raise ConfigError("no story file: set `stories:` in the watchlist")
    bank = stories.load(cfg.stories)
    print(f"{cfg.stories}: {len(bank)} stories, all fine")
    for s in bank:
        print(f"  {s.id}: {s.title}")


def cmd_ask(args, cfg, store):
    if args.story:
        if not args.job:
            raise SystemExit("--story needs --job KEY: which job's prep sheet to find a story for")
        return cmd_story(args, cfg, store)
    if args.mock:
        if not args.job:
            raise SystemExit("--mock needs --job KEY: which job to practise for")
        return cmd_mock(args, cfg, store)
    if not args.question:
        raise SystemExit("ask what? e.g. jobwatch ask \"What follow-ups are due?\"")
    info, pieces = chat.start(cfg, store, chat.clean([{"role": "user", "content": " ".join(args.question)}]),
                              args.job)
    print(f"({info['label']}: {info['model']})", file=sys.stderr)
    _stream(pieces)


def cmd_drill(args, cfg, store):
    """A drill video, from a job's prep sheet or (KEY is a file) from a prep sheet written by hand."""
    page = Path(args.key).expanduser()
    if page.suffix.lower() in (".html", ".htm") and page.is_file():
        title, cards = drill.from_page(page.read_text(encoding="utf-8"))
        title = title or page.stem
    else:
        sheet = prep.build(cfg, store, args.key, draft=args.draft)
        title, cards = f"{sheet.title}, {sheet.company}", drill.from_sheet(sheet, stories.load(cfg.stories))
    if not cards:
        raise SystemExit("no questions with answers to drill: add --draft (answers from your stories and resume), "
                         f"or practise some with: jobwatch ask --job {args.key} --mock")
    pause = 0 if args.no_pause else args.pause
    print(f"({len(cards)} questions, {'no pause' if not pause else f'{pause:g} s to answer each'}; "
          "Kokoro speaks on this computer)", file=sys.stderr)
    out = drill.render(drill.segments(cards, title, pause), args.drill)
    print(f"wrote {out}", file=sys.stderr)


def cmd_prep(args, cfg, store):
    if args.drill:
        return cmd_drill(args, cfg, store)
    sheet = prep.build(cfg, store, args.key, draft=args.draft, questions=args.questions)
    if args.draft:
        print(f"({sheet.draft_note})", file=sys.stderr)
    if args.questions and sheet.questions_note:
        print(f"({sheet.questions_note})", file=sys.stderr)
    if args.open:  # the browser needs a file to open; --out names it, otherwise it's a temp file
        out = args.out or Path(tempfile.mkdtemp(prefix="jobwatch-")) / "prep.html"
        _write(prep.html(sheet), out)
        webbrowser.open(out.resolve().as_uri())
    else:
        _write(prep.html(sheet) if args.format == "html" else prep.markdown(sheet), args.out)


def cmd_skills(args, cfg, store):
    _write(learn.markdown(learn.gather(cfg, store, args.timeline), include_covered=args.all), args.out)


def cmd_queue(args, cfg, store):
    if args.keys:
        args.status = "queued"
        return cmd_mark(args, cfg, store)
    _write(report.queue_markdown(queue(cfg, store, pay_budget=levels.QUEUE)), args.out)


def cmd_referrals(args, cfg, store):
    for verdict, who in (("use", args.use), ("skip", args.skip), ("clear", args.clear)):
        for name in who or []:
            p = referrals.rate(cfg, store, name, verdict, args.note or "")
            print({"use": f"{p['name']} sorts first when suggesting who to ask.",
                   "skip": f"{p['name']} won't be suggested.",
                   "clear": f"{p['name']} is back to the usual order."}[verdict])
    if args.use or args.skip or args.clear:
        return
    v = referrals.view(cfg, store)
    print(json.dumps(v, indent=2, ensure_ascii=False) if args.format == "json" else referrals.text(v))


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
                                 "Oracle Recruiting Cloud, SmartRecruiters, Avature, iCIMS, Jobvite, HN's Who is "
                                 "hiring) and get a ranked digest of new matches.")
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
    p.add_argument("--roles", metavar="TEXT", help="also list each board's open roles with TEXT in the title, "
                   "with place, pay and posted day")
    p.set_defaults(func=cmd_find, needs_config=False)

    p = sub.add_parser("fetch", help="check every board and record new roles")
    p.add_argument("--reread", nargs="+", default=[], metavar="BOARD",
                   help="read these boards' postings again, even ones already stored (by name or entry, as "
                        "`jobwatch list` shows them): after a jobwatch update that reads their pages better")
    p.set_defaults(func=cmd_fetch)

    for name, func, help_ in (("digest", cmd_digest, "ranked list of new matching jobs"),
                              ("run", cmd_run, "fetch, then digest (for a daily schedule)")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--score", type=int, default=None, metavar="N",
                       help="score the N most relevant unscored jobs with shortlist-ai (default: config)")
        p.add_argument("--all", action="store_true", help="every matching job: past the top display.today, and "
                       "those already shown in an earlier digest")
        p.add_argument("--peek", action="store_true", help="don't mark the listed jobs as shown")
        p.add_argument("--limit", type=int, default=None, metavar="N",
                       help="list the top N (default: display.today in the watchlist, 10 unless set)")
        p.add_argument("--format", choices=["md", "json"], default="md")
        p.add_argument("-o", "--out", type=Path)
        p.set_defaults(func=func)

    p = sub.add_parser("score", help="score Today's unscored jobs against your resume, most relevant first")
    p.add_argument("--limit", type=int, default=None, metavar="N", help="stop after N jobs")
    p.add_argument("--show-prompts", action="store_true",
                   help="print the prompts scoring sends (edited ones from scoring.prompts) and stop")
    p.add_argument("--backend", choices=BACKENDS, default=None,
                   help="score with this backend this time (default: scoring.backend in the watchlist)")
    p.add_argument("--model", default=None, help="score with this model this time (default: scoring.model, or "
                   "shortlist-ai's own for the backend)")
    p.add_argument("--rescore", type=float, nargs="?", const=0, default=None, metavar="MIN",
                   help="score again, best first, Today's and queued jobs whose score another model made (the other "
                   "backend, a fallback, or before scores said who made them), scoring at least MIN; no daily limit")
    p.add_argument("--compare", type=int, default=0, metavar="N",
                   help="score N already-scored jobs again (lowest to highest score) with --backend/--model and "
                   "show the old and new scores side by side; nothing is saved")
    p.add_argument("--stored-by", choices=BACKENDS, default=None,
                   help="with --compare: only jobs this backend scored (say, Claude's scores as the reference)")
    p.add_argument("--prompts", type=Path, default=None, metavar="FILE",
                   help="with --compare: edited prompts to try (YAML, name: text, as --show-prompts names them), "
                   "for this run only; the watchlist's prompts and every stored score stay as they are")
    p.add_argument("--batch-api", action="store_true",
                   help="score with Claude through the Message Batches API: half price, results in minutes (at most "
                   "a day); for big runs nobody is waiting on. A stopped run collects its batch next time")
    p.add_argument("--incomplete", action="store_true",
                   help="score again the jobs whose score left requirements unjudged (each counted as not met), "
                   "saved before such a result counted as a failure")
    p.add_argument("--redo-kept", action="store_true",
                   help="score again, with the scorer in use, the jobs whose score --keep-old kept from an earlier "
                   "one (with --batch-api: half price)")
    p.add_argument("--keep-old", nargs="?", const="", default=None, metavar="SCORER",
                   help="after a scorer change that doesn't change what scores mean (say, a prompt reordered for "
                   "caching), keep one earlier scorer's scores as current instead of scoring those jobs again: by "
                   "default the scorer in use just before, or the one whose id (after 'scorer-') is given. Scores "
                   "from other, replaced scorers stay set aside. Scores nothing")
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
                       "Careers, amazon.jobs, Oracle Recruiting Cloud, SmartRecruiters, Avature, iCIMS or Jobvite; "
                       "`add <company> "
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

    p = sub.add_parser("inbox", help="status updates from application emails (confirmations, rejections, interview "
                       "invitations, assignments, offers): proposes each application's new status and note; records "
                       "only what you confirm", description="Read emails about your applications and propose what "
                       "changes: the new status (only ever forward), a dated note quoting the decisive phrase, and "
                       "the next step. Give saved emails (.eml), an mbox export, a folder of them, or - to read one "
                       "email (or an mbox) from stdin. Each is matched to an application by its sender, company, "
                       "req id and title; the ones that match none are listed so you can add the application. "
                       "Nothing is recorded unless you give --apply (asks about each proposal) or --yes.")
    p.add_argument("emails", nargs="*", metavar="FILE | FOLDER | -", help=".eml or .mbox files, folders of them, "
                   "or - for stdin")
    p.add_argument("--apply", action="store_true", help="ask y/n about each proposal and record the ones you accept")
    p.add_argument("--yes", action="store_true", help="record every proposal without asking")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_inbox)

    p = sub.add_parser("suggest", help="companies to watch: those whose jobs came in from alerts, `add` or HN "
                       "posts while their board isn't on the watchlist, most matching jobs first, with the board to "
                       "add",
                       description="Companies to watch. Each job from a job-alert email, `jobwatch add` or a post "
                       "in HN's Who is hiring thread (one that passes your filters) whose company's board isn't on "
                       "the watchlist is noted; the companies with the most jobs that pass your filters (recent "
                       "ones counting more) are listed with their board: the one a job was found on or its HN post "
                       "links to, or one found under the company's name the way `find` looks (once per company, "
                       "kept). --add puts a board on the watchlist (the file is rewritten, the old one kept as "
                       ".bak); --dismiss stops suggesting a company; --rescan notes the HN posts already kept first "
                       "(after changing your filters, or for posts fetched before they were noted).")
    p.add_argument("--add", action="append", metavar="COMPANY", help="watch this company's board (its name as "
                   "listed, or the board's entry); repeatable")
    p.add_argument("--dismiss", action="append", metavar="COMPANY", help="don't suggest this company again; "
                   "repeatable")
    p.add_argument("--limit", type=int, default=None, metavar="N",
                   help="list N (default: suggestions.limit in the watchlist, 10 unless set; 0: all)")
    p.add_argument("--no-lookup", action="store_true", help="look for no boards: list what's known")
    p.add_argument("--rescan", action="store_true", help="first note the companies of the HN posts already kept "
                   "that pass your filters (still open; nothing is read from the web)")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_suggest)

    p = sub.add_parser("applications", aliases=["apps"],help="where each application stands, follow-ups first")
    p.add_argument("--due", action="store_true", help="only applications to follow up on now")
    p.add_argument("-o", "--out", type=Path)
    p.set_defaults(func=cmd_applications)

    p = sub.add_parser("calendar", help="your follow-up days and interviews as an iCalendar (.ics) file to import "
                       "into a calendar app; `jobwatch ui` serves the same feed to subscribe to")
    p.add_argument("-o", "--out", type=Path, help="write the file here (default: print it)")
    p.set_defaults(func=cmd_calendar, read_only=True)

    p = sub.add_parser("quiet", help="applications with no news for a few weeks (see `quiet:` in the watchlist), "
                       "and what to do next: a check-in, or mark it closed. Changes nothing")
    p.add_argument("-o", "--out", type=Path)
    p.set_defaults(func=cmd_quiet)

    p = sub.add_parser("snooze", help="push an application's follow-up out, keeping its stage; noted in its history")
    p.add_argument("keys", nargs="+", metavar="KEY", help="the application: its key, posting id or company")
    p.add_argument("--days", type=int, default=7, help="days from today (default 7)")
    p.set_defaults(func=cmd_snooze)

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
    p.add_argument("question", nargs="*")
    p.add_argument("--job", metavar="KEY", help="ask about this job (its key, or the end of it)")
    p.add_argument("--mock", action="store_true", help="with --job: a mock interview, one question at a time from "
                   "its prep sheet, with feedback and a tightened answer you can save to the sheet")
    p.add_argument("--story", action="store_true", help="with --job: find a story for one of its prep sheet's gaps "
                   "(or the words given): the model asks, you answer, and you save the story it writes up")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("prep", help="a prep sheet for a recruiter call or interview: their asks next to your "
                                    "resume lines, gaps to be honest about, what you sent, questions to expect")
    p.add_argument("key")
    p.add_argument("--format", choices=["md", "html"], default="md",
                   help="html is a standalone page that prints on Letter paper")
    p.add_argument("--open", action="store_true", help="write the HTML page (to -o, or a temp file) and open it "
                                                       "in the browser")
    p.add_argument("--draft", action="store_true", help="also draft likely questions for this role, with answer "
                   "outlines from your stories and resume only, with the chat's model (slow; kept for next time)")
    p.add_argument("--questions", action="store_true", help="also have the chat's model write questions for this "
                   "role from the posting's asks (no resume or stories are sent; kept for next time)")
    p.add_argument("-o", "--out", type=Path)
    p.add_argument("--drill", type=Path, metavar="OUT.mp4", help="make a drill video instead: each question asked, "
                   "a pause to answer it out loud, then the cue words while a second voice gives the sheet's answer "
                   "(needs jobwatch[video]; KEY may be a hand-written prep sheet's .html)")
    p.add_argument("--pause", type=float, default=drill.PAUSE, metavar="SECONDS",
                   help=f"with --drill: seconds to answer each question (default {drill.PAUSE:g})")
    p.add_argument("--no-pause", action="store_true", help="with --drill: no pause, for a quick review")
    p.set_defaults(func=cmd_prep)

    p = sub.add_parser("skills", help="skills your matching jobs ask for that your resume doesn't show, and "
                                      "courses and certifications to learn them")
    p.add_argument("--timeline", choices=config.TIMELINES,
                   help="how soon: week, month, quarter (default, or learning.timeline) or any")
    p.add_argument("--all", action="store_true", help="also skills your resume already shows")
    p.add_argument("-o", "--out", type=Path)
    p.set_defaults(func=cmd_skills)

    p = sub.add_parser("stories", help="check your story file (after editing it by hand) and list its stories")
    p.set_defaults(func=cmd_stories, read_only=True)

    p = sub.add_parser("queue", help="jobs to apply to next: `queue <key>...` adds, `queue` lists")
    p.add_argument("keys", nargs="*")
    p.add_argument("--note", help="e.g. 'ask Ana for a referral first'")
    p.add_argument("-o", "--out", type=Path)
    p.set_defaults(func=cmd_queue)

    p = sub.add_parser("referrals", help="the people you know at companies you're tracking, and whom to ask for "
                       "a referral: `--use NAME` puts someone first, `--skip NAME` never suggests them, "
                       "`--clear NAME` undoes it",
                       description="The connections (see `connections:` in the watchlist) who work at companies "
                       "with a new, queued or open job, closest ties first. --use puts a person ahead of closer "
                       "ties wherever 'You know...' is shown; --skip never suggests them (like connections_skip in "
                       "the watchlist, but changeable here and in the page's Referrals tab); --clear forgets "
                       "either. NAME is a full name or a linkedin.com/in/ link; --note keeps a few words with it.")
    p.add_argument("--use", action="append", metavar="NAME", help="ask this person first; repeatable")
    p.add_argument("--skip", action="append", metavar="NAME", help="never suggest this person; repeatable")
    p.add_argument("--clear", action="append", metavar="NAME", help="forget what was said about this person; "
                   "repeatable")
    p.add_argument("--note", help="e.g. 'doesn't check LinkedIn; reach on WhatsApp' (with --use or --skip)")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_referrals)

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

    p = sub.add_parser("advice", help="how the page's Queue/Skip suggestions fall across Today's jobs: how many "
                       "of each, and which rule said so how often. Read-only")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_advice, read_only=True)

    p = sub.add_parser("company", help="everything tracked at a company, whatever status: its jobs, dates, next "
                       "steps, people you know, and whether its board is watched. Read-only")
    p.add_argument("name", nargs="+", help="the company's name, part of it, or its domain (acme.com)")
    p.add_argument("--all", action="store_true", help="also the open roles your filters leave out (display.company: "
                   "all lists them every time)")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_company, read_only=True)

    p = sub.add_parser("search", help="tracked jobs, whatever status, with the text in their note, next step, "
                       "source, title or company (any case): which application did that recruiter call about? "
                       "Read-only")
    p.add_argument("text", nargs="+", help="what to look for, e.g. a recruiter's name or '$101/hr'")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_search, read_only=True)

    p = sub.add_parser("answers", help="what you answered before on application forms, newest first: questions "
                       "containing every word of QUERY, or without one each question once. Read-only")
    p.add_argument("query", nargs="*", help="words of the question, e.g. notice period")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_answers, read_only=True)

    p = sub.add_parser("profile", help="the roles on a LinkedIn experience page (title, company, dates, location, "
                       "bullets), to see who an interviewer is. Reads the page text you saved or copied "
                       "(linkedin.com/in/<name>/details/experience/); jobwatch never fetches linkedin.com")
    p.add_argument("file", metavar="FILE", help="the page text, saved to a file, or - for stdin")
    p.add_argument("--format", choices=["text", "json", "html"], default="text",
                   help="html is a <ul> to paste into a prep sheet")
    p.set_defaults(func=cmd_profile, needs_config=False)

    p = sub.add_parser("hidden", help="what the filters hide from Today, by filter; name one (e.g. excluded) to "
                       "list its jobs and why. Read-only")
    p.add_argument("kind", nargs="?", choices=KINDS, help="the filter whose jobs to list")
    p.add_argument("--limit", type=int, default=100, help="how many jobs to list (default 100)")
    p.add_argument("--since", metavar="AGO", help="only jobs first seen in the last AGO (6h, 90m, 1d), every "
                   "filter's listed: what a fetch or alert email just brought in")
    p.add_argument("--source", help="only this source's jobs (manual: from alert emails and links; greenhouse, ...)")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_hidden, read_only=True)

    p = sub.add_parser("logos", help="look up the company logos the page shows (from each company's own site), "
                       "for the companies named or every one with an open job")
    p.add_argument("name", nargs="*", help="a company's name as jobwatch shows it")
    p.add_argument("--again", action="store_true", help="look again, even for logos already kept")
    p.set_defaults(func=cmd_logos)
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
