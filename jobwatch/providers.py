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
    {"id": "openrouter", "label": "OpenRouter", "name": "openrouter", "url": "https://openrouter.ai/api/v1"},
    {"id": "groq", "label": "Groq", "name": "groq", "url": "https://api.groq.com/openai/v1"},
    {"id": "google", "label": "Google AI Studio (OpenAI-compatible)", "name": "google",
     "url": "https://generativelanguage.googleapis.com/v1beta/openai"},
    {"id": "custom", "label": "Custom (any OpenAI-compatible API)", "name": "", "url": ""},
)


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


def models(p: Provider, key: str) -> list[str]:
    """The model ids the provider lists at {url}/models, sorted ("models/" prefixes dropped: Google's list has them
    and its chat endpoint doesn't take them)."""
    data = _call(f"{p.url}/models", key)
    rows = data.get("data") if isinstance(data, dict) else None
    ids = {str(m["id"]).removeprefix("models/") for m in rows or [] if isinstance(m, dict) and m.get("id")}
    if not ids:
        raise ProviderError("error", "the API listed no models: type the model's id instead")
    return sorted(ids)


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
