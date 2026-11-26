"""Put one paste block of CHROMEWEBSTORE.md on the macOS clipboard, for the Web Store dashboard's fields.

    python chrome-extension/tools/paste_block.py --list            # each block with its character count
    python chrome-extension/tools/paste_block.py single            # copy "Single purpose"
    python chrome-extension/tools/paste_block.py activeTab         # copy "Justification: activeTab"
    python chrome-extension/tools/paste_block.py test-instructions # copy the "## Test Instructions" section

NAME is a block's `###` heading under "## Paste blocks for ..." (the "Justification: " lead is optional),
matched case-insensitively by unique prefix; an unknown or ambiguous NAME lists the choices. A block's text is
what sits between its heading and the next one. The host permission block is only its three paragraphs (Local
app, LinkedIn and Indeed, Ladders): the dashboard field takes 1,000 characters, and more is refused. The two
"Data use" blocks are ticks to read, not text to paste, so they are listed and never copied.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

EXTENSION_DIR = Path(__file__).resolve().parents[1]
STORE_DOC = EXTENSION_DIR / "CHROMEWEBSTORE.md"

PASTE_SECTION = "Paste blocks for"
TEST_SECTION = "Test Instructions"
TEST_NAME = "test-instructions"
HOST_BLOCK = "host permission justification"
HOST_PARAGRAPHS = ("Local app", "LinkedIn and Indeed", "Ladders")
HOST_LIMIT = 1000
READ_ONLY_PREFIX = "data use:"
READ_ONLY_NOTE = "(read, not pasted)"
LEAD = "justification: "


@dataclass
class Block:
    name: str  # the heading, as written
    text: str  # what gets pasted
    read_only: bool = False

    @property
    def keys(self) -> list[str]:
        """Lowercase names this block answers to: the whole heading, and without the "Justification: " lead."""
        full = self.name.lower()
        return [full, full[len(LEAD):]] if full.startswith(LEAD) else [full]


def headings(markdown: str):
    """Yield (level, title, body) for each heading, the body being the text up to the next heading."""
    found: list[tuple[int, str, list[str]]] = []
    fenced = False
    for line in markdown.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        match = None if fenced else re.match(r"(#{1,6})\s+(.*?)\s*$", line)
        if match:
            found.append((len(match.group(1)), match.group(2), []))
        elif found:
            found[-1][2].append(line)
    for level, title, body in found:
        yield level, title, "\n".join(body).strip()


def host_text(body: str) -> str:
    """The three paragraphs that go in the dashboard's host permission box, without the intro above them."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    picked = [next((p for p in paragraphs if p.startswith(start)), None) for start in HOST_PARAGRAPHS]
    missing = [start for start, p in zip(HOST_PARAGRAPHS, picked, strict=True) if p is None]
    if missing:
        raise SystemExit(f"the host permission block has no paragraph starting {', '.join(missing)}")
    return "\n\n".join(picked)


def load_blocks(markdown: str) -> list[Block]:
    blocks: list[Block] = []
    in_paste = False
    for level, title, body in headings(markdown):
        if level <= 2:
            in_paste = level == 2 and title.startswith(PASTE_SECTION)
            if level == 2 and title.startswith(TEST_SECTION):
                blocks.append(Block(TEST_NAME, body))
        elif in_paste and level == 3:
            if title.lower().startswith(HOST_BLOCK):
                body = host_text(body)
            blocks.append(Block(title, body, read_only=title.lower().startswith(READ_ONLY_PREFIX)))
    if not any(b.name != TEST_NAME for b in blocks):
        raise SystemExit(f"no '## {PASTE_SECTION} ...' section found")
    return blocks


def find_block(blocks: list[Block], name: str) -> Block:
    wanted = name.strip().lower()
    exact = [b for b in blocks if wanted in b.keys]
    matches = exact or [b for b in blocks if any(key.startswith(wanted) for key in b.keys)]
    if len(matches) == 1:
        return matches[0]
    choices = "\n".join(f"  {b.name}" for b in (matches or blocks))
    problem = "matches several blocks" if matches else "is not a block"
    raise SystemExit(f"'{name}' {problem}; choose one:\n{choices}")


def pbcopy(text: str) -> None:
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)


def copy_block(block: Block, clipboard=pbcopy) -> str:
    if block.read_only:
        return f"{block.name} {READ_ONLY_NOTE}: tick these by reading them; nothing was copied."
    if block.name.lower().startswith(HOST_BLOCK) and len(block.text) > HOST_LIMIT:
        raise SystemExit(
            f"{block.name}: {len(block.text):,} characters is over the dashboard's {HOST_LIMIT:,}; nothing was copied."
        )
    clipboard(block.text)
    return f"Copied {block.name} ({len(block.text):,} characters)"


def main(argv=None, clipboard=pbcopy, doc: Path = STORE_DOC, out=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", nargs="?", help="block name or unique prefix (see --list)")
    parser.add_argument("--list", action="store_true", help="list the blocks with their character counts")
    args = parser.parse_args(argv)
    out = out or sys.stdout
    blocks = load_blocks(doc.read_text(encoding="utf-8"))
    if args.list or not args.name:
        for block in blocks:
            note = f"  {READ_ONLY_NOTE}" if block.read_only else ""
            print(f"{len(block.text):>6,}  {block.name}{note}", file=out)
        return 0
    print(copy_block(find_block(blocks, args.name), clipboard), file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
