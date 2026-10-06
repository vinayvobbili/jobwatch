#!/usr/bin/env python3
"""Cut a release: bump the version everywhere, run the checks, commit, tag, push, and wait for it to land.

    scripts/release.py 0.2.3 -m "what's in it"      # commits "<name> 0.2.3 — what's in it", tags v0.2.3
    scripts/release.py 0.2.3 --dry-run              # shows the bump and stops

The tag triggers the Release workflow (PyPI). The version is bumped in pyproject.toml, the package's
``__version__`` and, when there is one, server.json (the MCP Registry entry), whose own workflow runs after
the release. After pushing, it polls PyPI (and the registry) until the new version shows up.

It refuses to run off main, with uncommitted changes, behind origin, or when the tag already exists.
Standard library only, so the same file works in any of these packages.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
PYPI = "https://pypi.org/pypi/{name}/json"
REGISTRY = "https://registry.modelcontextprotocol.io/v0.1/servers?search={name}"


def project_name(root: Path) -> str:
    m = re.search(r'^name = "([^"]+)"', (root / "pyproject.toml").read_text(), re.M)
    if not m:
        raise SystemExit("release: no name in pyproject.toml")
    return m.group(1)


def current_version(root: Path) -> str:
    m = re.search(r'^version = "([^"]+)"', (root / "pyproject.toml").read_text(), re.M)
    if not m:
        raise SystemExit("release: no version in pyproject.toml")
    return m.group(1)


def version_files(root: Path, name: str) -> list[Path]:
    """pyproject.toml, the package's __init__.py (flat or src layout), and server.json if there is one."""
    files = [root / "pyproject.toml"]
    package = name.replace("-", "_")
    for init in (root / package / "__init__.py", root / "src" / package / "__init__.py"):
        if init.exists():
            files.append(init)
            break
    if (root / "server.json").exists():
        files.append(root / "server.json")
    return files


def bump(text: str, path: Path, old: str, new: str) -> str:
    """Replace ``old`` with ``new`` where the file declares its version; fail if nothing changed."""
    if path.name == "pyproject.toml":
        pattern, repl = rf'^version = "{re.escape(old)}"', f'version = "{new}"'
    elif path.name == "server.json":
        pattern, repl = rf'"version": "{re.escape(old)}"', f'"version": "{new}"'
    else:
        pattern, repl = rf'^__version__ = "{re.escape(old)}"', f'__version__ = "{new}"'
    out, n = re.subn(pattern, repl, text, flags=re.M)
    if not n:
        raise SystemExit(f"release: {path.name} doesn't declare version {old}")
    return out


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def preflight(root: Path, tag: str) -> None:
    if git(root, "branch", "--show-current") != "main":
        raise SystemExit("release: switch to main first")
    if git(root, "status", "--porcelain"):
        raise SystemExit("release: commit or stash your changes first")
    git(root, "fetch", "--quiet", "origin", "main", "--tags")
    if git(root, "rev-list", "HEAD..origin/main"):
        raise SystemExit("release: main is behind origin; pull first")
    if git(root, "tag", "--list", tag):
        raise SystemExit(f"release: {tag} already exists")


def run_checks(root: Path) -> None:
    check = root / "scripts" / "check"
    cmd = [str(check)] if check.exists() else [sys.executable, "-m", "pytest", "-q"]
    print("== checks:", " ".join(cmd))
    subprocess.run(cmd, cwd=root, check=True)


def fetch_json(url: str):
    """GET a JSON document. A Python without root certificates (python.org's macOS build until its "Install
    Certificates" step is run) can't verify any HTTPS site, so then it's fetched with curl, which uses the
    system's certificates."""
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.load(r)
    except urllib.error.URLError as e:
        if not isinstance(e.reason, ssl.SSLCertVerificationError) or not shutil.which("curl"):
            raise
    out = subprocess.run(["curl", "-fsSL", "--max-time", "20", url], capture_output=True, text=True, check=False)
    if out.returncode:
        raise OSError(f"curl {url}: {out.stderr.strip() or f'exit {out.returncode}'}")
    return json.loads(out.stdout)


def published(name: str, version: str, registry_name: str | None) -> dict[str, bool | str]:
    """Which of PyPI (and the MCP Registry) already show ``version``: True, False, or why it couldn't be
    checked. A network error isn't "not yet": saying so keeps a broken check from looking like a slow release."""
    seen: dict[str, bool | str] = {}
    try:
        seen["PyPI"] = version in fetch_json(PYPI.format(name=name))["releases"]
    except urllib.error.HTTPError as e:
        seen["PyPI"] = False if e.code == 404 else f"can't check: HTTP {e.code}"  # 404: the first release
    except OSError as e:
        seen["PyPI"] = f"can't check: {e}"
    if registry_name:
        try:
            # Search by the part after the slash: a search with the full name (io.github.x/y) hangs.
            servers = fetch_json(REGISTRY.format(name=registry_name.rsplit("/", 1)[-1]))["servers"]
            seen["MCP Registry"] = any(s["server"]["name"] == registry_name and s["server"]["version"] == version
                                       for s in servers)
        except OSError as e:
            seen["MCP Registry"] = f"can't check: {e}"
    return seen


def _shown(v: bool | str) -> str:
    return "yes" if v is True else "not yet" if v is False else v


def wait_for(name: str, version: str, registry_name: str | None, timeout: float = 900, every: float = 20) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        seen = published(name, version, registry_name)
        print("   " + ", ".join(f"{k}: {_shown(v)}" for k, v in seen.items()))
        if all(v is True for v in seen.values()):
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(every)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("version", help="the new version, e.g. 0.2.3")
    ap.add_argument("-m", "--summary", default="", help="what's in it, for the commit message")
    ap.add_argument("--body", default="", help="extra commit message paragraph(s), e.g. trailers")
    ap.add_argument("--dry-run", action="store_true", help="show the bump, change nothing")
    ap.add_argument("--no-wait", action="store_true", help="push and exit without polling PyPI")
    args = ap.parse_args(argv)

    if not VERSION.match(args.version):
        raise SystemExit("release: give a version like 1.2.3")
    name, old, tag = project_name(ROOT), current_version(ROOT), f"v{args.version}"
    if tuple(map(int, args.version.split("."))) <= tuple(map(int, old.split("."))):
        raise SystemExit(f"release: {args.version} isn't newer than {old}")
    files = version_files(ROOT, name)
    bumped = {f: bump(f.read_text(), f, old, args.version) for f in files}
    print(f"{name} {old} -> {args.version}: " + ", ".join(str(f.relative_to(ROOT)) for f in files))
    if args.dry_run:
        return 0

    preflight(ROOT, tag)
    for f, text in bumped.items():
        f.write_text(text)
    run_checks(ROOT)
    title = f"{name} {args.version}" + (f" — {args.summary}" if args.summary else "")
    message = title + (f"\n\n{args.body}" if args.body else "")
    git(ROOT, "commit", "--quiet", "-am", message)
    git(ROOT, "tag", "-a", tag, "-m", f"{name} {args.version}")
    subprocess.run(["git", "push", "--quiet", "origin", "main", tag], cwd=ROOT, check=True)
    print(f"Pushed {tag}.")
    if args.no_wait:
        return 0

    registry_name = None
    if (ROOT / "server.json").exists():
        registry_name = json.loads((ROOT / "server.json").read_text())["name"]
    print("== waiting for it to publish")
    if wait_for(name, args.version, registry_name):
        print(f"{name} {args.version} is out.")
        return 0
    print("Not published yet; check the Actions tab.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
