# Development

[← jobwatch guide](README.md)

```
python -m venv .venv && .venv/bin/pip install -e '.[dev,mcp]'
.venv/bin/ruff check . && .venv/bin/python -m pytest -q
```

CI tests on Python 3.11 and 3.13. `scripts/check` runs the same checks on 3.13 locally (it needs
[uv](https://docs.astral.sh/uv/), which fetches the Python). `git config core.hooksPath .githooks` runs it before
every push. To run it on another Python (or several) for one run, `scripts/check --python 3.11`; repeat the option
for more, as in `--python 3.11 --python 3.13`. CI is unchanged.

Tests use canned board responses and never touch the network, except the check that every curated course
link still resolves: `JOBWATCH_LINK_TESTS=1 pytest tests/test_learn.py`. To see how `jobwatch ui` looks after a change,
`scripts/screenshots.py` captures every tab in light and dark, at wide, desktop and phone widths, plus the
chat with a canned reply (it needs
`pip install playwright && python -m playwright install chromium`).
When a tab feels slow, `jobwatch timing` measures it: it makes each tab's API calls (what the page itself asks for)
a few times and lists them slowest first, against a running page (`--url jobwatch.localhost:8765`) or, without one,
against the watchlist's store in a server started for the purpose. Today marks the jobs it lists as seen, so add
`--copy` when timing a real store: it works on a copy made in a temporary folder and leaves yours alone (`--tab Queue`,
`-n 5` and `--json` narrow or reshape it). Under the calls it says what each tab waits on before its first data (the
tab's heading and placeholders are on screen at 0 ms; see below), `--combined` adds the one-call forms Today and the
Queue had before they were split, `--profile /api/queue` lists the functions one call spends its time in, and
`--cold --copy` times a page opening on a freshly started server (page, API, Today's first data) and what building the
store's indexes saves.

Loading is progressive (see [the page](the-page.md#in-your-browser)): a tab draws its shell and fills each part as
its call lands. Today and the Queue ask for `?part=list` (the jobs, quick) and `?part=extra` (pay, advice, worth it,
why a job has no score, what it waits on: seconds, by job key) together, and the page merges the second into the cards;
the call with no `part` is both, as before. A renderer in `static/index.html` takes a `loadCtx()`: `ctx.get` is cancelled
when the user leaves the tab (a late answer draws nothing), `ctx.shell` draws the placeholders, and `ctx.swr` draws the
last answer from memory at once, then the fresh one if it differs (a POST clears that memory). The page is served the
moment the server listens; the work nobody waits for (the store's indexes, scoring, the first board check) starts after
the first tab has been answered (`STARTUP_WAIT` in `web.py`).
`scripts/demo/make-video` rebuilds the demo video from made-up data: see
`scripts/demo/README.md`.

Releases publish to PyPI through Trusted Publishing when a `v*` tag is pushed, and then to the MCP Registry
from `server.json` (keep its two versions in step with the package; a test checks).
`scripts/release.py 0.2.3 -m "what's in it"` does the whole release: it bumps all three versions, runs
`scripts/check`, commits, tags, pushes, and waits until PyPI and the registry show the new version
(`--dry-run` shows the bump first).

MIT licensed.
