"""The morning digest (`jobwatch digest --notify`, and the day's first scheduled check of the boards): the best new
matches pushed to you instead of waiting on the page.

After the first scheduled check of the day a macOS notification names the top few new matches, each with its fit
score or pay, and opens a digest page with the same list (more of it) next to your Today page. The matches are the
ones Today shows for the same filters (title, place, pay floor, age, minimum fit), still new or shown (never applied
to, queued or skipped), not a copy of a job you already acted on, and first seen since the last digest. With nothing
new there is no notification and no page: a quiet morning stays quiet. It runs on the computer's own clock and needs
no credentials: the notification goes through `terminal-notifier` when it's installed (a click opens the page),
else through osascript, which can't open anything on a click.

`morning.notify: off` in the watchlist turns the scheduled one off; `jobwatch digest --notify` always runs. Both save
the day's digest, so the scheduled one does not repeat a digest you already read. `--dry-run` reads and prints only.
"""

from __future__ import annotations

import html as _html
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from . import APP_HOST, service
from .closed_notice import NoticeError, popup
from .config import MORNING_PAGE, Config
from .localday import local_day
from .prep import _CSS, _switches
from .store import Store
from .watch import build_digest

FIRST_LOOK = timedelta(hours=24)   # with no digest before, matches first seen in this long
LONGEST = timedelta(days=3)        # however long ago the last digest was, never further back than this
SCORE_WAIT = 600                   # seconds the scheduled digest waits for the background scorer, so fits are in


def digest_url(store: Store, port: int | None = None) -> str:
    """Where the digest page is served (see web.py): the UI's address with this install's secret, which a click on a
    notification can't send a token for."""
    return f"http://{APP_HOST}:{port or service.installed_port() or 8765}/digest/{store.secret('digest')}"


def pick(cfg: Config, store: Store, since: datetime, limit: int = MORNING_PAGE) -> tuple[list[dict], int]:
    """(the new matches, best first and at most `limit`, how many there are): what Today ranks, kept to the jobs first
    seen after `since` and not (maybe) the same opening as one acted on. Each is {key, title, company, url, fit
    (0-100 or None), pay, place}."""
    found = []
    for e in build_digest(cfg, store, include_seen=True, score_top=0).entries:
        if e.duplicate or datetime.fromisoformat(e.record["first_seen"]) <= since:
            continue
        j = e.job
        found.append({"key": j.key, "title": j.title, "company": j.display_company, "url": j.url,
                      "fit": round(e.fit["score"]) if e.fit and not e.fit.get("stale") else None,
                      "pay": j.pay() or "", "place": "; ".join(j.places[:2])})
    return found[:limit], len(found)


def line(item: dict) -> str:
    """ "Platform Engineer, Initech (82/100 fit)": fit when scored, else pay, else where."""
    extra = f"{item['fit']}/100 fit" if item["fit"] is not None else item["pay"] or item["place"]
    return f"{item['title']}, {item['company']}" + (f" ({extra})" if extra else "")


def summary(items: list[dict], total: int, shown: int) -> tuple[str, str]:
    """(title, body) of the notification: how many new matches, then up to `shown` of them one to a line."""
    lines = [line(i) for i in items[:shown]]
    if total > len(lines):
        lines.append(f"+{total - len(lines)} more")
    return f"jobwatch: {total} new match{'es' * (total != 1)}", "\n".join(lines)


def notify(title: str, body: str, url: str = ""):
    """The notification. With terminal-notifier (brew install terminal-notifier) a click opens `url`; without it,
    osascript shows the text only (a notification it sends can't open a page). NoticeError when neither can show it."""
    if sys.platform != "darwin":
        raise NoticeError("the notification is macOS only: use --dry-run to read what it would say")
    if tool := shutil.which("terminal-notifier"):
        cmd = [tool, "-title", title, "-message", body or " ", "-group", "jobwatch-morning", "-sound", "default"]
        r = subprocess.run(cmd + (["-open", url] if url else []), capture_output=True, text=True, check=False)
        if r.returncode:
            raise NoticeError(f"terminal-notifier failed: {r.stderr.strip() or r.stdout.strip() or r.returncode}")
        return
    popup(title, body)


def run(cfg: Config, store: Store, scheduled: bool = False, dry_run: bool = False, now: datetime | None = None,
        port: int | None = None, show: Callable[[str, str, str], None] | None = None,
        wait: Callable[[], None] | None = None, by: str = "") -> str:
    """Tell you the new matches and save the digest. `scheduled`: the day's first scheduled check calls it, so it
    does nothing when morning.notify is off or today's digest is already made. `wait` (the background scorer's) is
    called first, so scores are in. `show` (default: notify) shows the notification. `dry_run` reads and prints
    only. Returns what to print."""
    show = show or notify
    now = now or datetime.now(UTC)
    day = local_day(now.isoformat())
    if scheduled and (not cfg.morning.notify or store.morning_digest(day)):
        return "The morning digest is off." if not cfg.morning.notify else "Today's digest was already made."
    if wait and not dry_run:
        wait()
    last = store.morning_digest()
    since = max(last["at"] if last else now - FIRST_LOOK, now - LONGEST)
    items, total = pick(cfg, store, since)
    if not items:
        if not dry_run:
            store.save_morning_digest(day, [], 0, now)
        return "No new matches since the last digest."
    title, body = summary(items, total, cfg.morning.top)
    url = digest_url(store, port)
    if dry_run:
        return f"Would say:\n{title}\n{body}\n{url}"
    show(title, body, url)  # first, so a notification that failed is tried again by the next check
    store.save_morning_digest(day, items, total, now)
    store.log("boards", f"Morning digest: {total} new match{'es' * (total != 1)}", detail=[line(i) for i in items],
              by=by or ("schedule" if scheduled else "cli"), jobs=[i["key"] for i in items])
    return f"{title}\n{body}\n{url}"


# -- the page

_EXTRA = """
.job{display:grid;grid-template-columns:auto 1fr auto;gap:4px 14px;align-items:center;padding:12px 14px;
animation:rise .5s cubic-bezier(.2,.7,.2,1) both}
.job .rank{width:30px;height:30px;border-radius:50%;display:grid;place-items:center;font-weight:800;font-size:13px;
color:#fff;background:var(--grad)}
.job h3{margin:0;font-size:16px;letter-spacing:-.01em}.job h3 a{text-decoration:none;color:var(--text)}
.job h3 a:hover{color:var(--accent)}
.job .where{color:var(--muted);font-size:13.5px}
.fit{font-weight:800;font-size:13px;padding:3px 11px;border-radius:999px;color:#fff;background:var(--s-offer)}
.fit.mid{background:var(--s-interviewing)}.fit.lo{background:var(--s-rejected)}
.pay{font-weight:700;font-size:13px;padding:3px 11px;border-radius:999px;background:var(--accent-soft);
color:var(--accent)}
.stack{display:grid;gap:10px;margin-top:22px}
.empty{padding:26px;text-align:center;color:var(--muted)}
a.go{display:inline-block;margin-top:18px;padding:9px 18px;border-radius:12px;color:#fff;font-weight:700;
text-decoration:none;background:var(--grad);box-shadow:var(--shadow);transition:transform .15s,box-shadow .15s}
a.go:hover{transform:translateY(-2px);box-shadow:var(--shadow-hover)}
"""


def _e(text) -> str:
    return _html.escape(str(text), quote=True)


def _badge(item: dict) -> str:
    if item["fit"] is not None:
        cls = "" if item["fit"] >= 75 else " mid" if item["fit"] >= 50 else " lo"
        return f'<span class="fit{cls}">{item["fit"]}/100 fit</span>'
    return f'<span class="pay">{_e(item["pay"])}</span>' if item["pay"] else ""


def page(digest: dict | None) -> str:
    """The digest page for a saved digest ({day, at, items, total} from Store.morning_digest, or None before the
    first): a standalone page with inline styles only, in the prep sheets' look, and links to each posting."""
    items = digest["items"] if digest else []
    n = digest["total"] if digest else 0
    day = _e(digest["day"]) if digest else ""
    cards = "".join(
        f'<section class="job" style="animation-delay:{min(i, 8) * 40}ms"><span class="rank">{i}</span><div>'
        f'<h3><a href="{_e(it["url"])}" target="_blank" rel="noopener noreferrer">{_e(it["title"])}</a></h3>'
        f'<div class="where">{_e(it["company"])}' + (f" · {_e(it['place'])}" if it["place"] else "")
        + f"</div></div>{_badge(it)}</section>"
        for i, it in enumerate(items, 1) if it["url"].startswith(("http://", "https://")))  # a link only if it's one
    body = (f'<div class="stack">{cards}</div>' if cards else
            '<section class="empty">No new matches yet. Your next scheduled check will leave a digest here.</section>')
    more = f'<p class="muted">+{n - len(items)} more on Today.</p>' if n > len(items) else ""
    picks, segs = _switches("system", "standard")
    return ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>jobwatch morning digest</title><style>{_CSS}{_EXTRA}</style></head>\n"
            f'<body>\n{picks}\n<div class="bar"><div class="brand">job<b>watch</b> <span>· morning digest</span></div>'
            f'{segs}</div>\n<main>\n<h1>{n} new match{"es" * (n != 1)}</h1>'
            f'<p class="meta"><span>{day}</span><span>the best of what the boards posted since your last '
            'digest</span></p>'
            f'{body}{more}<a class="go" href="/">Open Today</a>\n</main>\n</body></html>\n')
