"""Follow-up days in Apple Reminders (macOS only; off unless the watchlist says `follow_ups: reminders`).

An application with a follow-up day gets one reminder, "Follow up: Company — Role", due that day at 9:00 with an
alert, when there is something to do: its stage is live (screening, interviewing, offer; snoozed or not) or, at
applied, its next step is an action, not a wait ("Wait for the recruiter", "no action" and the like). A snoozed
applied one gets none (`follow_ups: reminders-all` makes one for every open application). The notes hold the next
step, the posting's link and a marker line, `jobwatch:<key>`, which is how the reminder is found again. Change or
clear the day, or an application stops qualifying (closed, snoozed, next step cleared), and the reminder moves or is
deleted. Reminders without the marker are never touched. One a person
completes by hand for the same day stays completed: it isn't made again.

The Reminders app is driven through osascript and JXA, so nothing is installed. The first run asks macOS for
permission to control Reminders. A failure never stops what the person was doing: it prints one line, once.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date, datetime

from .comps import LIVE
from .quiet import snoozed_until
from .store import ENDED, IN_PROGRESS, Store

DUE_HOUR = 9
MARKER = "jobwatch:"  # a notes line, then the application's key; one-offs carry none and are never synced
PERMISSION_HELP = ("jobwatch couldn't reach Reminders: turn on System Settings > Privacy & Security > Automation > "
                   "(your terminal or jobwatch's app) > Reminders, and check Privacy & Security > Reminders")

_warned = False


class RemindersError(Exception):
    """A failure to report as one plain line."""


# Each script reads ARGS (a JSON object spliced in as a literal) and prints one JSON value.
_PRELUDE = "const app = Application('Reminders'); app.includeStandardAdditions = true;\nconst ARGS = %s;\n"

# Every reminder whose notes carry the marker, in any list, open or completed: found[key] = [{r, done, due}].
_FIND = """
const found = {};
for (const l of app.lists()) {
  const q = l.reminders.whose({body: {_contains: 'jobwatch:'}});
  const n = q.length;
  if (!n) continue;
  // held by id: a query's own index shifts as others go
  const bodies = q.body(), dues = q.dueDate(), done = q.completed(), ids = q.id();
  for (let i = 0; i < n; i++) {
    const m = /^jobwatch:(\\S+)$/m.exec(bodies[i] || '');
    if (!m) continue;
    (found[m[1]] = found[m[1]] || []).push(
      {r: l.reminders.byId(ids[i]), done: done[i], due: dues[i] ? Math.floor(dues[i].getTime() / 1000) : null});
  }
}
"""

SYNC_BODY = _FIND + """
const out = {created: 0, moved: 0, deleted: 0, kept: 0};
const want = {};
for (const it of ARGS.items) want[it.key] = true;
for (const it of ARGS.items) {
  const have = found[it.key] || [];
  const open = have.filter(h => !h.done);
  const due = new Date(it.due * 1000);
  if (open.length) {
    const r = open[0].r;
    const same = open[0].due === it.due && r.name() === it.title && (r.body() || '') === it.notes;
    if (same) { out.kept++; } else {
      r.name = it.title; r.body = it.notes; r.dueDate = due; r.remindMeDate = due; out.moved++;
    }
    for (const extra of open.slice(1)) { app.delete(extra.r); out.deleted++; }
  } else if (have.some(h => h.due === it.due)) {
    out.kept++;  // finished by hand for this day: leave it
  } else {
    app.defaultList().reminders.push(app.Reminder({name: it.title, body: it.notes, dueDate: due, remindMeDate: due}));
    out.created++;
  }
}
for (const key of Object.keys(found)) {
  if (want[key] || !(ARGS.prune || ARGS.drop.includes(key))) continue;
  for (const h of found[key]) { app.delete(h.r); out.deleted++; }
}
JSON.stringify(out);
"""

ONCE_BODY = """
const due = new Date(ARGS.due * 1000);
const props = {name: ARGS.title, dueDate: due, remindMeDate: due};
if (ARGS.notes) props.body = ARGS.notes;
app.defaultList().reminders.push(app.Reminder(props));
JSON.stringify({title: ARGS.title, due: ARGS.due});
"""


def build_script(body: str, args: dict) -> str:
    """The JXA source: the prelude with `args` as JSON, then `body`."""
    return _PRELUDE % json.dumps(args) + body


def run_script(script: str, timeout: int = 120) -> dict:
    """Run JXA through osascript and return the JSON it printed."""
    try:
        proc = subprocess.run(["osascript", "-l", "JavaScript", "-e", script], check=False, capture_output=True,
                              text=True, timeout=timeout)
    except FileNotFoundError:
        raise RemindersError("osascript isn't available") from None
    except subprocess.TimeoutExpired:
        raise RemindersError("Reminders didn't answer in time") from None
    if proc.returncode != 0:
        err = proc.stderr.strip()
        if "-1743" in err or "not allowed" in err.lower() or "not authorized" in err.lower():
            raise RemindersError(PERMISSION_HELP)
        line = err.splitlines()[-1] if err else "osascript failed"
        raise RemindersError(line.split("Error: ", 1)[-1].replace("execution error: ", ""))
    try:
        return json.loads(proc.stdout)
    except ValueError:
        raise RemindersError(f"unexpected output from osascript: {proc.stdout.strip()[:80]!r}") from None


def enabled(cfg) -> bool:
    """Reminders sync is on: the watchlist asks for it and this is a Mac."""
    return cfg.follow_ups in ("reminders", "reminders-all") and sys.platform == "darwin"


def due_epoch(day: str) -> int:
    """9:00 local time on a YYYY-MM-DD day, in epoch seconds."""
    return int(datetime.combine(date.fromisoformat(day), datetime.min.time()).replace(hour=DUE_HOUR).timestamp())


# A next step that is a wait, not something to do: it starts with one of these words ("None; let it go" included),
# or says one of the phrases anywhere. "none" mid-sentence doesn't count ("follow up through Pooja if none").
WAITING = re.compile(r"^\W*(wait|waiting|waits|await|awaiting|awaits|passive|no action|none)\b|"
                     r"\b(hear back|hearing back|no action|passive)\b", re.IGNORECASE)


def waiting(next_step: str | None) -> bool:
    """The next step is a wait (or empty), so there's nothing for the person to do."""
    text = (next_step or "").strip()
    return not text or bool(WAITING.search(text))


def item(job, rec: dict, everything: bool = False) -> dict | None:
    """What the reminder for this application should be, or None when it should have none: it isn't open, has no
    follow-up day, or has nothing to do. A live stage (screening, interviewing, offer) always has something, snoozed
    or not; an applied one needs a next step that is an action, not a wait. everything: every open one with a day."""
    if rec["status"] not in IN_PROGRESS or not rec.get("follow_up"):
        return None
    if not everything and rec["status"] not in LIVE and (snoozed_until(rec) or waiting(rec.get("next_step"))):
        return None
    notes = [rec["next_step"]] if rec.get("next_step") else []
    if job.url:
        notes.append(job.url)
    notes.append(MARKER + job.key)
    return {"key": job.key, "title": f"Follow up: {job.display_company} — {job.title}",
            "due": due_epoch(rec["follow_up"]), "notes": "\n".join(notes)}


def _apply(items: list[dict], drop: list[str], prune: bool) -> dict:
    # each change takes Reminders a few seconds, so a full sync after many changes needs far longer than one mark
    return run_script(build_script(SYNC_BODY, {"items": items, "drop": drop, "prune": prune}),
                      timeout=900 if prune else 120)


def _warn(exc: Exception) -> None:
    """The one plain line, the first time only: a refused permission would otherwise repeat on every change."""
    global _warned
    if not _warned:
        _warned = True
        print(f"jobwatch: follow-up reminders skipped: {exc}", file=sys.stderr)


def refresh(cfg, store: Store, keys: list[str]) -> None:
    """Make Reminders match these applications' follow-up days, after they changed. Does nothing when it's off, and
    never raises: it is called inside marking, snoozing and the page, which must not fail over a reminder."""
    if not enabled(cfg) or not keys:
        return
    try:
        items, drop = [], []
        for key in dict.fromkeys(keys):
            job, rec = store.find(key)
            if want := item(job, rec, cfg.follow_ups == "reminders-all"):
                items.append(want)
            else:
                drop.append(job.key)
        _apply(items, drop, prune=False)
    except (RemindersError, KeyError, ValueError, OSError) as e:
        _warn(e)


def sync(cfg, store: Store) -> dict:
    """Make Reminders match every follow-up now: create the missing, move the changed, delete the ones whose
    application is closed, has no day, no longer qualifies or is gone. Idempotent. Returns counts: created, moved,
    deleted, kept.
    Raises RemindersError (the command prints it); off or not a Mac: nothing happens."""
    if not enabled(cfg):
        return {"created": 0, "moved": 0, "deleted": 0, "kept": 0}
    everything = cfg.follow_ups == "reminders-all"
    items = [want for job, rec in store.jobs((*IN_PROGRESS, *ENDED), include_closed=True)
             if (want := item(job, rec, everything))]
    return _apply(items, [], prune=True)


def sync_quietly(cfg, store: Store) -> None:
    """sync for places that go on whatever happens (the page starting)."""
    try:
        sync(cfg, store)
    except (RemindersError, OSError) as e:
        _warn(e)


def add_once(title: str, due: datetime, notes: str = "") -> dict:
    """A one-off reminder from the page's bell: title, a day and time, an optional note. Not tied to a follow-up day,
    so a sync leaves it alone. Raises RemindersError."""
    if not title.strip():
        raise RemindersError("a reminder needs a title")
    if sys.platform != "darwin":
        raise RemindersError("reminders need macOS")
    return run_script(build_script(ONCE_BODY, {"title": title.strip(), "due": int(due.timestamp()),
                                               "notes": notes.strip()}))
