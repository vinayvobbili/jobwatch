"""The Comps tab: your live opportunities side by side, to compare them. Each one's stage, dates, posted pay,
place, fit score and the people you know there come from what's already tracked; what a recruiter told you about
pay (base, bonus, equity, sign-on, what you asked for, what they offered, a note) is kept per job with
`jobwatch comp`, the `set_comp` tool or the page. The page, `jobwatch comps` and the `get_comps` tool all read
it here.

A company's health (public or private, funding, layoffs, rating, a risk note) is kept per company the same way:
`jobwatch health`, the `set_company_health` tool or the page; so is what kind of company it is (tech, consulting or
enterprise), and per job its role (building the product, customer-facing, internal tools) and a career note, which
the career part of the suggestion reads. Nothing is looked up from the web: the values come
from the person, or from Claude, who read them somewhere, with the links and the day they were true. The
suggestion at the top ranks the opportunities by plain rules (see WEIGHTS, which the watchlist's comps.weights
can change; the career part follows the watchlist's goals, when it has them); there is no model behind it."""

from __future__ import annotations

import re
from datetime import date

from . import lca
from .config import COMP_WEIGHTS, Config, Goals
from .contacts import company_key
from .score import resume_id
from .store import COMP_FIELDS, ENDED, STAGES, Store
from .watch import _fits, load_contacts

LIVE = ("screening", "interviewing", "offer")  # the stages compared unless asked for more
ORDER = ("offer", "interviewing", "screening", "applied")  # furthest along first
MOST_CONTACTS = 3
MOST_GAPS = 3
STALE_DAYS = 90  # health older than this is marked stale
# What the suggestion weighs, as a share of its score, unless the watchlist's comps.weights say otherwise: career
# value, pay against your target, the fit score, how far along the process is, and the company's health. Each
# part is 0-100 (see the _career, _pay, _fit, _progress and _health rules).
WEIGHTS = COMP_WEIGHTS
KIND_BASE = {"tech": 80, "consulting": 55, "enterprise": 40}  # the career part by the kind of company
KIND_WORDS = {"tech": "tech company", "consulting": "consulting", "enterprise": "enterprise"}
ROLE_ADJUST = {"product": 15, "customer": 5, "internal": -5}  # added to it by what the job builds
GOAL_KIND_SCORES = (90, 65, 40)  # the career part by the kind of company, from your goals: best choice first
GOAL_ROLE_SCORES = (10, 0, -10)  # added to it by what the job builds, best choice first
ROLE_WORDS = {"product": "builds product", "customer": "customer-facing", "internal": "internal tools"}
GOAL_STAGE_SCORES = (10, 0, -10)  # added by the company's stage (from its health), best choice first; goals only
STAGE_WORDS = {"startup": "startup", "growth": "growth stage", "public": "public company"}
_EARLY = re.compile(r"\b(?:pre-?seed|seed|angel|series\s*[ab])\b", re.I)
_LATER = re.compile(r"\b(?:series\s*[c-z]|late[- ]stage|pre-?ipo)\b", re.I)
PROGRESS = {"offer": 100, "interviewing": 70, "screening": 40, "applied": 15}
THIN = 20_000_000  # a private company that raised less than this in all counts as thinly funded
NEUTRAL = 50  # a part with nothing to go on: neither for nor against
# the inputs of a part with nothing to go on
UNKNOWN = ("no pay known", "not scored", "no company health kept", "no kind or role kept")
_NONE = re.compile(r"\s*(none|no|nil|n/a|0)\b", re.I)

_N = r"\$?(\d[\d,]*(?:\.\d+)?)\s*([kKmM])?"
_RANGE = re.compile(rf"(?<![\w.]){_N}\s*(?:-|\u2013|\u2014|to)\s*{_N}(?![\d%])")
_ONE = re.compile(rf"(?<![\w.]){_N}(?![\d%])(?!\s*%)")
_SCALE = {"": 1, "k": 1000, "m": 1_000_000}


def amount(text: str | None) -> tuple[int, int] | None:
    """The yearly amount or range a person wrote, as (low, high) dollars: "140-165K", "$150K - $185K", "165,000",
    "180K most likely their max". A K or M on one end of a range applies to both ("140-165K"). Percentages and
    anything under $1,000 aren't pay (None)."""
    text = text or ""
    for m in _RANGE.finditer(text):
        (low, lk), (high, hk) = (m.group(1), m.group(2)), (m.group(3), m.group(4))
        lk, hk = (lk or hk or "").lower(), (hk or lk or "").lower()
        low, high = sorted((float(low.replace(",", "")) * _SCALE[lk], float(high.replace(",", "")) * _SCALE[hk]))
        if low >= 1000:
            return round(low), round(high)
    for m in _ONE.finditer(text):
        value = round(float(m.group(1).replace(",", "")) * _SCALE[(m.group(2) or "").lower()])
        if value >= 1000:
            return value, value
    return None


def _best(rows: list[dict], value) -> list[str]:
    """The keys with the highest value, when at least two have one and they aren't all the same."""
    have = {r["key"]: v for r in rows if (v := value(r)) is not None}
    top = max(have.values(), default=None)
    return [k for k, v in have.items() if v == top] if len(have) > 1 and len(set(have.values())) > 1 else []


def company_of(store: Store, text: str) -> str:
    """The company a name or a job's key means: a job's company as written there, else the text itself."""
    try:
        return store.find(text)[0].display_company
    except KeyError:  # not a job (or several): it's the company's name
        return text.strip()


def _k(n: float) -> str:
    return f"${n / 1_000_000:.1f}M" if n >= 1_000_000 else f"${n / 1000:.0f}K"


def aged(health: dict | None, today: date | None = None) -> dict | None:
    """A company's health with how old it is: age_days since as_of (None when no day was given) and stale when that
    is over STALE_DAYS or unknown."""
    if not health:
        return None
    days = (((today or date.today()) - date.fromisoformat(health["as_of"])).days) if health.get("as_of") else None
    return {**health, "age_days": days, "stale": days is None or days > STALE_DAYS}


def _target(cfg: Config) -> tuple[float, str] | None:
    """The pay target from the watchlist's pay: settings, as (middle, words); None when none is set."""
    low, high = cfg.pay.target, cfg.pay.target_max or cfg.pay.target
    if not low:
        return None
    return (low + high) / 2, _k(low) + (f"-{_k(high)}" if high != low else "")


def _choice(prefs: tuple, value: str | None, scores: tuple, fixed: dict) -> tuple[int | None, str]:
    """(score, note) for a kind or role by the person's preferences: the first one listed scores scores[0], the
    next scores[1], and so on; one not listed ranks last; "any" scores the middle. With no preferences, or no
    value known, the fixed rule applies (no note). A value of None is not known: (None, "")."""
    if value is None:
        return None, ""
    if not prefs:
        return fixed.get(value), ""
    if prefs == ("any",):
        return scores[1], ""
    if value not in prefs:
        return scores[-1], "not on your list"
    n = prefs.index(value)
    return scores[n], f"your {('1st', '2nd', '3rd')[n]} choice"


def stage_of(health: dict | None) -> str | None:
    """startup, growth or public, from a company's health: public when it's listed, else from its stage ("Series
    B, $50M, 2025" is a startup, "Series D" growth stage); None when its health doesn't say."""
    h = health or {}
    if h.get("listing") == "public":
        return "public"
    stage = h.get("stage") or ""
    return "growth" if _LATER.search(stage) else "startup" if _EARLY.search(stage) else None


def _career(row: dict, goals: Goals | None = None) -> tuple[int, str, str]:
    """(part, input, phrase): what the job is worth to your career by plain rules. The kind of company starts it
    (tech 80, consulting 55, enterprise 40); the job's role adds to that (builds the product +15, customer-facing
    +5, internal tools -5); 0-100. A role with no kind known starts from NEUTRAL; neither known is NEUTRAL.
    With the watchlist's goals (a company_kinds, roles or stages preference), the steps follow your order instead:
    kinds score 90, 65, 40, roles add +10, 0, -10, and so does the company's stage (stage_of, only when its health
    says it), best first; the input says which choice of yours each is."""
    kind, role = (row["health"] or {}).get("kind"), row["comp"].get("role")
    kind = kind if kind in KIND_BASE else None
    role = role if role in ROLE_ADJUST else None
    g = goals if goals is not None and goals.scores else Goals()
    stage = stage_of(row["health"]) if g.stages else None  # no fixed rule: a stage counts only by your goals
    if kind is None and role is None and stage is None:
        return NEUTRAL, "no kind or role kept", "neither its kind of company nor its role is kept"
    base, kind_note = _choice(g.company_kinds, kind, GOAL_KIND_SCORES, KIND_BASE)
    adjust, role_note = _choice(g.roles, role, GOAL_ROLE_SCORES, ROLE_ADJUST)
    lift, stage_note = _choice(g.stages, stage, GOAL_STAGE_SCORES, {})
    part = max(0, min(100, (NEUTRAL if base is None else base) + (adjust or 0) + (lift or 0)))
    words = ", ".join(w + (f" ({n})" if n else "") for w, n in
                      ((KIND_WORDS.get(kind), kind_note), (ROLE_WORDS.get(role), role_note),
                       (STAGE_WORDS.get(stage), stage_note)) if w)
    return part, words, f"its career value is {part}/100 ({words})" + (", by your goals" if g.scores else "")


def _pay(row: dict, target: tuple[float, str] | None, top: float) -> tuple[int, str, str]:
    """(part, input, phrase): the pay known for the job (offered, else the base they gave, else as posted), the
    middle of its range, against your target; with no target, against the highest of these. The middle, not the top:
    a nationwide band ("$94K-$316K") isn't what anyone is paid. At the target is 80, 10% over 100, 10% under 50,
    30% under 0."""
    figure, what = next(((row[f"{k}_mid"], w) for k, w in (("offered", "offered"), ("base", "base told"))
                         if row[f"{k}_mid"]), (row["pay_mid"], "posted"))
    if not figure:
        return NEUTRAL, "no pay known", "no pay is known yet"
    ratio = figure / target[0] if target else figure / top
    part = max(0, min(100, round(80 + (ratio - 1) * 300)))
    against = f"your {target[1]} target" if target else "the best of these"
    gap = abs(ratio - 1)
    where = "about at" if gap < 0.03 else f"{gap:.0%} {'over' if ratio > 1 else 'under'}"
    return part, f"{_k(figure)} {what} vs {against}", f"{what} pay {_k(figure)} is {where} {against}"


def _fit(row: dict) -> tuple[int, str, str]:
    fit = row["fit"]
    if not fit:
        return NEUTRAL, "not scored", "it isn't fit-scored yet"
    s = round(fit["score"])
    return s, f"fit {s}/100, must-haves {fit['met']}/{fit['total']}", f"fit is {s}/100"


def _progress(row: dict) -> tuple[int, str, str]:
    s = row["status"]
    words = {"offer": "it is already an offer", "interviewing": "you are interviewing",
             "screening": "it is only at screening", "applied": "you have only applied"}
    return PROGRESS.get(s, 0), s, words.get(s, f"it is {s}")


def _health(row: dict) -> tuple[int, str, str]:
    """Start at 70 for a company we know a little of; public +10; a rating of 4.0+ +10, under 3.3 -10; recent
    layoffs -25; shrinking headcount -10, growing +10; a private company that raised under THIN -15; a risk note
    -10. Nothing known is NEUTRAL."""
    h = row["health"]
    if not h or not any(h.get(k) for k in ("listing", "stage", "raised", "layoffs", "rating", "risk", "headcount")):
        return NEUTRAL, "no company health kept", "nothing is kept on the company's health"
    part, notes, bad = 70, [], []
    if h["listing"] == "public":
        part += 10
        notes.append("public")
    if h["layoffs"] and not _NONE.match(h["layoffs"]):
        part -= 25
        bad.append("recent layoffs")
    if h["headcount"]:
        words = h["headcount"].lower()
        # a range of counts ("66-128") is no fall: only a signed number ("-5%") or a word says so
        if re.search(r"\b(shrink|declin|down|fall|cut)|(?<![\w.])-\d", words):
            part -= 10
            bad.append("shrinking headcount")
        elif re.search(r"\b(grow|up\b|rising|hiring)|(?<![\w.])\+\d", words):
            part += 10
            notes.append("growing headcount")
    if h["rating"] and (m := re.search(r"\d(?:\.\d+)?", h["rating"])):
        rating = float(m.group())
        if rating >= 4.0:
            part += 10
            notes.append(f"rated {rating:g}")
        elif rating < 3.3:
            part -= 10
            bad.append(f"rated {rating:g}")
    raised = amount(h["raised"])
    if h["listing"] != "public" and raised and raised[1] < THIN:
        part -= 15
        bad.append(f"thin funding ({_k(raised[1])} raised)")
    if h["risk"]:
        part -= 10
        bad.append("a risk noted")
    part = max(0, min(100, part))
    phrase = ("its health counts against it: " + ", ".join(bad)) if bad else \
        ("its health looks fine" + (f" ({', '.join(notes)})" if notes else ""))
    return part, ", ".join(notes + bad + (["stale"] if h["stale"] else [])) or "kept", phrase


def _shown(p: tuple) -> dict:
    """A part as the API sends it; known is False when it had nothing to go on (scored NEUTRAL, not a real 50)."""
    return {"score": p[0], "input": p[1], "known": p[1] not in UNKNOWN}


def part_text(k: str, p: dict) -> str:
    """'health 80 (public)', or 'health ? (no company health kept, counts as 50)' when nothing is known."""
    return f"{k} {p['score']} ({p['input']})" if p.get("known", True) else f"{k} ? ({p['input']}, counts as {NEUTRAL})"


def suggest(cfg: Config, rows: list[dict]) -> dict:
    """{"weights", "target", "ranking"}: the opportunities best first, by the weighted sum of five parts (career
    value, pay against your target, fit, how far along, company health), each part 0-100 with the input it came
    from, and a sentence on why: the strongest reason for it, and the weakest if that is a worry. The weights are
    the watchlist's comps.weights (see WEIGHTS for the default). Only rules, no model: the same data gives the
    same ranking."""
    weights = cfg.comps.weights
    target = _target(cfg)
    top = max((r[f"{k}_mid"] for r in rows for k in ("offered", "base") if r[f"{k}_mid"]), default=0) \
        or max((r["pay_mid"] or 0 for r in rows), default=0) or 1
    ranking = []
    for r in rows:
        parts = dict(zip(WEIGHTS, (_career(r, cfg.goals), _pay(r, target, top), _fit(r), _progress(r), _health(r)),
                         strict=True))
        total = round(sum(weights[k] * p[0] for k, p in parts.items()))
        known = {k: p for k, p in parts.items() if p[1] not in UNKNOWN}
        best = max(known, key=lambda k: parts[k][0] * weights[k], default=None)
        worst = min(parts, key=lambda k: parts[k][0])
        reason = (parts[best][2] if best else "little is known about it yet")
        reason = reason[0].upper() + reason[1:]
        if parts[worst][0] < 50 and worst != best:
            reason += f", but {parts[worst][2]}"
        ranking.append({"key": r["key"], "company": r["company"], "title": r["title"], "total": total,
                        "reason": reason + ".",
                        "parts": {k: _shown(p) for k, p in parts.items()}})
    ranking.sort(key=lambda x: -x["total"])
    return {"weights": weights, "target": target[1] if target else None, "ranking": ranking}


def worth(cfg: Config, store: Store, jobs: list[tuple]) -> dict[str, dict]:
    """{job key: {"score", "parts"}}: how worth it each (job, fit) pair is, for Today's and the queue's "Worth it"
    order. The same rules as the Comps suggestion (career, pay, fit, company health; the comps.weights, scaled to
    add up to 1 without progress, which a job not applied to yet has none of), from what is kept: the pay is the
    middle of the posted range (or what a recruiter told you, if kept), the career and health those of its
    company, and a part with nothing to go on is NEUTRAL. fit is the stored score as the lists carry it, or None.
    Health and comp details are read once for all of them, so thousands of jobs are cheap."""
    healths, kept, target = store.healths(), store.comps(), _target(cfg)
    aged_by: dict[str, dict | None] = {}
    rows = []
    for job, fit in jobs:
        company = company_key(job.display_company)
        if company not in aged_by:
            aged_by[company] = aged(healths.get(company))
        comp = kept.get(job.key) or {}
        read = {k: amount(comp.get(k)) for k in ("base", "offered")}
        posted = [p for p in (job.salary_min, job.salary_max) if p]
        rows.append({"key": job.key, "status": "", "health": aged_by[company], "comp": comp,
                     "fit": {"score": fit["score"], "met": fit.get("must_haves_met"),
                             "total": fit.get("must_haves_total")} if fit else None,
                     **{f"{k}_mid": (r[0] + r[1]) / 2 if r else None for k, r in read.items()},
                     "pay_mid": sum(posted) / len(posted) if posted else None})
    top = max((r[f"{k}_mid"] for r in rows for k in ("offered", "base") if r[f"{k}_mid"]), default=0) \
        or max((r["pay_mid"] or 0 for r in rows), default=0) or 1
    weights = {k: w for k, w in cfg.comps.weights.items() if k != "progress"}
    scale = sum(weights.values())
    out = {}
    for r in rows:
        parts = {"career": _career(r, cfg.goals), "pay": _pay(r, target, top), "fit": _fit(r), "health": _health(r)}
        score = sum(weights[k] * p[0] for k, p in parts.items()) / scale if scale else NEUTRAL
        out[r["key"]] = {"score": round(score), "parts": {k: _shown(p) for k, p in parts.items()}}
    return out


def _company_row(name: str, healths: dict) -> dict:
    """A column for a company with no job to it: only its health (kept under any spelling of its name, shown under
    the way it was first written)."""
    name = (healths.get(company_key(name)) or {}).get("name") or name.strip()
    return {"key": f"company:{company_key(name)}", "kind": "company", "company": name, "title": "", "url": "",
            "status": "", "applied_at": None, "next_step": None, "follow_up": None, "pay": "", "pay_max": None,
            "places": [], "fit": None, "contacts": [], "comp": dict.fromkeys(COMP_FIELDS), "base_max": None,
            "asked_max": None, "offered_max": None, "pay_mid": None, "base_mid": None, "asked_mid": None,
            "offered_mid": None, "health": aged(healths.get(company_key(name)))}


def choices(store: Store) -> list[dict]:
    """What the page's picker offers to compare: {id, kind, label} for every job queued or applied to (id is its
    key), then every company with health kept that has none of those jobs (id is its name)."""
    jobs = [r for r in store.jobs(("queued", *(s for s in STAGES if s not in ENDED)), include_closed=True)]
    out = [{"id": j.key, "kind": "job", "label": f"{j.display_company}: {j.title} ({rec['status']})"}
           for j, rec in jobs]
    have = {company_key(j.display_company) for j, _ in jobs}
    return out + [{"id": h["name"], "kind": "company", "label": f"{h['name']} (company only)"}
                  for k, h in sorted(store.healths().items()) if k not in have]


def view(cfg: Config, store: Store, stages: tuple[str, ...] = LIVE, keys: list[str] | None = None,
         companies: list[str] | None = None) -> dict:
    """{"stages": [...], "opportunities": [...], "best": {...}}: the applications at these stages, or, when keys
    and/or companies are given, just those: the jobs named in keys (whatever their stage) in that order, then a
    column of only health for each company name, even one with no job. Each has key, kind (job or company),
    company, title, url, status,
    applied_at, next_step, follow_up, pay (as posted), pay_max, places, fit ({score, met, total, gaps, stale}
    or None), contacts, comp (what was kept: base, bonus, equity, signon, asked, offered, note) and base_max,
    asked_max, offered_max: the top of each range written, in dollars, when it can be read (and pay_mid, base_mid,
    asked_mid, offered_mid: each range's middle, which the suggestion weighs), and health (the
    company's, with age_days and stale; None when none is kept). suggestion ranks them (see suggest). best says which
    opportunity (a list of keys: ties share) is highest in pay, base, offered and fit, for the page to mark."""
    bad = [s for s in stages if s not in STAGES or s in ENDED]
    if bad:
        raise ValueError(f"can only compare open application stages ({', '.join(s for s in STAGES if s not in ENDED)})"
                         f", not {', '.join(bad)}")
    if keys or companies:
        found = [store.find(k) for k in keys or []]
    else:
        found = [r for r in store.jobs(stages, include_closed=True) if r[1]["status"] in stages]
        found.sort(key=lambda r: (ORDER.index(r[1]["status"]) if r[1]["status"] in ORDER else len(ORDER),
                                  r[1]["applied_at"] or ""))
    rid = resume_id(cfg.resume, cfg.prompts) if cfg.resume and cfg.resume.is_file() else None
    fits = _fits(store, rid) if rid else {}
    known, kept, healths = load_contacts(cfg), store.comps(), store.healths()
    filings = lca.Index.open(lca.cache_path(cfg))
    rows = []
    for job, rec in found:
        fit, comp = fits.get(job.key), kept.get(job.key) or {}
        read = {k: amount(comp.get(k)) for k in ("base", "asked", "offered")}
        posted = [p for p in (job.salary_min, job.salary_max) if p]
        ranges = {**{f"{k}_max": r[1] if r else None for k, r in read.items()},
                  **{f"{k}_mid": (r[0] + r[1]) / 2 if r else None for k, r in read.items()},
                  "pay_mid": sum(posted) / len(posted) if posted else None}
        rows.append({
            "key": job.key, "kind": "job", "company": job.display_company, "title": job.title, "url": job.url,
            "status": rec["status"], "applied_at": rec["applied_at"], "next_step": rec["next_step"],
            "follow_up": rec["follow_up"], "pay": job.pay(), "pay_max": job.salary_max or job.salary_min,
            "places": job.places, "lca_pay": lca.as_dict(lca.for_job(filings, job)),
            "fit": {"score": fit["score"], "met": fit["must_haves_met"], "total": fit["must_haves_total"],
                    "gaps": (fit.get("gaps") or [])[:MOST_GAPS], "stale": bool(fit.get("stale"))} if fit else None,
            "contacts": [{k: p.get(k) for k in ("name", "position", "why")}
                         for p in (known.at(job.display_company, job.company) if known else [])[:MOST_CONTACTS]],
            "comp": {k: comp.get(k) for k in COMP_FIELDS},
            "health": aged(healths.get(company_key(job.display_company))),
            **ranges})
    if filings:
        filings.close()
    rows += [_company_row(name, healths) for name in companies or [] if company_key(name)]
    best = {"pay": _best(rows, lambda r: r["pay_max"]), "base": _best(rows, lambda r: r["base_max"]),
            "offered": _best(rows, lambda r: r["offered_max"]),
            "fit": _best(rows, lambda r: r["fit"] and round(r["fit"]["score"]))}
    return {"stages": list(stages), "today": date.today().isoformat(), "opportunities": rows, "best": best,
            "choices": choices(store), "suggestion": suggest(cfg, [r for r in rows if r["kind"] == "job"])}


def text(v: dict) -> str:
    """The same comparison for the terminal: one block per opportunity, furthest along first, with * after the
    highest in a row."""
    rows, best = v["opportunities"], v["best"]
    if not rows:
        return f"Nothing to compare: no applications at {', '.join(v['stages'])} (--applied adds the applied ones)."

    def star(r: dict, name: str, value: str | None) -> str:
        return value + (" *" if value and r["key"] in best[name] else "") if value else ""

    blocks = []
    for r in rows:
        c, fit = r["comp"], r["fit"]
        follow = f"(follow up {r['follow_up']})" if r["follow_up"] else ""
        next_step = " ".join(x for x in (r["next_step"], follow) if x)
        fit_line = ""
        if fit:
            fit_line = f"{fit['score']:.0f}/100, must-haves {fit['met']}/{fit['total']}"
            fit_line += " *" if r["key"] in best["fit"] else ""
            fit_line += f"; gaps: {'; '.join(fit['gaps'])}" if fit["gaps"] else ""
        know = "; ".join(p["name"] + (f" ({p['position']})" if p["position"] else "") for p in r["contacts"])
        rest = [("applied", r["applied_at"]), ("next", next_step), ("place", "; ".join(r["places"])),
                ("posted pay", star(r, "pay", r["pay"])), ("H-1B filings", (r.get("lca_pay") or {}).get("line")),
                ("base", star(r, "base", c["base"])), ("bonus", c["bonus"]),
                ("equity", c["equity"]), ("sign-on", c["signon"]), ("asked", c["asked"]),
                ("offered", star(r, "offered", c["offered"])), ("fit", fit_line), ("know", know),
                ("note", c["note"]), ("role", ROLE_WORDS.get(c["role"])), ("career note", c["career_note"]),
                *health_lines(r["health"]), ("link", r["url"]), ("key", r["key"])]
        head = (f"{r['company']}: {r['title']} [{r['status']}]" if r["kind"] == "job"
                else f"{r['company']} [company only]")
        blocks.append("\n".join([head]
                                + [f"  {name}: {value}" for name, value in rest if value]))
    ranked = suggestion_text(v["suggestion"]) + "\n\n" if v["suggestion"]["ranking"] else ""
    return (ranked + "\n\n".join(blocks)
            + ("\n\n* highest in its row" if any(best.values()) else ""))


def health_lines(h: dict | None) -> list[tuple[str, str]]:
    """A company's health as (label, value) rows, with a note when it is old: "as of 2026-05-01 (stale, 176 days)"."""
    if not h:
        return []
    when = f"as of {h['as_of']}" + (f" (stale, {h['age_days']} days)" if h["stale"] and h["age_days"] else "") \
        if h["as_of"] else "no date given (stale)"
    rows = [("company", " / ".join(x for x in (h["listing"], h["stage"]) if x)),
            ("kind", KIND_WORDS.get(h["kind"])), ("raised", h["raised"]),
            ("revenue", h["revenue"]), ("headcount", h["headcount"]), ("layoffs", h["layoffs"]),
            ("rating", h["rating"]), ("risk", h["risk"]), ("sources", h["sources"]), ("health", when)]
    return [(label, value) for label, value in rows if value]


def suggestion_text(s: dict) -> str:
    """The ranking with the weights and each part, for the terminal."""
    weights = ", ".join(f"{k} {w:.0%}" for k, w in s["weights"].items())
    out = [f"Suggestion (pay {'vs your ' + s['target'] + ' target' if s['target'] else 'vs the best of these'}; "
           f"weights: {weights})"]
    for n, r in enumerate(s["ranking"], 1):
        parts = ", ".join(part_text(k, p) for k, p in r["parts"].items())
        out += [f"  {n}. {r['company']}: {r['title']}  {r['total']}/100", f"     {r['reason']}", f"     {parts}"]
    return "\n".join(out)


