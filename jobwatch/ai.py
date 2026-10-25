"""Where jobwatch's AI runs (fit scores, title suggestions and the chat), and whether each choice is ready here.

- claude: Anthropic's API, billed per use. Needs jobwatch[score] and an API key: ANTHROPIC_API_KEY, or a macOS
  keychain item named by scoring.keychain (save_key puts one there), or the output of scoring.key_command.
- agy: Google's Antigravity CLI, on its subscription's quota. Fit scores only. Needs jobwatch[score] and agy.
- local: the on-device MLX model (Apple Silicon). Needs jobwatch[local]. Nothing leaves the computer.

status() only looks: no model is called and no key is read. test() makes one small call to the model.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

BACKENDS = ("claude", "agy", "local")  # the order the page lists them: biggest model first
KEYCHAIN = "jobwatch-anthropic"  # the keychain item save_key uses when scoring.keychain names none
# Where agy's installer and Homebrew put it: a launchd service's PATH (jobwatch ui as a service) has neither.
AGY_PLACES = ("~/.local/bin/agy", "/opt/homebrew/bin/agy", "/usr/local/bin/agy")
_KEY = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")
_ITEM = re.compile(r"[A-Za-z0-9._-]{1,64}")

INSTALL_SCORE = "pip install 'jobwatch[score]'"
INSTALL_LOCAL = "pip install 'jobwatch[local]'"
AGY_DOCS = "https://antigravity.google/docs/cli"
KEYS_PAGE = "https://console.anthropic.com/settings/keys"


def find_agy() -> str | None:
    """agy's path: on PATH, or where it's usually installed."""
    if found := shutil.which("agy"):
        return found
    for place in AGY_PLACES:
        p = Path(place).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


def apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _agy_supported() -> bool:
    """Whether the installed shortlist-ai can score with agy (0.2.0 and later)."""
    try:
        from shortlist_ai import backends
    except ImportError:
        return False
    return hasattr(backends, "AgyBackend")


def key_source(keychain: str, key_command: str = "") -> str:
    """Where Claude's API key would come from: "environment", "command", "keychain", or "" (none). The key isn't
    read, and the command isn't run: it may ask the person to approve."""
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "environment"
    if key_command:
        return "command"
    if keychain and sys.platform == "darwin":
        try:
            found = subprocess.run(["security", "find-generic-password", "-s", keychain],
                                   capture_output=True, timeout=30).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            found = False
        if found:
            return "keychain"
    return ""


def _step(text: str, command: str = "", link: str = "") -> dict:
    return {"text": text, **({"command": command} if command else {}), **({"link": link} if link else {})}


def status(keychain: str = "", key_command: str = "") -> dict:
    """Each choice: ready or not, what's still needed (steps, with a command to run or a page to open), and what
    it means for the user's data and bill. keychain: scoring.keychain; key_command: scoring.key_command."""
    scoring = _installed("shortlist_ai")
    claude_steps, agy_steps, local_steps = [], [], []
    if not scoring:
        claude_steps.append(_step("Install the scoring add-on", INSTALL_SCORE))
        agy_steps.append(_step("Install the scoring add-on", INSTALL_SCORE))
    key = key_source(keychain, key_command)
    if not key:
        claude_steps.append(_step("Create an API key on Anthropic's console, then paste it below: jobwatch keeps it "
                                  "in your macOS keychain, never in the settings file", link=KEYS_PAGE)
                            if sys.platform == "darwin" else
                            _step("Create an API key on Anthropic's console and set ANTHROPIC_API_KEY before "
                                  "starting jobwatch", link=KEYS_PAGE))
    if scoring and not _agy_supported():
        agy_steps.append(_step("Update the scoring add-on (agy needs shortlist-ai 0.2.0 or later)",
                               "pip install -U shortlist-ai"))
    agy = find_agy()
    if not agy:
        agy_steps.append(_step("Install the Antigravity CLI and sign in once with `agy`", link=AGY_DOCS))
    silicon = apple_silicon()
    if not silicon:
        local_steps.append(_step("Needs a Mac with Apple Silicon (M1 or later)"))
    elif not _installed("mlx_lm"):
        local_steps.append(_step("Install the on-device add-on (downloads a ~6 GB model on first use)",
                                 INSTALL_LOCAL))
    return {
        "claude": {"label": "Claude API", "ready": not claude_steps, "steps": claude_steps,
                   "key": key, "keychain": keychain or KEYCHAIN,
                   "can_save_key": sys.platform == "darwin" and not key_command,  # the command's key isn't ours
                   "about": "The strongest scores. Postings and your resume go to Anthropic; billed per job "
                            "scored (a few cents each)."},
        "agy": {"label": "Antigravity (agy)", "ready": not agy_steps, "steps": agy_steps, "path": agy or "",
                "about": "Claude and Gemini models on your Google AI subscription's quota, no per-use bill. "
                         "Postings and your resume go to Google. Fit scores only, about 35 seconds a job."},
        "local": {"label": "On this Mac", "ready": not local_steps, "steps": local_steps,
                  "possible": silicon,
                  "about": "Free and private: nothing leaves this computer. Smaller model, slower, and the "
                           "Mac is busy while it scores."},
    }


def test(backend: str, model: str = "", keychain: str = "", key_command: str = "") -> dict:
    """One small call to the model: {"ok": True, "seconds": ..., "model": ...} or {"ok": False, "error": ...}.
    The local model loads first (a minute or more the first time)."""
    from .score import load_api_key, turn

    if backend not in BACKENDS:
        return {"ok": False, "error": f"unknown backend {backend!r}"}
    try:
        from pydantic import BaseModel
        from shortlist_ai.backends import get_backend
    except ImportError:
        return {"ok": False, "error": f"needs the scoring add-on: {INSTALL_SCORE}"}

    class Ping(BaseModel):
        ok: bool

    if backend == "claude" and (problem := load_api_key(keychain, key_command)):
        return {"ok": False, "error": problem}
    start = time.monotonic()
    try:
        engine = get_backend(backend, model or None)
        if backend == "agy":
            engine.executable = find_agy() or "agy"
        with turn(backend):
            reply = engine.structured("Answer with ok set to true.", [{"type": "text", "text": "Ping."}], Ping)
    except Exception as e:  # what the model or its client raised, for the page to show
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:400]}
    return {"ok": bool(reply.ok), "seconds": round(time.monotonic() - start, 1),
            "model": getattr(engine, "model", model)}


def save_key(key: str, keychain: str = "") -> str:
    """Put an Anthropic API key in the macOS keychain item `keychain` (KEYCHAIN when unset), replacing one there,
    and use it from now on in this process. Returns the item's name. The key goes to `security` on its input, not
    its command line, so other processes can't see it; it is never written to the settings file or logged."""
    key, keychain = key.strip(), (keychain or KEYCHAIN).strip()
    if sys.platform != "darwin":
        raise ValueError("the keychain is macOS only: set ANTHROPIC_API_KEY before starting jobwatch instead")
    if not _KEY.fullmatch(key):
        raise ValueError("that doesn't look like an Anthropic API key (they start with sk-ant-)")
    if not _ITEM.fullmatch(keychain):
        raise ValueError("a keychain item name is letters, digits, dots, dashes and underscores")
    account = os.environ.get("USER") or "jobwatch"
    if not _ITEM.fullmatch(account):
        account = "jobwatch"
    line = f"add-generic-password -U -s {keychain} -a {account} -w {key}\n"
    try:
        done = subprocess.run(["security", "-i"], input=line, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ValueError(f"couldn't reach the keychain: {type(e).__name__}") from None
    if done.returncode or "error" in (done.stderr or "").lower():
        raise ValueError("the keychain didn't take the key: " + (done.stderr or "").replace(key, "…").strip()[:200])
    os.environ["ANTHROPIC_API_KEY"] = key
    return keychain
