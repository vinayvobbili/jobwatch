"""The last lines of the text logs the watchlist names (ui.activity_logs), for Activity. Read only, and only the
files the watchlist names: a request never says which file."""
from __future__ import annotations

import re
from pathlib import Path

LINES = 50
_TAIL_BYTES = 256 * 1024  # a log can be large: only its end is read
_STAMP = re.compile(r"^\s*\[?(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2})?)\]?[ \t:-]*")


def parse_line(line: str) -> dict:
    """{at, text}: at is the local time the line starts with (2026-01-02 03:04:05), or None when it has none."""
    m = _STAMP.match(line)
    if not m:
        return {"at": None, "text": line.strip()}
    clock = m.group(2) if m.group(2).count(":") == 2 else m.group(2) + ":00"
    return {"at": f"{m.group(1)}T{clock}", "text": line[m.end():].strip()}


def tail(path: Path, lines: int = LINES) -> list[str] | None:
    """The file's last non-empty lines, oldest first; None when there's no such file (yet) or it can't be read."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - _TAIL_BYTES))
            data = f.read()
    except OSError:
        return None
    rows = data.decode("utf-8", errors="replace").splitlines()
    if size > _TAIL_BYTES:
        rows = rows[1:]  # the first may be cut in half
    return [r for r in rows if r.strip()][-lines:]


def activity_logs(logs, lines: int = LINES) -> list[dict]:
    """One entry per configured log: {name, exists, lines: [{at, text}]}, newest first."""
    out = []
    for log in logs:
        rows = tail(log.path, lines)
        out.append({"name": log.name, "exists": rows is not None,
                    "lines": [parse_line(r) for r in reversed(rows or [])]})
    return out
