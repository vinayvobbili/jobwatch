"""Digests as Markdown (to read) or JSON (for other tools)."""

from __future__ import annotations

import json
from datetime import date

from .models import Job
from .sources import candidate_home
from .store import ENDED
from .watch import Digest, Entry, FetchReport


def fetch_summary(r: FetchReport) -> str:
    out = [f"Checked {r.boards} board(s): {r.jobs} open roles, {len(r.new)} new."]
    out += [f"  failed {board}: {err}" for board, err in r.errors.items()]
    return "\n".join(out)


def people(contacts: list[dict], most: int = 3) -> str:
    """ "Ana Li (Staff Engineer) [messaged 3×, last 2025-03-02]; Bo Chen and 2 more" """
    names = [p["name"] + (f" ({p['position']})" if p.get("position") else "")
             + (f" [{p['why']}]" if p.get("why") else "") for p in contacts[:most]]
    return "; ".join(names) + (f" and {len(contacts) - most} more" if len(contacts) > most else "")


def _line(e: Entry) -> list[str]:
    j = e.job
    facts = [j.display_company, "; ".join(j.locations[:3]) + (" …" if len(j.locations) > 3 else "")]
    if j.pay():
        facts.append(j.pay())
    if (age := j.age_days()) is not None:
        facts.append("posted today" if age == 0 else f"posted {age}d ago")
    out = [f"### [{j.title}]({j.url})", " · ".join(f for f in facts if f)]
    if e.same_title:
        places = sorted({loc for other in e.same_title for loc in other.locations[:1]} - set(j.locations))
        out.append(f"Also posted {len(e.same_title)} more time(s)"
                   + (f": {'; '.join(places[:4])}" if places else ""))
    if e.fit:
        f = e.fit
        out.append(f"**Fit {f['score']:.0f}/100**, must-haves {f['must_haves_met']}/{f['must_haves_total']}. "
                   + (f"Gaps: {'; '.join(f['gaps'])}" if f["gaps"] else "No must-have gaps."))
    if e.keywords:
        out.append(f"Keywords: {', '.join(e.keywords)}")
    if e.contacts:
        out.append(f"You know: {people(e.contacts)}")
    if e.record.get("closed"):
        out.append(f"**Closed** {e.record['closed'][:10]}: the posting is gone from the board.")
    if e.record.get("note"):
        out.append(f"Note: {e.record['note']}")
    out.append(f"`{j.key}`")
    return [*out, ""]


def to_markdown(d: Digest, title: str = "jobwatch digest") -> str:
    out = [f"# {title}", "", f"{len(d.entries)} matching job(s)."]
    if d.rejected:
        out[-1] += " Filtered out: " + ", ".join(f"{n} by {k}" for k, n in sorted(d.rejected.items())) + "."
    if d.scored:
        out.append(f"Scored {d.scored} with shortlist-ai.")
    if d.note:
        out.append(d.note)
    out += [f"- scoring failed for {k}: {v}" for k, v in d.score_errors.items()]
    out.append("")
    for e in d.entries:
        out += _line(e)
    return "\n".join(out).rstrip() + "\n"


def queue_markdown(entries: list[Entry]) -> str:
    if not entries:
        return "The queue is empty. Add jobs with `jobwatch queue <key>`.\n"
    out = [f"# Apply queue ({len(entries)})", ""]
    for e in entries:
        out += _line(e)
    return "\n".join(out).rstrip() + "\n"


def due(rec: dict, today: str | None = None) -> bool:
    """An open application whose follow-up day has come."""
    return bool(rec.get("follow_up")) and rec["status"] not in ENDED and rec["follow_up"] <= (
        today or date.today().isoformat())


def applications_markdown(rows: list[tuple[Job, dict]], today: str | None = None,
                          homes: dict[str, str | None] | None = None) -> str:
    if not rows:
        return "No applications yet. Mark a job applied, or add one with `jobwatch add \"Company\" \"Title\"`.\n"
    counts: dict[str, int] = {}
    for _, rec in rows:
        counts[rec["status"]] = counts.get(rec["status"], 0) + 1
    late = sum(due(rec, today) for _, rec in rows)
    out = [f"# Applications ({len(rows)})", "", ", ".join(f"{n} {s}" for s, n in counts.items())
           + (f". **{late} to follow up on now.**" if late else "."), ""]
    for job, rec in rows:
        title = f"[{job.title}]({job.url})" if job.url else job.title
        facts = [f"**{rec['status']}**", f"applied {rec['applied_at']}" if rec.get("applied_at") else "",
                 job.pay(), "posting closed" if rec.get("closed") else ""]
        out += [f"### {job.display_company}: {title}", " · ".join(f for f in facts if f)]
        if rec.get("next_step") or rec.get("follow_up"):
            when = f" by {rec['follow_up']}" if rec.get("follow_up") else ""
            out.append(("**Due:** " if due(rec, today) else "Next: ") + (rec.get("next_step") or "follow up") + when)
        if rec.get("note"):
            out.append(f"Note: {rec['note']}")
        if home := (homes or {}).get(job.key) or candidate_home(job.url):
            out.append(f"Status page (sign in): {home}")
        out += [f"`{job.key}`", ""]
    return "\n".join(out).rstrip() + "\n"


def to_json(d: Digest) -> str:
    return json.dumps({
        "jobs": [{**{k: v for k, v in e.job.to_dict().items() if k != "description"},
                  "status": e.record["status"], "first_seen": e.record["first_seen"],
                  "relevance": e.relevance, "keywords": e.keywords, "fit": e.fit, "contacts": e.contacts,
                  "same_title": [{"key": o.key, "url": o.url, "locations": o.locations} for o in e.same_title]}
                 for e in d.entries],
        "rejected": d.rejected, "scored": d.scored, "score_errors": d.score_errors, "note": d.note,
    }, indent=2, ensure_ascii=False)
