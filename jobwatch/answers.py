"""Answers given on earlier applications' forms, found again: what you wrote for "reason for leaving", "notice
period" or "salary" before. They're kept in each application's package (see package.py); this reads them across
all of them, newest application first."""

from __future__ import annotations

from .package import MANIFEST, Package
from .store import Store


def _when(rec: dict) -> str:
    return rec.get("applied_at") or (rec.get("status_at") or "")[:10] or (rec.get("first_seen") or "")[:10]


def find(store: Store, query: str = "") -> list[dict]:
    """The form answers whose question contains every word of the query (any case), newest application first:
    key, company, title, applied (its day), question, answer. Without a query, each distinct question once, with
    its latest answer and asked (how many applications had it)."""
    words = query.lower().split()
    rows = [(job, rec) for job, rec in store.jobs(include_closed=True)
            if (Package(store.packages, job.key).dir / MANIFEST).is_file()]
    rows.sort(key=lambda r: (_when(r[1]), r[1].get("first_seen") or ""), reverse=True)
    found, seen = [], {}
    for job, rec in rows:
        for a in Package(store.packages, job.key).data()["answers"]:
            q = " ".join(a["question"].lower().split())
            if not all(w in q for w in words):
                continue
            hit = {"key": job.key, "company": job.display_company, "title": job.title, "applied": _when(rec) or None,
                   "question": a["question"], "answer": a["answer"]}
            if words:
                found.append(hit)
            elif q in seen:
                seen[q]["asked"] += 1
            else:
                seen[q] = {**hit, "asked": 1}
                found.append(seen[q])
    return found


def text(found: list[dict], query: str = "") -> str:
    """`jobwatch answers`: the answers to read."""
    if not found:
        return (f"No saved form answer has a question with {query!r} in it." if query else
                "No form answers saved yet: `jobwatch attach --answers` or save_application_package keeps them.")
    out = []
    for f in found:
        by = f"{f['company']}, {f['title']}" + (f" ({f['applied']})" if f["applied"] else "")
        out += [f"{f['question']}" + (f"  (asked {f['asked']} times)" if f.get("asked", 1) > 1 else ""),
                f"  {by}", *(f"    {line}" for line in (f["answer"] or "(no answer)").splitlines()), ""]
    return "\n".join(out).rstrip()
