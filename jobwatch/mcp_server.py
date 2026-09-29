"""MCP server exposing jobwatch to an AI assistant: find boards, fetch, digest, and track applications."""

from __future__ import annotations

import json
import os

from mcp.server.mcpserver import MCPServer

from . import config, report, sources
from .store import Store
from .watch import build_digest, fetch_all

server = MCPServer(
    "jobwatch",
    instructions=(
        "Watches company job boards (Greenhouse, Lever, Ashby) from a watchlist file. fetch_jobs checks every "
        "board; digest ranks the new matches (optionally fit-scored with shortlist-ai); job_details gives a "
        "posting's full text for tailoring a resume; mark_job records applied/skipped. find_board looks up a "
        "company's board to add to the watchlist. jobwatch never applies to anything by itself."
    ),
)


def _open():
    cfg = config.load(os.environ.get("JOBWATCH_CONFIG"))
    return cfg, Store(cfg.state)


@server.tool()
def find_board(company: str) -> list[dict]:
    """Find a company's job board by name or by a job/careers link. Returns entries for the watchlist.
    A guessed board name can belong to another company: check the sample titles before adding one."""
    return [{"entry": f"{s}:{b}", "open_roles": len(jobs), "careers": sources.SOURCES[s].careers.format(board=b),
             "sample_titles": [j.title for j in jobs[:5]]}
            for s, b, jobs in sources.probe(company)]


@server.tool()
def fetch_jobs() -> str:
    """Check every board in the watchlist and record new roles."""
    cfg, store = _open()
    try:
        return report.fetch_summary(fetch_all(cfg, store))
    finally:
        store.close()


@server.tool()
def digest(score_top: int = 0, include_seen: bool = False, limit: int = 25, mark_shown: bool = True) -> dict:
    """New jobs that pass the filters, best first. score_top > 0 fit-scores that many of the most relevant
    unscored jobs with shortlist-ai (slow: minutes per job on the local backend)."""
    cfg, store = _open()
    try:
        d = build_digest(cfg, store, include_seen=include_seen, score_top=score_top, limit=limit)
        if mark_shown:
            store.set_status([k for e in d.entries for k in e.keys], "shown")
        return json.loads(report.to_json(d))
    finally:
        store.close()


@server.tool()
def job_details(key: str) -> dict:
    """A job's full posting text and tracking status, by key or posting id."""
    _, store = _open()
    try:
        job, rec = store.find(key)
        return {"key": job.key, "text": job.to_text(), **rec}
    finally:
        store.close()


@server.tool()
def mark_job(key: str, status: str, note: str | None = None) -> str:
    """Record a job's status: new, shown, applied or skipped. Use after the person applies or passes."""
    _, store = _open()
    try:
        job, _ = store.find(key)
        store.set_status([job.key], status, note)
        return f"{job.key}: {status}"
    finally:
        store.close()


@server.tool()
def list_jobs(status: str | None = None) -> list[dict]:
    """Tracked jobs, optionally only one status (e.g. applied), newest first."""
    _, store = _open()
    try:
        return [{"key": j.key, "company": j.display_company, "title": j.title, "url": j.url, **rec}
                for j, rec in store.jobs((status,) if status else None, include_closed=True)]
    finally:
        store.close()


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
