"""The watchlist file: which company boards to check, and what counts as a match."""

from __future__ import annotations

import os
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
    state: Path = DEFAULT_STATE
    cache: Path = DEFAULT_CACHE


def _board(entry, path: Path) -> Board:
    """ "greenhouse:anthropic", or {source: greenhouse, board: anthropic, name: Anthropic}."""
    if isinstance(entry, str):
        source, _, board = entry.partition(":")
        entry = {"source": source, "board": board}
    if not isinstance(entry, dict) or not entry.get("source") or not entry.get("board"):
        raise ConfigError(f"{path}: companies entries look like 'greenhouse:anthropic', got {entry!r}")
    if entry["source"] not in SOURCES:
        raise ConfigError(f"{path}: unknown source {entry['source']!r} (supported: {', '.join(SOURCES)})")
    return Board(entry["source"], str(entry["board"]), entry.get("name", ""))


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


def load(explicit: str | Path | None = None) -> Config:
    path = find_config(explicit)
    raw = yaml.safe_load(path.read_text()) or {}
    base = path.parent
    try:
        filters = Filters.from_dict(raw.get("filters"))
    except (TypeError, ValueError) as e:
        raise ConfigError(f"{path}: {e}") from None
    scoring = raw.get("scoring") or {}
    boards = [_board(e, path) for e in raw.get("companies") or []]
    dupes = {b for b in boards if boards.count(b) > 1}
    if dupes:
        raise ConfigError(f"{path}: listed twice: {', '.join(f'{b.source}:{b.board}' for b in dupes)}")
    return Config(
        path=path, boards=boards, filters=filters,
        keywords={str(k): float(v) for k, v in (raw.get("keywords") or {}).items()},
        resume=_path(raw["resume"], base) if raw.get("resume") else None,
        connections=_path(raw["connections"], base) if raw.get("connections") else None,
        backend=scoring.get("backend", "local"), score_top=int(scoring.get("top", 0)),
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

# Optional: LinkedIn's Connections.csv, to show who you know at each company (a referral beats applying cold).
# connections: ~/Downloads/Connections.csv

# state: ~/.local/share/jobwatch/state.db
"""
