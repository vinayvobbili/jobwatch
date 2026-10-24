# Development

[← jobwatch guide](README.md)

```
python -m venv .venv && .venv/bin/pip install -e '.[dev,mcp]'
.venv/bin/ruff check . && .venv/bin/python -m pytest -q
```

CI tests on Python 3.10 and 3.13. `scripts/check` runs the same checks on both locally (it needs
[uv](https://docs.astral.sh/uv/), which fetches each Python). `git config core.hooksPath .githooks` runs it before
every push.

Tests use canned board responses and never touch the network, except the check that every curated course
link still resolves: `JOBWATCH_LINK_TESTS=1 pytest tests/test_learn.py`. To see how `jobwatch ui` looks after a change,
`scripts/screenshots.py` captures every tab in light and dark, at wide, desktop and phone widths, plus the
chat with a canned reply (it needs
`pip install playwright && python -m playwright install chromium`).
`scripts/demo/make-video` rebuilds the demo video from made-up data: see
`scripts/demo/README.md`.

Releases publish to PyPI through Trusted Publishing when a `v*` tag is pushed, and then to the MCP Registry
from `server.json` (keep its two versions in step with the package; a test checks).
`scripts/release.py 0.2.3 -m "what's in it"` does the whole release: it bumps all three versions, runs
`scripts/check`, commits, tags, pushes, and waits until PyPI and the registry show the new version
(`--dry-run` shows the bump first).

MIT licensed.
