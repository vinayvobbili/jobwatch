"""MCP server exposing jobwatch to an AI assistant: find boards, fetch, digest, and track applications."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__, config, contacts, learn, prep, report, sources, watch
from .score import resume_id
from .store import Store
from .watch import build_digest, fetch_all, load_contacts, queue, save_job, watched_name

server = MCPServer(
    "jobwatch",
    instructions=(
        "Watches company job boards (Greenhouse, Lever, Ashby, Workable, Workday, Eightfold, Jibe, Rippling) from a "
        "watchlist file. "
        "find_board looks up a company's board (by name, or a job or careers page link), add_board puts it on the "
        "watchlist, list_boards and remove_board manage the rest. "
        "fetch_jobs checks every board; get_digest ranks the new matches (optionally fit-scored with shortlist-ai); "
        "get_job gives a posting's full text for tailoring a resume; mark_job records queued/applied/skipped "
        "and later stages (screening, interviewing, offer, rejected, withdrawn) with a next step and follow-up "
        "day; list_queued_jobs "
        "lists the jobs queued to apply to next, with people the user knows there (ask them for a referral "
        "before applying), with warnings to check first (pay, place, flagged text). add_application adds one found "
        "elsewhere (from its link, a LinkedIn link it matches to the company's own board, or pasted text); "
        "list_applications shows where each stands. After the person submits, save_application_package keeps the "
        "resume, cover letter and form answers they sent; get_application_package reads them back before a call or "
        "interview, and get_interview_prep puts the posting, the resume and what was sent on one sheet. "
        "list_skill_gaps lists what the matching jobs ask for that the resume doesn't show, with courses and "
        "certifications to close each gap. check_postings checks that queued jobs and open applications are still "
        "posted. jobwatch never applies to anything by itself: the person reviews and submits every application."
    ),
    version=__version__,
    website_url="https://github.com/vinayvobbili/jobwatch",
)


def _hints(read_only: bool = False, destructive: bool = False, idempotent: bool = False,
           web: bool = False) -> ToolAnnotations:
    """What a tool does, for clients that ask before running one: whether it changes the person's records,
    can overwrite something in them, is safe to repeat, and reads job boards on the internet."""
    return ToolAnnotations(read_only_hint=read_only, destructive_hint=destructive,
                           idempotent_hint=read_only or idempotent, open_world_hint=web)


READ = _hints(read_only=True)

# Kept in step with store.STATUSES and config.TIMELINES (tests check), so clients see the allowed values.
Status = Literal["new", "shown", "queued", "applied", "screening", "interviewing", "offer", "rejected", "withdrawn",
                 "skipped"]
Timeline = Literal["week", "month", "quarter", "any"]

Key = Annotated[str, Field(description=(
    "The job: its key as other tools return it (source:board:posting id, e.g. greenhouse:acme:4012345), just "
    "the posting id, or the company's name when that names one job (the one queued or applied to there). "
    "When it matches several, the error lists their keys."))]
Entry = Annotated[str, Field(description=(
    "The board as source:board, the way find_board and list_boards give it (e.g. greenhouse:stripe)."))]
Day = Field(description="A day: YYYY-MM-DD, or +N for N days from today. An empty string clears it.")


def _open():
    cfg = config.load(os.environ.get("JOBWATCH_CONFIG"))
    return cfg, Store(cfg.state)


def _boards(cfg: config.Config) -> list[dict]:
    return [{"entry": f"{b.source}:{b.board}", "name": b.name, "careers": sources.careers_url(b.source, b.board)}
            for b in cfg.boards]


@server.tool(annotations=_hints(read_only=True, web=True))
def find_board(
    company: Annotated[str, Field(description=(
        "A company name (\"Stripe\"), or a link to one of its job postings or its careers page."))],
) -> list[dict]:
    """Find a company's job board by name or by a job/careers link. Returns entries for the watchlist.
    A guessed board name can belong to another company: check the sample titles before adding one.
    Use it before add_board; to track one job from its link, use add_application instead."""
    return [{"entry": f"{s}:{b}", "open_roles": sources.open_roles(jobs), "careers": sources.careers_url(s, b),
             "sample_titles": [j.title for j in jobs[:5]]}
            for s, b, jobs in sources.probe(company)]


@server.tool(annotations=READ)
def list_boards() -> dict:
    """The boards on the watchlist (entry, display name, careers page) and where the watchlist file is. Use it to
    see what fetch_jobs checks; add_board and remove_board change it."""
    cfg = config.load(os.environ.get("JOBWATCH_CONFIG"))
    return {"watchlist": str(cfg.path), "boards": _boards(cfg)}


@server.tool(annotations=_hints(idempotent=True))
def add_board(
    entry: Entry,
    name: Annotated[str, Field(description=(
        "The company's name as it should show, when the board's own name isn't it (e.g. a Workday tenant id)."))]
    = "",
) -> dict:
    """Add a company's board to the watchlist, so fetch_jobs checks it from now on. Find the entry with
    find_board first and check its sample titles: a guessed board name can belong to another company. Adding
    one that's already there only updates its name. Creates the watchlist when there is none yet. The watchlist
    is rewritten (a copy of the old one is kept as .bak; comments in a hand-written file are not kept)."""
    cfg = config.add_board(config.locate(os.environ.get("JOBWATCH_CONFIG")), entry, name)
    return {"watchlist": str(cfg.path), "boards": _boards(cfg)}


@server.tool(annotations=_hints(destructive=True, idempotent=True))
def remove_board(entry: Entry) -> dict:
    """Take a board off the watchlist, so fetch_jobs stops checking it. Jobs and applications already recorded
    from it are kept. The watchlist is rewritten, with a copy of the old one kept as .bak."""
    cfg = config.remove_board(config.find_config(os.environ.get("JOBWATCH_CONFIG")), entry)
    return {"watchlist": str(cfg.path), "boards": _boards(cfg)}


@server.tool(annotations=_hints(idempotent=True, web=True))
def fetch_jobs() -> str:
    """Check every board in the watchlist and record new roles. Returns counts, and each board that failed to
    load (skipped; the rest are still recorded). Run it before get_digest, which lists the new roles themselves."""
    cfg, store = _open()
    try:
        return report.fetch_summary(fetch_all(cfg, store))
    finally:
        store.close()


@server.tool(annotations=_hints(web=True))
def get_digest(
    score_top: Annotated[int, Field(ge=0, description=(
        "How many of the most relevant unscored jobs to fit-score against the resume with shortlist-ai first. "
        "0 (the default) skips scoring; each job takes minutes on the local backend, so keep it small."))] = 0,
    include_seen: Annotated[bool, Field(description=(
        "Also include jobs already shown in an earlier digest, not just new ones."))] = False,
    limit: Annotated[int, Field(ge=1, description="The most jobs to return, best first.")] = 25,
    mark_shown: Annotated[bool, Field(description=(
        "Mark the returned jobs as shown, so the next digest leaves them out. False to peek without "
        "changing anything."))] = True,
) -> dict:
    """New jobs that pass the watchlist's filters, best first (fit score when scored, then keyword relevance),
    with people the user knows at each company. Call fetch_jobs first to pick up today's postings. This is for
    finding jobs to consider; for jobs already queued use list_queued_jobs, and for applications use
    list_applications."""
    cfg, store = _open()
    try:
        d = build_digest(cfg, store, include_seen=include_seen, score_top=score_top, limit=limit)
        if mark_shown:
            store.set_status([k for e in d.entries for k in e.keys], "shown")
        return json.loads(report.to_json(d))
    finally:
        store.close()


@server.tool(annotations=READ)
def get_job(key: Key) -> dict:
    """Everything about one job, by key or posting id: the full posting text, pay, tracking (status, note, next
    step, follow-up), its fit score against the resume (score, must-haves met, gaps), people the user knows
    there plus a LinkedIn search for a referral, skills it asks for that the resume doesn't show, what was
    sent with the application, and candidate_home: the company's page where the person signs in to see the
    application's status (Workday only; each company has its own account). Use it to tailor a resume or decide
    whether to apply; for only what was sent use get_application_package, and for a call or interview use
    get_interview_prep."""
    cfg, store = _open()
    try:
        job, rec = store.find(key)
        known = load_contacts(cfg)
        fit = store.score(job.key, resume_id(cfg.resume)) if cfg.resume and cfg.resume.is_file() else None
        return {"key": job.key, "company": job.display_company, "title": job.title, "url": job.url,
                "pay": job.pay(), "locations": job.locations, "text": job.to_text(), **rec, "fit": fit,
                "contacts": known.at(job.display_company, job.company) if known else [],
                "find_referral": contacts.linkedin_search(job.display_company),
                "candidate_home": store.candidate_home(job),
                "skill_gaps": learn.job_gaps(cfg, store, job), "package": store.package(job.key).data()}
    finally:
        store.close()


@server.tool(annotations=_hints(destructive=True, idempotent=True))
def mark_job(
    key: Key,
    status: Annotated[Status | None, Field(description=(
        "The new status; omit to keep it and only update the rest. applied only after the person has submitted "
        "the application themselves."))] = None,
    note: Annotated[str | None, Field(description="Replaces the whole note. Prefer add_note for news.")] = None,
    add_note: Annotated[str | None, Field(description=(
        "A line to add to the note, dated today, keeping what's there (\"recruiter replied: onsite only\")."))]
    = None,
    next_step: Annotated[str | None, Field(description=(
        "What happens next (\"recruiter screen Tuesday\"). An empty string clears it."))] = None,
    follow_up: Annotated[str | None, Day] = None,
    applied_on: Annotated[str | None, Field(description="The day applied (YYYY-MM-DD), if not today.")] = None,
    url: Annotated[str | None, Field(description=(
        "The link of a job added by hand: its posting, or the company's careers site once the posting is "
        "gone."))] = None,
    text: Annotated[str | None, Field(description=(
        "The posting's text, pasted (found later, or a copy once the posting is gone), so it can be scored and "
        "prepped."))] = None,
) -> str:
    """Record a job's status: new, shown, queued (to apply to next), applied, screening, interviewing, offer,
    rejected, withdrawn or skipped (omit status to keep it and only update the rest). key is the job's key, its
    posting id, or its company's name when that names one job (the one queued or applied to there); when it
    names several, nothing changes and the error lists them. Use applied only after
    the person has submitted the application themselves. add_note adds a dated line to the note, keeping what's
    there: prefer it for news ("recruiter replied: onsite only"); note replaces the whole note. next_step says
    what happens next ("recruiter screen Tuesday"); follow_up is the day to act (YYYY-MM-DD or +N days);
    applied_on is the day applied, if not today. url sets the link of a job added by hand (its posting, or the
    company's careers site once the posting is gone), and text its posting's text, pasted (found later, or from
    a copy once the posting is gone), so it can be scored and prepped. An empty string clears a field.
    For a job jobwatch doesn't track yet, use add_application."""
    _, store = _open()
    try:
        job, rec = store.find(key)
        if text is not None:
            store.set_description(job.key, text)
        if status:
            store.set_status([job.key], status, note, on=applied_on)
        else:
            store.track(job.key, note=note, applied=applied_on)
        store.track(job.key, next_step=next_step, follow_up=follow_up)
        if url is not None:
            store.set_url(job.key, url)
        if add_note:
            store.add_note(job.key, add_note)
        return f"{job.key}: {status or rec['status']}"
    finally:
        store.close()


@server.tool(annotations=_hints(web=True))
def add_application(
    company: Annotated[str, Field(description="The company; may be left out when url is a job link it can read.")]
    = "",
    title: Annotated[str, Field(description="The job title; may be left out when url is a job link it can read.")]
    = "",
    url: Annotated[str, Field(description=(
        "A link to the job: Greenhouse, Lever, Ashby, Workable, Workday, Rippling or LinkedIn are read in full; "
        "any other link is just kept."))] = "",
    status: Annotated[str, Field(description=(
        "applied (the default; only once the person has applied themselves), queued for one they're "
        "considering, or a later stage such as interviewing."))] = "applied",
    applied_on: Annotated[str, Field(description="The day applied (YYYY-MM-DD), if not today.")] = "",
    note: Annotated[str | None, Field(description="A note: who referred them, how they found it...")] = None,
    next_step: Annotated[str | None, Field(description="What happens next (\"hiring manager call Friday\").")]
    = None,
    follow_up: Annotated[str | None, Day] = None,
    text: Annotated[str, Field(description=(
        "The posting's text, pasted, when the link can't be read, so it can be scored and prepped."))] = "",
) -> str:
    """Add a job jobwatch didn't find (a referral, a recruiter, LinkedIn...), so everything is in one place: an
    application (only after the person has applied themselves), or status queued for one they're considering.
    A url to one job on Greenhouse, Lever, Ashby, Workable, Workday or Rippling is read in full (company and
    title may be left out); so is a LinkedIn job link, which is tracked on the company's own board when the same
    job is found there. Otherwise give company and title, and text (the posting, pasted) so it can be scored.
    For a job jobwatch already tracks (it came from get_digest or get_job), use mark_job instead."""
    cfg, store = _open()
    try:
        job, read = save_job(store, url, company or watched_name(cfg, url), title, text, status=status, note=note,
                             applied=applied_on or None, boards=cfg.boards)
        store.track(job.key, next_step=next_step, follow_up=follow_up)
        return f"{job.key}: {status} ({job.display_company}, {job.title}; " \
               f"{'read from the link' if read else 'text given' if text.strip() else 'title only'})"
    finally:
        store.close()


@server.tool(annotations=READ)
def list_applications(
    due_only: Annotated[bool, Field(description="Only those whose follow-up day has come.")] = False,
) -> list[dict]:
    """Every application (applied or a later stage) and where it stands, follow-ups due soonest first;
    candidate_home is the company's page for checking its status, when it has one (Workday). Use it to see what
    needs a follow-up; for jobs not applied to yet use list_queued_jobs, and for any status use list_jobs."""
    _, store = _open()
    try:
        fields = ("status", "applied_at", "status_at", "next_step", "follow_up", "note", "closed")
        return [{"key": j.key, "company": j.display_company, "title": j.title, "url": j.url, "pay": j.pay(),
                 "candidate_home": store.candidate_home(j), "due": report.due(rec),
                 **{k: rec.get(k) for k in fields}}
                for j, rec in store.applications() if report.due(rec) or not due_only]
    finally:
        store.close()


@server.tool(annotations=READ)
def list_queued_jobs() -> list[dict]:
    """Jobs queued to apply to, oldest first, with fit scores, notes, people the user knows there (ask them for
    a referral before applying) and warnings to check first (pay, place, flagged text). Use it to pick the next
    application; jobs get here through mark_job with status queued. For applications already sent use
    list_applications."""
    cfg, store = _open()
    try:
        return [{"key": e.job.key, "company": e.job.display_company, "title": e.job.title, "url": e.job.url,
                 "pay": e.job.pay(), "fit": e.fit, "contacts": e.contacts, "note": e.record.get("note"),
                 "queued_at": e.record.get("status_at"), "closed": e.record.get("closed"), "warnings": e.warnings}
                for e in queue(cfg, store)]
    finally:
        store.close()


@server.tool(annotations=_hints(idempotent=True, web=True))
def check_postings() -> list[dict]:
    """Check that the postings of queued jobs and open applications still take applications, and record the
    ones that closed or came back. result is open, closed, reopened, or unknown (check it yourself). Run it
    before working through list_queued_jobs, so time isn't spent on closed postings."""
    _, store = _open()
    try:
        return [{"key": c.job.key, "company": c.job.display_company, "title": c.job.title, "url": c.job.url,
                 "result": c.result, "detail": c.detail} for c in watch.check_postings(store)]
    finally:
        store.close()


@server.tool(annotations=READ)
def list_jobs(
    status: Annotated[Status | None, Field(description="Only jobs with this status; omit for all.")] = None,
) -> list[dict]:
    """Tracked jobs with their tracking fields, newest first, including closed postings. A plain list by status
    (e.g. every skipped job); for ranked new jobs use get_digest, for the next to apply to list_queued_jobs, and
    for follow-ups list_applications."""
    _, store = _open()
    try:
        return [{"key": j.key, "company": j.display_company, "title": j.title, "url": j.url, **rec}
                for j, rec in store.jobs((status,) if status else None, include_closed=True)]
    finally:
        store.close()


@server.tool(annotations=_hints(destructive=True))
def save_application_package(
    key: Key,
    files: Annotated[list[str] | None, Field(description=(
        "Local paths to the files exactly as uploaded (resume PDF, cover letter...). Copies are kept."))] = None,
    answers: Annotated[list[dict] | None, Field(description=(
        "The form's questions and the answers given, as [{\"question\": ..., \"answer\": ...}]. Replaces any "
        "saved before."))] = None,
    note: Annotated[str | None, Field(description="A cover letter or message pasted into the form.")] = None,
) -> dict:
    """Keep what was sent with an application, as copies: files (local paths to the resume PDF, cover letter...
    exactly as uploaded), answers (the form's questions and the answers given, [{question, answer}]; replaces
    any saved before) and note (a cover letter or message pasted into the form). Call it once the person has
    submitted, with what they actually sent; get_application_package reads it back."""
    _, store = _open()
    try:
        pkg = store.package(key)
        for f in files or []:
            path = Path(f).expanduser()
            pkg.attach(path.name, path.read_bytes())
        pkg.write(answers=answers, note=note)
        return pkg.data()
    finally:
        store.close()


@server.tool(annotations=READ)
def get_application_package(key: Key) -> dict:
    """What was sent with an application: files kept (with their folder), form answers, note, and the day the
    posting was saved as it read then (posting.md in the folder). Use it to check exactly what was sent; for a
    full prep sheet use get_interview_prep, and for the posting and fit use get_job."""
    _, store = _open()
    try:
        return store.package(key).data()
    finally:
        store.close()


@server.tool(annotations=READ)
def get_interview_prep(key: Key) -> dict:
    """A prep sheet for a recruiter call or interview: stage and next step, each requirement and responsibility
    in the posting next to the closest resume line (quoted, never written), gaps to be honest about, what was
    sent, questions to expect and to ask, and the posting. For an application added by hand, the posting is found
    on a watched board by its requisition id. markdown is the sheet ready to read. Use it before a call;
    get_job and get_application_package give the raw pieces."""
    cfg, store = _open()
    try:
        sheet = prep.build(cfg, store, key)
        return {**prep.to_dict(sheet), "markdown": prep.markdown(sheet)}
    finally:
        store.close()


@server.tool(annotations=READ)
def list_skill_gaps(
    timeline: Annotated[Timeline | None, Field(description=(
        "How soon the person wants to close a gap: week, month, quarter or any. Omit for the watchlist's "
        "learning.timeline."))] = None,
) -> dict:
    """Skills today's matching jobs and the person's applications ask for, most in demand first, each with
    on_resume, how many jobs mention it, how many scored jobs list it as a missing must-have, and ways to learn
    it: curated courses and certifications (official pages, each with a rough time and whether it fits the
    timeline) and searches on Coursera, LinkedIn Learning, edX and nearby colleges. Also fit-score gaps no
    course closes (clearance, citizenship, degree, travel). Recommend only from these links; never suggest
    claiming a skill the resume doesn't show. For one job's gaps use get_job; to prepare for a call use
    get_interview_prep."""
    cfg, store = _open()
    try:
        return learn.to_dict(learn.gather(cfg, store, timeline))
    finally:
        store.close()


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
