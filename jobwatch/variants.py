"""`jobwatch find --try-variants NAME`: a company's name as people write it ("Initech Holdings, Inc.") isn't always the
one its job board goes by. This tries the likely variants of the name in turn, most likely first, and says which one
found a board, so one call replaces several `find` calls.

The variants: the name as given; a name written as one word with inner capitals ("InitechSystems") split into words;
the name without a legal suffix (Inc, LLC, Corp, Ltd, Holding...); that name cut to its first two words (when it has
three or more), and to its first word. Each is looked up the way `find` looks up a name (sources.probe), which
tries the joined and hyphenated board names of its words ("initechsystems", "initech-systems") and the company's own
careers site, so those forms are covered by each variant. A name that's a link, a source:board entry or a domain is
looked up as it is.
"""

from __future__ import annotations

import re

from . import sources

# Legal-form words at the end of a company's name: "Initech Holdings, Inc." is Initech's board's "initech"
SUFFIXES = frozenset({"inc", "incorporated", "llc", "corp", "corporation", "ltd", "limited", "holding", "holdings",
                      "co", "company", "plc", "gmbh", "lp", "llp"})
LEADING = frozenset({"the"})  # not a name's first word: "The Trade Desk" is the board "tradedesk"
MIN_FIRST = 3  # a first word shorter than this ("A", "Go") names too many other companies


def _words(name: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", name)


def _without_suffixes(words: list[str]) -> list[list[str]]:
    """The words with each legal suffix taken off in turn: Initech Holdings Inc -> [Initech Holdings, Initech]."""
    out = []
    while len(words) > 1 and words[-1].lower() in SUFFIXES:
        words = words[:-1]
        out.append(words)
    return out


def _split_caps(word: str) -> list[str]:
    """"InitechSystems" -> Initech, Systems; a word with no inner capital stays whole."""
    return re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+", word) if re.search(r"[a-z0-9][A-Z]", word) else [word]


def names(name: str) -> list[str]:
    """The variants of a company's name to look up, as given first, each name once (a link, a source:board entry or
    a domain gives itself alone)."""
    name = " ".join(name.split())
    if not name or ":" in name or "/" in name or ("." in name and " " not in name):
        return [name] if name else []
    words = _words(name)
    tries = [name]
    if len(words) == 1 and len(split := _split_caps(words[0])) > 1:
        tries.append(" ".join(split))
        words = split
    stages = _without_suffixes(words)
    tries += [" ".join(s) for s in stages]
    stripped = stages[-1] if stages else words
    if len(stripped) > 2:
        tries.append(" ".join(stripped[:2]))
    first = next((w for w in stripped if w.lower() not in LEADING), "")
    if len(first) >= MIN_FIRST and len(stripped) > 1:
        tries.append(first)
    out, seen = [], set()
    for t in tries:
        if t and (same := tuple(w.lower() for w in _words(t))) not in seen:  # "Initech Inc" and "initech-inc" are one
            seen.add(same)
            out.append(t)
    return out


def probe(name: str, limited: set[str] | None = None,
          untested: set[str] | None = None) -> tuple[str, list[tuple[str, str, list]], list[str]]:
    """Look the variants up in turn until one finds a board with open roles: (the variant that found it, its
    boards as sources.probe gives them, the variants tried before it). With none found, the variant that found a
    board with no open roles, if any, else the name as given, with the boards found (if any) and every variant tried.
    `limited` and `untested` are sources.probe's: shared across names, and the sources no answer came from."""
    tried, empty = [], None
    for variant in names(name):
        hits = sources.probe(variant, limited=limited, untested=untested)
        if any(jobs for _, _, jobs in hits):
            return variant, hits, tried
        if hits and empty is None:
            empty = (variant, hits)
        tried.append(variant)
    return (*empty, [t for t in tried if t != empty[0]]) if empty else (name, [], tried)
