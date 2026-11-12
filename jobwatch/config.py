"""The watchlist file: which company boards to check, and what counts as a match."""

from __future__ import annotations

import io
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import time, timedelta
from pathlib import Path
from string import Formatter
from urllib.parse import urlsplit

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import LiteralScalarString
from ruamel.yaml.util import load_yaml_guess_indent

from . import GUIDE
from .filters import Filters
from .score import Provider, check_prompts
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
    # Filter settings for this board's jobs only, as written under the entry's filters: (a college's adjunct
    # openings: other titles, hourly pay); each replaces the watchlist's own. Config.filters_for has them merged.
    filters: dict = field(default_factory=dict, compare=False)

    @property
    def label(self) -> str:
        return self.name or self.board

    @property
    def entry(self) -> str:
        return f"{self.source}:{self.board}"


ALERT_SENDERS = ("jobalerts-noreply@linkedin.com", "builtin.com", "jobalert.indeed.com", "match.indeed.com")


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
    every: timedelta | None = None            # the page reads it this often too, between checks; None: only with them
    mark_read: bool = False                   # mark the alert emails it read as read (off: the folder is read-only)


MAIL_LEAST = timedelta(minutes=15)  # alerts.imap.every's floor: alerts come a few times a day, not by the minute


def _mail_every(raw, path: Path) -> timedelta | None:
    """alerts.imap.every: "2h", "90m"; unset, 0 or off: the mailbox is read with each check for new jobs only."""
    if raw is None or raw is False or str(raw).strip().lower() in _OFF:
        return None
    every = duration(raw) if not isinstance(raw, bool) else None
    if every is None:
        raise ConfigError(f"{path}: alerts.imap.every looks like 2h or 90m (or off), got {raw!r}")
    if every and every < MAIL_LEAST:
        raise ConfigError(f"{path}: alerts.imap.every must be at least 15m, got {raw!r}")
    return every or None


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
                    days=int(raw.get("days", 3)), every=_mail_every(raw.get("every"), path),
                    mark_read=raw.get("mark_read") is True)
    except (TypeError, ValueError) as e:
        raise ConfigError(f"{path}: alerts.imap: {e}") from None


def _section(raw, name: str, cls, path: Path, example: str) -> dict:
    """A mapping of settings (pay, chat...): checked for names `cls` doesn't have. A setting left empty is unset."""
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: {name} looks like {example}, got {raw!r}")
    unknown = set(raw) - set(cls.__dataclass_fields__)
    if unknown:
        raise ConfigError(f"{path}: unknown {name} setting(s): {', '.join(sorted(unknown))}")
    return {k: v for k, v in raw.items() if v is not None and v != ""}


def _whole(raw, name: str, path: Path, zero: str) -> int:
    """A setting that's a whole number, 0 or more; `zero` says what 0 means."""
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ConfigError(f"{path}: {name} must be a whole number, 0 or more ({zero}), got {raw!r}")
    return raw


def _between(raw, name: str, path: Path, low: float, high: float | None = None, means: str = "",
             whole: bool = True):
    """A number from low to high (no top without high); `means` says what it is."""
    kinds = int if whole else (int, float)
    if isinstance(raw, bool) or not isinstance(raw, kinds) or raw < low or (high is not None and raw > high):
        span = f"from {low} to {high}" if high is not None else f"{low} or more"
        raise ConfigError(f"{path}: {name} must be a {'whole ' if whole else ''}number {span}"
                          f"{f' ({means})' if means else ''}, got {raw!r}")
    return raw


@dataclass(frozen=True)
class Pay:
    """pay in the watchlist: what a job's level pays at its company, from Levels.fyi (see levels.py). Off unless
    levels is true; off, nothing is ever asked of Levels.fyi."""
    levels: bool = False
    years: int | None = None   # your years of experience: a title without a seniority word gets the level they fit
    region: str = ""           # a Levels.fyi location slug (as in its links), for remote jobs and those near you
    ask_over: float = 10       # percent over the level's median base to ask for: room to meet in the middle
    round: int = 5000          # the ask is rounded up to this (0: not rounded)
    today: int = 15            # Today's jobs (most relevant first) whose pay is looked up
    # Your own numbers, for the prep sheet (annual base, in the posting's currency; 0: not set). The floor is
    # private: it is shown on your own sheet and never put in anything sent to Claude (see prep.py).
    target: int = 0            # what you'd like to be offered (the low end when target_max is set)
    target_max: int = 0        # the top of a target range (0: a single target); `target: 180000-210000` sets both
    floor: int = 0             # the least you'd accept


def _target(raw, path: Path) -> tuple[int, int]:
    """pay.target as (low, high): a whole number, or a range written 180000-210000 or 180K-210K; (n, 0) for one."""
    if isinstance(raw, str):
        parts = [p.strip().lower().replace(",", "").replace("$", "") for p in re.split(r"\s*[-–—]\s*|\s+to\s+", raw)]
        try:
            n = [int(float(p[:-1]) * 1000) if p.endswith("k") else int(p) for p in parts]
        except ValueError:
            n = []
        if len(n) == 2 and 0 < n[0] <= n[1]:
            return n[0], n[1]
        raise ConfigError(f"{path}: pay.target must be a whole number or a range like 180000-210000 "
                          f"(low first), got {raw!r}")
    return _whole(raw, "pay.target", path, "0 leaves it unset"), 0


def _pay(raw, path: Path) -> Pay:
    raw = _section(raw, "pay", Pay, path, "{levels: true, years: 10}")
    if not isinstance(raw.get("levels", False), bool):
        raise ConfigError(f"{path}: pay.levels must be true or false, got {raw['levels']!r}")
    try:
        years = None if raw.get("years") is None else int(raw["years"])
    except (TypeError, ValueError):
        raise ConfigError(f"{path}: pay.years must be a number of years, got {raw['years']!r}") from None
    target, top = _target(raw.get("target", Pay.target), path)
    if "target_max" in raw:
        top = _whole(raw["target_max"], "pay.target_max", path, "0 means a single target")
    if top and top < target:
        raise ConfigError(f"{path}: pay.target_max ({top}) is below pay.target ({target}): the range goes low to high")
    return Pay(levels=raw.get("levels", False), years=years, region=str(raw.get("region") or "").strip(),
               ask_over=_between(raw.get("ask_over", Pay.ask_over), "pay.ask_over", path, 0, 100,
                                 "percent over the level's median base", whole=False),
               round=_whole(raw.get("round", Pay.round), "pay.round", path, "0 doesn't round"),
               today=_whole(raw.get("today", Pay.today), "pay.today", path, "0 looks up none of Today's"),
               target=target, target_max=top if top != target else 0,
               floor=_whole(raw.get("floor", Pay.floor), "pay.floor", path, "0 leaves it unset"))


BACKENDS = ("claude", "local", "agy")  # Anthropic's API, the on-device model (Apple Silicon), or Google's agy CLI
CHAT_BACKENDS = ("claude", "local")  # what the assistant can run on (agy only scores)


def fallback_entry(entry: str) -> tuple[str, str]:
    """A scoring.fallback entry's (backend, model): "agy" is ("agy", ""), "agy:gemini-3.8-flash-medium" names the
    model, so one backend can be tried again with another model (its own quota) before the next backend."""
    backend, _, model = entry.partition(":")
    return backend.strip(), model.strip()
CHAT_PLACEHOLDERS = ("today", "context")  # what chat.prompt must keep: today's date, and the data it reads


@dataclass(frozen=True)
class Chat:
    """chat in the watchlist: the assistant's model and how long it goes on (see chat.py)."""
    backend: str = ""          # claude or local; unset: scoring.backend's (load fills it in)
    claude_model: str = "claude-sonnet-5-5"  # quick, conversational replies; fit scores keep their own model
    local_model: str = ""      # chat.local_model: read and ignored (the local model server runs whichever model it has)
    max_tokens: int = 1500     # the longest reply
    max_turns: int = 24        # the most recent messages of a conversation sent with each question
    prompt: str = ""           # the edited system prompt; unset: chat.SYSTEM
    keychain: str = ""         # macOS keychain item with the Anthropic API key; unset: scoring.keychain's
    key_command: str = ""      # a command that prints the key, in place of the keychain; unset: scoring.key_command's

    @property
    def model(self) -> str:
        return self.claude_model if self.backend == "claude" else self.local_model


def _template(text: str, name: str, fields: tuple[str, ...], path: Path) -> str:
    """An edited prompt filled in with str.format: it must keep each of `fields`, and only those."""
    try:
        found = {f for _, f, _, _ in Formatter().parse(text) if f is not None}
    except ValueError as e:
        raise ConfigError(f"{path}: {name}: {e} (write a literal brace as {{{{ or }}}})") from None
    braces = ", ".join("{" + f + "}" for f in fields)
    if missing := [f for f in fields if f not in found]:
        raise ConfigError(f"{path}: {name} must keep {', '.join('{' + f + '}' for f in missing)}: the data goes "
                          "there")
    if unknown := sorted(found - set(fields)):
        raise ConfigError(f"{path}: {name} has unknown placeholder(s) {', '.join('{' + f + '}' for f in unknown)} "
                          f"(it takes {braces}; write a literal brace as {{{{ or }}}})")
    try:
        text.format(**{f: "" for f in fields})
    except (ValueError, KeyError, IndexError) as e:
        raise ConfigError(f"{path}: {name}: {e}") from None
    return text


def _chat(raw, backend: str, path: Path, keychain: str = "", key_command: str = "") -> Chat:
    raw = _section(raw, "chat", Chat, path, "{backend: local, max_tokens: 1500}")
    chosen = str(raw.get("backend") or (backend if backend in CHAT_BACKENDS else "local"))
    if chosen not in CHAT_BACKENDS:
        raise ConfigError(f"{path}: chat.backend must be one of {', '.join(CHAT_BACKENDS)} (or left out for "
                          f"scoring.backend's), got {chosen!r}")
    prompt = raw.get("prompt") or ""
    if not isinstance(prompt, str):
        raise ConfigError(f"{path}: chat.prompt is the assistant's instructions, as text, got {prompt!r:.80}")
    return Chat(backend=chosen, claude_model=str(raw.get("claude_model", Chat.claude_model)).strip(),
                local_model=str(raw.get("local_model", Chat.local_model)).strip(),
                max_tokens=_between(raw.get("max_tokens", Chat.max_tokens), "chat.max_tokens", path, 1, 64000,
                                    "the longest reply, in tokens"),
                max_turns=_between(raw.get("max_turns", Chat.max_turns), "chat.max_turns", path, 1, 200,
                                   "the latest messages sent with each question"),
                prompt=_template(prompt, "chat.prompt", CHAT_PLACEHOLDERS, path) if prompt.strip() else "",
                keychain=str(raw.get("keychain") or keychain).strip(),
                key_command=str(raw.get("key_command") or key_command).strip())


PREP_PLACEHOLDERS = ("context",)  # what prep.prompt must keep: the posting, resume and stories it reads


@dataclass(frozen=True)
class Prep:
    """prep in the watchlist: drafted questions and answers on a prep sheet (see drafts.py). They use the chat's
    backend and model."""
    max_tokens: int = 4000     # the longest draft: eight or so questions with outlines, as JSON
    prompt: str = ""           # the edited instructions; unset: drafts.PROMPT
    sheets: Path | None = None  # a folder of prep sheets you wrote (acme-onsite.html), linked from Interviews
    cache_max: str = ""        # slidecast's clip cache cap when an edit re-renders a drill video (12G, 800M)


def _prep(raw, path: Path) -> Prep:
    raw = _section(raw, "prep", Prep, path, "{max_tokens: 4000}")
    prompt = raw.get("prompt") or ""
    if not isinstance(prompt, str):
        raise ConfigError(f"{path}: prep.prompt is the drafting instructions, as text, got {prompt!r:.80}")
    if not isinstance(raw.get("sheets", ""), str):
        raise ConfigError(f"{path}: prep.sheets is a folder, got {raw['sheets']!r}")
    cache_max = str(raw.get("cache_max") or "").strip()
    if cache_max and not re.fullmatch(r"\d+[GgMm]?", cache_max):
        raise ConfigError(f"{path}: prep.cache_max is a size like 15G or 800M, got {cache_max!r}")
    return Prep(max_tokens=_between(raw.get("max_tokens", Prep.max_tokens), "prep.max_tokens", path, 500, 64000,
                                    "the longest draft, in tokens"),
                prompt=_template(prompt, "prep.prompt", PREP_PLACEHOLDERS, path) if prompt.strip() else "",
                sheets=_path(raw["sheets"], path.parent) if raw.get("sheets") else None, cache_max=cache_max)


@dataclass(frozen=True)
class Suggestions:
    """suggestions in the watchlist: Companies to watch (see suggest.py)."""
    half_life: int = 30  # days: a job that came in this long ago counts half as much as one that came in today
    limit: int = 10      # companies listed, and so the most looked for at once
    auto_watch: bool = False  # each check adds the boards that meet the rules (see suggest.auto_watch)
    min_jobs: int = 2         # matching jobs that make a company worth watching on their own
    never_watch: tuple[str, ...] = ()  # companies auto_watch leaves alone (agencies and colleges it tells itself)


def _suggestions(raw, path: Path) -> Suggestions:
    raw = _section(raw, "suggestions", Suggestions, path, "{half_life: 30, limit: 10}")
    if not isinstance(raw.get("auto_watch", False), bool):
        raise ConfigError(f"{path}: suggestions.auto_watch is true or false, got {raw['auto_watch']!r}")
    never = raw.get("never_watch") or []
    if not isinstance(never, list) or not all(isinstance(n, str) and n.strip() for n in never):
        raise ConfigError(f"{path}: suggestions.never_watch is a list of company names, got {never!r:.80}")
    return Suggestions(
        half_life=_between(raw.get("half_life", Suggestions.half_life), "suggestions.half_life", path, 1, 3650,
                           "days until a job counts half"),
        limit=_between(raw.get("limit", Suggestions.limit), "suggestions.limit", path, 1, 50,
                       "companies listed"),
        auto_watch=raw.get("auto_watch", False),
        min_jobs=_between(raw.get("min_jobs", Suggestions.min_jobs), "suggestions.min_jobs", path, 1, 20,
                          "matching jobs that make a company worth watching"),
        never_watch=tuple(n.strip() for n in never))


@dataclass(frozen=True)
class SlowBoards:
    """slow_boards in the watchlist: a board whose last read took `seconds` or more is read only every `every_days`
    days, so one huge board doesn't hold up every check. every_days 0: every board on every check."""
    seconds: int = 120
    every_days: int = 2


def _slow_boards(raw, path: Path) -> SlowBoards:
    raw = _section(raw, "slow_boards", SlowBoards, path, "{seconds: 120, every_days: 2}")
    return SlowBoards(
        seconds=_between(raw.get("seconds", SlowBoards.seconds), "slow_boards.seconds", path, 1, 86400,
                         "seconds a read takes before a board counts as slow"),
        every_days=_between(raw.get("every_days", SlowBoards.every_days), "slow_boards.every_days", path, 0, 30,
                            "days between reads of a slow board"))


@dataclass(frozen=True)
class ActivityLog:
    """One entry of ui.activity_logs: a text log (a program's, one line per event, often starting with a
    date and time) that Activity shows beside jobwatch's own. Read only; `path` is expanded per user."""
    name: str
    path: Path


@dataclass(frozen=True)
class Ui:
    """ui in the watchlist: activity_logs, other programs' log files Activity also shows (each last lines)."""
    activity_logs: tuple[ActivityLog, ...] = ()


def _ui(raw, path: Path) -> Ui:
    raw = _section(raw, "ui", Ui, path, "{activity_logs: [{name: Globex watcher, path: ~/logs/globex.log}]}")
    logs = raw.get("activity_logs", [])
    example = "activity_logs: [{name: Globex watcher, path: ~/logs/globex.log}]"
    if not isinstance(logs, list):
        raise ConfigError(f"{path}: ui.activity_logs looks like {example}, got {logs!r}")
    out: list[ActivityLog] = []
    for entry in logs:
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: ui.activity_logs entries look like {{name: Globex watcher, path: "
                              f"~/logs/globex.log}}, got {entry!r}")
        unknown = set(entry) - {"name", "path"}
        if unknown:
            raise ConfigError(f"{path}: unknown ui.activity_logs setting(s): {', '.join(sorted(unknown))}")
        name, where = entry.get("name"), entry.get("path")
        if not isinstance(name, str) or not name.strip() or not isinstance(where, str) or not where.strip():
            raise ConfigError(f"{path}: each ui.activity_logs entry needs a name and a path, got {entry!r}")
        if any(name.strip() == x.name for x in out):
            raise ConfigError(f"{path}: ui.activity_logs names {name.strip()} twice")
        out.append(ActivityLog(name.strip(), Path(os.path.expandvars(where)).expanduser()))
    return Ui(tuple(out))


INCOMING_SOURCES = ("texts", "whatsapp", "gmail", "linkedin")  # what jw-incoming (toolbelt) can poll


@dataclass(frozen=True)
class Incoming:
    """incoming in the watchlist: which sources jw-incoming polls for new personal messages (sources: a true or
    false for each of INCOMING_SOURCES; one left out is on) and the Gmail address it reads. jobwatch itself
    never polls them: jw-incoming reads this section. The app password is in the Keychain, never here."""
    sources: tuple[str, ...] = INCOMING_SOURCES  # the ones that are on
    gmail_account: str = ""


def _incoming(raw, path: Path) -> Incoming:
    example = "{sources: {texts: true, whatsapp: true, gmail: true, linkedin: true}, gmail_account: you@example.com}"
    raw = _section(raw, "incoming", Incoming, path, example)
    sources = raw.get("sources", {})
    if not isinstance(sources, dict):
        raise ConfigError(f"{path}: incoming.sources looks like {{texts: true, whatsapp: true, gmail: true, "
                          f"linkedin: true}}, got {sources!r}")
    unknown = set(sources) - set(INCOMING_SOURCES)
    if unknown:
        raise ConfigError(f"{path}: unknown incoming.sources setting(s): {', '.join(sorted(map(str, unknown)))} "
                          f"(sources are {', '.join(INCOMING_SOURCES)})")
    for name, on in sources.items():
        if not isinstance(on, bool):
            raise ConfigError(f"{path}: incoming.sources.{name} is true or false, got {on!r}")
    account = raw.get("gmail_account", "")
    if not isinstance(account, str) or (account.strip() and "@" not in account):
        raise ConfigError(f"{path}: incoming.gmail_account is an email address like you@example.com, got {account!r}")
    return Incoming(tuple(n for n in INCOMING_SOURCES if sources.get(n, True)), account.strip())


# What the Comps suggestion weighs (see comps.py), as a share of its score, when the watchlist doesn't say.
COMP_WEIGHTS = {"career": 0.25, "pay": 0.30, "fit": 0.20, "progress": 0.10, "health": 0.15}


@dataclass(frozen=True)
class Comps:
    """comps in the watchlist: how much each part of the Comps suggestion counts (career, pay, fit, progress,
    health). Written as any numbers 0 or more; they are scaled to add up to 1. A part left out keeps its default."""
    weights: dict = field(default_factory=lambda: dict(COMP_WEIGHTS))


def _comps(raw, path: Path) -> Comps:
    raw = _section(raw, "comps", Comps, path, "{weights: {career: 25, pay: 30}}")
    given = raw.get("weights") or {}
    if not isinstance(given, dict):
        raise ConfigError(f"{path}: comps.weights looks like {{career: 25, pay: 30, fit: 20}}, got {given!r}")
    if unknown := set(given) - set(COMP_WEIGHTS):
        raise ConfigError(f"{path}: unknown comps.weights name(s): {', '.join(sorted(map(str, unknown)))} "
                          f"(use {', '.join(COMP_WEIGHTS)})")
    weights = {k: _between(given.get(k, COMP_WEIGHTS[k]), f"comps.weights.{k}", path, 0, whole=False)
               for k in COMP_WEIGHTS}
    if not (total := sum(weights.values())):
        raise ConfigError(f"{path}: comps.weights can't all be 0: the suggestion would weigh nothing")
    return Comps(weights={k: w / total for k, w in weights.items()})


@dataclass(frozen=True)
class Pace:
    """pace in the watchlist: how many applications to send a day (daily), and the most (max). Today and the
    queue say how many went out today. A few good ones a day beat a burst; daily 0 turns it off, for someone
    fully in the job market."""
    daily: int = 3
    max: int = 5


def _pace(raw, path: Path) -> Pace:
    if raw is None:
        return Pace()
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: pace looks like {{daily: 3, max: 5}}, got {raw!r}")
    unknown = set(raw) - set(Pace.__dataclass_fields__)
    if unknown:
        raise ConfigError(f"{path}: unknown pace setting(s): {', '.join(sorted(unknown))}")
    daily = _whole(raw.get("daily", Pace.daily), "pace.daily", path, "0 turns the pace off")
    most = _whole(raw["max"], "pace.max", path, "the most a day") if "max" in raw else max(Pace.max, daily)
    if daily and most < daily:
        raise ConfigError(f"{path}: pace.max (the most a day) can't be less than pace.daily, got "
                          f"daily {daily} and max {most}")
    return Pace(daily, most)


@dataclass(frozen=True)
class Calendar:
    """calendar in the watchlist: remind, the minutes before an interview or call that the calendar feed has a
    reminder (see ics.py); 0 for none. Follow-up days are all-day events and never have one."""
    remind: int = 0


def _calendar(raw, path: Path) -> Calendar:
    if raw is None:
        return Calendar()
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: calendar looks like {{remind: 30}}, got {raw!r}")
    unknown = set(raw) - set(Calendar.__dataclass_fields__)
    if unknown:
        raise ConfigError(f"{path}: unknown calendar setting(s): {', '.join(sorted(unknown))}")
    return Calendar(_between(raw.get("remind", Calendar.remind), "calendar.remind", path, 0, 10080,
                             "minutes before an interview; 0 for no reminder"))


@dataclass(frozen=True)
class Speech:
    """speech in the watchlist: url, the OpenAI-style speech-to-text endpoint (…/v1/audio/transcriptions) that a
    spoken answer is sent to, from the voice mock interview and the rehearsal page's mic. Unset: LOCAL_STT_URL, else
    the local model server's (see speech.speech_url). jobwatch never loads a speech model itself."""
    url: str = ""


def _speech(raw, path: Path) -> Speech:
    raw = _section(raw, "speech", Speech, path, "{url: http://127.0.0.1:8010/v1/audio/transcriptions}")
    url = raw.get("url", "")
    if not url:
        return Speech()
    parts = urlsplit(url) if isinstance(url, str) else None
    if (not parts or parts.scheme not in ("http", "https") or not parts.hostname
            or not parts.path.rstrip("/").endswith("/audio/transcriptions") or parts.query or parts.fragment):
        raise ConfigError(f"{path}: speech.url is an OpenAI-style speech-to-text endpoint, http(s)://host:port/v1/"
                          f"audio/transcriptions, got {url!r}")
    try:
        parts.port  # noqa: B018  (a port that isn't a number raises here)
    except ValueError:
        raise ConfigError(f"{path}: speech.url has a port that isn't a number: {url!r}") from None
    return Speech(url.rstrip("/"))


@dataclass(frozen=True)
class Quiet:
    """quiet in the watchlist: days without news (a stage change or a note) before an application counts as
    gone quiet, by stage; 0 never counts that stage. `long`: days after which a quiet one stops crowding the
    follow-ups due (it sorts below the fresh ones). The days a stage waits shrink as it gets closer to an offer."""
    applied: int = 21
    screening: int = 14
    interviewing: int = 10
    long: int = 45


def _quiet(raw, path: Path) -> Quiet:
    if raw is None:
        return Quiet()
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: quiet looks like {{applied: 21, screening: 14, interviewing: 10, long: 45}}, "
                          f"got {raw!r}")
    unknown = set(raw) - set(Quiet.__dataclass_fields__)
    if unknown:
        raise ConfigError(f"{path}: unknown quiet setting(s): {', '.join(sorted(unknown))}")
    return Quiet(**{k: _whole(raw.get(k, getattr(Quiet, k)), f"quiet.{k}", path,
                              "0 never counts it" if k != "long" else "0 never sorts them below")
                    for k in Quiet.__dataclass_fields__})


def _prompts(raw, path: Path) -> dict[str, str]:
    """scoring.prompts: {name: text} for the fit-score prompts that were edited; one left out is shortlist-ai's own.
    Checked by the installed shortlist-ai, when it takes edited prompts (see score.check_prompts)."""
    if not raw:
        return {}
    if not isinstance(raw, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in raw.items()):
        raise ConfigError(f"{path}: scoring.prompts maps a prompt's name to its text, got {raw!r:.80}")
    if problem := check_prompts(raw):
        raise ConfigError(f"{path}: scoring.prompts: {problem}")
    return dict(raw)


_PROVIDER_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_PROVIDER_KEYS = {"url", "keychain", "workers", "response_format", "account_url"}


def _providers(raw, path: Path) -> tuple[Provider, ...]:
    """scoring.providers: {name: {url, keychain, workers, response_format}} for OpenAI-compatible APIs. A name is
    then a backend in scoring.backend and scoring.fallback entries (acme:<model>); it can't be a built-in one."""
    if not raw:
        return ()
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: scoring.providers maps a provider's name to its url (and keychain), "
                          f"got {raw!r:.80}")
    out = []
    for name, block in raw.items():
        where = f"{path}: scoring.providers.{name}"
        if not isinstance(name, str) or not _PROVIDER_NAME.fullmatch(name) or name in BACKENDS:
            raise ConfigError(f"{path}: a provider's name is lowercase letters, digits, dashes and underscores, "
                              f"and not {', '.join(BACKENDS)}, got {name!r}")
        if not isinstance(block, dict) or set(block) - _PROVIDER_KEYS or not str(block.get("url") or "").strip():
            raise ConfigError(f"{where} is a block with url (the API's /v1 base) and optionally keychain, workers "
                              f"and response_format, got {block!r:.80}")
        url = str(block["url"]).strip().rstrip("/")
        if urlsplit(url).scheme not in ("http", "https") or not urlsplit(url).hostname:
            raise ConfigError(f"{where}.url is an http(s) address, got {url!r}")
        keychain = str(block.get("keychain") or "").strip()
        if keychain and not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", keychain):
            raise ConfigError(f"{where}.keychain is letters, digits, dots, dashes and underscores, got {keychain!r}")
        response_format = str(block.get("response_format") or "json_schema")
        if response_format not in ("json_schema", "json_object", "none"):
            raise ConfigError(f"{where}.response_format is json_schema, json_object or none, got {response_format!r}")
        workers = _whole(block.get("workers", 1), f"scoring.providers.{name}.workers", path,
                         "1 makes one call at a time")
        account = str(block.get("account_url") or "").strip()
        if account and (urlsplit(account).scheme not in ("http", "https") or not urlsplit(account).hostname):
            raise ConfigError(f"{where}.account_url is an http(s) address, got {account!r}")
        out.append(Provider(name, url, keychain, max(1, workers), response_format, account))
    return tuple(out)


# What you want next, which the Comps suggestion's career part scores jobs against (see comps._career).
GOAL_KINDS = ("tech", "consulting", "enterprise")  # kinds of company, as Comps keeps them
GOAL_ROLES = ("product", "customer", "internal")   # what the job builds, as Comps keeps it
GOAL_TRACKS = ("ic", "manager", "either")          # an individual contributor, a people manager, or both
GOAL_STAGES = ("startup", "growth", "public")      # seed to Series B, Series C and later, listed (Comps reads health)


@dataclass(frozen=True)
class Goals:
    """goals in the watchlist: who you are and what you want next. company_kinds, roles and stages are in order of
    preference (first is best; ("any",) cares about none); the career part of the Comps suggestion scores from them
    (a stage only for a company whose health says its stage). about, track and horizon are in your own words: shown
    beside the suggestion and read by "Suggest titles from my resume", they change no score."""
    about: str = ""
    company_kinds: tuple = ()
    roles: tuple = ()
    stages: tuple = ()
    track: str = "either"
    horizon: str = ""

    @property
    def scores(self) -> bool:
        """Whether the career part follows these goals (a kind, role or stage preference is set) or the fixed
        rules."""
        return bool(self.company_kinds or self.roles or self.stages)


def _preferences(raw, name: str, allowed: tuple, path: Path) -> tuple:
    """goals.company_kinds or goals.roles: a list (or text with commas) of `allowed` names, best first, or "any"
    alone. A name left out ranks after the ones listed."""
    if isinstance(raw, str):
        raw = [p for p in re.split(r"[,\s]+", raw) if p]
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise ConfigError(f"{path}: goals.{name} looks like [{', '.join(allowed[:2])}] (best first), got {raw!r}")
    names = tuple(x.strip().lower() for x in raw)
    bad = [x for x in names if x not in (*allowed, "any")]
    if bad:
        raise ConfigError(f"{path}: goals.{name} can only name {', '.join(allowed)} or any, got {', '.join(bad)}")
    if len(set(names)) != len(names):
        raise ConfigError(f"{path}: goals.{name} names {next(x for x in names if names.count(x) > 1)} twice")
    if "any" in names and len(names) > 1:
        raise ConfigError(f"{path}: goals.{name}: any means no preference, so it stands alone")
    return names


def _goals(raw, path: Path) -> Goals:
    raw = _section(raw, "goals", Goals, path, "{company_kinds: [tech, consulting], roles: [product], track: ic}")
    track = str(raw.get("track", Goals.track)).strip().lower()
    if track not in GOAL_TRACKS:
        raise ConfigError(f"{path}: goals.track must be one of {', '.join(GOAL_TRACKS)}, got {raw['track']!r}")
    text = {}
    for k in ("about", "horizon"):
        if not isinstance(raw.get(k, ""), str):
            raise ConfigError(f"{path}: goals.{k} is text in your own words, got {raw[k]!r}")
        text[k] = raw.get(k, "").strip()
    return Goals(company_kinds=_preferences(raw.get("company_kinds", []), "company_kinds", GOAL_KINDS, path),
                 roles=_preferences(raw.get("roles", []), "roles", GOAL_ROLES, path),
                 stages=_preferences(raw.get("stages", []), "stages", GOAL_STAGES, path), track=track, **text)


@dataclass(frozen=True)
class Applicant:
    """applicant in the watchlist: your details as application forms ask for them, for the browser extension to
    fill (see autofill.py and chrome-extension/API.md). All text; one left empty is never filled. The voluntary
    self-identification questions (gender and the rest) are "decline" unless set: the form's "I don't wish to
    answer". salary unset is your pay target."""
    first_name: str = ""
    last_name: str = ""
    preferred_name: str = ""
    email: str = ""
    phone: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    postal_code: str = ""
    linkedin: str = ""
    github: str = ""
    website: str = ""
    work_authorized: str = ""   # yes or no: allowed to work in the job's country
    needs_sponsorship: str = ""  # yes or no: now or in the future
    relocate: str = ""          # yes or no
    notice_period: str = ""
    salary: str = ""
    gender: str = "decline"
    race: str = "decline"
    hispanic: str = "decline"
    veteran: str = "decline"
    disability: str = "decline"


APPLICANT_YES_NO = ("work_authorized", "needs_sponsorship", "relocate")


def _applicant(raw, path: Path) -> Applicant:
    raw = _section(raw, "applicant", Applicant, path, "{first_name: Jordan, email: jordan@example.com}")
    out = {}
    for k, v in raw.items():
        if isinstance(v, bool) and k in APPLICANT_YES_NO:  # YAML reads a bare yes or no as true or false
            v = "yes" if v else "no"
        if not isinstance(v, (str, int, float)) or isinstance(v, bool):
            raise ConfigError(f"{path}: applicant.{k} is text, got {v!r}")
        out[k] = str(v).strip()
        if k in APPLICANT_YES_NO and out[k].lower() not in ("yes", "no", ""):
            raise ConfigError(f"{path}: applicant.{k} must be yes or no, got {v!r}")
    return Applicant(**out)


@dataclass
class Config:
    path: Path
    boards: list[Board]
    filters: Filters = field(default_factory=Filters)
    keywords: dict[str, float] = field(default_factory=dict)
    focus: list[str] = field(default_factory=list)  # title regexes for the work wanted most: first on Today
    resume: Path | None = None
    connections: Path | None = None  # LinkedIn Connections.csv, for "you know someone there"
    connections_skip: list[str] = field(default_factory=list)  # people never to suggest: names or profile links
    employer: list[str] = field(default_factory=list)  # where you work now: colleagues there aren't referrals
    stories: Path | None = None      # your projects, for drafted interview answers (see stories.py)
    resume_kit: str = ""             # resume-kit's command to tailor a resume (see tailor.py); unset: `resume`
    backend: str = "local"
    score_providers: tuple[Provider, ...] = ()  # scoring.providers: OpenAI-compatible APIs, each a backend by its name
    score_model: str = ""      # scoring.model: the model fit scores use; unset: shortlist-ai's for the backend
    api_keychain: str = ""     # scoring.keychain: macOS keychain item with the Anthropic API key (for Claude)
    api_key_command: str = ""  # scoring.key_command: a command that prints the key, in place of the keychain read
    score_fallback: tuple[str, ...] = ()  # scoring.fallback: backends tried in turn when this can't score
    score_same_as: tuple[str, ...] = ()   # scoring.same_as: other scorers (backend:model) whose scores count as its own
    agy_model: str = ""        # scoring.agy_model: agy's model as a fallback (scoring.model as the backend)
    score_daily: int = 0       # scoring.daily: the most jobs the backend scores a day, then the fallback (0: no cap)
    score_per_company: int = 0  # scoring.per_company: the most jobs from one company scored in the background a day
    score_workers: int = 4    # scoring.workers: Claude calls at once (the local model takes one at a time)
    score_top: int = 0
    auto_score: bool = True    # the page scores new matches in the background (default: on for local only)
    score_batch: int = 10      # scoring.batch: jobs the page scores in a row before it rests (0: no rests)
    score_batch_api: bool = False  # scoring.batch_api: the page scores with Claude through the Batches API (half price)
    score_rest: int = 10       # scoring.rest: minutes it rests between batches
    unload_after: int = 5      # scoring.unload_after: read and ignored (the local model server unloads when idle)
    prompts: dict[str, str] = field(default_factory=dict)  # scoring.prompts: the edited fit-score prompts
    chat: Chat = field(default_factory=lambda: Chat(backend="local"))
    prep: Prep = field(default_factory=Prep)
    timeline: str = "quarter"  # how soon you want to close a skill gap: see TIMELINES
    near: str = ""             # a city, for certificate programs at colleges nearby
    learn_jobs: int = 5        # learning.jobs: example jobs listed with each skill
    suggest: Suggestions = field(default_factory=Suggestions)
    slow_boards: SlowBoards = field(default_factory=SlowBoards)
    ui: Ui = field(default_factory=Ui)
    incoming: Incoming = field(default_factory=Incoming)
    theme: str = "system"      # the page: see THEMES and WIDTHS
    width: str = "standard"
    today: int = 10            # display.today: Today and the digest lead with this many of the best (0: all)
    company_view: str = "matches"  # display.company: which open roles a company's page lists (COMPANY_VIEWS)
    pace: Pace = field(default_factory=Pace)
    calendar: Calendar = field(default_factory=Calendar)
    quiet: Quiet = field(default_factory=Quiet)
    speech: Speech = field(default_factory=Speech)
    state: Path = DEFAULT_STATE
    cache: Path = DEFAULT_CACHE
    imap: Imap | None = None   # alerts.imap: read job-alert emails from a mailbox (off unless set)
    pay: Pay = field(default_factory=Pay)
    comps: Comps = field(default_factory=Comps)
    goals: Goals = field(default_factory=Goals)
    applicant: Applicant = field(default_factory=Applicant)
    # How often `jobwatch ui` checks the boards by itself (fetch_every); None: only when asked. Or the times of
    # day it checks (fetch_every: 8am, 2pm, 8pm), this computer's clock; then fetch_every is None.
    fetch_every: timedelta | None = None
    fetch_at: tuple[time, ...] = ()
    # Boards from a source this jobwatch doesn't know (a newer version's, or a typo): kept in the file and
    # shown as errors, skipped when checking for jobs, so one bad entry doesn't stop everything else.
    unknown: list[Board] = field(default_factory=list)
    # (source, board) -> the filters for that board's jobs, for the entries with their own (see Board.filters)
    board_filters: dict[tuple[str, str], Filters] = field(default_factory=dict)
    # (title regexes, filters) per tracks: entry: a kind of job judged by other rules wherever it comes from
    tracks: list[tuple[list[str], Filters]] = field(default_factory=list)

    @property
    def backends(self) -> tuple[str, ...]:
        """Every scoring backend this watchlist can use: the built-in ones, then its scoring.providers."""
        return (*BACKENDS, *(p.name for p in self.score_providers))

    def provider(self, backend: str) -> Provider | None:
        """The scoring.providers entry that is this backend, if it is one."""
        return next((p for p in self.score_providers if p.name == backend), None)

    def filters_for(self, job) -> Filters:
        """The filters a job is judged by: its board's own (a watchlist entry's filters:), else the first track
        whose titles its title matches (tracks:), else the watchlist's. A track is how a job from a board that
        isn't watched (an alert email's, one added by link) gets other rules."""
        if own := self.board_filters.get((job.source, job.company)):
            return own
        return next((f for titles, f in self.tracks if any(re.search(t, job.title, re.I) for t in titles)),
                    self.filters)

    def filters_of(self, b: Board) -> Filters:
        """The filters for a watched board's jobs: what it's searched for and which postings are read in full."""
        return self.board_filters.get((b.source, b.board), self.filters)


UNKNOWN_SOURCE = "unknown source: update jobwatch or remove this board"
_LINK = re.compile(r"https?://[\w-]+(?:\.[\w-]+)+(?:[/?#]\S*)?", re.I)


def _board(entry, path: Path, strict: bool = True) -> Board:
    """ "greenhouse:globex", or {source: greenhouse, board: globex, name: Globex}, or the board as
    source:board in a mapping: {board: "ashby:acme", careers: https://acme.example/careers}. careers is the
    company's own careers site, for when the board's hosted job pages are offline; filters, settings that
    replace the watchlist's filters for this board's jobs ({titles: [adjunct], min_salary: 0}).
    Not strict: a source this version doesn't know is let through (see Config.unknown)."""
    if isinstance(entry, str):
        entry = {"board": entry}
    if isinstance(entry, dict) and not entry.get("source") and ":" in str(entry.get("board") or ""):
        source, _, board = str(entry["board"]).partition(":")
        entry = {**entry, "source": source, "board": board}
    if not isinstance(entry, dict) or not entry.get("source") or not entry.get("board"):
        raise ConfigError(f"{path}: companies entries look like 'greenhouse:globex', got {entry!r}")
    if strict and entry["source"] not in SOURCES:
        raise ConfigError(f"{path}: unknown source {entry['source']!r} (supported: {', '.join(SOURCES)})")
    careers = str(entry.get("careers") or "").strip()
    if careers and not _LINK.fullmatch(careers):
        raise ConfigError(f"{path}: {entry['source']}:{entry['board']}: careers is a link to the company's own "
                          f"careers site (https://...), got {careers!r}")
    own = entry.get("filters") or {}
    if not isinstance(own, dict):
        raise ConfigError(f"{path}: {entry['source']}:{entry['board']}: filters are settings like the watchlist's "
                          f"own, e.g. {{titles: [adjunct, instructor], min_salary: 0}}, got {own!r}")
    if unknown := set(own) - set(Filters.__dataclass_fields__):
        raise ConfigError(f"{path}: {entry['source']}:{entry['board']}: unknown filter setting(s): "
                          f"{', '.join(sorted(map(str, unknown)))}")
    return Board(str(entry["source"]), str(entry["board"]), entry.get("name") or "", careers, dict(own))


def _focus(raw, path: Path) -> list[str]:
    """focus: title regexes for the work you want most ("security", "\\bai\\b"): a job whose title matches one
    leads Today and the scoring line, ahead of better scores outside it; one that matches more leads one that
    matches fewer."""
    focus = [raw] if isinstance(raw, str) else [str(x) for x in raw or []]
    for x in focus:
        try:
            re.compile(x)
        except re.error as e:
            raise ConfigError(f"{path}: focus: {x!r} isn't a regex: {e}") from None
    return focus


def _tracks(raw, base: dict, path: Path) -> list[tuple[list[str], Filters]]:
    """tracks: a list of {titles: [regex, ...], filters: {...}}: a job whose title matches one of a track's titles
    is judged by the watchlist's filters with the track's replacing them one by one, like a board's own."""
    out = []
    for n, t in enumerate(raw or [], 1):
        where = f"{path}: tracks entry {n}"
        if not isinstance(t, dict) or set(t) - {"name", "titles", "filters"} or not t.get("titles"):
            raise ConfigError(f"{where} looks like {{titles: ['\\badjunct\\b'], filters: {{min_salary: 0}}}}, "
                              f"got {t!r:.80}")
        titles = [t["titles"]] if isinstance(t["titles"], str) else [str(x) for x in t["titles"]]
        for x in titles:
            try:
                re.compile(x)
            except re.error as e:
                raise ConfigError(f"{where}: {x!r} isn't a regex: {e}") from None
        own = t.get("filters") or {}
        if not isinstance(own, dict) or (unknown := set(own) - set(Filters.__dataclass_fields__)):
            raise ConfigError(f"{where}: filters are settings like the watchlist's own"
                              + (f"; unknown: {', '.join(sorted(map(str, unknown)))}" if isinstance(own, dict)
                                 else f", got {own!r:.80}"))
        try:
            out.append((titles, Filters.from_dict({**base, **own})))
        except (TypeError, ValueError) as e:
            raise ConfigError(f"{where}: {e}") from None
    return out


def _item(b: Board) -> str | dict:
    """A board as the watchlist writes it: "greenhouse:stripe", or a mapping when it has a name, careers link or
    filters of its own."""
    if not (b.name or b.careers or b.filters):
        return b.entry
    return {"source": b.source, "board": b.board, **({"name": b.name} if b.name else {}),
            **({"careers": b.careers} if b.careers else {}), **({"filters": b.filters} if b.filters else {})}


FETCH_EVERY = timedelta(hours=6)  # fetch_every's default
FETCH_LEAST = timedelta(hours=1)  # every check asks every board again: no more often than this
_OFF = ("0", "off", "no", "never", "false")
_EVERY = re.compile(r"(\d+(?:\.\d+)?)\s*(m|mins?|minutes?|h|hrs?|hours?|d|days?)?", re.I)


def duration(raw) -> timedelta | None:
    """"6h", "90m", "1d", or a number of hours, as a timedelta; None if it isn't one."""
    if not (m := _EVERY.fullmatch(str(raw).strip())):
        return None
    n, unit = float(m.group(1)), (m.group(2) or "h")[0].lower()
    return timedelta(minutes=n) if unit == "m" else timedelta(days=n) if unit == "d" else timedelta(hours=n)


def _every(raw, path: Path) -> timedelta | None:
    """fetch_every: "6h", "90m", "1d", or a number of hours; 0 or off: never (YAML reads a bare off as false)."""
    if raw is None:
        return FETCH_EVERY
    if raw is False or str(raw).strip().lower() in _OFF:
        return None
    every = duration(raw) if not isinstance(raw, bool) else None
    if every is None:
        raise ConfigError(f"{path}: fetch_every looks like 6h, 90m or 1d (or off), got {raw!r}")
    if not every:
        return None
    if every < FETCH_LEAST:
        raise ConfigError(f"{path}: fetch_every must be at least 1h (each check asks every board again), "
                          f"got {raw!r}")
    return every


_CLOCK = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.I)


def _at(raw, path: Path) -> tuple[time, ...]:
    """fetch_every as times of day: "8am, 2pm, 8pm", "08:00, 14:00, 20:00" or a list of them; () when it's an
    interval. A list in YAML may come as numbers: 8 is 8 o'clock, and an unquoted 14:00 reads as 840 (minutes)."""
    if isinstance(raw, (list, tuple)):
        items = list(raw)
    elif isinstance(raw, str) and re.search(r"am|pm|:", raw, re.I):
        items = [p for p in re.split(r"[,\s]+(?![ap]m)", raw.strip()) if p]
    else:
        return ()
    times = []
    for item in items:
        if isinstance(item, int) and not isinstance(item, bool):
            hour, minute = (item, 0) if item < 24 else divmod(item, 60)
        elif (m := _CLOCK.fullmatch(str(item).strip())):
            hour, minute = int(m.group(1)), int(m.group(2) or 0)
            if m.group(3):
                hour = hour % 12 + (12 if m.group(3).lower() == "pm" else 0) if 1 <= hour <= 12 else 99
        else:
            hour = minute = 99
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ConfigError(f"{path}: fetch_every's times look like 8am, 2pm, 8pm or 08:00, 14:00, got {item!r}")
        times.append(time(hour, minute))
    if not times:
        raise ConfigError(f"{path}: fetch_every lists no times, got {raw!r}")
    return tuple(sorted(set(times)))


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


SETTINGS = ("companies", "filters", "keywords", "focus", "resume", "connections", "connections_skip", "employer",
            "stories", "resume_kit", "scoring",
            "chat", "prep",
            "learning", "display", "pace", "calendar", "pay", "comps", "goals", "applicant", "alerts", "suggestions",
            "slow_boards", "ui", "incoming", "speech", "fetch_every")
TIMELINES = ("week", "month", "quarter", "any")  # this week, this month, the next few months, no rush
THEMES = ("system", "light", "dark")          # the page's colors; system follows the computer's setting
WIDTHS = ("standard", "wide", "full")         # how wide the page grows on a big monitor
# A company's page lists the open roles you haven't acted on that pass every filter Today uses (matches), or all
# of them (all). Postings you queued, applied to or skipped are listed either way.
COMPANY_VIEWS = ("matches", "all")


def _command(value, path: Path) -> str:
    """resume_kit: the command to run, as text ("~/tools/resume-kit/.venv/bin/resume"); unset: "" (`resume` on PATH)."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ConfigError(f"{path}: resume_kit is the resume-kit command, as text, got {value!r}")
    return value.strip()


def _near(learning: dict, filters: Filters) -> str:
    """The city for nearby programs: as set, else the first place in the location filter that isn't remote."""
    if "near" in learning:
        return str(learning["near"] or "").strip()
    return next((loc.strip() for loc in filters.locations if loc.strip() and "remote" not in loc.lower()
                 and not re.search(r"[\\^$*+?()[\]{}|]", loc)), "")


HEADER = "# jobwatch watchlist, saved by jobwatch. Docs: https://github.com/vinayvobbili/jobwatch\n"


def _round_trip(text: str):
    """A reader-writer for this file that keeps its comments, quotes and indentation (ruamel.yaml's round trip)."""
    dash = (load_yaml_guess_indent(text)[2] or 0) if text.strip() else 0  # where list dashes sit under their key
    rt = YAML()
    rt.preserve_quotes = True
    rt.width = 4096  # never re-wrap a long line
    rt.indent(mapping=2, sequence=dash + 2, offset=dash)
    return rt


def _fresh(value):
    """A new value as the round trip writes it: text of several lines (an edited prompt) as a block."""
    if isinstance(value, dict):
        return {k: _fresh(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_fresh(v) for v in value]
    return LiteralScalarString(value) if isinstance(value, str) and "\n" in value else value


def _same_scalar(old, new) -> bool:
    return (old == new and isinstance(old, bool) == isinstance(new, bool)
            and isinstance(old, str) == isinstance(new, str))


def _merge(old, new):
    """new, written into old's place: what didn't change keeps its comments and layout, and so does the rest
    around what did."""
    if isinstance(old, CommentedMap) and isinstance(new, dict):
        for key in [k for k in old if k not in new]:
            del old[key]
        for key, value in new.items():
            old[key] = _merge(old[key], value) if key in old else _fresh(value)
        return old
    if isinstance(old, CommentedSeq) and isinstance(new, list):
        if old == new:
            return old
        seq, used = CommentedSeq(), set()
        if old.fa.flow_style():  # [remote, Denver] stays on one line
            seq.fa.set_flow_style()
        for value in new:  # an item kept keeps its own comment; a new one comes as given
            at = next((i for i, item in enumerate(old) if i not in used and item == value), None)
            if at is None:
                seq.append(_fresh(value))
                continue
            used.add(at)
            seq.append(old[at])
            if at in old.ca.items:  # after the append: append moves comments at or past its index on by one
                seq.ca.items[len(seq) - 1] = old.ca.items[at]
        seq.ca.comment = old.ca.comment
        return seq
    if not isinstance(new, (dict, list)) and _same_scalar(old, new):
        return old
    return _fresh(new)


def _sections(rt, text: str) -> tuple[str, dict[str, str]]:
    """The file's text before its first key (a header), and each top-level key's own lines, in order."""
    data = rt.load(text) if text.strip() else None
    if not isinstance(data, CommentedMap) or not data:
        return text, {}
    lines = text.splitlines(keepends=True)
    starts = sorted((data.lc.key(key)[0], key) for key in data)
    ends = [line for line, _ in starts[1:]] + [len(lines)]
    return "".join(lines[:starts[0][0]]), {key: "".join(lines[start:end])
                                           for (start, key), end in zip(starts, ends, strict=True)}


def _means(section: str):
    try:
        return yaml.safe_load(section)
    except yaml.YAMLError:
        return section


def _splice(rt, old_text: str, new_text: str) -> str:
    """new_text, but each section that means what it did before keeps its old lines byte for byte, so a value
    wrapped or quoted by hand (or by an older jobwatch) isn't rewritten when it didn't change."""
    head, old = _sections(rt, old_text)
    _, new = _sections(rt, new_text)
    kept = [old[key] if key in old and _means(old[key]) == _means(section) else section for key, section in new.items()]
    return head + "".join(s if s.endswith("\n") else s + "\n" for s in kept)


def save(path: Path, settings: dict) -> Config:
    """Update the watchlist's settings (other keys, such as state, are kept) and write it.

    The new file is checked before it replaces the old one, which is kept as <name>.bak.
    Comments, quotes and indentation in a hand-written file are kept; only the changed values change."""
    unknown = set(settings) - set(SETTINGS)
    if unknown:
        raise ConfigError(f"unknown setting(s): {', '.join(sorted(unknown))}")
    old_text = path.read_text(encoding="utf-8") if path.is_file() else ""
    rt = _round_trip(old_text)
    raw = rt.load(old_text) if old_text.strip() else None
    if not isinstance(raw, CommentedMap):
        raw = CommentedMap()
    for key, value in settings.items():
        if value in (None, "", [], {}):
            raw.pop(key, None)
        else:
            raw[key] = _merge(raw[key], value) if key in raw else _fresh(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = io.StringIO()
    rt.dump(raw, out)
    text = _splice(rt, old_text, out.getvalue()) if raw else out.getvalue()
    if not old_text.lstrip().startswith("#"):
        text = HEADER + text
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
        companies[at] = _item(Board(new.source, new.board, name or old.name, new.careers or old.careers, old.filters))
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
    providers = _providers(scoring.get("providers"), path)
    known = (*BACKENDS, *(p.name for p in providers))
    backend = scoring.get("backend") or "local"
    if backend not in known:
        raise ConfigError(f"{path}: scoring.backend must be one of {', '.join(known)}, got {backend!r}")
    if backend in (p.name for p in providers) and not str(scoring.get("model") or "").strip():
        raise ConfigError(f"{path}: scoring.backend {backend} is an API from scoring.providers: set scoring.model")
    # On by default only for the on-device model: with Claude every score is a paid API call.
    auto_score = scoring.get("auto", backend == "local")
    if not isinstance(auto_score, bool):
        raise ConfigError(f"{path}: scoring.auto must be true or false, got {auto_score!r}")
    batch_api = scoring.get("batch_api", False)
    if not isinstance(batch_api, bool):
        raise ConfigError(f"{path}: scoring.batch_api must be true or false, got {batch_api!r}")
    if batch_api and backend != "claude":
        raise ConfigError(f"{path}: scoring.batch_api is for Claude's Batches API: it needs scoring.backend: claude, "
                          f"not {backend}")
    fallback = scoring.get("fallback") or []
    fallback = [fallback] if isinstance(fallback, str) else fallback
    others = ", ".join(b for b in known if b != backend)
    main_model = str(scoring.get("model") or "").strip()

    def same_as_main(entry: str) -> bool:
        b, m = fallback_entry(entry)
        return b == backend and (not m or m == main_model)

    if (not isinstance(fallback, list) or any(not isinstance(b, str) for b in fallback)
            or any(fallback_entry(b)[0] not in known or same_as_main(b) for b in fallback)
            or len({fallback_entry(b) for b in fallback}) != len(fallback)):
        raise ConfigError(f"{path}: scoring.fallback is a backend other than scoring.backend ({others}), or a "
                          f"backend:model (agy:gemini-3.8-flash-medium, even scoring.backend's with another model), or "
                          f"a list of them in the order to try, or left out, got {scoring.get('fallback')!r}")
    named = {p.name for p in providers}
    if bare := [b for b in fallback if fallback_entry(b)[0] in named and not fallback_entry(b)[1]]:
        raise ConfigError(f"{path}: scoring.fallback entry {bare[0]!r} is an API from scoring.providers: "
                          f"name its model, as {bare[0]}:<model>")
    fallback = [":".join(p for p in fallback_entry(b) if p) for b in fallback]
    same_as = scoring.get("same_as") or []
    same_as = [same_as] if isinstance(same_as, str) else same_as
    if not isinstance(same_as, list) or any(not isinstance(s, str) or fallback_entry(s)[0] not in known
                                            or not fallback_entry(s)[1] for s in same_as):
        raise ConfigError(f"{path}: scoring.same_as is a backend:model (claude:claude-sonnet-5-5) whose scores count "
                          f"as scoring.backend's, or a list of them, got {scoring.get('same_as')!r}")
    same_as = [":".join(fallback_entry(s)) for s in same_as]
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
    today = _whole(display.get("today", 10), "display.today", path, "0 shows every match")
    company_view = str(display.get("company", "matches"))
    if company_view not in COMPANY_VIEWS:
        raise ConfigError(f"{path}: display.company must be one of {', '.join(COMPANY_VIEWS)}, got {company_view!r}")
    listed = [_board(e, path, strict=False) for e in raw.get("companies") or []]
    dupes = {b for b in listed if listed.count(b) > 1}
    if dupes:
        raise ConfigError(f"{path}: listed twice: {', '.join(f'{b.source}:{b.board}' for b in dupes)}")
    alerts = raw.get("alerts") or {}
    if not isinstance(alerts, dict) or set(alerts) - {"imap"}:
        raise ConfigError(f"{path}: alerts has one setting, imap (see {GUIDE}/applying.md#job-alert-emails)")
    boards = [b for b in listed if b.source in SOURCES]
    own: dict[tuple[str, str], Filters] = {}
    for b in boards:
        if b.filters:  # the board's settings replace the watchlist's, one by one
            try:
                own[(b.source, b.board)] = Filters.from_dict({**(raw.get("filters") or {}), **b.filters})
            except (TypeError, ValueError) as e:
                raise ConfigError(f"{path}: {b.entry}: {e}") from None
    employer = raw.get("employer") or []
    employer = [employer] if isinstance(employer, str) else employer
    return Config(
        path=path, boards=boards, unknown=[b for b in listed if b.source not in SOURCES], filters=filters,
        board_filters=own, tracks=_tracks(raw.get("tracks"), raw.get("filters") or {}, path),
        keywords={str(k): float(v) for k, v in (raw.get("keywords") or {}).items()},
        focus=_focus(raw.get("focus"), path),
        resume=_path(raw["resume"], base) if raw.get("resume") else None,
        connections=_path(raw["connections"], base) if raw.get("connections") else None,
        connections_skip=[str(s).strip() for s in raw.get("connections_skip") or [] if str(s).strip()],
        employer=[s for e in employer if (s := str(e).strip())],
        stories=_path(raw["stories"], base) if raw.get("stories") else None,
        resume_kit=_command(raw.get("resume_kit"), path),
        backend=backend, score_providers=providers, score_model=str(scoring.get("model") or "").strip(),
        score_top=_whole(scoring.get("top", 0), "scoring.top", path, "0 scores none when the digest is made"),
        auto_score=auto_score, prompts=_prompts(scoring.get("prompts"), path),
        score_batch=_whole(scoring.get("batch", 10), "scoring.batch", path, "0 scores everything in one go"),
        score_batch_api=batch_api,
        score_rest=_whole(scoring.get("rest", 10), "scoring.rest", path, "0 rests not at all"),
        unload_after=_whole(scoring.get("unload_after", 5), "scoring.unload_after", path, "0 keeps the model loaded"),
        api_keychain=str(scoring.get("keychain") or "").strip(), score_fallback=tuple(fallback),
        score_same_as=tuple(same_as),
        api_key_command=str(scoring.get("key_command") or "").strip(),
        agy_model=str(scoring.get("agy_model") or "").strip(),
        score_daily=_whole(scoring.get("daily", 0), "scoring.daily", path, "0 sets no daily limit"),
        score_per_company=_whole(scoring.get("per_company", 0), "scoring.per_company", path,
                                 "0 sets no cap per company"),
        score_workers=max(1, _whole(scoring.get("workers", 4), "scoring.workers", path, "1 makes one call at a time")),
        chat=_chat(raw.get("chat"), backend, path, str(scoring.get("keychain") or "").strip(),
                   str(scoring.get("key_command") or "").strip()),
        prep=_prep(raw.get("prep"), path),
        timeline=timeline, near=_near(learning, filters),
        learn_jobs=_whole(learning.get("jobs", 5), "learning.jobs", path, "0 lists none"),
        suggest=_suggestions(raw.get("suggestions"), path),
        slow_boards=_slow_boards(raw.get("slow_boards"), path), ui=_ui(raw.get("ui"), path),
        incoming=_incoming(raw.get("incoming"), path),
        theme=theme, width=width, today=today, company_view=company_view,
        pace=_pace(raw.get("pace"), path), calendar=_calendar(raw.get("calendar"), path),
        quiet=_quiet(raw.get("quiet"), path), speech=_speech(raw.get("speech"), path),
        state=_path(raw["state"], base) if raw.get("state") else DEFAULT_STATE,
        cache=_path(raw["cache"], base) if raw.get("cache") else DEFAULT_CACHE,
        imap=_imap(alerts.get("imap"), path), pay=_pay(raw.get("pay"), path),
        comps=_comps(raw.get("comps"), path), goals=_goals(raw.get("goals"), path),
        applicant=_applicant(raw.get("applicant"), path),
        fetch_every=None if (at := _at(raw.get("fetch_every"), path)) else _every(raw.get("fetch_every"), path),
        fetch_at=at,
    )


def defaults() -> dict:
    """What each setting is when the watchlist leaves it out, as Settings shows it (by section, as written)."""
    imap = Imap("", "")
    return {"scoring": {"backend": "local", "top": 0},
            "chat": {k: v for k, v in asdict(Chat()).items()
                     if k not in ("backend", "prompt", "keychain", "key_command")},
            "learning": {"timeline": "quarter", "jobs": Config.learn_jobs},
            "display": {"theme": "system", "width": "standard", "today": Config.today, "company": "matches"},
            "pace": asdict(Pace()),
            "calendar": asdict(Calendar()),
            "speech": asdict(Speech()),
            "incoming": {"sources": dict.fromkeys(INCOMING_SOURCES, True), "gmail_account": ""},
            "pay": {k: v for k, v in asdict(Pay()).items() if k not in ("years", "target", "target_max", "floor")},
            "comps": {"weights": dict(COMP_WEIGHTS)},
            "goals": {"track": Goals.track},
            "applicant": {k: v for k, v in asdict(Applicant()).items() if v},
            "suggestions": asdict(Suggestions()),
            "alerts": {"imap": {"port": imap.port, "folder": imap.folder, "days": imap.days,
                                "senders": list(imap.senders), "mark_read": imap.mark_read}},
            "fetch_every": "6h", "state": str(DEFAULT_STATE), "cache": str(DEFAULT_CACHE)}


EXAMPLE = """\
# jobwatch watchlist. Docs: https://github.com/vinayvobbili/jobwatch
#
# Find a company's board with:  jobwatch find "Company Name"   (or paste a careers/job link)

companies:
  - greenhouse:globex
  - lever:spotify
  - ashby:initech
  # - {source: greenhouse, board: stripe, name: Stripe}
  # - {board: ashby:acme, careers: https://acme.example/careers}   # its Ashby pages are offline: link here
  # - {board: greenhouse:initech, filters: {titles: [adjunct, instructor], min_salary: 0}}  # its own filters

# A kind of job judged by other filters wherever it comes from (an alert email's too), by its title:
# tracks:
#   - {titles: [adjunct, lecturer], filters: {titles: [cyber, computer], min_salary: 0}}

# `jobwatch ui` checks every board by itself this often (6h, 90m, 1d; off: only when you press the button),
# or at set times of day: fetch_every: 8am, 2pm, 8pm
fetch_every: 6h

filters:
  titles: ["engineer", "developer"]            # regexes; the title must match one
  exclude_titles: ["intern", "manager"]
  # exclude_text: ["red team|offensive security"]  # regexes on the posting's text; a match rejects the job
  # exclude_companies: ["Initech"]             # companies whose jobs you never want (Today hides one in a click)
  locations: ["remote", "New York"]            # "remote" = remote in remote_country; other text is matched
  remote_country: US                           # or "any"
  # home_state: NY                             # leave out remote jobs open only in other states
  # nearby_offices: ["Initech"]                # companies with an office near you: their jobs anywhere show, to
  #                                            # ask the recruiter about that office (`jobwatch offices` finds them)
  # known_offices: ["Initech"]                 # ones you know have a tech office near you: never doubted
  min_salary: 150000                          # listed pay must reach this; jobs without pay still pass
  max_age_days: 30
  # min_fit: 70                                # hide jobs whose fit score is below this; unscored ones still show
  # company_notes:                             # a note shown on a company's jobs
  #   Initech: "downgraded 11/1: no new applications or referral asks"
  # flags:                                   # not filters: warnings on queued jobs whose posting says this
  #   "active (TS|top secret)": clearance

# Today (and `jobwatch digest`) lead with your best few matches; the rest are a click (or --all) away.
# display:
#   today: 10            # how many picks a day; 0 shows every match
#   company: matches     # a company's page lists the open roles your filters pass; all lists every one

# How many applications to send a day: a few good ones beat a burst. Today and the queue say how many went
# out today. Nothing is ever blocked. daily: 0 turns it off (when looking for work is your full-time job).
# pace:
#   daily: 3
#   max: 5

# `jobwatch calendar` writes your follow-up days and interviews as a .ics file; the page serves the same feed
# to subscribe to. remind: minutes before an interview or call to be reminded (0: no reminder).
# calendar:
#   remind: 30
# An application with no news (a stage change or a note) for this many days has gone quiet: the Applications
# page groups them, `jobwatch quiet` lists them with what to do next, and one that's quiet for `long` days
# stops crowding the follow-ups due. Nothing is ever changed for you. 0 never counts that stage.
# quiet:
#   applied: 21
#   screening: 14
#   interviewing: 10
#   long: 45

# Relevance: keyword -> weight. Title hits count double. Prefix "re:" for a regex.
keywords:
  Python: 2
  machine learning: 2
  distributed systems: 1

# The work you want most, as title regexes: these jobs lead Today and are scored first, ahead of better
# scores outside them (the rest still show, after). A title that matches more of them ranks higher.
# focus: [security, '\\bml\\b', machine learning]

# Optional fit scoring with shortlist-ai (pip install 'jobwatch[score]').
# resume: ~/Documents/resume.pdf
scoring:
  backend: claude        # claude (ANTHROPIC_API_KEY), local (a model server: LOCAL_LLM_URL) or agy (Antigravity CLI)
  # The voice mock interview turns speech into text at LOCAL_LLM_URL's /audio/transcriptions (or LOCAL_STT_URL).
  top: 0                # score this many of the most relevant new jobs per digest
  # model: ""            # the model fit scores use; leave out for shortlist-ai's own for the backend
  # keychain: anthropic  # macOS keychain item holding the API key, when ANTHROPIC_API_KEY isn't set (chat too)
  # key_command: op read op://Private/Anthropic/credential  # or a command that prints the key, run in its place
  # fallback: [agy, local]  # other backends, tried in order, when this can't score (no key, no credit) or is at...
  # daily: 40            # ...the most jobs it scores a day (0: no limit); the fallback's are scored again later
  # per_company: 25      # the most jobs from one company the page scores a day (0: no cap); the rest wait for tomorrow
  # agy_model: claude-sonnet-5-5-medium  # agy's model as a fallback (`agy models`); as backend: `model`
  # An entry can name its model, so one backend is tried again on another model's quota first:
  #   backend: agy, model: claude-sonnet-5-5-medium, fallback: [agy:gemini-3.8-flash-medium, local]
  # An OpenAI-compatible API (a free tier, say) is a provider; its name is then a backend in fallback entries:
  #   providers: {acme: {url: "https://api.example.com/v1", keychain: jobwatch-acme}}
  #   fallback: [acme:<model>, local]
  # workers: 4           # Claude calls at once (the local model takes one at a time)
  # auto: true          # `jobwatch ui` scores every new match in the background (default: on for local)
  # batch: 10            # ...this many jobs in a row, then rests (0: no rests)
  # rest: 10             # ...for this many minutes
  # prompts: {}          # edited fit-score prompts, by name (Settings > Fit score prompt; see --show-prompts)

# The assistant (`jobwatch ask`, Ask jobwatch on the page). Leave a setting out for its default.
# chat:
#   backend: local                                  # claude or local; default: scoring.backend
#   claude_model: claude-sonnet-5-5
#   max_tokens: 1500                                # the longest reply
#   max_turns: 24                                   # the latest messages sent with each question
#   # prompt: |                                     # its instructions (Settings > Chat); keep {today} and {context}

# Optional: your projects in your own words (see examples/stories.yaml in the repo). `jobwatch prep KEY --draft`
# drafts likely questions and answer outlines from them and your resume only, with the chat's model.
# stories: ~/Documents/stories.yaml
# prep:
#   max_tokens: 4000                                # the longest draft
#   # prompt: |                                     # the drafting instructions; keep {context}
#   # sheets: ~/Documents/prep                      # prep sheets you wrote (acme-onsite.html), on Interviews
#   # cache_max: 15G                                # slidecast's clip cache cap when an edit re-renders a drill video

# Where a spoken answer is turned into text (the voice mock interview, the rehearsal page's mic): an OpenAI-style
# endpoint. Default: LOCAL_STT_URL, else the local model server's (LOCAL_LLM_URL) /audio/transcriptions.
# speech:
#   url: http://127.0.0.1:8010/v1/audio/transcriptions

# Optional: tailor a resume to a job from its card with resume-kit (https://github.com/vinayvobbili/resume-kit).
# Its `resume` command is found on PATH; name it here when it isn't.
# resume_kit: ~/tools/resume-kit/.venv/bin/resume

# Expected pay from Levels.fyi (off unless levels is true). See docs/guide/watchlist.md in jobwatch's repo.
# pay:
#   levels: true
#   years: 10              # your years of experience
#   ask_over: 10           # ask this many percent over the level's median base
#   round: 5000            # rounded up to this
#   today: 15              # how many of Today's jobs get looked up
#   target: 180000         # your target base: shown on prep sheets next to the posted range
#   # target: 180000-210000  # or a range (or target_max: 210000 beside target: 180000)
#   floor: 150000          # your private floor: on your own sheet only, never sent to Claude

# What you want next: the Comps tab's career part scores jobs against it. Best first; "any" cares about none.
# Leave company_kinds and roles out and the career part keeps its fixed rules (tech 80, consulting 55,
# enterprise 40; product +15, customer +5, internal -5).
# goals:
#   about: "Staff engineer, ten years in security tooling, ready to build product again."
#   company_kinds: [tech, consulting, enterprise]   # or: any
#   roles: [product, customer, internal]            # what the job builds; or: any
#   stages: [growth, startup, public]               # seed-Series B, Series C+, listed; for companies whose
#                                                   # Company health says it; or: any
#   track: ic                                       # ic, manager or either
#   horizon: "take risks for the next 3-5 years"

# How the Comps tab ranks your opportunities (any numbers, scaled to add up to 1). See docs/guide/comps.md.
# comps:
#   weights: {career: 25, pay: 30, fit: 20, progress: 10, health: 15}

# Companies to watch (from alerts, `add` and HN posts):
# suggestions:
#   half_life: 30          # days: a job this old counts half as much as one from today
#   limit: 10              # how many companies are listed
#   auto_watch: false      # true: each check adds a board when one of the company's jobs is on it and you've
#                          # applied there, it has an office near you, or it has min_jobs matching jobs
#   min_jobs: 2            # matching jobs that make a company worth watching on their own (1: any matching job;
#                          # `jobwatch suggest --preview-auto --min-jobs 1` shows what that would add)
#   never_watch: [Globex Staffing]  # companies auto_watch leaves alone; staffing and recruiting agencies and
#                          # colleges are left alone anyway, unless you applied there

# A board this slow to read is read less often (0 days: every board on every check; `fetch --all` reads them all):
# slow_boards:
#   seconds: 120
#   every_days: 2

# Other programs' log files, shown on Activity beside jobwatch's own (the last 50 lines, newest first; read only):
# ui:
#   activity_logs:
#     - {name: Globex watcher, path: "~/Library/Logs/globex-watcher.log"}

# Which sources jw-incoming (toolbelt) polls for new personal messages; a source left out is on. The Gmail
# app password is in the Keychain (`jw-incoming --set-password you@example.com`), never here:
# incoming:
#   sources: {texts: true, whatsapp: true, gmail: true, linkedin: true}
#   gmail_account: you@example.com

# Skills to build:
# learning:
#   timeline: quarter      # week, month, quarter or any
#   jobs: 5                # example jobs listed with each skill

# Optional: LinkedIn's Connections.csv, to show who you know at each company (a referral beats applying cold).
# connections: ~/Downloads/Connections.csv
# People never to suggest, by name or LinkedIn profile link:
# connections_skip: [Jane Doe, https://www.linkedin.com/in/example-john]
# Where you work now: your colleagues there aren't listed as people you know (an internal move needs no referral).
# employer: Initech

# state: ~/.local/share/jobwatch/state.db
"""
