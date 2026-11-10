"""Speech to text for the voice mock interview (mock.py) and the rehearsal page's mic (rehearse.py): the recording
the page made, sent to the shared local model server's OpenAI-style /audio/transcriptions, and the words that come
back. The watchlist's speech.url names another endpoint.

The server is the one chat and fit scores use (chat.local_url, LOCAL_LLM_URL), so nothing leaves this computer.
LOCAL_STT_URL names the endpoint itself when speech runs somewhere else. The audio is held in memory only while it
is forwarded: it is never written to disk. The browser's own SpeechRecognition is not used, because it sends the
audio to a cloud service.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import urllib.parse
import uuid

from . import chat

PATH = "/audio/transcriptions"
CONNECT_TIMEOUT = 3   # seconds to reach the server
READ_TIMEOUT = 300    # seconds for it to answer: the request may wait behind other programs', and the model loads
MAX_AUDIO = 20 * 1024 * 1024
BUSY = 503            # the server's answer when memory is short


class SpeechUnavailable(RuntimeError):
    """Speech to text can't run now. status is what to tell the page: 503 when the server is down or short of
    memory (type the answer instead), 502 for any other trouble it reports."""

    def __init__(self, message: str, status: int = 503):
        super().__init__(message)
        self.status = status


def speech_url(configured: str = "") -> str:
    """Where audio is sent: the watchlist's speech.url when given, else LOCAL_STT_URL, else the local model server's
    /audio/transcriptions."""
    return (configured or os.environ.get("LOCAL_STT_URL") or chat.local_url() + PATH).rstrip("/")


def reachable(url: str, timeout: float = 1.0) -> bool:
    """Whether something listens at the endpoint's host and port. Only a connection is opened: nothing is sent, so
    no model is loaded to answer it."""
    parts = urllib.parse.urlsplit(url)
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
        with socket.create_connection((parts.hostname or "", port), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def _multipart(audio: bytes, name: str, content_type: str, fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
             for k, v in fields.items()]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                 f"Content-Type: {content_type}\r\n\r\n".encode() + audio + b"\r\n")
    return b"".join(parts) + f"--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def _said(resp: http.client.HTTPResponse) -> str:
    """What the server says went wrong: its JSON error message, else the status line."""
    try:
        body = json.loads(resp.read().decode("utf-8", "replace"))
        err = body.get("error", body) if isinstance(body, dict) else body
        message = err.get("message") if isinstance(err, dict) else err
    except (ValueError, OSError):
        message = None
    return str(message or resp.reason)


def transcribe(audio: bytes, content_type: str = "audio/webm", name: str = "answer.webm", url: str = "") -> dict:
    """{text, duration, segments} for a recording (duration in seconds, 0 when the server doesn't say), sent to url
    (the watchlist's speech.url) or speech_url()'s default. Raises SpeechUnavailable when the server is down or
    busy, or says no."""
    if not audio:
        raise ValueError("no audio was sent")
    if len(audio) > MAX_AUDIO:
        raise SpeechUnavailable(f"that recording is too long to transcribe ({MAX_AUDIO // 1024 // 1024} MB at most)",
                                413)
    url = speech_url(url)
    parts = urllib.parse.urlsplit(url)
    cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    body, ctype = _multipart(audio, os.path.basename(name) or "answer.webm", content_type or "audio/webm",
                             {"model": "local", "response_format": "verbose_json"})
    conn = cls(parts.hostname, parts.port, timeout=CONNECT_TIMEOUT)
    try:
        try:
            conn.connect()
            conn.sock.settimeout(READ_TIMEOUT)
            conn.request("POST", parts.path or "/", body=body, headers={"Content-Type": ctype})
            resp = conn.getresponse()
        except (OSError, http.client.HTTPException) as e:
            raise SpeechUnavailable(f"no speech-to-text server at {url} (start the local model server, or set "
                                    "LOCAL_STT_URL). Type your answer instead.") from e
        if resp.status == BUSY:
            raise SpeechUnavailable(f"the speech-to-text server is busy or short of memory ({_said(resp)}). "
                                    "Try again in a moment, or type your answer instead.")
        if resp.status >= 400:
            raise SpeechUnavailable(f"the speech-to-text server said {resp.status}: {_said(resp)}. Type your "
                                    "answer instead.", 502)
        try:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        except (ValueError, OSError, http.client.HTTPException) as e:
            raise SpeechUnavailable("the speech-to-text server sent a reply jobwatch can't read", 502) from e
    finally:
        conn.close()
    if not isinstance(data, dict):
        raise SpeechUnavailable("the speech-to-text server sent a reply jobwatch can't read", 502)
    try:
        duration = max(0.0, float(data.get("duration") or 0))
    except (TypeError, ValueError):
        duration = 0.0
    return {"text": str(data.get("text") or "").strip(), "duration": duration,
            "segments": data.get("segments") if isinstance(data.get("segments"), list) else []}
