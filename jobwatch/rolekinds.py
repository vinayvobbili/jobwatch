"""The kinds of work a job's title names (cyber and security, automation, AI and ML, forward deployed, software
engineering), for Today's Roles checkboxes: untick one and the jobs that are only that kind leave the wall. A
title can name several ("Security Software Engineer" is security and software engineering) and stays while any
of its kinds is ticked; one that names none is "other"."""

from __future__ import annotations

import re

# (key, label, title pattern), in the order the page lists them.
ROLE_KINDS = (
    ("security", "Cyber & security", r"security|cyber\w*|threat\w*|detection|incident|soc|soar|siem|secops|appsec|"
                                     r"devsecops|forensic\w*|vulnerabilit\w*|iam|identity|zero trust"),
    ("automation", "Automation", r"automation|automate\w*|soar|orchestration|workflows?|rpa"),
    ("ai", "AI & ML", r"ai|a\.i\.|ml|llms?|gen ?ai|agent\w*|machine learning|artificial intelligence|deep learning|"
                      r"nlp|inference|applied scien\w*|data scien\w*"),
    ("forward", "Forward deployed", r"forward[- ]deployed|fde|solutions? (engineer|architect)\w*|"
                                    r"(field|customer) engineer\w*"),
    ("software", "Software engineering", r"software|developer|engineer\w*|swe|full[- ]?stack|back[- ]?end|"
                                         r"platform|infrastructure|sre|reliability|devops|architect\w*"),
)
OTHER = ("other", "Other")
_PATTERNS = [(key, re.compile(rf"\b({pattern})\b", re.I)) for key, _, pattern in ROLE_KINDS]


def role_kinds(title: str) -> list[str]:
    """The kinds of work the title names, in ROLE_KINDS order; ["other"] when it names none."""
    return [key for key, pattern in _PATTERNS if pattern.search(title or "")] or [OTHER[0]]


def labels() -> list[list[str]]:
    """[key, label] of every kind, "other" last, for the page."""
    return [[key, label] for key, label, _ in ROLE_KINDS] + [list(OTHER)]
