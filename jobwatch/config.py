"""The watchlist file: which company boards to check, and what counts as a match."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import timedelta
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
    # The company's own careers site, for a board whose hosted job pages may be offline (see sources.Hosted): its
    # jobs link there then. Not part of what makes two entries the same board.
    careers: str = field(default="", compare=False)

    @property
    def label(self) -> str:
        return self.name or self.board

    @property
    def entry(self) -> str:
        return f"{self.source}:{self.board}"


ALERT_SENDERS = ("jobalerts-noreply@linkedin.com", "builtin.com", "jobalert.indeed.com")


@dataclass(frozen=True)
class Imap:
    """Where `jobwatch alerts --imap` reads job-alert emails (alerts.imap in the watchlist; off unless set).
    The password is never in the watchlist: it comes from the environment variable named by password_env, or
    from the macOS keychain item named by keychain (`security find-generic-password -s <keychain> -a <user>`)."""
    host: str
    user: str
    port: int = 993
    folder: str = "INBOX"
    password_env: str = ""
    keychain: str = ""
    senders: tuple[str, ...] = ALERT_SENDERS  # FROM searches: an address or a domain
    days: int = 3                             # emails from the last N days


def _imap(raw, path: Path) -> Imap | None:
    if not raw:
        return None
    if not isinstance(raw, dict) or not raw.get("host") or not raw.get("user"):
        raise ConfigError(f"{path}: alerts.imap needs host and user (and password_env or keychain)")
    if "password" in raw:
        raise ConfigError(f"{path}: alerts.imap doesn't take a password: put it in an environment variable "
                          "(password_env) or the macOS keychain (keychain), and remove it from the file")
    unknown = set(raw) - set(Imap.__dataclass_fields__)
    if unknown:
        raise ConfigError(f"{path}: unknown alerts.imap setting(s): {', '.join(sorted(unknown))}")
    if not (raw.get("password_env") or raw.get("keychain")):
        raise ConfigError(f"{path}: alerts.imap needs password_env (an environment variable's name) or keychain "
                          "(a macOS keychain item's name) for the password")
    senders = raw.get("senders") or ALERT_SENDERS
    try:
        return Imap(host=str(raw["host"]), user=str(raw["user"]), port=int(raw.get("port", 993)),
                    folder=str(raw.get("folder", "INBOX")), password_env=str(raw.get("password_env", "")),
                    keychain=str(raw.get("keychain", "")),
                    senders=tuple(str(s) for s in ([senders] if isinstance(senders, str) else senders)),
                    days=int(raw.get("days", 3)))
    except (TypeError, ValueError) as e:
        raise ConfigError(f"{path}: alerts.imap: {e}") from None


@dataclass(frozen=True)
class Pay:
    """pay in the watchlist: what a job's level pays at its company, from Levels.fyi (see levels.py). Off unless
    levels is true; off, nothing is ever asked of Levels.fyi."""
    levels: bool = False
    years: int | None = None   # your years of experience: a title without a seniority word gets the level they fit
    region: str = ""           # a Levels.fyi location slug (as in its links), for remote jobs and those near you


def _pay(raw, path: Path) -> Pay:
    if not raw:
        return Pay()
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: pay looks like {{levels: true, years: 10}}, got {raw!r}")
    unknown = set(raw) - set(Pay.__dataclass_fields__)
    if unknown:
        raise ConfigError(f"{path}: unknown pay setting(s): {', '.join(sorted(unknown))}")
    if not isinstance(raw.get("levels", False), bool):
        raise ConfigError(f"{path}: pay.levels must be true or false, got {raw['levels']!r}")
    try:
        years = None if raw.get("years") is None else int(raw["years"])
    except (TypeError, ValueError):
        raise ConfigError(f"{path}: pay.years must be a number of years, got {raw['years']!r}") from None
    return Pay(levels=raw.get("levels", False), years=years, region=str(raw.get("region") or "").strip())


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
    imap: Imap | None = None   # alerts.imap: read job-alert emails from a mailbox (off unless set)
    pay: Pay = field(default_factory=Pay)
    # How often `jobwatch ui` checks the boards by itself (fetch_every); None: only when asked.
    fetch_every: timedelta | None = None
    # Boards from a source this jobwatch doesn't know (a newer version's, or a typo): kept in the file and
    # shown as errors, skipped when checking for jobs, so one bad entry doesn't stop everything else.
    unknown: list[Board] = field(default_factory=list)


UNKNOWN_SOURCE = "unknown source: update jobwatch or remove this board"
_LINK = re.compile(r"https?://[\w-]+(?:\.[\w-]+)+(?:[/?#]\S*)?", re.I)


def _board(entry, path: Path, strict: bool = True) -> Board:
    """ "greenhouse:anthropic", or {source: greenhouse, board: anthropic, name: Anthropic}, or the board as
    source:board in a mapping: {board: "ashby:acme", careers: https://acme.example/careers}. careers is the
    company's own careers site, for when the board's hosted job pages are offline.
    Not strict: a source this version doesn't know is let through (see Config.unknown)."""
    if isinstance(entry, str):
        entry = {"board": entry}
    if isinstance(entry, dict) and not entry.get("source") and ":" in str(entry.get("board") or ""):
        source, _, board = str(entry["board"]).partition(":")
        entry = {**entry, "source": source, "board": board}
    if not isinstance(entry, dict) or not entry.get("source") or not entry.get("board"):
        raise ConfigError(f"{path}: companies entries look like 'greenhouse:anthropic', got {entry!r}")
    if strict and entry["source"] not in SOURCES:
        raise ConfigError(f"{path}: unknown source {entry['source']!r} (supported: {', '.join(SOURCES)})")
    careers = str(entry.get("careers") or "").strip()
    if careers and not _LINK.fullmatch(careers):
        raise ConfigError(f"{path}: {entry['source']}:{entry['board']}: careers is a link to the company's own "
                          f"careers site (https://...), got {careers!r}")
    return Board(str(entry["source"]), str(entry["board"]), entry.get("name") or "", careers)


def _item(b: Board) -> str | dict:
    """A board as the watchlist writes it: "greenhouse:stripe", or a mapping when it has a name or careers link."""
    if not (b.name or b.careers):
        return b.entry
    return {"source": b.source, "board": b.board, **({"name": b.name} if b.name else {}),
            **({"careers": b.careers} if b.careers else {})}


FETCH_EVERY = timedelta(hours=6)  # fetch_every's default
FETCH_LEAST = timedelta(hours=1)  # every check asks every board again: no more often than this
_OFF = ("0", "off", "no", "never", "false")
_EVERY = re.compile(r"(\d+(?:\.\d+)?)\s*(m|mins?|minutes?|h|hrs?|hours?|d|days?)?", re.I)


def _every(raw, path: Path) -> timedelta | None:
    """fetch_every: "6h", "90m", "1d", or a number of hours; 0 or off: never (YAML reads a bare off as false)."""
    if raw is None:
        return FETCH_EVERY
    if raw is False or str(raw).strip().lower() in _OFF:
        return None
    m = _EVERY.fullmatch(str(raw).strip()) if not isinstance(raw, bool) else None
    if not m:
        raise ConfigError(f"{path}: fetch_every looks like 6h, 90m or 1d (or off), got {raw!r}")
    n, unit = float(m.group(1)), (m.group(2) or "h")[0].lower()
    every = timedelta(minutes=n) if unit == "m" else timedelta(days=n) if unit == "d" else timedelta(hours=n)
    if not every:
        return None
    if every < FETCH_LEAST:
        raise ConfigError(f"{path}: fetch_every must be at least 1h (each check asks every board again), "
                          f"got {raw!r}")
    return every


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


SETTINGS = ("companies", "filters", "keywords", "resume", "connections", "scoring", "learning", "display",
            "fetch_every")
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


def add_board(path: Path, entry: str, name: str = "", careers: str = "") -> Config:
    """Add a board ("greenhouse:stripe", as find_board gives it) to the watchlist, creating the file if needed.
    careers: the company's own careers site, for a board whose hosted job pages are offline. Adding one that's
    already there only updates its name and careers link, when given; the rest of its entry is kept."""
    new = _board({"board": entry, "careers": careers}, path)  # checks the careers link too
    companies = _companies(path)
    at = next((i for i, e in enumerate(companies) if _same(e, new, path)), None)
    if at is None:
        companies.append(_item(Board(new.source, new.board, name, new.careers)))
    elif name or new.careers:
        old = _board(companies[at], path, strict=False)
        companies[at] = _item(Board(new.source, new.board, name or old.name, new.careers or old.careers))
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
    alerts = raw.get("alerts") or {}
    if not isinstance(alerts, dict) or set(alerts) - {"imap"}:
        raise ConfigError(f"{path}: alerts has one setting, imap (see the README's job-alert emails section)")
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
        imap=_imap(alerts.get("imap"), path), pay=_pay(raw.get("pay"), path),
        fetch_every=_every(raw.get("fetch_every"), path),
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
  # - {board: ashby:acme, careers: https://acme.example/careers}   # its Ashby pages are offline: link here

# `jobwatch ui` checks every board by itself this often (6h, 90m, 1d; off: only when you press the button).
fetch_every: 6h

filters:
  titles: ["engineer", "developer"]            # regexes; the title must match one
  exclude_titles: ["intern", "manager"]
  locations: ["remote", "New York"]            # "remote" = remote in remote_country; other text is matched
  remote_country: US                           # or "any"
  # home_state: NY                             # leave out remote jobs open only in other states
  min_salary: 150000                          # listed pay must reach this; jobs without pay still pass
  max_age_days: 30
  # min_fit: 70                                # hide jobs whose fit score is below this; unscored ones still show
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
