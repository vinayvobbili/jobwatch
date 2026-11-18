"""Which local model to run on this computer, by its memory (Settings and onboarding, "On this Mac").

The table is the same one the home page and docs/guide/fit-scores.md show (a test keeps them in step). Only the 16 GB
row was tested (shortlist-ai's `shortlist eval` on a 16 GB Apple Silicon Mac); the others are sized by memory.
Apple Silicon gets mlx-community repos, served with vllm-mlx; Windows, Linux and Intel Macs get Ollama tags.
"""

from __future__ import annotations

import ctypes
import http.client
import json
import platform
import re
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

HF = "https://huggingface.co/mlx-community/"
OLLAMA = "https://ollama.com/library/"
SERVE_PORT = 8010  # where the local model server is looked for (chat.LOCAL_URL)
OLLAMA_URL = "http://127.0.0.1:11434/v1"


@dataclass(frozen=True)
class Alt:
    """The "also good" Gemma 4 model beside a row's Qwen suggestion."""
    name: str       # the model, as a person reads it
    mlx: str        # its mlx-community repo
    tag: str        # its Ollama tag
    note: str = ""  # what was measured, only where something was


@dataclass(frozen=True)
class Tier:
    ram: str        # the row's label
    min_gb: int     # the least memory (nominal GB) it is suggested for
    name: str       # the model, as a person reads it
    mlx: str        # its mlx-community repo (Apple Silicon)
    tag: str        # its Ollama tag (everything else)
    alt: Alt | None = None  # the Gemma 4 beside it
    tested: bool = False


# Gemma 4 loads through mlx-vlm (mlx_lm has no class for it); vllm-mlx installs that and loads any gemma-4 repo by
# its name, so the serve command is the same as for a Qwen. The 8 GB row gets E2B: E4B's 5.2 GB of weights would
# leave an 8 GB computer too little (Qwen3.5-4B is 3.1 GB, E2B 3.6 GB).
GEMMA_E2B = Alt("Gemma 4 E2B, 4-bit", "gemma-4-e2b-it-4bit", "gemma4:e2b-it-q4_K_M")
GEMMA_12B = Alt("Gemma 4 12B, 4-bit", "gemma-4-12B-it-4bit", "gemma4:12b-it-q4_K_M",
                "tested: most accurate (29/29 vs 28/29), about 50% slower, +1.7 GB")
GEMMA_26B = Alt("Gemma 4 26B-A4B, 4-bit", "gemma-4-26b-a4b-it-4bit", "gemma4:26b-a4b-it-q4_K_M")
GEMMA_31B = Alt("Gemma 4 31B, 4-bit", "gemma-4-31b-it-4bit", "gemma4:31b-it-q4_K_M")

TIERS = (
    Tier("8 GB", 0, "Qwen3.5-4B, 4-bit", "Qwen3.5-4B-MLX-4bit", "qwen3.5:4b-q4_K_M", GEMMA_E2B),
    Tier("16 GB", 16, "Qwen3.5-9B, 4-bit", "Qwen3.5-9B-MLX-4bit", "qwen3.5:9b-q4_K_M", GEMMA_12B, tested=True),
    Tier("24-32 GB", 24, "Qwen3.8-27B, 4-bit", "Qwen3.8-27B-4bit", "qwen3.8:27b-q4_K_M", GEMMA_26B),
    Tier("48 GB and up", 48, "Qwen3.6-35B-A3B, 4-bit", "Qwen3.6-35B-A3B-4bit", "qwen3.6:35b-a3b-q4_K_M", GEMMA_31B),
)
# with this much memory or more the biggest row's 8-bit build fits
EIGHT_BIT_GB = 64
EIGHT_BIT = Tier("64 GB and up", EIGHT_BIT_GB, "Qwen3.6-35B-A3B, 8-bit", "Qwen3.6-35B-A3B-8bit", "qwen3.6:35b-a3b-q8_0",
                 GEMMA_31B)
SIZES = (4, 6, 8, 12, 16, 18, 24, 32, 36, 48, 64, 96, 128, 192, 256, 384, 512)  # memory sizes computers ship with
SLACK = 0.93  # an OS reports a little under what is installed (Linux and Windows hold some back)


def ram_bytes() -> int | None:
    """Installed memory in bytes, or None when this system won't say."""
    try:
        if sys.platform == "darwin":
            return int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True,
                                      timeout=5).stdout.strip())
        if sys.platform.startswith("linux"):
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
        if sys.platform == "win32":
            class Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong), ("pt", ctypes.c_ulonglong), ("pa", ctypes.c_ulonglong),
                            ("vt", ctypes.c_ulonglong), ("va", ctypes.c_ulonglong), ("ve", ctypes.c_ulonglong)]
            s = Status()
            s.length = ctypes.sizeof(s)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
            return int(s.total) or None
    except (OSError, ValueError, subprocess.SubprocessError, AttributeError):
        pass
    return None


def is_apple_silicon() -> bool:
    """A Mac with an M-series chip, even when Python itself runs under Rosetta."""
    if sys.platform != "darwin":
        return False
    if platform.machine() == "arm64":
        return True
    try:
        return subprocess.run(["sysctl", "-n", "hw.optional.arm64"], capture_output=True, text=True,
                              timeout=5).stdout.strip() == "1"
    except (OSError, subprocess.SubprocessError):
        return False


def system_name(apple: bool) -> str:
    return ("Apple Silicon" if apple else "Intel Mac" if sys.platform == "darwin"
            else "Windows" if sys.platform == "win32" else "Linux")


def nominal_gb(total: int) -> int:
    """The memory size installed, from what the system reports (15.2 GB reported is a 16 GB computer)."""
    gb = total / 2**30
    return max([s for s in SIZES if s * SLACK <= gb] or [SIZES[0]])


def tier_for(gb: int) -> Tier:
    return [t for t in TIERS if gb >= t.min_gb][-1]


def pick(gb: int) -> Tier:
    """The model suggested for this much memory: the biggest row that fits, its 8-bit build from 64 GB."""
    t = tier_for(gb)
    return EIGHT_BIT if t is TIERS[-1] and gb >= EIGHT_BIT_GB else t


def serve_command(t: Tier | Alt, apple: bool) -> str:
    return f"vllm-mlx serve mlx-community/{t.mlx} --port {SERVE_PORT}" if apple else f"ollama pull {t.tag}"


def model_id(t: Tier | Alt, apple: bool) -> str:
    return f"mlx-community/{t.mlx}" if apple else t.tag


def billions(model: str) -> float:
    """A model's size in billions of parameters from its id (the biggest number before a B: 35 in Qwen3.6-35B-A3B,
    not the 3 of its active experts); 0 when the id doesn't say."""
    found = re.findall(r"(?<![A-Za-z0-9.])(\d+(?:\.\d+)?)[Bb](?![A-Za-z])", model)
    return max(map(float, found), default=0.0)


def configured_model(scoring: dict, default: str = "") -> str:
    """The local model scoring.* sets: scoring.model when local scores first, else a `local:model` step in
    scoring.fallback; a local step with no model (or local scoring first with none set) is the scorer's `default`.
    "" when local isn't in the chain."""
    if scoring.get("backend") == "local":
        return str(scoring.get("model") or "").strip() or default
    for entry in scoring.get("fallback") or []:
        backend, _, model = str(entry).partition(":")
        if backend == "local":
            return model.strip() or default
    return ""


def running_model(url: str, timeout: float = 1.5) -> str | None:
    """The model id the local server at `url` (its /v1 base) reports from GET /models, or None when it isn't
    reachable or lists none. Only asks: it never loads a model."""
    parts = urllib.parse.urlsplit(url.rstrip("/") + "/models")
    cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    try:
        conn = cls(parts.hostname, parts.port, timeout=timeout)
        try:
            conn.request("GET", parts.path)
            resp = conn.getresponse()
            data = json.loads(resp.read()) if resp.status == 200 else {}
        finally:
            conn.close()
        return str(data["data"][0]["id"]) or None
    except (OSError, ValueError, KeyError, IndexError, TypeError, http.client.HTTPException):
        return None


def recommend(configured: str = "", total: int | None = None, apple: bool | None = None) -> dict:
    """What the page shows: the suggestion for this computer, the whole table, and what is set already.

    configured: the local model in use (scoring.model, or the scorer's default), "" when none. total: bytes of
    memory (None: ask the system). apple: whether this is Apple Silicon (None: ask the system). Unknown memory
    gives no suggestion (the table still shows)."""
    apple = is_apple_silicon() if apple is None else apple
    total = ram_bytes() if total is None else total
    gb = nominal_gb(total) if total else None

    def flavor(t: Tier) -> dict:
        a = t.alt
        return {"ram": t.ram, "model": t.name, "id": model_id(t, apple), "tested": t.tested,
                "link": (HF + t.mlx) if apple else (OLLAMA + t.tag.split(":")[0]),
                "command": serve_command(t, apple),
                "alt": a and {"model": a.name, "id": model_id(a, apple), "note": a.note,
                              "link": (HF + a.mlx) if apple else (OLLAMA + a.tag),
                              "command": serve_command(a, apple)}}

    rows = [flavor(t) for t in TIERS]
    rows[-1]["model"] += f" (8-bit with {EIGHT_BIT_GB} GB or more)"
    out = {"ram_gb": gb, "system": system_name(apple), "apple": apple, "rows": rows, "suggested": None,
           "configured": None, "note": "" if apple else f"Then start jobwatch with LOCAL_LLM_URL={OLLAMA_URL} and "
           "set scoring.model to the tag."}
    if gb is None:
        return out
    t = pick(gb)
    out["suggested"] = {**flavor(t), "gb": gb, "tested": t.tested}
    out["suggested"]["row"] = tier_for(gb).ram
    if configured:
        # larger than this computer's suggestion: it may swap, or crowd out the apps in use
        out["configured"] = {"model": configured, "larger": billions(configured) > billions(t.name)}
    return out
