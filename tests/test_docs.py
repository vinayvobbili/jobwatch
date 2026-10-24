"""The README is a short landing page and the details live in docs/guide: every link between them goes somewhere.
A relative link or a link to this repo's own files on GitHub names a file that's there, and its #anchor a heading
in it (GitHub's anchors: lowercase, punctuation dropped, spaces to hyphens)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REPO = "https://github.com/vinayvobbili/jobwatch/blob/main/"
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs" / "guide").glob("*.md"))]
LINK = re.compile(r"\]\(([^)\s]+)\)")


def anchors(path: Path) -> set[str]:
    text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)  # no headings in code
    heads = re.findall(r"^#{1,6} (.+?)\s*$", text, re.M)
    return {re.sub(r"[^\w\- ]", "", re.sub(r"`|\*\*", "", h)).strip().lower().replace(" ", "-") for h in heads}


def targets(path: Path):
    text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
    for link in LINK.findall(text):
        if link.startswith(REPO):
            link = str(ROOT / link[len(REPO):])
        elif link.startswith(("http://", "https://", "mailto:")):
            continue
        file, _, anchor = link.partition("#")
        yield link, (path if not file else (path.parent / file).resolve()), anchor


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_link_in_the_docs_goes_somewhere(doc):
    broken = []
    for link, target, anchor in targets(doc):
        if not target.exists():
            broken.append(f"{link}: no such file")
        elif anchor and target.suffix == ".md" and anchor not in anchors(target):
            broken.append(f"{link}: no heading #{anchor}")
    assert broken == []


def test_the_guide_index_lists_every_page():
    guide = ROOT / "docs" / "guide"
    listed = set(re.findall(r"\]\(([\w-]+\.md)\)", (guide / "README.md").read_text(encoding="utf-8")))
    assert listed == {p.name for p in guide.glob("*.md")} - {"README.md"}


def test_the_readme_stays_a_landing_page():
    """The details go in the guide; the README is what someone reads before installing."""
    words = len((ROOT / "README.md").read_text(encoding="utf-8").split())
    assert words < 1500, f"README.md has {words} words: move the details to docs/guide"
