"""Setting up scoring.providers (OpenAI-compatible cloud APIs) from Settings: the presets that fill in a base url,
the settings an added or removed provider writes, the provider's model list and a one-call check of its key.

The key is read only to be sent to the provider as a Bearer token. It is never returned, logged or put in an
error: whatever the provider or the network says is scrubbed of it first."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

from .config import _PROVIDER_NAME, BACKENDS
from .score import Provider

# A key's characters, for ai.save_key: every provider's key is a plain token.
KEY = re.compile(r"[A-Za-z0-9._~+/=:-]{8,512}")
TIMEOUT = 30  # seconds for one call

# Where the page's picker starts: the base url each hosted API documents. "name" is the suggested provider name.
PRESETS = (
    {"id": "openrouter", "label": "OpenRouter", "name": "openrouter", "url": "https://openrouter.ai/api/v1",
     "links": [{"label": "Keys", "url": "https://openrouter.ai/settings/keys"},
               {"label": "Credits & usage", "url": "https://openrouter.ai/settings/credits"}]},
    {"id": "groq", "label": "Groq", "name": "groq", "url": "https://api.groq.com/openai/v1",
     "links": [{"label": "Keys", "url": "https://console.groq.com/keys"},
               {"label": "Usage", "url": "https://console.groq.com/settings/usage"}]},
    {"id": "google", "label": "Google AI Studio (OpenAI-compatible)", "name": "google",
     "url": "https://generativelanguage.googleapis.com/v1beta/openai",
     "links": [{"label": "Keys", "url": "https://aistudio.google.com/apikey"},
               {"label": "Usage", "url": "https://aistudio.google.com/usage"}]},
    {"id": "custom", "label": "Custom (any OpenAI-compatible API)", "name": "", "url": "", "links": []},
)


def links(p: Provider) -> list[dict]:
    """The account pages to link from a provider's card: its preset's when its base url matches one, plus an
    "Account" link when the provider sets account_url."""
    url = p.url.rstrip("/")
    out = [dict(link) for preset in PRESETS if preset["url"] and preset["url"] == url for link in preset["links"]]
    if p.account_url:
        out.append({"label": "Account", "url": p.account_url})
    return out


class ProviderError(Exception):
    """Why a call to a provider didn't work. kind: "auth" (key refused), "rate" (rate limited or out of quota),
    "unreachable" or "error"."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def _call(url: str, key: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json", "User-Agent": "jobwatch",
                 **({"Content-Type": "application/json"} if body is not None else {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        code = e.code
        if code in (401, 403):
            raise ProviderError("auth", f"the key was refused (HTTP {code})") from None
        if code == 429:
            raise ProviderError("rate", "rate limited or out of quota (HTTP 429)") from None
        raise ProviderError("error", f"the API answered HTTP {code}") from None
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise ProviderError("unreachable", f"couldn't reach the API ({type(e).__name__})") from None
    except ValueError:
        raise ProviderError("error", "the API's answer wasn't JSON") from None


def models(p: Provider, key: str) -> list[dict]:
    """The models the provider lists at {url}/models, sorted by id, as {"id", "context", "free"} ("models/" prefixes
    dropped: Google's list has them and its chat endpoint doesn't take them). context is the window in tokens (0 when
    not stated); free is True for a ":free" id or a listed price of zero (OpenRouter's pricing)."""
    data = _call(f"{p.url}/models", key)
    rows = data.get("data") if isinstance(data, dict) else None
    found: dict[str, dict] = {}
    for m in rows or []:
        if isinstance(m, dict) and m.get("id"):
            mid = str(m["id"]).removeprefix("models/")
            found[mid] = {"id": mid, "context": _tokens(m.get("context_length")),
                          "free": _is_free(mid, m.get("pricing"))}
    if not found:
        raise ProviderError("error", "the API listed no models: type the model's id instead")
    return [found[i] for i in sorted(found)]


# -- sorting the list into what is worth trying for fit scoring (a judgment over a long posting and a resume, as JSON)

LARGE_B = 100  # billions of parameters (total, for a mixture of experts): most accurate
MEDIUM_B = 30  # from here up to LARGE_B: balanced; under it: small
# Names that mark a model that can't do the job: embedders, rerankers, safety and guard models, reward models,
# vision, video, speech and image models, and code models.
_NOT_FOR_SCORING = re.compile(
    r"embed|retriever|rerank|guard|safety|topic-control|reward|detector|vision|video|cosmos|diffusion|whisper"
    r"|speech|(?<!de)code|starcoder|(?<![a-z0-9])(?:vlm|vl|asr|tts|ocr)(?![a-z0-9])")
_PREFERRED = re.compile(r"instruct|chat|reason|think|(?<![a-z0-9])(?:it|r1)(?![a-z0-9])")
# 70b, 1.5b, 1t; 8x22b (experts x size); 30b-a3b and 550b-a55b (total, active); a12b alone (active only)
_SIZE = re.compile(r"(?<![a-z0-9.])(?:(\d+)x)?(\d+(?:\.\d+)?)([bt])(?![a-z0-9])")
_ACTIVE = re.compile(r"(?<![a-z0-9])a(\d+(?:\.\d+)?)b(?![a-z0-9])")
GROUPS = (
    ("large", f"Large: most accurate ({LARGE_B}B+ or big MoE)"),
    ("medium", f"Medium: balanced ({MEDIUM_B}–{LARGE_B}B)"),
    ("small", f"Small: fast, likely no better than a local model (under {MEDIUM_B}B)"),
    ("unknown", "Size not stated"),
    ("skip", "Not for fit scoring"),
)


def _tokens(value) -> int:
    try:
        return max(int(float(value)), 0)
    except (TypeError, ValueError):
        return 0


def _is_free(mid: str, pricing) -> bool:
    if mid.endswith(":free"):
        return True
    if isinstance(pricing, dict) and pricing.get("prompt") is not None and pricing.get("completion") is not None:
        try:
            return float(pricing["prompt"]) == 0 and float(pricing["completion"]) == 0
        except (TypeError, ValueError):
            return False
    return False


def not_for_scoring(model_id: str) -> bool:
    """True for an id that names an embedder, a guard/safety/reward model, vision/video/speech or a code model."""
    return bool(_NOT_FOR_SCORING.search(model_id.lower().rpartition("/")[2]))


def size_billions(model_id: str) -> float | None:
    """Parameters in billions parsed from the id: the total for a mixture of experts (8x22b is 176, 30b-a3b is 30),
    the active count when only that is stated (a12b), None when the id says nothing."""
    name = model_id.lower().removesuffix(":free").rpartition("/")[2]
    for count, size, unit in _SIZE.findall(name):
        b = float(size) * (1000 if unit == "t" else 1) * (int(count) if count else 1)
        return b
    active = _ACTIVE.search(name)
    return float(active.group(1)) if active else None


def _group_of(model_id: str) -> str:
    if not_for_scoring(model_id):
        return "skip"
    b = size_billions(model_id)
    return "unknown" if b is None else "large" if b >= LARGE_B else "medium" if b >= MEDIUM_B else "small"


def _detail(m: dict) -> str:
    ctx = m.get("context") or 0
    parts = (["free"] if m.get("free") else []) + (
        [f"{ctx / 1_000_000:.3g}M ctx" if ctx >= 1_000_000 else f"{round(ctx / 1000)}K ctx"] if ctx else [])
    return " · ".join(parts)


def group_models(entries: list[dict], free_only: bool = False) -> dict:
    """The models as the picker's groups, in GROUPS order, empty ones left out: {"groups": [{"id", "label", "models":
    [{"id", "detail", "free"}]}], "count", "free" (how many are free, so the page can offer the filter)}. Inside a
    group instruct/reasoning models come first, then larger before smaller. free_only keeps only the free ones."""
    free = sum(1 for m in entries if m.get("free"))
    kept = [m for m in entries if m.get("free") or not free_only]
    buckets: dict[str, list[tuple]] = {gid: [] for gid, _ in GROUPS}
    for m in kept:
        mid = m["id"]
        b = size_billions(mid)
        row = {"id": mid, "detail": _detail(m), "free": bool(m.get("free"))}
        buckets[_group_of(mid)].append(((not _PREFERRED.search(mid.lower()), -(b or 0), mid), row))
    groups = [{"id": gid, "label": label, "models": [row for _, row in sorted(buckets[gid], key=lambda t: t[0])]}
              for gid, label in GROUPS if buckets[gid]]
    return {"groups": groups, "count": len(kept), "free": free}


def check(p: Provider, key: str, model: str) -> dict:
    """One tiny chat call with `model`: {"status": "ok" | "auth" | "rate" | "unreachable" | "error", "message", and
    "seconds" when it answered}. Never raises, never contains the key."""
    start = time.monotonic()
    try:
        _call(f"{p.url}/chat/completions", key, {"model": model, "max_tokens": 8, "temperature": 0,
                                                 "messages": [{"role": "user", "content": "Reply with: ok"}]})
    except ProviderError as e:
        return {"status": e.kind, "message": str(e).replace(key, "…")}
    return {"status": "ok", "message": "answered", "seconds": round(time.monotonic() - start, 1)}


def add(scoring: dict, name: str, url: str) -> dict:
    """The scoring section with provider `name` at `url` added. ValueError says what's wrong with either. The
    keychain item is left to default (jobwatch-<name>); config.save checks the result in full."""
    name, url = (name or "").strip(), (url or "").strip().rstrip("/")
    if not _PROVIDER_NAME.fullmatch(name) or name in BACKENDS:
        raise ValueError(f"a provider's name is lowercase letters, digits, dashes and underscores (not "
                         f"{', '.join(BACKENDS)}), got {name!r}")
    if not re.fullmatch(r"https?://[^\s/]+[^\s]*", url):
        raise ValueError("the base URL is an http(s) address, like https://api.example.com/v1")
    have = dict(scoring.get("providers") or {})
    if name in have:
        raise ValueError(f"there is a provider named {name} already")
    return {**scoring, "providers": {**have, name: {"url": url}}}


def remove(scoring: dict, name: str) -> dict:
    """The scoring section without provider `name`, and without its steps in the fallback chain and same_as. The
    keychain item stays. ValueError when it is the main backend: another has to score first."""
    have = dict(scoring.get("providers") or {})
    if name not in have:
        raise ValueError(f"there is no provider named {name}")
    if scoring.get("backend") == name:
        raise ValueError(f"{name} scores first: put another step first in the chain, save, then remove it")
    out = {k: v for k, v in scoring.items() if k not in ("providers", "fallback", "same_as")}
    for key in ("fallback", "same_as"):
        entries = [e for e in ([scoring[key]] if isinstance(scoring.get(key), str) else scoring.get(key) or [])
                   if str(e).partition(":")[0] != name]
        if entries:
            out[key] = entries
    left = {k: v for k, v in have.items() if k != name}
    if left:
        out["providers"] = left
    return out
