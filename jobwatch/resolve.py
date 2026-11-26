"""Rows whose client isn't named, matched to the named company's copy of the same opening.

A staffing or list source (Ladders) posts a client's job under its own name: "Ladders", "a leader in the enterprise
technology space". The client's own board often has the same job, under the real company. `jobwatch dupes` compares
jobs inside one company, so it never pairs the two. This does, across companies: an unnamed-client row (see
filters.unnamed_client) and a named job match when they have the same title (seniority included), the same pay
range (each end within a percent: one posting rounds to the thousand, the other doesn't) and the same remote setting.

Only rows Today could list (new or shown, still open) are looked at, and only against open jobs at a named
company. Applying marks the unnamed copy skipped with a note naming its twin; the twin is never touched, and
nothing queued, applied or already skipped is ever changed or deleted.
"""

from __future__ import annotations

from dataclasses import dataclass

from .dupes import _order, title_key
from .filters import agency_name, unnamed_client
from .models import Job
from .store import Store
from .text import parse_pay

ELIGIBLE = ("new", "shown")  # what Today lists: the only rows resolve looks at
NEAREST = 3  # same-title jobs --explain lists for a row: the ones that differ least
TOLERANCE = 0.01  # how far apart two pay figures may be (a fraction) and still be the same band


@dataclass
class Twin:
    unnamed: Job
    unnamed_record: dict
    named: Job
    named_record: dict

    @property
    def note(self) -> str:
        return (f"Same opening as {self.named.display_company}'s “{self.named.title}” ({self.named.key}); "
                "this copy doesn't name its client")


def pay_of(job: Job) -> tuple[int, int] | None:
    """The job's pay range: the board's own, else the yearly range its posting text states (a Greenhouse board often
    gives none, only the posting's "$238,400 - $330,200"). None when neither does, or the pay is an hourly rate."""
    if job.salary_min is not None and job.salary_max is not None:
        return (job.salary_min, job.salary_max) if not job.is_rate else None
    found = parse_pay(job.description)
    return (found[0], found[1]) if found and not found[2] else None


def same_band(a: tuple[int, int] | None, b: tuple[int, int] | None) -> bool:
    """Two pay ranges that agree at both ends to within TOLERANCE (a posting rounded to the thousand is the same)."""
    return bool(a and b) and all(abs(x - y) <= TOLERANCE * max(x, y) for x, y in zip(a, b, strict=True))


def is_remote(job: Job) -> bool | None:
    """Whether the job can be done remotely (None: no place stated, which proves nothing). "United States; Remote"
    and "United States (Remote)" are both remote; a country beside it is no office."""
    return "remote" in job.where if job.where else None


def twins(store: Store) -> list[Twin]:
    """Every unnamed-client row Today could list, paired with the best named twin: the job furthest along (applied,
    then queued, then skipped, then not acted on), the same posting twice going by the key. Changes nothing."""
    wanted: dict[tuple, list[tuple[Job, dict, tuple[int, int]]]] = {}
    for job, rec in store.iter_jobs(ELIGIBLE):
        if unnamed_client(job) and (pay := pay_of(job)) and (remote := is_remote(job)) is not None:
            wanted.setdefault((title_key(job.title), remote), []).append((job, rec, pay))
    best: dict[str, tuple[Job, dict]] = {}
    for job, rec in store.iter_jobs():  # open jobs only
        # the cheap checks first: only these titles' postings are read for pay
        if not (rows := wanted.get((title_key(job.title), is_remote(job)))) or agency_name(job.display_company):
            continue
        if not (pay := pay_of(job)):
            continue
        for row, _, row_pay in rows:
            if same_band(pay, row_pay) and (row.key not in best or (_order(rec), job.key) <
                                           (_order(best[row.key][1]), best[row.key][0].key)):
                best[row.key] = (job, rec)
    return [Twin(job, rec, *best[job.key]) for rows in wanted.values() for job, rec, _ in rows if job.key in best]


def near_misses(store: Store, found: list[Twin]) -> list[tuple[Job, list[str]]]:
    """For each unnamed-client row Today could list that has no twin: (the row, a line for each of the nearest open
    jobs at a named company with the same title, saying how it differs: "Initech (applied): pay $150,000–$180,000,
    not $140,000–$180,000"). Rows with no same-title job are left out. What `resolve --explain` prints."""
    matched = {t.unnamed.key for t in found}
    rows = [(job, rec) for job, rec in store.iter_jobs(ELIGIBLE) if unnamed_client(job) and job.key not in matched]
    by_title: dict[tuple, list[Job]] = {}
    for job, _ in rows:
        by_title.setdefault(title_key(job.title), []).append(job)
    lines: dict[str, list[tuple[int, str]]] = {}
    for other, rec in store.iter_jobs():
        if not (mine := by_title.get(title_key(other.title))) or agency_name(other.display_company):
            continue
        for job in mine:
            how = []
            if not same_band(a := pay_of(job), b := pay_of(other)):
                how.append(f"pay {_range(b)}, not {_range(a)}")
            if is_remote(job) != is_remote(other):
                how.append("no place stated" if is_remote(other) is None else
                           "on-site, not remote" if is_remote(job) else "remote, not on-site")
            lines.setdefault(job.key, []).append(
                (len(how), f"{other.display_company} ({rec['status']}): {', '.join(how) or 'same'}"))
    return [(job, [line for _, line in sorted(lines[job.key])[:NEAREST]]) for job, _ in rows if job.key in lines]


def _range(pay: tuple[int, int] | None) -> str:
    return f"${pay[0]:,}–${pay[1]:,}" if pay else "none stated"


def only(found: list[Twin], keys: list[str]) -> list[Twin]:
    """The pairs the keys name, in the order found. A key is either end of a pair: the unnamed copy's or its twin's
    (the dry run prints both). A key that names no pair is an error, so a typo never applies less than you meant."""
    chosen = [t for t in found if t.unnamed.key in keys or t.named.key in keys]
    known = {k for t in found for k in (t.unnamed.key, t.named.key)}
    if missing := [k for k in keys if k not in known]:
        raise ValueError(f"no pair has key {', '.join(missing)}; the keys are the ones `jobwatch resolve` prints")
    return chosen


def apply(store: Store, found: list[Twin]) -> int:
    """Mark each unnamed copy skipped, with a note naming its twin after any note it has. Returns how many."""
    for t in found:
        old = (t.unnamed_record.get("note") or "").strip()
        store.set_status([t.unnamed.key], "skipped", f"{old}\n{t.note}" if old else t.note)
    return len(found)


def text(found: list[Twin], applied: bool) -> str:
    """`jobwatch resolve`'s output: each pair, then what was or would be done."""
    if not found:
        return "No unnamed-client row has a named twin: same title, pay range and remote setting at another company."
    out = []
    for t in found:
        n = t.named_record["status"]
        out.append(f"{t.unnamed.display_company}: {t.unnamed.title}  {_range(pay_of(t.unnamed))}  `{t.unnamed.key}`")
        out.append(f"  = {t.named.display_company} ({n}): {t.named.title}  {_range(pay_of(t.named))}  `{t.named.key}`")
    out.append(f"\n{len(found)} unnamed-client row(s) match a named twin. " + (
        "Each is marked skipped with a note naming its twin; the twins are untouched." if applied else
        "Nothing was changed: --apply marks each unnamed copy skipped (the twin is never touched); "
        "--apply --only KEY [KEY ...] does it for just the pairs whose keys (above) you name."))
    return "\n".join(out)


def name_client(store: Store, key: str, company: str) -> Job:
    """Name the client of an unnamed-client row: its company becomes the client's, so Today lists it again."""
    job, _ = store.find(key)
    company = company.strip()
    if not company:
        raise ValueError("which company is the client?")
    if not unnamed_client(job):
        raise ValueError(f"{job.key} isn't an unnamed-client row")
    job.company_name = company
    store.update(job)
    return job
