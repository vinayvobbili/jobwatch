"""Degree requirements a fit score called a gap, though your education meets them.

A fit score judges each requirement against the resume as the scorer's model read it, and it can lose a degree's
level on the way ("MS in Computer Science" read as a subject with no level), so a posting's "Bachelor's degree in
Computer Science or a related discipline" comes back partly met and lands among the gaps. The profile jobwatch
reads (profile.yaml, the facts resume-kit builds resumes from: next to the watchlist, else resume-kit's content
folder) lists the degrees themselves. Where a gap is a plain degree requirement and a degree in the profile is at
that level or above, in the field asked for (or a related one, when the posting says so), the gap is dropped
and counts as met. The score itself isn't changed, and nothing is scored again.

Conservative on purpose: a PhD requirement, a field the profile lacks, and a line that also asks for years of
experience, a certification or a clearance are left alone. With no education in the profile nothing changes.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

SEPARATOR = " · "  # how a gap string can join several requirements
LEVELS = {1: "bachelor's", 2: "master's", 3: "doctorate"}

# A level named in words, or by an abbreviation (case matters: "MS Office" is no degree).
_DOCTORATE = re.compile(r"ph\.?\s?d\b|doctor(?:ate|al)?\b", re.I)
_MASTER_WORD = re.compile(r"\bmaster(?:'?s)?\b|\bgraduate degree\b", re.I)
_BACHELOR_WORD = re.compile(r"\bbachelor(?:'?s)?\b|\bundergraduate\b", re.I)
_MASTER_ABBR = re.compile(r"(?<![A-Za-z])(?:M\.?S\.?c?|M\.?Tech|M\.?Eng|MBA)(?![A-Za-z])")
_BACHELOR_ABBR = re.compile(r"(?<![A-Za-z])(?:B\.?S\.?c?|B\.?Tech|B\.?E\.|B\.?Eng|B\.?A\.)(?![A-Za-z])")
# What makes a gap a degree requirement: a word, or an abbreviation followed by its subject ("BS in Physics").
_DEGREE_WORD = re.compile(r"\bdegrees?\b|\bbachelor|\bmaster(?:'?s)?\b|\bundergraduate\b|ph\.?\s?d\b|\bdoctorate\b",
                          re.I)
_ABBR_IN = re.compile(r"(?<![A-Za-z])(?:B\.?S\.?c?|B\.?A\.|M\.?S\.?c?|MBA)\s+in\b")
_EXPERIENCE_ALTERNATIVE = re.compile(r"\b(?:or\s+)?(?:equivalent|related|relevant|practical|work|professional)"
                                     r"(?:\s+work)?\s+experience\b", re.I)
# What else a line asks for makes it more than a degree: dropping it would hide the rest.
_MORE_THAN_DEGREE = re.compile(r"\byears?\b|\byrs?\b|\bexperience\b|certif|clearance|licen[cs]e|proficien", re.I)
_QUALIFIER = re.compile(r"\brelated\b|\brelevant\b|\bequivalent\b|\bsimilar\b|\btechnical\b|\banalytical\b"
                        r"|\bquantitative\b|\bscientific\b|\bSTEM\b", re.I)
_SUBJECT_FILLER = re.compile(r"\bof\s+(?:science|arts)\b", re.I)
_NAMED_FIELD = re.compile(r"\b(?:in|majoring in)\s+(?:an?\s+|the\s+)?(?!an?\b|the\b|related\b|relevant\b|technical\b"
                          r"|similar\b|equivalent\b|quantitative\b|analytical\b|scientific\b|STEM\b)([A-Za-z]+)", re.I)
# Subjects a technical posting means, by family: a degree in the same family as the posting's names it.
_FAMILIES = {
    "computing": re.compile(r"comput|software|informatic|information (?:technology|systems|science)|cyber|\bIT\b",
                            re.I),
    "engineering": re.compile(r"engineering|technology", re.I),
    "math": re.compile(r"mathemat|statistic|\bdata\b|analytic|quantitative|operations research", re.I),
    "physics": re.compile(r"physic", re.I),
}


@dataclass(frozen=True)
class Degree:
    level: int           # 1 bachelor's, 2 master's, 3 doctorate
    text: str            # as the profile writes it ("MS in Computer Science, ...")
    fields: frozenset    # the subject families it names (_FAMILIES)

    @property
    def technical(self) -> bool:
        return bool(self.fields)


def _families(text: str) -> frozenset:
    return frozenset(name for name, rx in _FAMILIES.items() if rx.search(text))


def level_in(text: str) -> set[int]:
    """The degree levels a text names."""
    found = set()
    if _DOCTORATE.search(text):
        found.add(3)
    if _MASTER_WORD.search(text) or _MASTER_ABBR.search(text):
        found.add(2)
    if _BACHELOR_WORD.search(text) or _BACHELOR_ABBR.search(text):
        found.add(1)
    return found


def parse_degree(text: str) -> Degree | None:
    """One degree line from the profile ("MS in Computer Science, Cybersecurity concentration"); None when it
    names no level jobwatch knows."""
    if not (levels := level_in(text)):
        return None
    return Degree(max(levels), " ".join(text.split()), _families(text))


def profile_file(watchlist: Path) -> Path | None:
    """The profile to read: profile.yaml next to the watchlist, else in resume-kit's content folder
    (RESUME_KIT_CONTENT, else ~/.config/resume-kit/content). None when there is none."""
    content = Path(os.environ.get("RESUME_KIT_CONTENT") or "~/.config/resume-kit/content").expanduser()
    for p in (watchlist.parent / "profile.yaml", content / "profile.yaml"):
        if p.is_file():
            return p
    return None


_CACHE: dict[Path, tuple[float, tuple[Degree, ...]]] = {}


def load(path: Path | None) -> tuple[Degree, ...]:
    """The degrees in the profile's `education:` list, each entry's `degree` (and `field`, if it has one); empty
    when there is no file, no section or a file that doesn't read. Kept until the file changes."""
    if not path:
        return ()
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return ()
    if (hit := _CACHE.get(path)) and hit[0] == stamp:
        return hit[1]
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        raw = None
    items = raw.get("education") if isinstance(raw, dict) else None
    out = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict):
            text = " ".join(str(item[k]) for k in ("degree", "field") if item.get(k))
        else:
            text = str(item)
        if text and (d := parse_degree(text)):
            out.append(d)
    _CACHE[path] = (stamp, tuple(out))
    return _CACHE[path][1]


def required_level(requirement: str) -> int | None:
    """The degree level a requirement asks for (the lowest it names: "Bachelor's or Master's" is a bachelor's); None
    when it isn't a plain degree requirement, or asks for a doctorate, years, a certification and the like."""
    if not (_DEGREE_WORD.search(requirement) or _ABBR_IN.search(requirement)):
        return None
    if _MORE_THAN_DEGREE.search(_EXPERIENCE_ALTERNATIVE.sub("", requirement)):
        return None
    levels = level_in(requirement)
    if 3 in levels:
        return None
    return min(levels) if levels else 1  # a "degree" with no level asks for a bachelor's


def meets(requirement: str, education: tuple[Degree, ...]) -> Degree | None:
    """The degree in the profile that meets a degree requirement, or None (it isn't one, or none does)."""
    if not (need := required_level(requirement)):
        return None
    plain = _SUBJECT_FILLER.sub("", requirement)
    families = _families(plain)
    qualified = bool(_QUALIFIER.search(plain))
    named = _NAMED_FIELD.search(plain)
    enough = sorted((d for d in education if d.level >= need), key=lambda d: d.level)
    if not families:
        return None if named or not enough else enough[0]  # "a bachelor's degree": any field
    # The subject the posting names first, then (when it says "or related") any technical one.
    return next((d for d in enough if d.fields & families), None) or next(
        (d for d in enough if qualified and d.technical), None)


def reconcile(fit: dict | None, education: tuple[Degree, ...]) -> dict | None:
    """The fit with its met degree requirements taken out of the gaps and counted as met. A copy, with
    "reconciled": the notes saying which and why; the fit itself when nothing was met (or there's no education).
    Gaps can join several requirements with " · ": only the degree part goes."""
    if not fit or not education or not fit.get("gaps"):
        return fit
    notes: list[str] = []
    gaps = []
    for gap in fit["gaps"]:
        kept = []
        for part in str(gap).split(SEPARATOR):
            if d := meets(part, education):
                notes.append(f"{part.strip()}: met by your {d.text} (the score was not made again)")
            else:
                kept.append(part)
        if kept:
            gaps.append(SEPARATOR.join(kept))
    if not notes:
        return fit
    out = {**fit, "gaps": gaps, "reconciled": notes}
    total = fit.get("must_haves_total") or 0
    out["must_haves_met"] = min(total, (fit.get("must_haves_met") or 0) + len(notes))  # never past the total
    if fit.get("requirements"):
        out["requirements"] = [_row(r, education) for r in fit["requirements"]]
    return out


def _row(row: dict, education: tuple[Degree, ...]) -> dict:
    """A requirement row, made met when it is a must-have degree requirement the profile meets."""
    if row.get("kind") != "must_have" or row.get("verdict") == "met" or not (d := meets(
            str(row.get("requirement", "")), education)):
        return row
    return {**row, "verdict": "met", "reconciled": f"met by your {d.text}"}
