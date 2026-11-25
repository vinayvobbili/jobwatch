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
against the watchlist's store in a server started for the purpose. Today marks the jobs it lists as seen, so point
`-c` at a copy of the store when timing a real one (`--tab Queue`, `-n 5` and `--json` narrow or reshape it).
`scripts/demo/make-video` rebuilds the demo video from made-up data: see
`scripts/demo/README.md`.

Releases publish to PyPI through Trusted Publishing when a `v*` tag is pushed, and then to the MCP Registry
from `server.json` (keep its two versions in step with the package; a test checks).
`scripts/release.py 0.2.3 -m "what's in it"` does the whole release: it bumps all three versions, runs
`scripts/check`, commits, tags, pushes, and waits until PyPI and the registry show the new version
(`--dry-run` shows the bump first).

MIT licensed.
