"""MCP server exposing jobwatch to an AI assistant: find boards, fetch, digest, and track applications."""

from __future__ import annotations

import importlib.util
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import (
    __version__,
    alerts,
    answers,
    company,
    comps,
    config,
    contacts,
    dupes,
    inbox,
    learn,
    levels,
    prep,
    profile,
    quiet,
    referrals,
    report,
    sources,
    stories,
    storyfind,
    suggest,
    watch,
)
from .score import resume_id
from .store import Store
from .watch import build_digest, fetch_all, load_contacts, queue, save_job, set_link, unscored_reason, watched_name

server = MCPServer(
    "jobwatch",
    instructions=(
        "Watches company job boards (Greenhouse, Lever, Ashby, Workable, Workday, Eightfold, Jibe, Rippling, "
        "Google Careers, Amazon, Oracle Recruiting Cloud, SmartRecruiters, Avature, iCIMS, Jobvite) and Hacker "
        "News' monthly \"Ask HN: Who is hiring?\" thread (one job per company's post) from a watchlist file. "
        "find_board looks up a company's board (by name, or a job or careers page link), add_board puts it on the "
        "watchlist, list_boards and remove_board manage the rest. list_suggested_boards lists companies whose jobs "
        "keep coming in from alerts, add_application or HN posts while their board isn't watched, with what to pass "
        "add_board; dismiss_suggested_board stops suggesting one. "
        "fetch_jobs checks every board; get_digest ranks the new matches (optionally fit-scored with shortlist-ai); "
        "get_job gives a posting's full text for tailoring a resume; mark_job records queued/applied/skipped "
        "and later stages (screening, interviewing, offer, rejected, withdrawn) with a next step and follow-up "
        "day; list_queued_jobs "
        "lists the jobs queued to apply to next, with people the user knows there (ask them for a referral "
        "before applying), with warnings to check first (pay, place, flagged text). add_application adds one found "
        "elsewhere (from its link, a LinkedIn link it matches to the company's own board, or pasted text); "
        "import_job_alerts takes job-alert emails (LinkedIn, Built In, Indeed and others) that you fetched with a "
        "mail connector, as raw messages or HTML bodies, and tracks their jobs (matched to the company's own board "
        "where it can) as new jobs for get_digest; it never needs the person's mail password. "
        "read_status_emails reads emails about the person's applications (confirmations, rejections, interview "
        "invitations, assignments, offers, recruiter replies) and proposes each one's new status and a dated note: "
        "present the proposals and call mark_job only for the ones the person confirms. "
        "list_applications shows where each stands; get_comps puts the live ones side by side (pay, fit, stage), "
        "and set_comp keeps what a recruiter said about pay (base, bonus, equity, what was asked and offered), "
        "set_company_health the company's funding, layoffs and rating that you looked up. After the person submits, "
        "save_application_package keeps the resume, cover letter and form answers they sent; "
        "get_application_package reads them back before a call or "
        "interview, find_past_answers finds what they answered before to a form question (\"notice period\") "
        "across all of them, and get_interview_prep puts the posting, the resume and what was sent on one sheet, with "
        "story_gaps: what a story from the person's own past would help with. Interview them about one, and "
        "save_story keeps what they confirm in their story file for drafted answers. "
        "list_skill_gaps lists what the matching jobs ask for that the resume doesn't show, with courses and "
        "certifications to close each gap. check_postings checks that queued jobs and open applications are still "
        "posted. The same opening can be tracked twice (an application added by hand, then the job again from an "
        "alert under another title): before drafting a referral request or an application, check get_job's "
        "duplicate_of and list_queued_jobs' warnings; strong means the same req or posting id (already applied: "
        "don't apply or ask for a referral again), otherwise it's the same title only (check it's a different "
        "opening). find_duplicates lists such pairs already in the store. get_company looks one company up by name "
        "or domain across every status, closed postings too: its jobs, people the user knows there, and whether its "
        "board is watched. rate_contact records whom the user wants asked for referrals first (use) or never "
        "(skip), with a short note, when they say so about someone in a contacts list. read_profile turns the text "
        "of a LinkedIn experience page that the person pasted or copied into a list of roles (who the interviewer "
        "is); it only parses that text, jobwatch never fetches linkedin.com. "
        "jobwatch never applies to anything by itself: the person reviews and submits every application."
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


_STARTED = time.time()


def _code_dirs() -> list[Path]:
    """Where the code this server runs lives: jobwatch, and shortlist-ai's scorer when it's installed."""
    dirs = [Path(__file__).parent]
    if spec := importlib.util.find_spec("shortlist_ai"):
        dirs += [Path(p) for p in spec.submodule_search_locations or ()]
    return dirs


def _changed_since_start() -> str | None:
    """A module changed (updated or edited) after this server started, when one has: the server still runs the
    old code, so its tools can fail or answer wrongly until it starts again."""
    for d in _code_dirs():
        for f in d.glob("*.py"):
            if f.stat().st_mtime > _STARTED:
                return f"{d.name}/{f.name}"
    return None


def _config() -> config.Config:
    if changed := _changed_since_start():  # a ToolError, so the model reads what to do
        raise ToolError(f"jobwatch's code changed after this MCP server started ({changed}), so it would run "
                        "the old code: restart the server (in Claude Code: /mcp, jobwatch, Reconnect)")
    return config.load(os.environ.get("JOBWATCH_CONFIG"))


def _open():
    cfg = _config()
    return cfg, Store(cfg.state)


def _pay(result, job) -> dict:
    """expected_pay, only when the watchlist turns Levels.fyi pay on (see levels.py)."""
    return {} if result is None else {"expected_pay": levels.as_dict(result, job)}


def _boards(cfg: config.Config) -> list[dict]:
    return [{"entry": b.entry, "name": b.name, "careers": sources.careers_url(b.source, b.board),
             "careers_link": b.careers} for b in cfg.boards]


@server.tool(annotations=_hints(read_only=True, web=True))
def find_board(
    company: Annotated[str, Field(description=(
        "A company name (\"Stripe\"), or a link to one of its job postings or its careers page."))],
) -> list[dict]:
    """Find a company's job board by name or by a job/careers link. Returns entries for the watchlist.
    A guessed board name can belong to another company: check the sample titles before adding one.
    Google (with YouTube and DeepMind) is one board, google:google (its US roles; google:google/any for all).
    So is Amazon (with AWS), amazon:amazon (its US roles; amazon:amazon/any for all).
    A Workday, Oracle Recruiting Cloud or Jibe board that isn't found by name is found from a link to a job on it.
    An Avature careers portal is host/portal (avature:careers.initech.example/careers); a name finds one only at
    name.avature.net/careers, so give a job link from any other.
    An iCIMS careers site is icims:<company> (careers-<company>.icims.com), or the whole host for another
    (icims:jobs-acme.icims.com); a name finds one at careers-<name>.icims.com.
    A Jobvite careers site is jobvite:<company> (jobs.jobvite.com/<company>); a name finds one there.
    Hacker News' "Who is hiring?" thread is one board, hn:whoishiring (hn:whoishiring/N: the last N months'),
    found by "Hacker News" or the news.ycombinator.com/submitted?id=whoishiring link.
    Use it before add_board; to track one job from its link, use add_application instead."""
    return [{"entry": f"{s}:{b}", "open_roles": sources.open_roles(jobs), "careers": sources.careers_url(s, b),
             "sample_titles": [j.title for j in jobs[:5]]}
            for s, b, jobs in sources.probe(company)]


@server.tool(annotations=READ)
def list_boards() -> dict:
    """The boards on the watchlist (entry, display name, careers: the board's own page, careers_link: the
    company's own careers site when the watchlist gives one) and where the watchlist file is. Use it to see what
    fetch_jobs checks; add_board and remove_board change it."""
    cfg = _config()
    return {"watchlist": str(cfg.path), "boards": _boards(cfg)}


@server.tool(annotations=_hints(idempotent=True))
def add_board(
    entry: Entry,
    name: Annotated[str, Field(description=(
        "The company's name as it should show, when the board's own name isn't it (e.g. a Workday tenant id)."))]
    = "",
    careers: Annotated[str, Field(description=(
        "The company's own careers site (https://...), for a board whose hosted job pages are offline (fetch_jobs "
        "warns about those): its jobs then link there."))] = "",
) -> dict:
    """Add a company's board to the watchlist, so fetch_jobs checks it from now on. Find the entry with
    find_board first and check its sample titles: a guessed board name can belong to another company
    (list_suggested_boards gives entries for companies whose jobs keep coming in from alerts or HN). Adding
    one that's already there only updates its name and careers link. For Google, leave name empty: each role
    keeps its own employer (Google, YouTube, DeepMind). Creates the watchlist when there is none yet. The
    watchlist is rewritten (a copy of the old one is kept as .bak; comments in a hand-written file are not
    kept)."""
    cfg = config.add_board(config.locate(os.environ.get("JOBWATCH_CONFIG")), entry, name, careers)
    return {"watchlist": str(cfg.path), "boards": _boards(cfg)}


@server.tool(annotations=_hints(destructive=True, idempotent=True))
def remove_board(entry: Entry) -> dict:
    """Take a board off the watchlist, so fetch_jobs stops checking it. Jobs and applications already recorded
    from it are kept. The watchlist is rewritten, with a copy of the old one kept as .bak."""
    cfg = config.remove_board(config.find_config(os.environ.get("JOBWATCH_CONFIG")), entry)
    return {"watchlist": str(cfg.path), "boards": _boards(cfg)}


@server.tool(annotations=_hints(idempotent=True, web=True))
def list_suggested_boards(
    limit: Annotated[int | None, Field(ge=1, description=(
        "The most companies to return, best first. Omit for the watchlist's suggestions.limit (10 unless "
        "set)."))] = None,
    look_up_boards: Annotated[bool, Field(description=(
        "Look for the board of each listed company that hasn't been looked for yet, the way find_board does "
        "(once per company; what's found is kept). False makes no requests."))] = True,
    rescan: Annotated[bool, Field(description=(
        "First note the companies of the HN posts already kept (still open) that pass the filters: after the "
        "filters change, or for posts fetched before they were noted. Reads nothing from the web; safe to "
        "repeat."))] = False,
) -> list[dict]:
    """Companies to watch: those whose jobs came in from job-alert emails (import_job_alerts), add_application or
    posts in HN's Who is hiring thread (fetch_jobs, when it's watched) while their board isn't on the watchlist,
    ranked by how many of their jobs pass the watchlist's filters, recent ones counting more. Each: company,
    matching_jobs, last_seen, board (source:board, or null), board_found (posting: one of its jobs is on that
    board, or its HN post links to it; name: found under its name, so check with
    find_board's sample titles that it's theirs), careers, sample_titles, and add_board: the arguments to pass to
    add_board to watch it (null when no board was found: find_board with a link to its careers page may find
    one). dismiss_suggested_board stops suggesting one. rescan picks up HN posts kept before (see its
    description). Suggest; let the person decide which to add."""
    cfg, store = _open()
    try:
        if rescan:
            suggest.rescan(cfg, store)
        return [s.to_dict() for s in suggest.suggestions(cfg, store, limit=limit, look=look_up_boards)]
    finally:
        store.close()


@server.tool(annotations=_hints(idempotent=True))
def dismiss_suggested_board(
    company: Annotated[str, Field(description=(
        "The company as list_suggested_boards names it (any case; Inc, LLC and the like aside), or its board."))],
) -> str:
    """Stop suggesting a company in list_suggested_boards, when the person doesn't want to watch it. Its jobs
    stay tracked. To watch one instead, use add_board with its add_board arguments."""
    _, store = _open()
    try:
        return f"{suggest.dismiss(store, company).name} won't be suggested again."
    finally:
        store.close()


@server.tool(annotations=_hints(idempotent=True, web=True))
def fetch_jobs() -> str:
    """Check every board in the watchlist and record new roles. Returns counts, each board that failed to load
    (skipped; the rest are still recorded), and warnings: a board whose hosted job pages are offline while its
    jobs are still listed, which needs the company's careers site (add_board with careers). Run it before
    get_digest, which lists the new roles themselves."""
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
    limit: Annotated[int | None, Field(ge=1, description=(
        "The most jobs to return, best first. Default: the watchlist's display.today (10 unless set; 25 when "
        "it's 0, for every match)."))] = None,
    mark_shown: Annotated[bool, Field(description=(
        "Mark the returned jobs as shown, so the next digest leaves them out. False to peek without "
        "changing anything."))] = True,
) -> dict:
    """New jobs that pass the watchlist's filters, best first (fit score when scored, then keyword relevance),
    with people the user knows at each company. Call fetch_jobs first to pick up today's postings. This is for
    finding jobs to consider; for jobs already queued use list_queued_jobs, and for applications use
    list_applications. total is how many matched before the limit (jobs left out stay new for the next
    digest). not_scored, when set, says why a job is never fit-scored (a Hacker News post listing several
    roles). pace, unless the user turned it off: applications sent today against how many they aim for a day
    (daily) and the most (max); once met, suggest the rest wait for tomorrow, but never refuse to help."""
    cfg, store = _open()
    try:
        d = build_digest(cfg, store, include_seen=include_seen, score_top=score_top,
                         limit=limit or cfg.today or 25)
        if mark_shown:
            store.set_status([k for e in d.entries for k in e.keys], "shown")
        return {**json.loads(report.to_json(d)), "pace": watch.pace(cfg, store)}
    finally:
        store.close()


@server.tool(annotations=READ)
def get_job(key: Key) -> dict:
    """Everything about one job, by key or posting id: the full posting text, pay, tracking (status, note, next
    step, follow-up), its fit score against the resume (score, must-haves met, gaps, and requirements: each
    requirement with its verdict, met/partial/not_met, and the resume's words backing it; scores saved
    before jobwatch kept these have none), people the user knows there plus a LinkedIn search for a
    referral, skills it asks for that the resume doesn't show, what was
    sent with the application, and candidate_home: the company's page where the person signs in to see the
    application's status (Workday only; each company has its own account). link_note, when set, says the board's
    hosted job pages are offline and where to apply instead (url is then the company's careers site, when the
    watchlist gives one). With no fit score, unscored_reason
    says why ({code, text}: no_text means it needs its posting, a link via mark_job(url=) or the text pasted;
    queued means it's in the page's background scorer's line; many_roles, a post listing several roles, is never
    scored). duplicate_of is the job already applied to,
    queued or skipped that this one is (maybe) the same opening as: key, title, status, date, why, strong (a
    shared req or posting id; false: the same title only, so check it's a different opening), reposted, and
    text, the warning to heed; null when there's none. Check it before drafting a referral request or an
    application. Use it to tailor a resume or decide whether to apply; for only what was sent use
    get_application_package, and for a call or interview use get_interview_prep."""
    cfg, store = _open()
    try:
        job, rec = store.find(key)
        known = load_contacts(cfg)
        fit = store.score(job.key, resume_id(cfg.resume, cfg.prompts)) if cfg.resume and cfg.resume.is_file() else None
        same = dupes.check(store, job.key)
        return {"key": job.key, "company": job.display_company, "title": job.title, "url": job.url,
                "link_note": job.link_note or None,
                "pay": job.pay(), "locations": job.places, "text": job.to_text(), **rec,
                "duplicate_of": same.to_dict() if same else None, "fit": fit,
                "unscored_reason": None if fit else unscored_reason(cfg, store, job),
                "contacts": known.at(job.display_company, job.company) if known else [],
                "find_referral": contacts.linkedin_search(job.display_company),
                "candidate_home": store.candidate_home(job),
                "skill_gaps": learn.job_gaps(cfg, store, job), "package": store.package(job.key).data(),
                **_pay(levels.for_one_job(cfg, store, job), job)}
    finally:
        store.close()


@server.tool(annotations=_hints(destructive=True, idempotent=True, web=True))
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
    company's careers site once the posting is gone); when the job has no posting text and the link is to one
    job on a supported board, the posting is read from it (text, pay, places), so it can be scored. text sets
    its posting's text, pasted (found later, or from a copy once the posting is gone), so it can be scored and
    prepped. An empty string clears a field. For a job jobwatch doesn't track yet, use add_application.
    Queuing a job that's (maybe) the same opening as one applied to or queued still queues it, and the reply
    ends with the warning: tell the person."""
    _, store = _open()
    said = ""
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
            said = f" ({set_link(store, job.key, url)})"
        if add_note:
            store.add_note(job.key, add_note)
        same = dupes.check(store, job.key) if status == "queued" else None
        return f"{job.key}: {status or rec['status']}{said}" + (f". Check: {same.line}" if same else "")
    finally:
        store.close()


@server.tool(annotations=_hints(web=True))
def add_application(
    company: Annotated[str, Field(description="The company; may be left out when url is a job link it can read.")]
    = "",
    title: Annotated[str, Field(description="The job title; may be left out when url is a job link it can read.")]
    = "",
    url: Annotated[str, Field(description=(
        "A link to the job: Greenhouse, Lever, Ashby, Workable, Workday, Rippling, Google Careers, amazon.jobs, "
        "Oracle Recruiting Cloud, SmartRecruiters, Avature, iCIMS, Jobvite or LinkedIn are read in full; "
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
    A url to one job on Greenhouse, Lever, Ashby, Workable, Workday, Rippling, Google Careers (a
    .../jobs/results/<id> link), amazon.jobs (a .../jobs/<id> link), Oracle Recruiting Cloud (an
    ...oraclecloud.com/.../sites/<site>/job/<id> link), SmartRecruiters (a jobs.smartrecruiters.com/<company>/<id>
    link), an Avature portal (a .../JobDetail/<title>/<id> link) or
    iCIMS (a .../jobs/<id>/<title>/job link) or Jobvite (a jobs.jobvite.com/<company>/job/<id> link) is read in
    full (company and
    title may be left out). A LinkedIn job link is never read (LinkedIn's robots.txt disallows it): give company
    and title with it (and text to score it), and it's tracked on the company's own board when the same job is
    found there. Otherwise give company and title, and text (the posting, pasted) so it can be scored.
    For a job jobwatch already tracks (it came from get_digest or get_job), use mark_job instead; for the jobs in
    job-alert emails, import_job_alerts. When it's (maybe) the same opening as one already applied to, queued or
    skipped, the reply ends with that warning: tell the person."""
    cfg, store = _open()
    try:
        job, read = save_job(store, url, company or watched_name(cfg, url), title, text, status=status, note=note,
                             applied=applied_on or None, boards=cfg.boards)
        store.track(job.key, next_step=next_step, follow_up=follow_up)
        same = dupes.check(store, job.key)
        return f"{job.key}: {status} ({job.display_company}, {job.title}; " \
               f"{'read from the link' if read else 'text given' if text.strip() else 'title only'})" + \
               (f". Check: {same.line}" if same else "")
    finally:
        store.close()


@server.tool(annotations=_hints(idempotent=True, web=True))
def import_job_alerts(
    emails: Annotated[list[str], Field(description=(
        "The alert emails, one string each: the raw message (RFC822, as a mail connector's raw format gives it, "
        "base64url-encoded as from Gmail's API is fine too; best, since it names the sender) or just its HTML or "
        "plain-text body."))],
    follow_links: Annotated[bool, Field(description=(
        "Look for each job that passes the filters on the company's own board, and read links robots.txt "
        "allows. False tracks each job as the email has it, with no requests."))] = True,
    dry_run: Annotated[bool, Field(description="Say what would be tracked, and record nothing.")] = False,
) -> dict:
    """Track the jobs in job-alert emails (LinkedIn, Built In, Indeed; other senders with a generic reader).
    Search the person's mail for them first, e.g. from:jobalerts-noreply@linkedin.com, from:builtin.com,
    from:jobalert.indeed.com, from:match.indeed.com (Indeed's job matches, as its app notifies them), and pass
    each message in; jobwatch never needs a mail password. Links lose their
    tracking parameters. Each job whose title, place and pay pass the watchlist's filters is looked for on the
    company's own board (a link to a supported board is read from there); job sites' pages are read only when
    their robots.txt allows (LinkedIn's and Indeed's don't, so the email's details are used). Jobs already tracked
    are left alone (known); new ones show up in get_digest, with via saying where they came from. Returns
    counts and each job: key, result (new, known, duplicate: twice in these emails), how (board, posting, page or
    email), filtered (why the filters leave it out of the digest, or null) and duplicate_of (the job applied to,
    queued or skipped that it's maybe the same opening as, as get_job gives it, or null). For emails about the
    person's applications (confirmations, rejections, interviews), use read_status_emails."""
    cfg, store = _open()
    try:
        r = alerts.intake(cfg, store, [alerts.message(e) for e in emails if e.strip()], follow=follow_links,
                          dry_run=dry_run)
        return alerts.to_dict(r)
    finally:
        store.close()


@server.tool(annotations=READ)
def read_status_emails(
    emails: Annotated[list[str], Field(description=(
        "The emails about applications, one string each: the raw message (RFC822, as a mail connector's raw format "
        "gives it, base64url-encoded as from Gmail's API is fine too; best, since it names the sender and date) or "
        "just its HTML or plain-text body."))],
) -> dict:
    """Read emails about the person's applications (a "thank you for applying" confirmation, a rejection, an
    interview invitation or scheduling link, a take-home assignment, an offer, a recruiter's reply) and PROPOSE
    what changes; nothing is recorded. Search the person's mail first (e.g. their applications' companies, or
    "thank you for applying", "your application", "interview"), and pass each message in; jobwatch never needs a
    mail password. Present the proposals to the person and only call mark_job for the ones they confirm, with
    the proposal's mark_job arguments (status, add_note, next_step, follow_up). Returns proposals (key, company,
    title, current_status, suggested_status (null: only a note), kind, note, next_step, email (date, sender,
    subject), confidence, why, mark_job), unmatched (emails about no tracked application, with the company
    guessed: offer to add it with add_application, or say it's an application it can't tell apart), nothing_new
    (emails that add nothing: already recorded or already past that stage) and other (the count of emails that
    aren't about an application). A status only moves forward: a late confirmation for an application already
    interviewing is not a proposal. For job-alert emails use import_job_alerts."""
    _, store = _open()
    try:
        return inbox.to_dict(inbox.propose(store, [alerts.message(e) for e in emails if e.strip()]))
    finally:
        store.close()


@server.tool(annotations=READ)
def list_applications(
    due_only: Annotated[bool, Field(description="Only those whose follow-up day has come.")] = False,
) -> list[dict]:
    """Every application (applied or a later stage) and where it stands, follow-ups due soonest first;
    candidate_home is the company's page for checking its status, when it has one (Workday). Use it to see what
    needs a follow-up; for jobs not applied to yet use list_queued_jobs, and for any status use list_jobs.
    quiet is set on an application with no stage change or note for weeks (the watchlist's quiet: days per
    stage): days, since, posting_open, long (quiet so long that it sorts below the fresher ones), move (nudge:
    a short check-in to the recruiter or a contact, or close: likely closed, ask the person whether to mark it
    rejected or withdrawn; never change it on your own), advice, and contacts the person knows there."""
    cfg, store = _open()
    try:
        fields = ("status", "applied_at", "status_at", "next_step", "follow_up", "note", "closed")
        rows = store.applications()
        found = quiet.find(rows, cfg.quiet, known=watch.load_contacts(cfg))
        return [{"key": j.key, "company": j.display_company, "title": j.title, "url": j.url, "pay": j.pay(),
                 "candidate_home": store.candidate_home(j), "due": report.due(rec), "quiet": found.get(j.key),
                 **{k: rec.get(k) for k in fields}}
                for j, rec in quiet.order(rows, found) if report.due(rec) or not due_only]
    finally:
        store.close()


@server.tool(annotations=READ)
def get_comps(
    stages: Annotated[list[Literal["applied", "screening", "interviewing", "offer"]] | None, Field(description=(
        "Which stages to compare; default screening, interviewing and offer. Add applied for the ones still waiting."
    ))] = None,
    keys: Annotated[list[str] | None, Field(description=(
        "Compare just these jobs (each as in get_job's key), whatever their stage. Overrides stages."))] = None,
    companies: Annotated[list[str] | None, Field(description=(
        "Add these companies' health as columns of their own, even ones with no job tracked (Levels.fyi-style "
        "company comparison). Overrides stages."))] = None,
) -> dict:
    """Open applications side by side, to compare offers and processes: for each, its stage, applied day, next
    step and follow-up, pay as posted, places, fit score (must-haves met, top gaps), people the person knows
    there, and the compensation details they were told (base, bonus, equity, sign-on, asked, offered, note; set
    them with set_comp), and the company's health (set it with set_company_health; stale when older than 90
    days: research it again). best says which opportunity is highest in posted pay, base, offered and fit.
    suggestion ranks them by rules (career value from the company's kind and the job's role, pay against the
    person's target, fit, how far along, company health) with the weights, each part's score and input, and a
    reason: explain it, and say what is missing (no health kept, no kind or role, no pay known) rather than
    guessing. Use it when the person asks how their opportunities compare; for one application's status use
    list_applications."""
    cfg, store = _open()
    try:
        try:
            return comps.view(cfg, store, tuple(stages or comps.LIVE), keys, companies)
        except (KeyError, ValueError) as e:
            raise ToolError(str(e.args[0] if isinstance(e, KeyError) else e)) from None
    finally:
        store.close()


@server.tool(annotations=_hints(destructive=True, idempotent=True))
def set_comp(
    key: Key,
    base: Annotated[str | None, Field(description=(
        "The base salary (range) the recruiter gave, as said: \"165-195K\". An empty string clears it."))] = None,
    bonus: Annotated[str | None, Field(description="Bonus, as said (\"10% target\"). Empty clears it.")] = None,
    equity: Annotated[str | None, Field(description="Equity, as said (\"40K RSUs over 4 years\"). Empty clears it."
                                        )] = None,
    signon: Annotated[str | None, Field(description="Sign-on bonus, as said. Empty clears it.")] = None,
    asked: Annotated[str | None, Field(description="What the person asked for (\"210-230K\"). Empty clears it."
                                       )] = None,
    offered: Annotated[str | None, Field(description="What they offered. Empty clears it.")] = None,
    note: Annotated[str | None, Field(description=(
        "A few words (\"195K most likely their max\"). Replaces the old note. Empty clears it."))] = None,
    role: Annotated[Literal["product", "customer", "internal", ""] | None, Field(description=(
        "What the job is, for its career value: product (builds the company's own product), customer "
        "(forward-deployed, solutions, customer-facing engineering) or internal (builds internal tools or "
        "platforms for the business). Empty clears it."))] = None,
    career_note: Annotated[str | None, Field(description=(
        "A few words on its career value (\"observability product, staff IC\"). Empty clears it."))] = None,
) -> dict:
    """Keep what a recruiter told the person about pay for a job, so get_comps can put it next to the others, and
    what the job is for their career (role, career_note). Only the
    fields given change; an empty string clears one. Write amounts the way they were said ("165-195K",
    "$215,000"): the first amount found is read to mark the highest. Returns what is kept for the job."""
    _, store = _open()
    try:
        try:
            job, _ = store.find(key)
            store.set_comp(job.key, base=base, bonus=bonus, equity=equity, signon=signon, asked=asked,
                           offered=offered, note=note, role=role, career_note=career_note)
        except (KeyError, ValueError) as e:
            raise ToolError(str(e.args[0] if isinstance(e, KeyError) else e)) from None
        return {"key": job.key, "company": job.display_company, "title": job.title, "comp": store.comp(job.key)}
    finally:
        store.close()


@server.tool(annotations=_hints(destructive=True, idempotent=True))
def set_company_health(
    company: Annotated[str, Field(description="The company's name, or the key of one of its jobs.")],
    listing: Annotated[Literal["public", "private", ""] | None, Field(description=(
        "public or private. An empty string clears it."))] = None,
    kind: Annotated[Literal["tech", "consulting", "enterprise", ""] | None, Field(description=(
        "What kind of company: tech (software, security or AI product company), consulting, or enterprise (a "
        "non-tech business whose IT builds for itself: bank, insurer, real-estate finance). The career part of "
        "get_comps reads it. Empty clears it."))] = None,
    stage: Annotated[str | None, Field(description=(
        "Stage and last round, as found (\"Series B, $50M, 2025\")."))] = None,
    raised: Annotated[str | None, Field(description="Total raised (\"$80M\"). Under $20M for a private company counts "
                                        "as thin funding.")] = None,
    revenue: Annotated[str | None, Field(description="Revenue or growth, if known.")] = None,
    headcount: Annotated[str | None, Field(description="Headcount trend (\"growing\", \"shrinking\").")] = None,
    layoffs: Annotated[str | None, Field(description=(
        "Recent layoffs, with when (\"10% in March 2026\"), or \"none\" when you found none."))] = None,
    rating: Annotated[str | None, Field(description="Employee rating (\"4.1 Glassdoor\").")] = None,
    risk: Annotated[str | None, Field(description="A short risk note; any text counts against the company.")] = None,
    sources: Annotated[str | None, Field(description="The links these came from, separated by spaces.")] = None,
    as_of: Annotated[str | None, Field(description=(
        "The day the facts were read, YYYY-MM-DD; today when left out. Older than 90 days shows as stale."))] = None,
) -> dict:
    """Keep what is known of a company's health, per company, for get_comps to show and weigh. Search the web
    yourself (jobwatch fetches none of these sites) and record what you found with its source links and the day;
    say so when you could not find something, and leave that field out rather than guessing. Only the fields
    given change; an empty string clears one. Returns what is kept, with how old it is."""
    _, store = _open()
    try:
        try:
            name = comps.company_of(store, company)
            store.set_health(name, listing=listing, stage=stage, raised=raised, revenue=revenue, headcount=headcount,
                             layoffs=layoffs, rating=rating, risk=risk, sources=sources, as_of=as_of, kind=kind)
        except ValueError as e:
            raise ToolError(str(e)) from None
        return {"company": name, "health": comps.aged(store.health(name))}
    finally:
        store.close()


@server.tool(annotations=READ)
def list_queued_jobs() -> list[dict]:
    """Jobs queued to apply to, oldest first, with fit scores, notes, people the user knows there (ask them for
    a referral before applying) and warnings to check first (pay, place, flagged text). The first warning, and
    duplicate_of, say when it's (maybe) the same opening as one already applied to, queued or skipped: read them
    before asking anyone for a referral. Use it to pick the next application; jobs get here through mark_job
    with status queued. For applications already sent use list_applications."""
    cfg, store = _open()
    try:
        return [{"key": e.job.key, "company": e.job.display_company, "title": e.job.title, "url": e.job.url,
                 "pay": e.job.pay(), "fit": e.fit, "contacts": e.contacts, "note": e.record.get("note"),
                 "queued_at": e.record.get("status_at"), "closed": e.record.get("closed"), "warnings": e.warnings,
                 "duplicate_of": e.duplicate.to_dict() if e.duplicate else None, **_pay(e.pay, e.job)}
                for e in queue(cfg, store, pay_budget=levels.QUEUE)]
    finally:
        store.close()


@server.tool(annotations=_hints(idempotent=True, web=True))
def check_postings() -> list[dict]:
    """Check that the postings of queued jobs and open applications still take applications, and record the
    ones that closed or came back. result is open, closed, reopened, or unknown (check it yourself); an open
    job's detail may say its board's hosted pages are offline and where to apply instead. Run it before working
    through list_queued_jobs, so time isn't spent on closed postings."""
    cfg, store = _open()
    try:
        return [{"key": c.job.key, "company": c.job.display_company, "title": c.job.title, "url": c.job.url,
                 "result": c.result, "detail": c.detail} for c in watch.check_postings(store, watched=cfg.boards)]
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


@server.tool(annotations=READ)
def find_duplicates(
    strong_only: Annotated[bool, Field(description=(
        "Only pairs that share a req or posting id (the same opening), not the same title alone."))] = False,
) -> list[dict]:
    """Jobs tracked twice: pairs of tracked jobs, open or closed, where the person queued, applied to or skipped
    one and the other is the same opening (strong: a shared req or posting id, from a title, note, posting text or
    link; why says which, "reposted as req ..." for a repost) or maybe the same (why "same title": check it's a
    different opening). The same opening first, applications first. Each: why, strong, and both jobs (key,
    company, title, status, date, closed), the one acted on first. Read-only: the person decides what to skip
    (mark_job). For one job, get_job's duplicate_of says the same."""
    _, store = _open()
    try:
        return [dupes.pair_dict(p) for p in dupes.pairs(store, strong_only=strong_only)]
    finally:
        store.close()


@server.tool(annotations=READ)
def read_profile(
    text: Annotated[str, Field(description=(
        "The page text of someone's LinkedIn experience page (linkedin.com/in/<name>/details/experience/), as "
        "the person's own browser shows it: copied, or from a browser tool's page text. Not a link."))],
) -> list[dict]:
    """Who an interviewer or contact is: their roles, from the text of their LinkedIn experience page, for
    interview prep. Each: title, company, start, end ("Present" if current), duration, location, workplace
    (Hybrid, Remote or On-site) and bullets (the description). The page's sidebars and footer are dropped.
    This only parses text it is given: jobwatch never reads linkedin.com (its robots.txt disallows it), so get
    the page text through the person's own browser. Returns an error when no roles are found."""
    if not (found := profile.roles(text)):
        raise ToolError("no roles found: pass the text of the /details/experience/ page, not a link")
    return [asdict(r) for r in found]


@server.tool(annotations=READ)
def get_company(
    name: Annotated[str, Field(description=(
        "A company's name (\"Acme Robotics\"), part of it (\"acme\"), or its domain (\"acme.com\"); case, "
        "punctuation and suffixes such as Inc don't matter."))],
    every_role: Annotated[bool, Field(description=(
        "Also list the open roles the filters leave out (other cities, low pay...). Default: the watchlist's "
        "display.company setting (matches: only the roles Today's filters pass)."))] = False,
) -> dict:
    """Everything tracked at one company, whatever the status of its jobs (new, queued, applied, screening,
    interviewing, offer, rejected, withdrawn, skipped) and open or closed. company, counts (jobs by status), and
    jobs: each with key, title, status, posted, applied_at, closed, next_step, follow_up, due, note, package
    (what was saved: files, answers, note) and duplicate_of (see get_job); contacts: people the user knows there,
    with find_referral, a LinkedIn search for someone who could introduce them; watch: whether the company's
    board is on the watchlist and, when it isn't, add_board (the entry and name to pass add_board) and command.
    Closed postings never acted on are only counted (closed_unacted), so are open ones not acted on that the
    filters leave out (left_out, with left_out_by: filter -> count) unless every_role, and the other open ones
    not acted on are listed up to 25 (more_open). also names other companies the name matched. Returns an error
    when none matches. Use it when the person names a company and you don't know which stage it's at; for one
    job's full text, fit and prep use get_job, for every application list_applications, and for all jobs of one
    status list_jobs."""
    cfg, store = _open()
    try:
        if not (v := company.view(cfg, store, name, every=True if every_role else None)):
            # a ToolError, so the model reads the message: any other exception's text stays on the server
            raise ToolError(f"no tracked job is at a company matching {name!r}")
        return v
    finally:
        store.close()


@server.tool(annotations=_hints(destructive=True, idempotent=True))
def rate_contact(
    who: Annotated[str, Field(description=(
        "The connection's full name (\"Ana Li\") or LinkedIn profile link (linkedin.com/in/...)."))],
    verdict: Annotated[Literal["use", "skip", "clear"], Field(description=(
        "use: ask them first; skip: never suggest them; clear: back to the usual order."))],
    note: Annotated[str | None, Field(description=(
        "A few words to show beside their name, e.g. \"doesn't check LinkedIn; reach on WhatsApp\"."))] = None,
) -> dict:
    """Record what the person says about someone they know at a company: use (a good person to ask for a
    referral: listed first wherever contacts are), skip (never suggest them, e.g. never answers messages) or
    clear (forget it), with an optional short note that is shown with their name. Call it when the person
    tells you whom to ask or not to ask; it only changes how contacts are ordered and listed. Returns the
    connection (name, company, position, verdict, note). Errors when no connection (or more than one) has
    that name: then use their profile link."""
    cfg, store = _open()
    try:
        try:
            p = referrals.rate(cfg, store, who, verdict, note or "")
        except ValueError as e:
            raise ToolError(str(e)) from None
        return {k: p[k] for k in ("name", "company", "position", "url", "verdict", "note")}
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
def find_past_answers(
    query: Annotated[str, Field(description=(
        "Words of the question to look for (\"notice period\", \"reason leaving\"): every word must be in the "
        "question, any case. Empty lists each distinct question once, with its latest answer."))] = "",
) -> list[dict]:
    """Form answers the person gave on earlier applications (kept by save_application_package), newest
    application first: key, company, title, applied, question and answer; without a query each question once,
    with asked (how many applications had it). Use it before filling a form, to reuse what was answered to
    \"reason for leaving\", \"notice period\" or \"salary\" instead of writing it again; for everything sent with
    one application use get_application_package."""
    _, store = _open()
    try:
        return answers.find(store, query)
    finally:
        store.close()


@server.tool(annotations=READ)
def get_interview_prep(
    key: Key,
    draft_answers: Annotated[bool, Field(description=(
        "Also have jobwatch's own model (the chat's backend) draft 6-10 questions likely for this role, each with "
        "the ask it probes and an answer outline built only from the person's story file and resume, citing the "
        "story ids used; one with no story says so (no_story) with an honest angle. Invented story ids and "
        "numbers are taken out before they're returned. Slow the first time, then kept. With the claude backend "
        "the posting, resume and stories go to Anthropic. False is rule-based and instant."))] = False,
    role_questions: Annotated[bool, Field(description=(
        "Also have jobwatch's own model (the chat's backend) write questions for this role from the posting's asks "
        "(role_questions), without answers. Only the posting goes to the model, and to Anthropic with the claude "
        "backend. Slow the first time, then kept; questions saved earlier are always returned."))] = False,
) -> dict:
    """A prep sheet for a recruiter call or interview: stage and next step, each requirement and responsibility
    in the posting next to the closest resume line (quoted, never written), gaps to be honest about, what was
    sent, questions to expect and to ask, and the posting. For an application added by hand, the posting is found
    on a watched board by its requisition id. markdown is the sheet ready to read. Also: brief, the company as
    the posting and the person's own notes tell it (about: the posting's lines; facts; notes; contacts: people
    they know there; source), nothing looked up elsewhere, so say it's from the posting; pay, the posted range
    (posted, posted_min, posted_max), the person's target (target, and target_max when it's a range) and how it
    sits against the range (target_note); and
    role_questions, questions for this role written from the posting's asks (questions_note says where they came
    from; empty: expect's generic questions stand). The person's private pay floor is never returned here
    (pay.floor_withheld says one is set): don't ask for it or guess it. With draft_answers, drafted holds the
    drafted questions and draft_note how they were made, or why there are none. practised holds the answers the
    person kept from mock interviews (jobwatch ask --job KEY --mock): question, answer as they said it, and
    improved, the tightened version built from their own words and stories. Present a drafted answer as the
    person's only where it cites their stories. story_gaps lists what a story would help with (ask, why): asks
    with nothing close on the resume, drafted questions with no story yet, missing must-haves; to fill one,
    interview the person and keep what they confirm with save_story. Use it before a call; get_job and
    get_application_package give the raw pieces."""
    cfg, store = _open()
    try:
        sheet = prep.without_floor(prep.build(cfg, store, key, draft=draft_answers, questions=role_questions))
        return {**prep.to_dict(sheet), "story_gaps": storyfind.gaps(sheet), "markdown": prep.markdown(sheet)}
    finally:
        store.close()


Line = Field(description="Two or three sentences, in the person's first person, using only what they told you.")


@server.tool(annotations=_hints())
def save_story(
    id: Annotated[str, Field(description=(
        "A short name drafted answers cite it by: lowercase letters, digits and dashes (alert-dedupe). A taken "
        "one gets -2, -3..."))],
    title: Annotated[str, Field(description="A few words: what it was.")],
    did: Annotated[str, Line],
    hard: Annotated[str, Line],
    result: Annotated[str, Line],
    skills: Annotated[list[str] | None, Field(description=(
        "Tools and skills it shows, as the person named them."))] = None,
    avoid: Annotated[list[str] | None, Field(description=(
        "Details that came up but the person didn't confirm, or asked to keep out (a tool they weren't sure of, "
        "a place). Drafted answers and mock answers that say one are taken out."))] = None,
) -> dict:
    """Add a story to the person's story file (the watchlist's stories:, or stories.yaml beside it, which the
    watchlist then names), for drafted interview answers and mock interviews. Use it after interviewing the
    person about one of get_interview_prep's story_gaps: ask one question at a time; if you offer typical details
    to jog their memory, say they're common patterns, not their case; keep their real role (took part is not
    led); keep internal system names, people's names and countries out. Only what they confirmed goes in did,
    hard and result; the rest goes in avoid. Show them the story and save it only after they say yes. Returns
    the story as saved, the file and how many stories it has."""
    cfg = _config()
    try:
        saved, path = storyfind.save(cfg, {"id": id, "title": title, "did": did, "hard": hard, "result": result,
                                           "skills": skills or [], "avoid": avoid or []})
    except config.ConfigError as e:  # a ToolError, so the model reads what to fix
        raise ToolError(str(e)) from None
    return {"story": saved.to_dict(), "file": str(path), "stories": len(stories.load(path))}


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
