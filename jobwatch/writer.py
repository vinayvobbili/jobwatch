"""One call to the model that writes a draft for the person to read: what `jobwatch followup` and `jobwatch cover`
share with the extension's Draft reply (reply.py).

It runs on the shared local model server (chat.py's `local` backend), so what the model reads (your tracker, your
resume, your stories) stays on this computer. `reply.backend: chat` in the watchlist is the opt-in to the chat's
backend and model instead, the same setting Draft reply has. Nothing here sends or saves anything.
"""

from __future__ import annotations

from . import chat
from .config import Config
from .reply import _THINK


def complete(cfg: Config, prompt: str, ask: str, max_tokens: int) -> tuple[str, dict]:
    """(the model's text with its reasoning taken out, where it ran: chat.where's dict). chat.ChatUnavailable when
    the backend can't run; any other error is the model's or its server's."""
    c = cfg.chat
    backend, model = (c.backend, c.model) if cfg.reply.backend == "chat" else ("local", "")
    where = chat.where(backend, model)
    if backend == "claude":
        chat.check(backend, c.keychain, c.key_command)
    else:
        chat.check(backend)
    # No system role for the local model: with the instructions there, Gemma writes empty thought blocks until it
    # runs out of tokens (see reply.draft). As one user message it writes the draft.
    system, user = ("", f"{prompt}\n\n{ask}") if backend == "local" else (prompt, ask)
    text = "".join(p for p in chat.reply(backend, system, [{"role": "user", "content": user}], model=model,
                                         max_tokens=max_tokens) if isinstance(p, str))
    return _THINK.sub("", text).strip(), where
