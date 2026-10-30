#!/usr/bin/env python3
"""Cut a release: bump the version everywhere, run the checks, commit, tag, push, and wait for it to land.

    scripts/release.py 0.2.3 -m "what's in it"      # commits "<name> 0.2.3 — what's in it", tags v0.2.3
    scripts/release.py 0.2.3 --dry-run              # shows the bump and stops
    scripts/release.py 1.4.0 --root ../other-pkg    # releases another project with this copy

The tag triggers the Release workflow (PyPI). The version is bumped in pyproject.toml, the package's
``__version__`` and, when there is one, server.json (the MCP Registry entry), whose own workflow runs after
the release, and the Claude plugin and desktop extension (plugin/, desktop/) with their pins on the package.
After pushing, it polls PyPI (and the registry) until the new version shows up.

A first release can give the version the files already declare: when its tag doesn't exist yet, it goes out as
it is, tagged without a bump commit.

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


LITERAL = re.compile(r'^__version__ = "([^"]+)"', re.M)  # a version written out, not read from metadata


def static_version(root: Path) -> str | None:
    m = re.search(r'^version = "([^"]+)"', (root / "pyproject.toml").read_text(), re.M)
    return m.group(1) if m else None


def hatch_version_file(root: Path) -> Path | None:
    """The file a Hatch project reads its version from (`[tool.hatch.version] path = ...`), if it does."""
    m = re.search(r'^\[tool\.hatch\.version\]\s*\npath = "([^"]+)"', (root / "pyproject.toml").read_text(), re.M)
    return root / m.group(1) if m else None


def current_version(root: Path) -> str:
    """pyproject.toml's version, or, when it's dynamic, the one in the file Hatch reads it from."""
    if v := static_version(root):
        return v
    path = hatch_version_file(root)
    m = LITERAL.search(path.read_text()) if path and path.exists() else None
    if not m:
        raise SystemExit("release: no version in pyproject.toml, nor a [tool.hatch.version] file declaring one")
    return m.group(1)


def version_files(root: Path, name: str) -> list[Path]:
    """Every file that writes the version out: pyproject.toml (unless it's dynamic), the file Hatch reads it
    from, the package's __init__.py (flat or src layout), and server.json if there is one. An __init__.py that
    reads its version from the installed metadata has nothing to bump and is left alone."""
    files = [root / "pyproject.toml"] if static_version(root) else []
    package = name.replace("-", "_")
    for init in (hatch_version_file(root), root / package / "__init__.py", root / "src" / package / "__init__.py"):
        if init and init.exists() and init not in files and LITERAL.search(init.read_text()):
            files.append(init)
    if (root / "server.json").exists():
        files.append(root / "server.json")
    files += [p for p in (root / f for f in CLAUDE_FILES) if p.exists()]
    return files


# The Claude plugin (its manifest, the server it runs pinned to the release, and the environment its lock comes
# from) and the Claude Desktop extension (its manifest, and the environment that pins the release), when the
# package ships them.
CLAUDE_FILES = ("plugin/.claude-plugin/plugin.json", "plugin/.mcp.json", "plugin/pyproject.toml",
                "desktop/manifest.json", "desktop/pyproject.toml")


def bump(text: str, path: Path, old: str, new: str, name: str = "") -> str:
    """Replace ``old`` with ``new`` where the file declares its version; fail if nothing changed. An
    ``__version__`` that had drifted from the release version is set to the new one too (see `drift`).
    A pin on the package itself (``jobwatch[mcp]==0.6.0``, in the plugin's server command or the desktop
    extension's dependencies) moves with it."""
    if path.name == "pyproject.toml":
        pattern, repl = rf'^version = "{re.escape(old)}"', f'version = "{new}"'
    elif path.suffix == ".json":
        pattern, repl = rf'"version": "{re.escape(old)}"', f'"version": "{new}"'
    else:
        pattern, repl = LITERAL.pattern, f'__version__ = "{new}"'
    out, n = re.subn(pattern, repl, text, flags=re.M)
    pins = 0
    if name:
        out, pins = re.subn(rf'(\b{re.escape(name)}(?:\[[\w,-]+\])?)=={re.escape(old)}\b', rf"\g<1>=={new}", out)
    if not (n or pins):
        raise SystemExit(f"release: {path.name} doesn't declare version {old}")
    return out


def drift(files: list[Path], old: str) -> list[str]:
    """Files whose ``__version__`` says something other than the current release, which this release fixes."""
    out = []
    for f in files:
        m = LITERAL.search(f.read_text()) if f.suffix == ".py" else None
        if m and m.group(1) != old:
            out.append(f"{f.name} said {m.group(1)}, not {old}")
    return out


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def tagged(root: Path, tag: str) -> bool:
    """Whether ``tag`` exists; outside a git repository nothing can be released, so it counts as taken."""
    try:
        return bool(git(root, "tag", "--list", tag))
    except (subprocess.CalledProcessError, FileNotFoundError):
        return True


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
    """The project's scripts/check, or else its tests with its own virtualenv's Python (another project's
    dependencies aren't installed in the Python running this script)."""
    check, venv = root / "scripts" / "check", root / ".venv" / "bin" / "python"
    python = str(venv) if venv.exists() else sys.executable
    cmd = [str(check)] if check.exists() else [python, "-m", "pytest", "-q"]
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
    ap.add_argument("--root", type=Path, default=None,
                    help="the project to release (default: the one this script is in)")
    args = ap.parse_args(argv)
    root = (args.root or ROOT).expanduser().resolve()

    if not VERSION.match(args.version):
        raise SystemExit("release: give a version like 1.2.3")
    name, old, tag = project_name(root), current_version(root), f"v{args.version}"
    # The version the files already declare goes out as it is when it was never tagged: a first release.
    as_is = args.version == old and not tagged(root, tag)
    if not as_is and tuple(map(int, args.version.split("."))) <= tuple(map(int, old.split("."))):
        raise SystemExit(f"release: {args.version} isn't newer than {old}")
    files = version_files(root, name)
    bumped = {} if as_is else {f: bump(f.read_text(), f, old, args.version, name) for f in files}
    for line in drift(files, old):
        print(f"note: {line}; this release sets it to {args.version}")
    if as_is:
        print(f"{name} {old}: not tagged yet, released as the files declare it (no bump)")
    else:
        print(f"{name} {old} -> {args.version}: " + ", ".join(str(f.relative_to(root)) for f in files))
    if args.dry_run:
        return 0

    preflight(root, tag)
    before = {f: f.read_text() for f in bumped}
    for f, text in bumped.items():
        f.write_text(text)
    try:
        run_checks(root)
    except subprocess.CalledProcessError:
        for f, text in before.items():  # leave the tree as it was, so a fix-and-retry starts clean
            f.write_text(text)
        raise SystemExit("release: the checks failed; the version bump was undone") from None
    title = f"{name} {args.version}" + (f" — {args.summary}" if args.summary else "")
    message = title + (f"\n\n{args.body}" if args.body else "")
    if bumped:
        git(root, "commit", "--quiet", "-am", message)
    git(root, "tag", "-a", tag, "-m", f"{name} {args.version}")
    subprocess.run(["git", "push", "--quiet", "origin", "main", tag], cwd=root, check=True)
    print(f"Pushed {tag}.")
    if args.no_wait:
        return 0

    registry_name = None
    if (root / "server.json").exists():
        registry_name = json.loads((root / "server.json").read_text())["name"]
    print("== waiting for it to publish")
    if wait_for(name, args.version, registry_name):
        print(f"{name} {args.version} is out.")
        return 0
    print("Not published yet; check the Actions tab.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
