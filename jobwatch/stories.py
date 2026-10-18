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
      avoid: [the vendor's name]

`avoid` is optional: details you don't remember for sure or don't want said. A drafted answer or a tightened
mock answer that says one is not offered. add() appends a story (Find a story, storyfind.py) without touching the
rest of the file, so its comments stay.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import yaml

from .config import ConfigError

# What each field is, for the error that says it's missing.
FIELDS = {"id": "a short name to cite it by, like alert-dedupe",
          "title": "a few words: what it was",
          "did": "what you did, yourself",
          "hard": "the hard part",
          "result": "what came of it, with numbers if you have them"}
OPTIONAL = ("skills", "avoid")
_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_FIELD = 1200  # a story is a few sentences; much longer and it crowds out the posting in the prompt
MAX_STORIES = 60
MAX_AVOID = 12
HEADER = ("# Your stories for jobwatch: real projects in your own words (see examples/stories.yaml in the repo).\n"
          "# Drafted interview answers may only use these and your resume.\n")


@dataclass(frozen=True)
class Story:
    id: str
    title: str
    did: str
    hard: str
    result: str
    skills: tuple[str, ...] = field(default=())
    avoid: tuple[str, ...] = field(default=())  # details not to say: not remembered for sure, or kept out

    def text(self) -> str:
        """The story as the model reads it, and as invented numbers are checked against."""
        lines = [f"[{self.id}] {self.title}", f"Did: {self.did}", f"Hard part: {self.hard}",
                 f"Result: {self.result}"]
        lines += [f"Skills: {', '.join(self.skills)}"] if self.skills else []
        return "\n".join(lines + ([f"Don't say (not confirmed): {'; '.join(self.avoid)}"] if self.avoid else []))

    def to_dict(self) -> dict:
        """As the story file has it: the optional fields only when set."""
        out = asdict(self)
        return {k: list(v) if isinstance(v, tuple) else v for k, v in out.items() if v or k in FIELDS}


def _words(text: str) -> str:
    return " ".join(re.findall(r"[\w'’+#-]+(?:\.[\w+#-]+)*", text.lower()))  # node.js is a word, "cat." is cat


def said(text: str, bank: list[Story]) -> list[str]:
    """The `avoid` details of these stories that the text says (matched as whole words, ignoring case)."""
    words = f" {_words(text)} "
    return [a for s in bank for a in s.avoid if (w := _words(a)) and f" {w} " in words]


def _list(raw, name: str, where: str, example: str) -> list[str]:
    value = raw.get(name) or []
    if isinstance(value, str):
        value = value.split(",") if name == "skills" else [value]
    if not isinstance(value, list) or not all(isinstance(s, str) for s in value):
        raise ConfigError(f"{where}: {name} is a list, like {example}, got {value!r:.80}")
    return [" ".join(s.split()) for s in value if s.strip()]


def _story(raw, where: str) -> Story:
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
    avoid = _list(raw, "avoid", where, "[the vendor's name]")
    if len(avoid) > MAX_AVOID:
        raise ConfigError(f"{where}: {len(avoid)} details to avoid; keep it to {MAX_AVOID}")
    return Story(**values, skills=tuple(_list(raw, "skills", where, "[Python, Kafka]")), avoid=tuple(avoid))


def check(raw) -> Story:
    """One story from outside the file (Find a story, an MCP client), checked the same way as the file's."""
    return _story(raw, "the story")


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
    out = [_story(s, f"{path}: story {n}") for n, s in enumerate(raw, 1)]
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


def _free_id(wanted: str, taken: set[str]) -> str:
    n, out = 2, wanted
    while out in taken:
        out, n = f"{wanted}-{n}", n + 1
    return out


def add(path: Path, story: Story) -> Story:
    """Append a story to the file (made if missing), with a free id (alert-dedupe-2 when alert-dedupe is taken),
    and return it as saved. The rest of the file is left as it is, comments too; the new text is read back
    before it replaces the old file, which is kept as <name>.bak."""
    text = path.read_text(encoding="utf-8") if path.is_file() else HEADER
    bank = parse(text, path)
    if len(bank) >= MAX_STORIES:
        raise ConfigError(f"{path}: already {len(bank)} stories; keep the best {MAX_STORIES} before adding one")
    story = replace(story, id=_free_id(story.id, {s.id for s in bank}))
    item = re.search(r"^([ \t]*)-[ \t]+id:", text, re.M)
    if item:
        indent = item.group(1)
    elif isinstance(yaml.safe_load(text), dict):  # an empty `stories:` heading: start its list
        text, indent = re.sub(r"^stories:.*$", "stories:", text, count=1, flags=re.M), "  "
    else:
        indent = ""
    block = yaml.safe_dump([story.to_dict()], sort_keys=False, allow_unicode=True, width=110)
    new = text.rstrip("\n") + "\n\n" + "".join(indent + line if line.strip() else line
                                                for line in block.splitlines(keepends=True))
    if story not in parse(new, path):
        raise ConfigError(f"{path}: couldn't add the story without changing the others; add it by hand")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".new")
    tmp.write_text(new, encoding="utf-8")
    if path.is_file():
        path.replace(path.with_name(path.name + ".bak"))
    tmp.replace(path)
    return story
