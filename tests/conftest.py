"""Canned board responses shaped like the real Greenhouse, Lever and Ashby APIs. No network in tests."""

from __future__ import annotations

import http.client
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from jobwatch import sources

NOW = datetime.now(timezone.utc)
TOKEN = "test-token"


def iso(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


GREENHOUSE = {
    "jobs": [
        {
            "id": 101, "title": "Senior Software Engineer, Platform", "company_name": "Acme",
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/101",
            "location": {"name": "Austin, TX | Remote-Friendly, United States"},
            "offices": [{"name": "Austin", "location": "Austin, Texas, United States"}],
            "metadata": [{"name": "Location Type", "value": "Remote"}],
            "departments": [{"name": "Engineering"}],
            "first_published": iso(3),
            # Greenhouse sends its HTML entity-escaped.
            "content": "&lt;p&gt;Build &lt;strong&gt;Python&lt;/strong&gt; services.&lt;/p&gt;&lt;ul&gt;"
                       "&lt;li&gt;Distributed systems&lt;/li&gt;&lt;/ul&gt;&lt;p&gt;Annual Salary: $180,000 "
                       "&amp;mdash; $240,000 USD&lt;/p&gt;",
        },
        {
            "id": 102, "title": "Account Executive", "company_name": "Acme",
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/102",
            "location": {"name": "London, UK"}, "offices": [], "metadata": [], "departments": [{"name": "Sales"}],
            "first_published": iso(1), "content": "&lt;p&gt;Sell things.&lt;/p&gt;",
        },
    ],
    "meta": {"total": 2},
}

LEVER = [
    {
        "id": "aaaa-1111", "text": "Machine Learning Engineer",
        "hostedUrl": "https://jobs.lever.co/globex/aaaa-1111",
        "categories": {"department": "AI", "location": "Remote (United States)",
                       "allLocations": ["Remote (United States)"]},
        "workplaceType": "remote", "createdAt": int((NOW - timedelta(days=10)).timestamp() * 1000),
        "descriptionPlain": "Train machine learning models in Python.",
        "lists": [{"text": "You will:", "content": "<li>Ship LLM features</li>"}],
        "additionalPlain": "Benefits.",
        "salaryRange": {"currency": "USD", "interval": "per-year-salary", "min": 150000, "max": 210000},
    },
    {
        "id": "bbbb-2222", "text": "Data Engineer (Contract)",
        "hostedUrl": "https://jobs.lever.co/globex/bbbb-2222",
        "categories": {"department": "Data", "location": "Toronto, ON", "allLocations": ["Toronto, ON"]},
        "workplaceType": "onsite", "createdAt": int((NOW - timedelta(days=90)).timestamp() * 1000),
        "descriptionPlain": "Pipelines.", "lists": [],
        "salaryRange": {"currency": "USD", "interval": "per-hour-wage", "min": 60, "max": 80},
    },
]

ASHBY = {
    "jobs": [
        {
            "id": "c1", "title": "Staff AI Engineer", "department": "Research", "location": "Denver, CO",
            "secondaryLocations": [{"location": "Remote"}], "isListed": True, "isRemote": True,
            "workplaceType": "Hybrid", "publishedAt": iso(0),
            "jobUrl": "https://jobs.ashbyhq.com/initech/c1",
            "address": {"postalAddress": {"addressCountry": "United States"}},
            "descriptionPlain": "Agents, RAG and evaluation. Python.",
            "compensation": {"compensationTiers": [{"components": [
                {"compensationType": "Salary", "interval": "1 YEAR", "currencyCode": "USD",
                 "minValue": 230000, "maxValue": 300000},
                {"compensationType": "EquityCashValue", "interval": "1 YEAR", "minValue": None}]}]},
        },
        {
            "id": "c2", "title": "Unlisted Role", "isListed": False, "location": "Remote",
            "jobUrl": "https://jobs.ashbyhq.com/initech/c2", "descriptionPlain": "",
        },
    ],
}

RESPONSES = {
    "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true": GREENHOUSE,
    "https://api.lever.co/v0/postings/globex?mode=json": LEVER,
    "https://api.ashbyhq.com/posting-api/job-board/initech?includeCompensation=true": ASHBY,
}


class FakeWeb:
    """Stands in for sources.get_json: serves RESPONSES, 404s everything else, records calls."""

    def __init__(self, responses=None):
        self.responses = dict(RESPONSES if responses is None else responses)
        self.calls: list[str] = []

    def __call__(self, url, timeout=30, body=None):
        self.calls.append(url)
        if url not in self.responses:
            raise sources.NotFound(url)
        value = self.responses[url]
        if callable(value):  # answers a POST: value(body)
            value = value(body)
        if isinstance(value, Exception):
            raise value
        return value


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    """A test that reaches the real internet fails, rather than quietly depending on live boards.
    The exception: tests marked `network`, which only run when asked for."""
    if request.node.get_closest_marker("network"):
        return

    def refuse(*args, **kwargs):
        raise AssertionError("tests must not use the network; use the `web` fixture")

    monkeypatch.setattr(sources.urllib.request, "urlopen", refuse)


@pytest.fixture(autouse=True)
def no_real_state(tmp_path, monkeypatch):
    """A watchlist without `state:` uses the default database: in tests, never the real one in $HOME."""
    from jobwatch import config

    monkeypatch.setattr(config, "DEFAULT_STATE", tmp_path / "default-state" / "state.db")
    monkeypatch.setattr(config, "DEFAULT_CACHE", tmp_path / "default-cache")
    monkeypatch.setattr(config, "DEFAULT_PATHS", (tmp_path / "jobwatch.yaml", tmp_path / "home-config.yaml"))
    monkeypatch.delenv("JOBWATCH_CONFIG", raising=False)


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb()
    monkeypatch.setattr(sources, "get_json", fake)
    # Boards read as web pages or XML (SmartRecruiters, Avature) aren't in RESPONSES: looking for a board finds
    # none there.
    monkeypatch.setattr(sources, "get_text", FakeWeb({}))
    return fake


@pytest.fixture
def watchlist(tmp_path):
    path = tmp_path / "jobwatch.yaml"
    path.write_text(
        "companies:\n  - greenhouse:acme\n  - lever:globex\n  - {source: ashby, board: initech, name: Initech}\n"
        "filters:\n  locations: [remote, Denver]\n  exclude_titles: [contract]\n  max_age_days: 30\n"
        "keywords:\n  Python: 2\n  LLM: 3\n  RAG: 3\n"
        "state: state.db\ncache: cache\n"
    )
    return path


@pytest.fixture
def server(watchlist, web):
    """`jobwatch ui` on a free port, serving the test watchlist; yields the port."""
    from jobwatch.web import serve

    srv = serve(watchlist, port=0, open_browser=False, token=TOKEN)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.app.refresher.stop(10)  # its first check (on the fake boards) ends before they go away
    srv.shutdown()
    srv.server_close()


def request(port, method, path, body=None, headers=None, host=None, raw=None, with_headers=False):
    """(status, body), or (status, body, headers). `raw` sends bytes as they are instead of JSON."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Host": host or f"127.0.0.1:{port}", **(headers or {})}
    conn.request(method, path, body=raw if raw is not None else json.dumps(body) if body is not None else None,
                 headers=h)
    r = conn.getresponse()
    data = r.read()
    conn.close()
    return (r.status, data, dict(r.getheaders())) if with_headers else (r.status, data)
