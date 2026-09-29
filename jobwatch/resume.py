"""The resume as plain text, for the chat and the skills report."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

MAX_RESUME = 16000


@lru_cache(maxsize=4)
def _text(path: str, mtime: float) -> str:
    p = Path(path)
    if p.suffix.lower() in (".txt", ".md"):
        return p.read_text(encoding="utf-8", errors="replace")
    try:
        from shortlist_ai.documents import load_document
    except ImportError:
        return ""
    return load_document(p).text


def resume_text(path: Path | None) -> str:
    """The resume as text (cached until the file changes); empty when there's none or it can't be read.
    PDFs and .docx need shortlist-ai (pip install 'jobwatch[score]')."""
    if not path or not path.is_file():
        return ""
    try:
        return _text(str(path), path.stat().st_mtime)[:MAX_RESUME]
    except Exception:
        return ""
