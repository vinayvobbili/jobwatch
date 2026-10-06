"""MCP server exposing jobwatch to an AI assistant: find boards, fetch, digest, and track applications."""

from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import config, contacts, learn, prep, report, sources, watch
from .score import resume_id
from .store import Store
from .watch import build_digest, fetch_all, load_contacts, queue, save_job, watched_name

server = MCPServer(
    "jobwatch",
    instructions=(
        "Watches company job boards (Greenhouse, Lever, Ashby, Workable, Workday, Eightfold, Jibe, Rippling) from a "
        "watchlist file. "
        "fetch_jobs checks every board; digest ranks the new matches (optionally fit-scored with shortlist-ai); "
        "job_details gives a posting's full text for tailoring a resume; mark_job records queued/applied/skipped "
        "and later stages (screening, interviewing, offer, rejected, withdrawn) with a next step and follow-up "
        "day; apply_queue "
        "lists the jobs queued to apply to next, with people the user knows there (ask them for a referral "
        "before applying), with warnings to check first (pay, place, flagged text). add_application adds one found "
        "elsewhere (from its link, a LinkedIn link it matches to the company's own board, or pasted text); "
        "applications shows where each stands. After the person submits, save_application_package keeps the "
        "resume, cover letter and form answers they sent; application_package reads them back before a call or "
        "interview, and interview_prep puts the posting, the resume and what was sent on one sheet. skill_gaps "
        "lists what the matching jobs ask for that the resume doesn't show, with courses and certifications to "
        "close each gap. check_postings checks that queued jobs and open applications are still posted. find_board "
        "looks up a company's board (by name, or a job or careers page link) to add to the watchlist. "
        "jobwatch never applies to anything by itself: the person reviews and submits every application."
    ),
)


def _hints(read_only: bool = False, destructive: bool = False, idempotent: bool = False,
           web: bool = False) -> ToolAnnotations:
    """What a tool does, for clients that ask before running one: whether it changes the person's records,
    can overwrite something in them, is safe to repeat, and reads job boards on the internet."""
    return ToolAnnotations(read_only_hint=read_only, destructive_hint=destructive,
                           idempotent_hint=read_only or idempotent, open_world_hint=web)


READ = _hints(read_only=True)


def _open():
    cfg = config.load(os.environ.get("JOBWATCH_CONFIG"))
    return cfg, Store(cfg.state)


@server.tool(annotations=_hints(read_only=True, web=True))
def find_board(company: str) -> list[dict]:
    """Find a company's job board by name or by a job/careers link. Returns entries for the watchlist.
    A guessed board name can belong to another company: check the sample titles before adding one."""
    return [{"entry": f"{s}:{b}", "open_roles": sources.open_roles(jobs), "careers": sources.careers_url(s, b),
             "sample_titles": [j.title for j in jobs[:5]]}
            for s, b, jobs in sources.probe(company)]


@server.tool(annotations=_hints(idempotent=True, web=True))
def fetch_jobs() -> str:
    """Check every board in the watchlist and record new roles."""
    cfg, store = _open()
    try:
        return report.fetch_summary(fetch_all(cfg, store))
    finally:
        store.close()


@server.tool(annotations=_hints(web=True))
def digest(score_top: int = 0, include_seen: bool = False, limit: int = 25, mark_shown: bool = True) -> dict:
    """New jobs that pass the filters, best first. score_top > 0 fit-scores that many of the most relevant
    unscored jobs with shortlist-ai (slow: minutes per job on the local backend)."""
    cfg, store = _open()
    try:
        d = build_digest(cfg, store, include_seen=include_seen, score_top=score_top, limit=limit)
        if mark_shown:
            store.set_status([k for e in d.entries for k in e.keys], "shown")
        return json.loads(report.to_json(d))
    finally:
        store.close()


@server.tool(annotations=READ)
def job_details(key: str) -> dict:
    """Everything about one job, by key or posting id: the full posting text, pay, tracking (status, note, next
    step, follow-up), its fit score against the resume (score, must-haves met, gaps), people the user knows
    there plus a LinkedIn search for a referral, skills it asks for that the resume doesn't show, what was
    sent with the application, and candidate_home: the company's page where the person signs in to see the
    application's status (Workday only; each company has its own account)."""
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
def mark_job(key: str, status: str | None = None, note: str | None = None, add_note: str | None = None,
             next_step: str | None = None, follow_up: str | None = None, applied_on: str | None = None,
             url: str | None = None) -> str:
    """Record a job's status: new, shown, queued (to apply to next), applied, screening, interviewing, offer,
    rejected, withdrawn or skipped (omit status to keep it and only update the rest). Use applied only after
    the person has submitted the application themselves. add_note adds a dated line to the note, keeping what's
    there: prefer it for news ("recruiter replied: onsite only"); note replaces the whole note. next_step says
    what happens next ("recruiter screen Tuesday"); follow_up is the day to act (YYYY-MM-DD or +N days);
    applied_on is the day applied, if not today. url sets the link of a job added by hand (its posting, or the
    company's careers site once the posting is gone). An empty string clears a field."""
    _, store = _open()
    try:
        job, rec = store.find(key)
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
def add_application(company: str = "", title: str = "", url: str = "", status: str = "applied", applied_on: str = "",
                    note: str | None = None, next_step: str | None = None, follow_up: str | None = None,
                    text: str = "") -> str:
    """Add a job jobwatch didn't find (a referral, a recruiter, LinkedIn...), so everything is in one place: an
    application (only after the person has applied themselves), or status queued for one they're considering.
    A url to one job on Greenhouse, Lever, Ashby, Workable, Workday or Rippling is read in full (company and
    title may be left out); so is a LinkedIn job link, which is tracked on the company's own board when the same
    job is found there. Otherwise give company and title, and text (the posting, pasted) so it can be scored."""
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
def applications(due_only: bool = False) -> list[dict]:
    """Every application and where it stands, follow-ups due soonest first; candidate_home is the company's
    page for checking its status, when it has one (Workday). due_only: only those whose follow-up day has come."""
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
def apply_queue() -> list[dict]:
    """Jobs queued to apply to, oldest first, with fit scores, notes and people the user knows there."""
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
    ones that closed or came back. result is open, closed, reopened, or unknown (check it yourself)."""
    _, store = _open()
    try:
        return [{"key": c.job.key, "company": c.job.display_company, "title": c.job.title, "url": c.job.url,
                 "result": c.result, "detail": c.detail} for c in watch.check_postings(store)]
    finally:
        store.close()


@server.tool(annotations=READ)
def list_jobs(status: str | None = None) -> list[dict]:
    """Tracked jobs, optionally only one status (e.g. applied), newest first."""
    _, store = _open()
    try:
        return [{"key": j.key, "company": j.display_company, "title": j.title, "url": j.url, **rec}
                for j, rec in store.jobs((status,) if status else None, include_closed=True)]
    finally:
        store.close()


@server.tool(annotations=_hints(destructive=True))
def save_application_package(key: str, files: list[str] | None = None, answers: list[dict] | None = None,
                             note: str | None = None) -> dict:
    """Keep what was sent with an application, as copies: files (local paths to the resume PDF, cover letter...
    exactly as uploaded), answers (the form's questions and the answers given, [{question, answer}]; replaces
    any saved before) and note (a cover letter or message pasted into the form). Call it once the person has
    submitted, with what they actually sent."""
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
def application_package(key: str) -> dict:
    """What was sent with an application: files kept (with their folder), form answers, note, and the day the
    posting was saved as it read then (posting.md in the folder). Use it to prepare for a call or interview."""
    _, store = _open()
    try:
        return store.package(key).data()
    finally:
        store.close()


@server.tool(annotations=READ)
def interview_prep(key: str) -> dict:
    """A prep sheet for a recruiter call or interview: stage and next step, each requirement and responsibility
    in the posting next to the closest resume line (quoted, never written), gaps to be honest about, what was
    sent, questions to expect and to ask, and the posting. For an application added by hand, the posting is found
    on a watched board by its requisition id. markdown is the sheet ready to read."""
    cfg, store = _open()
    try:
        sheet = prep.build(cfg, store, key)
        return {**prep.to_dict(sheet), "markdown": prep.markdown(sheet)}
    finally:
        store.close()


@server.tool(annotations=READ)
def skill_gaps(timeline: str | None = None) -> dict:
    """Skills today's matching jobs and the person's applications ask for, most in demand first, each with
    on_resume, how many jobs mention it, how many scored jobs list it as a missing must-have, and ways to learn
    it: curated courses and certifications (official pages, each with a rough time and whether it fits the
    timeline) and searches on Coursera, LinkedIn Learning, edX and nearby colleges. Also fit-score gaps no
    course closes (clearance, citizenship, degree, travel). timeline: week, month, quarter or any (default: the
    watchlist's learning.timeline). Recommend only from these links; never suggest claiming a skill the resume
    doesn't show."""
    cfg, store = _open()
    try:
        return learn.to_dict(learn.gather(cfg, store, timeline))
    finally:
        store.close()


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
