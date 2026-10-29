"""Digests as Markdown (to read) or JSON (for other tools)."""

from __future__ import annotations

import json
from datetime import date

from . import lca, levels
from .alerts import LABELS
from .models import Job
from .score import scorer_label
from .sources import candidate_home
from .store import ENDED, STAGES
from .watch import MANY_ROLES, Digest, Entry, FetchReport, scorable


def fetch_summary(r: FetchReport) -> str:
    out = [f"Checked {r.boards} board(s): {r.jobs} open roles, {len(r.new)} new."]
    if r.emails is not None:
        out[0] = out[0][:-1] + f" (with {r.emails} job-alert email(s) from the mailbox)."
    out += [f"  failed {board}: {err}" for board, err in r.errors.items()]
    out += [f"  warning {board}: {text}" for board, text in r.warnings.items()]
    return "\n".join(out)


def people(contacts: list[dict], most: int = 3) -> str:
    """ "Ana Li (Staff Engineer) [messaged 3×, last 2025-03-02]; Bo Chen and 2 more" """
    names = [p["name"] + (f" ({p['position']})" if p.get("position") else "")
             + (f" [{p['why']}]" if p.get("why") else "") for p in contacts[:most]]
    return "; ".join(names) + (f" and {len(contacts) - most} more" if len(contacts) > most else "")


VERDICTS = {"met": "met", "partial": "partly", "not_met": "missing"}


def _trim(text: str, most: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= most else text[:most - 1].rstrip() + "…"


def fit_lines(fit: dict) -> list[str]:
    """A fit score and why: "Fit 85/100, must-haves 5/6", then each requirement with its verdict and the
    resume's words that back it. Scores saved before requirements were kept show only the first line."""
    out = [f"Fit {fit['score']:.0f}/100, must-haves {fit['must_haves_met']}/{fit['must_haves_total']}"
           + (f" (scored by {scorer_label(fit['scored_by'])})" if fit.get("scored_by") else "")]
    for r in fit.get("requirements") or []:
        kind = "must" if r["kind"] == "must_have" else "nice"
        quote = f'  "{_trim(r["evidence"][0], 90)}"' if r.get("evidence") else ""
        out.append(f"  {VERDICTS.get(r['verdict'], r['verdict']):7} [{kind}] {_trim(r['requirement'], 80)}{quote}")
    return out


REFUSED_LINE = "Expected pay: Levels.fyi is refusing jobwatch's requests for now; it's asked again tomorrow."


def pay_lines(pay, job: Job) -> list[str]:
    """Expected pay from Levels.fyi and how it was worked out, with its page and credit."""
    if pay == levels.PENDING:
        return ["Expected pay: not looked up yet (Levels.fyi is asked a few pages at a time); try again shortly."]
    if pay == levels.REFUSED:
        return [REFUSED_LINE]
    if not isinstance(pay, levels.Estimate):
        return []
    return [f"Expected pay: {pay.line(job.pay())}", *(f"  - {w}" for w in pay.why), f"  {pay.credit}: {pay.url}"]


def lca_lines(est: lca.Estimate | None) -> list[str]:
    """Base pay filed for H-1B hires and how it was worked out, with its credit."""
    if not est:
        return []
    label = est.label[0].lower() + est.label[1:]
    return [f"{est.line()} ({label})", *(f"  - {w}" for w in est.why), f"  {est.credit}: {est.url}"]


def _line(e: Entry) -> list[str]:
    j = e.job
    facts = [j.display_company, "; ".join(j.places[:3]) + (" …" if len(j.places) > 3 else "")]
    if j.pay():
        facts.append(j.pay())
    if (age := j.age_days()) is not None:
        facts.append("posted today" if age == 0 else f"posted {age}d ago")
    out = [f"### [{j.title}]({j.url})", " · ".join(f for f in facts if f)]
    if j.link_note:
        out.append(f"**Link:** {j.link_note}")
    if e.same_title:
        places = sorted({loc for other in e.same_title for loc in other.locations[:1]} - set(j.locations))
        out.append(f"Also posted {len(e.same_title)} more time(s)"
                   + (f": {'; '.join(places[:4])}" if places else ""))
    if e.fit:
        f = e.fit
        old = " (old score, rescoring)" if f.get("stale") else ""
        by = f" (scored by {scorer_label(f['scored_by'])})" if f.get("scored_by") else ""
        out.append(f"**Fit {f['score']:.0f}/100**{old}, must-haves {f['must_haves_met']}/{f['must_haves_total']}{by}. "
                   + (f"Gaps: {'; '.join(f['gaps'])}" if f["gaps"] else "No must-have gaps."))
    elif not scorable(j):
        out.append(f"{MANY_ROLES[1]}.")
    if isinstance(e.pay, levels.Estimate):  # set on queued jobs only, never in a digest
        out.append(f"Expected pay: {e.pay.line(j.pay())} ({e.pay.credit}: {e.pay.url})")
    if e.lca:
        out.append(f"{e.lca.line()} ({e.lca.label[0].lower() + e.lca.label[1:]}; {e.lca.credit}: {e.lca.url})")
    if e.warnings:
        out.append(f"**Check:** {'; '.join(e.warnings)}")
    if e.keywords:
        out.append(f"Keywords: {', '.join(e.keywords)}")
    if e.contacts:
        out.append(f"You know: {people(e.contacts)}")
    if e.record.get("closed"):
        out.append(f"**Closed** {e.record['closed'][:10]}: the posting is gone from the board.")
    if e.record.get("note"):
        out.append(f"Note: {e.record['note']}")
    out.append(f"Source: {found_on(j, e.record.get('via'))}")
    out.append(f"`{j.key}`" + (f" (via {e.record['via']})" if e.record.get("via") else ""))
    return [*out, ""]


BOARDS = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "workable": "Workable", "workday": "Workday",
          "eightfold": "Eightfold", "jibe": "Jibe", "rippling": "Rippling", "oracle": "Oracle Recruiting Cloud",
          "smartrecruiters": "SmartRecruiters", "avature": "Avature", "icims": "iCIMS",
          "jobvite": "Jobvite"}


def found_on(job: Job, via: str | None = None) -> str:
    """Where a job came from, in words: "Acme's Greenhouse board", "a LinkedIn job-alert email, matched to Acme's
    Lever board", "an Indeed job-alert email (not found on the company's board)", or "added by hand"."""
    if job.source == "hn":
        board = "Hacker News' \"Who is hiring?\" thread"
    elif job.source == "google":
        board = "Google Careers"
    elif job.source == "amazon":
        board = "amazon.jobs"
    elif job.source != "manual":
        board = f"{job.display_company}'s {BOARDS.get(job.source, job.source)} board"
    else:
        board = ""
    if not via:
        return board or "added by hand (a link or `jobwatch add`)"
    sender = LABELS.get(via, via.removesuffix("-alert").replace("-", " ").title())
    email = f"{'an' if sender[0] in 'AEIOU' else 'a'} {sender} job-alert email"
    return f"{email}, matched to {board}" if board else f"{email} (not found on the company's board)"


def to_markdown(d: Digest, title: str = "jobwatch digest", more: str = "", pace: dict | None = None) -> str:
    """The digest to read. When the limit cut some (d.total), it says so, and ends with `more`: how to see
    them. `pace`: today's applications against the pace (see watch.pace)."""
    more_n = d.total - len(d.entries)
    out = [f"# {title}", "", (f"Top {len(d.entries)} of {d.total}" if more_n > 0 else str(len(d.entries)))
           + " matching job(s)."]
    if d.rejected:
        out[-1] += " Filtered out: " + ", ".join(f"{n} by {k}" for k, n in sorted(d.rejected.items())) + "."
    if pace:
        out.append(pace["line"] + ("" if pace["line"].endswith((".", "!")) else "."))
    if d.scored:
        out.append(f"Scored {d.scored} with shortlist-ai.")
    if d.note:
        out.append(d.note)
    out += [f"- scoring failed for {k}: {v}" for k, v in d.score_errors.items()]
    out.append("")
    for e in d.entries:
        out += _line(e)
    if more_n > 0:
        out.append(f"{more_n} more match" + (f": {more}" if more else "."))
    return "\n".join(out).rstrip() + "\n"


def queue_markdown(entries: list[Entry]) -> str:
    if not entries:
        return "The queue is empty. Add jobs with `jobwatch queue <key>`.\n"
    out = [f"# Apply queue ({len(entries)})", ""]
    for e in entries:
        out += _line(e)
    return "\n".join(out).rstrip() + "\n"


def due(rec: dict, today: str | None = None) -> bool:
    """An open application (or a queued job) whose follow-up day has come. A skipped job's leftover follow-up
    isn't due: skipping it ended it."""
    return (bool(rec.get("follow_up")) and rec["status"] in ("queued", *STAGES) and rec["status"] not in ENDED
            and rec["follow_up"] <= (today or date.today().isoformat()))


def quiet_line(q: dict) -> str:
    """ "Quiet 25 days (since 2026-09-19), posting open. A short check-in... You know: Ana Li (Engineer)" """
    out = (f"**Gone quiet:** {q['days']} days (since {q['since']}), posting "
           f"{'open' if q['posting_open'] else 'closed'}. {q['advice']}")
    return out + (f" You know: {people(q['contacts'])}" if q.get("contacts") else "")


def applications_markdown(rows: list[tuple[Job, dict]], today: str | None = None,
                          homes: dict[str, str | None] | None = None, quiet: dict[str, dict] | None = None,
                          more: str = "") -> str:
    if not rows:
        return "No applications yet. Mark a job applied, or add one with `jobwatch add \"Company\" \"Title\"`.\n"
    counts: dict[str, int] = {}
    for _, rec in rows:
        counts[rec["status"]] = counts.get(rec["status"], 0) + 1
    late = sum(due(rec, today) for _, rec in rows)
    out = [f"# Applications ({len(rows)})", "", ", ".join(f"{n} {s}" for s, n in counts.items())
           + (f". **{late} to follow up on now.**" if late else "."), ""]
    if gone := len(quiet or {}):
        out[-2] += f" {gone} gone quiet (`jobwatch quiet`)."
    for job, rec in rows:
        title = f"[{job.title}]({job.url})" if job.url else job.title
        facts = [f"**{rec['status']}**", f"applied {rec['applied_at']}" if rec.get("applied_at") else "",
                 job.pay(), "posting closed" if rec.get("closed") else ""]
        out += [f"### {job.display_company}: {title}", " · ".join(f for f in facts if f)]
        if rec.get("next_step") or rec.get("follow_up"):
            when = f" by {rec['follow_up']}" if rec.get("follow_up") else ""
            out.append(("**Due:** " if due(rec, today) else "Next: ") + (rec.get("next_step") or "follow up") + when)
        if q := (quiet or {}).get(job.key):
            out.append(quiet_line(q))
        if rec.get("note"):
            out.append(f"Note: {rec['note']}")
        if home := (homes or {}).get(job.key) or candidate_home(job.url):
            out.append(f"Status page (sign in): {home}")
        out += [f"`{job.key}`", ""]
    if more:
        out.append(more)
    return "\n".join(out).rstrip() + "\n"


def quiet_markdown(rows: list[tuple[Job, dict]], found: dict[str, dict]) -> str:
    """The applications that have gone quiet, the longest quiet first, each with what to do next."""
    if not found:
        return "Nothing has gone quiet. An application is quiet after a few weeks with no news; see `quiet:` " \
               "in the watchlist.\n"
    out = [f"# Gone quiet ({len(found)})", ""]
    for job, rec in sorted((r for r in rows if r[0].key in found), key=lambda r: -found[r[0].key]["days"]):
        title = f"[{job.title}]({job.url})" if job.url else job.title
        out += [f"### {job.display_company}: {title}", f"**{rec['status']}** · " + quiet_line(found[job.key]),
                f"`{job.key}`", ""]
    out.append("To push one out: `jobwatch snooze KEY [--days 7]`. To end one: `jobwatch mark rejected KEY` (or "
               "withdrawn). `jobwatch check` refreshes whether the postings are still up. Nothing changes by itself.")
    return "\n".join(out) + "\n"


def to_json(d: Digest) -> str:
    return json.dumps({
        "jobs": [{**{k: v for k, v in e.job.to_dict().items() if k != "description"},
                  "status": e.record["status"], "first_seen": e.record["first_seen"], "via": e.record.get("via"),
                  "relevance": e.relevance, "keywords": e.keywords, "fit": e.fit,
                  "not_scored": None if scorable(e.job) else MANY_ROLES[1], "contacts": e.contacts,
                  "same_title": [{"key": o.key, "url": o.url, "locations": o.locations} for o in e.same_title],
                  "duplicate_of": e.duplicate.to_dict() if e.duplicate else None}
                 for e in d.entries],
        "rejected": d.rejected, "scored": d.scored, "score_errors": d.score_errors, "note": d.note,
        "total": max(d.total, len(d.entries)),
    }, indent=2, ensure_ascii=False)
