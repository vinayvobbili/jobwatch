"""A person's roles, from the text of their LinkedIn experience page: who the interviewer is, for a prep sheet.

The person copies the page text (linkedin.com/in/<slug>/details/experience/, as their own browser shows it, or a
browser tool's page text) and gives it here. jobwatch never reads linkedin.com (its robots.txt disallows every
page): this only parses text it is handed and never fetches anything. The page's sidebars and footer ("More
profiles for you", the language list) are dropped.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass, field

MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
WHEN = rf"(?:{MONTH} )?\d{{4}}"
DURATION = r"(?:\d+ yrs?(?: \d+ mos?)?|\d+ mos?)"
DATES = re.compile(rf"^({WHEN}) - ({WHEN}|Present)(?: · ({DURATION}))?$")
KIND = r"(?:Full-time|Part-time|Contract|Self-employed|Freelance|Internship|Apprenticeship|Seasonal|Temporary)"
COMPANY_KIND = re.compile(rf"^(.+?) · {KIND}$")
GROUP_SPAN = re.compile(rf"^(?:{KIND} · )?{DURATION}$")
WORKPLACE = {"Hybrid", "Remote", "On-site"}
END = ("More profiles for you", "People also viewed", "People you may know", "Explore premium profiles")


@dataclass
class Role:
    title: str
    company: str
    start: str
    end: str
    duration: str = ""
    location: str = ""
    workplace: str = ""
    bullets: list[str] = field(default_factory=list)

    @property
    def dates(self) -> str:
        return f"{self.start} – {self.end}"


def _body(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if "Experience" in lines:
        lines = lines[lines.index("Experience") + 1:]
    stop = next((i for i, line in enumerate(lines) if line in END or (line == "About" and i + 1 < len(lines)
                 and lines[i + 1] == "Accessibility")), len(lines))
    return lines[:stop]


def _bullets(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        if line[:2] in ("- ", "• "):
            out.append(line[2:].strip())
        elif out:
            out[-1] += " " + line  # a bullet the page wrapped onto the next line
        else:
            out.append(line)
    return out


def roles(text: str) -> list[Role]:
    """The roles on the page text, newest first as the page lists them; empty when it has none."""
    lines = _body(text)
    dated = [i for i, line in enumerate(lines) if DATES.match(line)]
    groups = [i for i in range(len(lines) - 1) if GROUP_SPAN.match(lines[i + 1]) and not DATES.match(lines[i])]
    # A role on its own reads Title, "Company · Full-time" (or just "Company"), dates. A company with several
    # roles has a header (its name, then "Full-time · 3 yrs") and each role under it reads Title, dates. A role
    # on its own closes the group above it. Text alone can't tell a type-less "Company" line just after a group
    # from another role in that group; it's read as another role in the group.
    starts, companies, group, prev = {}, {}, None, -1
    for d in dated:
        if any(prev < g < d for g in groups):
            group = max(g for g in groups if g < d)
        if d >= 2 and (m := COMPANY_KIND.match(lines[d - 1])):
            starts[d], companies[d], group = d - 2, m.group(1), None
        elif group is not None:
            starts[d], companies[d] = d - 1, lines[group]
        else:
            starts[d], companies[d] = d - 2, lines[d - 1]
        prev = d
    out = []
    for n, d in enumerate(dated):
        company = companies[d]
        later = [starts[x] for x in dated[n + 1:]] + [g for g in groups if g > d]
        rest = lines[d + 1:min(later, default=len(lines))]
        workplace = next((line for line in rest if line in WORKPLACE), "")
        rest = [line for line in rest if line not in WORKPLACE]
        # A location is a short line before any bullet ("Israel", "Austin, Texas, United States"); a line that
        # reads like a sentence is the description.
        location = (rest.pop(0) if rest and rest[0][:2] not in ("- ", "• ") and len(rest[0]) <= 60
                    and not rest[0].endswith(".") else "")
        start, end, duration = DATES.match(lines[d]).groups()
        out.append(Role(lines[starts[d]], company, start, end, duration or "", location, workplace, _bullets(rest)))
    return out


def render(found: list[Role], fmt: str) -> str:
    """The roles as text (one block each), json, or an html <ul> to paste into a prep sheet."""
    if fmt == "json":
        return json.dumps([asdict(r) for r in found], indent=2)
    if fmt == "html":
        items = []
        for r in found:
            where = " · ".join(x for x in (r.dates, r.location) if x)
            sub = "".join(f"<li>{html.escape(b)}</li>" for b in r.bullets)
            items.append(f"<li><b>{html.escape(r.company)}:</b> {html.escape(r.title)} ({html.escape(where)})"
                         + (f"<ul>{sub}</ul>" if sub else "") + "</li>")
        return "<ul>\n" + "\n".join(items) + "\n</ul>"
    blocks = []
    for r in found:
        head = f"{r.title}, {r.company} ({r.dates}" + (f", {r.duration}" if r.duration else "") + ")"
        extra = " · ".join(x for x in (r.location, r.workplace) if x)
        blocks.append("\n".join([head] + ([f"  {extra}"] if extra else []) + [f"  - {b}" for b in r.bullets]))
    return "\n".join(blocks)
