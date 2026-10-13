"""The story bank: your real projects, in your own words, for drafting interview answers (see drafts.py).

An optional YAML file, named by `stories:` in the watchlist. Each story is something you did, told the way
you'd tell it on a call: what you did, the hard part and what came of it. Drafted answers may only use these and
the resume, so a story here is a claim you've made yourself. See examples/stories.yaml.

    - id: alert-dedupe
      title: Cut duplicate on-call alerts
      did: Built a service that groups alerts for the same incident before they page anyone.
      hard: Two teams' alerts named the same host three different ways.
      result: Pages per week went from 120 to 35 in two months.
      skills: [Python, Kafka]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import ConfigError

# What each field is, for the error that says it's missing.
FIELDS = {"id": "a short name to cite it by, like alert-dedupe",
          "title": "a few words: what it was",
          "did": "what you did, yourself",
          "hard": "the hard part",
          "result": "what came of it, with numbers if you have them"}
OPTIONAL = ("skills",)
_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_FIELD = 1200  # a story is a few sentences; much longer and it crowds out the posting in the prompt
MAX_STORIES = 60


@dataclass(frozen=True)
class Story:
    id: str
    title: str
    did: str
    hard: str
    result: str
    skills: tuple[str, ...] = field(default=())

    def text(self) -> str:
        """The story as the model reads it, and as invented numbers are checked against."""
        lines = [f"[{self.id}] {self.title}", f"Did: {self.did}", f"Hard part: {self.hard}",
                 f"Result: {self.result}"]
        return "\n".join(lines + ([f"Skills: {', '.join(self.skills)}"] if self.skills else []))


def _story(raw, n: int, path: Path) -> Story:
    where = f"{path}: story {n}"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} looks like {{id: ..., title: ..., did: ..., hard: ..., result: ...}}, "
                          f"got {raw!r:.80}")
    if isinstance(raw.get("id"), str) and raw["id"].strip():
        where += f" ({raw['id'].strip()})"
    unknown = set(raw) - set(FIELDS) - set(OPTIONAL)
    if unknown:
        raise ConfigError(f"{where}: unknown field(s) {', '.join(sorted(map(str, unknown)))} "
                          f"(a story has {', '.join(FIELDS)} and optional {', '.join(OPTIONAL)})")
    values = {}
    for name, means in FIELDS.items():
        value = raw.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ConfigError(f"{where} needs {name}: {means}")
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise ConfigError(f"{where}: {name} is text, got {value!r:.80}")
        value = " ".join(str(value).split())
        if len(value) > MAX_FIELD:
            raise ConfigError(f"{where}: {name} is {len(value)} characters; keep it under {MAX_FIELD} (a few "
                              "sentences: the call is where you tell the rest)")
        values[name] = value
    if not _ID.fullmatch(values["id"]):
        raise ConfigError(f"{where}: id is lowercase letters, digits and dashes, like alert-dedupe, "
                          f"got {values['id']!r}")
    skills = raw.get("skills") or []
    if isinstance(skills, str):
        skills = skills.split(",")
    if not isinstance(skills, list) or not all(isinstance(s, str) for s in skills):
        raise ConfigError(f"{where}: skills is a list, like [Python, Kafka], got {skills!r:.80}")
    return Story(**values, skills=tuple(s.strip() for s in skills if s.strip()))


def parse(text: str, path: Path) -> list[Story]:
    """The stories in a story file's text, checked: every error names the file, the story and what to fix."""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: not valid YAML: {e}") from None
    if raw is None:
        return []
    if isinstance(raw, dict) and set(raw) == {"stories"}:  # the list under a stories: heading reads the same
        raw = raw["stories"] or []
    if not isinstance(raw, list):
        raise ConfigError(f"{path}: a story file is a list of stories, each starting with '- id:' "
                          "(see examples/stories.yaml)")
    if len(raw) > MAX_STORIES:
        raise ConfigError(f"{path}: {len(raw)} stories; keep the best {MAX_STORIES}")
    out = [_story(s, n, path) for n, s in enumerate(raw, 1)]
    seen: set[str] = set()
    for s in out:
        if s.id in seen:
            raise ConfigError(f"{path}: two stories have the id {s.id!r}: give each its own")
        seen.add(s.id)
    return out


def load(path: Path | None) -> list[Story]:
    """The story bank, or [] with none set. A file that's set but missing or wrong is an error, not an empty
    bank: drafting without the stories you meant to give would quietly say "no story yet" everywhere."""
    if not path:
        return []
    if not path.is_file():
        raise ConfigError(f"{path}: no story file there (stories: in the watchlist names it)")
    return parse(path.read_text(encoding="utf-8"), path)
