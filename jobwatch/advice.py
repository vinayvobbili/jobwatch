"""A suggestion on each job: queue it or skip it, and why, in a few words ("the posted pay goes up to $260K",
"you've applied to 2 roles at Globex this past week"). Advice only: the person decides, and nothing is hidden
or marked for it."""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from .config import Config
from .dupes import companies
from .store import STAGES, Store
from .watch import STRONG_FIT, Entry, plural

WEEK = timedelta(days=7)
BUSY = 2    # applications at one company in a week: more starts to look like spraying
FRESH = 3   # days: posted this recently, an application is among the first read


@dataclass
class Advice:
    action: str                                     # "queue" or "skip"
    reasons: list[str]
    though: list[str] = field(default_factory=list)  # for a skip: what speaks for it anyway
    codes: list[str] = field(default_factory=list)   # the rule behind each reason (REASONS)

    @property
    def line(self) -> str:
        """ "Skip: you've applied to 2 roles at Globex this past week (though the posted pay goes up to $260K)" """
        head = f"{self.action.capitalize()}: {'; '.join(self.reasons)}"
        return head + (f" (though {self.though[0]})" if self.though else "")

    def to_dict(self) -> dict:
        return {"action": self.action, "reasons": self.reasons, "though": self.though, "codes": self.codes,
                "line": self.line}


class History:
    """The applications sent, by the names their company goes by (dupes.companies), to see how many went to one
    company lately. Build it once for a batch of jobs."""

    def __init__(self, store: Store, today: date | None = None):
        self.today = today or date.today()
        self.by_company: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for job, rec in store.jobs(STAGES, include_closed=True):
            for name in companies(job):
                self.by_company[name].append((job.key, rec.get("applied_at") or ""))

    def _at(self, entry: Entry) -> list[tuple[str, str]]:
        rows = {r[0]: r for n in companies(entry.job) for r in self.by_company.get(n, [])}
        return [r for key, r in rows.items() if key != entry.job.key]

    def applied_lately(self, entry: Entry) -> int:
        """Applications sent to the company in the past WEEK, whatever became of them (a rejection for one role
        is no reason to skip another there)."""
        since = (self.today - WEEK).isoformat()
        return sum(1 for _, applied in self._at(entry) if applied >= since)


def _k(n: int) -> str:
    return f"${n / 1000:.0f}K"


def _ago(day: str, today: date) -> str:
    days = (today - date.fromisoformat(day)).days
    return "today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago"


def _target(cfg: Config) -> str:
    p = cfg.pay
    return f"{_k(p.target)}–{_k(p.target_max)}" if p.target_max else _k(p.target)


def advise(cfg: Config, entry: Entry, history: History, expected: dict | None = None) -> Advice | None:
    """Queue or skip, and why; None when nothing stands out either way. Any reason to skip wins: applying twice,
    too often at one company, under the pay floor, or missing most must-haves costs more than a good job
    gained. A rejection there isn't one: another role at that company is its own chance. `expected`: the job's
    expected pay from Levels.fyi, as levels.as_dict gives it."""
    job, fit = entry.job, entry.fit
    company = job.display_company
    floor = cfg.pay.floor or cfg.filters_for(job).min_salary or 0
    expected = expected if expected and not (expected.get("pending") or expected.get("refused")) else {}
    top = job.salary_max or job.salary_min
    skip, go, extra = [], [], []  # (code, reason): the code names the rule (REASONS)

    d = entry.duplicate
    if d and d.strong and d.applied and entry.record.get("status") not in STAGES:
        skip.append(("applied_before", f"you already applied to this opening on {d.day}"))
    if (n := history.applied_lately(entry)) >= BUSY:
        skip.append(("busy", f"you've applied to {plural(n, 'role')} at {company} this past week"))
    if top and floor and top < floor:
        skip.append(("under_floor", f"the posted pay tops out at {_k(top)}, under your floor"))
    elif not top and floor and expected.get("base") and expected["base"] < floor:
        skip.append(("under_floor", f"Levels.fyi's median base for this level is {_k(expected['base'])}, under "
                                    "your floor"))
    if fit and fit.get("must_haves_total") and fit.get("must_haves_met", 0) * 2 < fit["must_haves_total"]:
        skip.append(("must_haves", f"it meets {fit.get('must_haves_met', 0)} of {fit['must_haves_total']} "
                                   "must-haves"))

    target, high = cfg.pay.target, cfg.pay.target_max or cfg.pay.target
    vs = lambda n: f"{'above' if n > high else 'within'} your {_target(cfg)} target"  # noqa: E731
    if target and top and top >= target:
        go.append(("pay", f"the posted pay goes up to {_k(top)}, {vs(top)}"))
    elif target and not top and expected.get("ask") and expected["ask"] >= target:
        go.append(("pay", f"Levels.fyi suggests asking ~{_k(expected['ask'])} base, {vs(expected['ask'])}"))
    if fit and fit.get("score", 0) >= STRONG_FIT:
        go.append(("strong_fit", f"a strong fit ({round(fit['score'])}/100)"))
    if entry.contacts:
        who = entry.contacts[0]
        go.append(("contact", f"you know {who['name']} there: ask for a referral first"
                   + (f" ({who['note']})" if who.get("note") else "")))
    if (age := job.age_days()) is not None and age <= FRESH:
        extra.append(("fresh", f"posted {_ago((history.today - timedelta(days=age)).isoformat(), history.today)}, "
                               "so it's read early"))

    if skip:
        return Advice("skip", [r for _, r in skip], [r for _, r in go], [c for c, _ in skip])
    if go:
        return Advice("queue", [r for _, r in go + extra], codes=[c for c, _ in go + extra])
    return None


# Each rule, for `jobwatch advice`: what makes it fire.
REASONS = {
    "applied_before": "the same opening (a shared req or posting id) was applied to already",
    "busy": f"{BUSY} or more applications at the company in the past {WEEK.days} days",
    "under_floor": "the posted pay, or Levels.fyi's median base when none is posted, is under pay.floor",
    "must_haves": "the fit score found fewer than half the must-haves",
    "pay": "the posted pay, or Levels.fyi's ask when none is posted, reaches pay.target",
    "strong_fit": f"a fit score of {STRONG_FIT} or more",
    "contact": "someone you know works there",
    "fresh": f"posted in the last {FRESH} days (only alongside another reason to queue)",
}


def summary(cfg: Config, store: Store, entries: list[Entry]) -> dict:
    """How the advice falls across these jobs (Today's, say): {"jobs", "by_action": {queue, skip, none},
    "by_reason": {code: jobs}}, with no expected pay (that's looked up in the background)."""
    history = History(store)
    by_action, by_reason = Counter(), Counter()
    for e in entries:
        said = advise(cfg, e, history, None)
        by_action[said.action if said else "none"] += 1
        by_reason.update(said.codes if said else [])
    return {"jobs": len(entries), "by_action": {a: by_action[a] for a in ("queue", "skip", "none")},
            "by_reason": dict(by_reason.most_common())}


def summary_text(s: dict) -> str:
    a = s["by_action"]
    lines = [f"{plural(s['jobs'], 'job')}: queue {a['queue']}, skip {a['skip']}, no suggestion {a['none']}"]
    lines += [f"  {n:>5}  {code}: {REASONS.get(code, '')}" for code, n in s["by_reason"].items()]
    return "\n".join(lines)
