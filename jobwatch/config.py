"""The watchlist file: which company boards to check, and what counts as a match."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .filters import Filters
from .sources import SOURCES

DEFAULT_PATHS = (Path("jobwatch.yaml"), Path.home() / ".config" / "jobwatch" / "config.yaml")
DEFAULT_STATE = Path.home() / ".local" / "share" / "jobwatch" / "state.db"
DEFAULT_CACHE = Path(os.environ.get("JOBWATCH_CACHE", Path.home() / ".cache" / "jobwatch"))


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Board:
    source: str
    board: str
    name: str = ""

    @property
    def label(self) -> str:
        return self.name or self.board


@dataclass
class Config:
    path: Path
    boards: list[Board]
    filters: Filters = field(default_factory=Filters)
    keywords: dict[str, float] = field(default_factory=dict)
    resume: Path | None = None
    connections: Path | None = None  # LinkedIn Connections.csv, for "you know someone there"
    backend: str = "local"
    score_top: int = 0
    auto_score: bool = True    # the page scores new matches in the background (default: on for local only)
    timeline: str = "quarter"  # how soon you want to close a skill gap: see TIMELINES
    near: str = ""             # a city, for certificate programs at colleges nearby
    theme: str = "system"      # the page: see THEMES and WIDTHS
    width: str = "standard"
    state: Path = DEFAULT_STATE
    cache: Path = DEFAULT_CACHE
    # Boards from a source this jobwatch doesn't know (a newer version's, or a typo): kept in the file and
    # shown as errors, skipped when checking for jobs, so one bad entry doesn't stop everything else.
    unknown: list[Board] = field(default_factory=list)


UNKNOWN_SOURCE = "unknown source: update jobwatch or remove this board"


def _board(entry, path: Path, strict: bool = True) -> Board:
    """ "greenhouse:anthropic", or {source: greenhouse, board: anthropic, name: Anthropic}.
    Not strict: a source this version doesn't know is let through (see Config.unknown)."""
    if isinstance(entry, str):
        source, _, board = entry.partition(":")
        entry = {"source": source, "board": board}
    if not isinstance(entry, dict) or not entry.get("source") or not entry.get("board"):
        raise ConfigError(f"{path}: companies entries look like 'greenhouse:anthropic', got {entry!r}")
    if strict and entry["source"] not in SOURCES:
        raise ConfigError(f"{path}: unknown source {entry['source']!r} (supported: {', '.join(SOURCES)})")
    return Board(str(entry["source"]), str(entry["board"]), entry.get("name", ""))


def _path(value, base: Path) -> Path:
    p = Path(os.path.expandvars(str(value))).expanduser()
    return p if p.is_absolute() else base / p


def find_config(explicit: str | Path | None = None) -> Path:
    candidates = [Path(explicit)] if explicit else (
        [Path(os.environ["JOBWATCH_CONFIG"])] if os.environ.get("JOBWATCH_CONFIG") else list(DEFAULT_PATHS))
    for p in candidates:
        p = p.expanduser()
        if p.is_file():
            return p
    raise ConfigError(f"no config found (looked for {', '.join(map(str, candidates))}); "
                      "create one with `jobwatch init`")


def locate(explicit: str | Path | None = None) -> Path:
    """The watchlist to use, even if it doesn't exist yet (then: where a new one goes)."""
    try:
        return find_config(explicit)
    except ConfigError:
        if explicit or os.environ.get("JOBWATCH_CONFIG"):
            return Path(explicit or os.environ["JOBWATCH_CONFIG"]).expanduser()
        return DEFAULT_PATHS[1]


SETTINGS = ("companies", "filters", "keywords", "resume", "connections", "scoring", "learning", "display")
TIMELINES = ("week", "month", "quarter", "any")  # this week, this month, the next few months, no rush
THEMES = ("system", "light", "dark")          # the page's colors; system follows the computer's setting
WIDTHS = ("standard", "wide", "full")         # how wide the page grows on a big monitor


def _near(learning: dict, filters: Filters) -> str:
    """The city for nearby programs: as set, else the first place in the location filter that isn't remote."""
    if "near" in learning:
        return str(learning["near"] or "").strip()
    return next((loc.strip() for loc in filters.locations if loc.strip() and "remote" not in loc.lower()
                 and not re.search(r"[\\^$*+?()[\]{}|]", loc)), "")


def save(path: Path, settings: dict) -> Config:
    """Update the watchlist's settings (other keys, such as state, are kept) and write it.

    The new file is checked before it replaces the old one, which is kept as <name>.bak.
    Comments in a hand-written file are not kept."""
    unknown = set(settings) - set(SETTINGS)
    if unknown:
        raise ConfigError(f"unknown setting(s): {', '.join(sorted(unknown))}")
    raw = (yaml.safe_load(path.read_text()) or {}) if path.is_file() else {}
    for key, value in settings.items():
        if value in (None, "", [], {}):
            raw.pop(key, None)
        else:
            raw[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "# jobwatch watchlist, saved by jobwatch. Docs: https://github.com/vinayvobbili/jobwatch\n" + \
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)
    tmp = path.with_name(path.name + ".new")
    tmp.write_text(text, encoding="utf-8")
    try:
        cfg = load(tmp)
    except ConfigError as e:
        tmp.unlink()
        raise ConfigError(str(e).replace(str(tmp), str(path))) from None
    except Exception:
        tmp.unlink()
        raise
    if path.is_file():
        path.replace(path.with_name(path.name + ".bak"))
    tmp.replace(path)
    cfg.path = path
    return cfg


def _companies(path: Path) -> list:
    return list(((yaml.safe_load(path.read_text()) or {}) if path.is_file() else {}).get("companies") or [])


def _same(entry, board: Board, path: Path) -> bool:
    b = _board(entry, path, strict=False)
    return (b.source, b.board) == (board.source, board.board)


def add_board(path: Path, entry: str, name: str = "") -> Config:
    """Add a board ("greenhouse:stripe", as find_board gives it) to the watchlist, creating the file if needed.
    Adding one that's already there only updates its name, when one is given."""
    new = _board(entry, path)
    item = {"source": new.source, "board": new.board, "name": name} if name else f"{new.source}:{new.board}"
    companies = _companies(path)
    at = next((i for i, e in enumerate(companies) if _same(e, new, path)), None)
    if at is None:
        companies.append(item)
    elif name:
        companies[at] = item
    return save(path, {"companies": companies})


def remove_board(path: Path, entry: str) -> Config:
    """Take a board ("greenhouse:stripe") off the watchlist. Jobs already recorded from it are kept.
    One from a source this version doesn't know can be taken off too."""
    gone = _board(entry, path, strict=False)
    companies = _companies(path)
    kept = [e for e in companies if not _same(e, gone, path)]
    if len(kept) == len(companies):
        raise ConfigError(f"{entry!r} isn't on the watchlist")
    return save(path, {"companies": kept})


def load(explicit: str | Path | None = None) -> Config:
    path = find_config(explicit)
    raw = yaml.safe_load(path.read_text()) or {}
    base = path.parent
    try:
        filters = Filters.from_dict(raw.get("filters"))
    except (TypeError, ValueError) as e:
        raise ConfigError(f"{path}: {e}") from None
    scoring = raw.get("scoring") or {}
    backend = scoring.get("backend", "local")
    # On by default only for the on-device model: with Claude every score is a paid API call.
    auto_score = scoring.get("auto", backend == "local")
    if not isinstance(auto_score, bool):
        raise ConfigError(f"{path}: scoring.auto must be true or false, got {auto_score!r}")
    learning = raw.get("learning") or {}
    timeline = str(learning.get("timeline", "quarter"))
    if timeline not in TIMELINES:
        raise ConfigError(f"{path}: learning.timeline must be one of {', '.join(TIMELINES)}, got {timeline!r}")
    display = raw.get("display") or {}
    theme, width = str(display.get("theme", "system")), str(display.get("width", "standard"))
    if theme not in THEMES:
        raise ConfigError(f"{path}: display.theme must be one of {', '.join(THEMES)}, got {theme!r}")
    if width not in WIDTHS:
        raise ConfigError(f"{path}: display.width must be one of {', '.join(WIDTHS)}, got {width!r}")
    listed = [_board(e, path, strict=False) for e in raw.get("companies") or []]
    dupes = {b for b in listed if listed.count(b) > 1}
    if dupes:
        raise ConfigError(f"{path}: listed twice: {', '.join(f'{b.source}:{b.board}' for b in dupes)}")
    boards = [b for b in listed if b.source in SOURCES]
    return Config(
        path=path, boards=boards, unknown=[b for b in listed if b.source not in SOURCES], filters=filters,
        keywords={str(k): float(v) for k, v in (raw.get("keywords") or {}).items()},
        resume=_path(raw["resume"], base) if raw.get("resume") else None,
        connections=_path(raw["connections"], base) if raw.get("connections") else None,
        backend=backend, score_top=int(scoring.get("top", 0)), auto_score=auto_score,
        timeline=timeline, near=_near(learning, filters), theme=theme, width=width,
        state=_path(raw["state"], base) if raw.get("state") else DEFAULT_STATE,
        cache=_path(raw["cache"], base) if raw.get("cache") else DEFAULT_CACHE,
    )


EXAMPLE = """\
# jobwatch watchlist. Docs: https://github.com/vinayvobbili/jobwatch
#
# Find a company's board with:  jobwatch find "Company Name"   (or paste a careers/job link)

companies:
  - greenhouse:anthropic
  - lever:spotify
  - ashby:openai
  # - {source: greenhouse, board: stripe, name: Stripe}

filters:
  titles: ["engineer", "developer"]            # regexes; the title must match one
  exclude_titles: ["intern", "manager"]
  locations: ["remote", "New York"]            # "remote" = remote in remote_country; other text is matched
  remote_country: US                           # or "any"
  min_salary: 150000                           # listed pay must reach this; jobs without pay still pass
  max_age_days: 30
  # flags:                                     # not filters: warnings on queued jobs whose posting says this
  #   "active (TS|top secret)": clearance

# Relevance: keyword -> weight. Title hits count double. Prefix "re:" for a regex.
keywords:
  Python: 2
  machine learning: 2
  distributed systems: 1

# Optional fit scoring with shortlist-ai (pip install 'jobwatch[score]').
# resume: ~/Documents/resume.pdf
scoring:
  backend: claude        # claude (ANTHROPIC_API_KEY) or local (Apple Silicon, pip install 'jobwatch[local]')
  top: 0                 # score this many of the most relevant new jobs per digest
  # auto: true           # `jobwatch ui` scores every new match in the background (default: on for local)

# Optional: LinkedIn's Connections.csv, to show who you know at each company (a referral beats applying cold).
# connections: ~/Downloads/Connections.csv

# state: ~/.local/share/jobwatch/state.db
"""
