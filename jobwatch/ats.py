"""ATS check (`jobwatch ats KEY`, the second step of Prepare on a queued job, and the extension's ATS check): which of
the posting's keywords the resume for a job doesn't show, read the way an applicant tracking system's parser reads
it: from the built PDF's text, not from the version's source.

The latest result for a job's own resume is kept (see prepare.py), so the Queue card shows it again after a reload.

Everything is checked here, on this computer, with no model:
- the keywords are the skills the posting names (the catalog behind `jobwatch skills`, so "K8s" and "Kubernetes"
  are one) plus the tools and acronyms its requirement lines name (PostgreSQL, CI/CD, C++). One asked for under
  the requirements is a must; one under the nice-to-haves or elsewhere in the posting counts for half as much;
- the resume is the file kept with the job (the tailored PDF), else the watchlist's. A PDF is read with pdftotext
  (poppler) when it's installed, else with shortlist-ai, as `jobwatch ask` reads it;
- the format checks are what makes a parser drop a field: no text at all (a scanned page), no email or phone, no
  Experience, Education or Skills heading, symbols that came out as boxes, the posting's title words missing.

A missing keyword is a prompt to look, not an order: add it only where it's true of you.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from . import prep, prepare
from .autofill import resume_for
from .config import Config
from .learn import catalog
from .resume import resume_text
from .store import Store

MOST = 30            # keywords checked per posting
MUST_WEIGHT = 2      # a requirement counts for twice a nice-to-have
MIN_TEXT = 300       # characters of text below which a PDF has probably no text layer (a scan or an image)
READ_TIMEOUT = 30
NO_READER = ("Can't read the PDF's text: install poppler (`brew install poppler`, which has pdftotext) or "
             "`pip install 'jobwatch[score]'`.")

# Words that look like tools (capitalized, an acronym) but aren't.
_SKIP = set("""us usa uk eu eeo eoe hr it ok pto and the for our you we are not all new job full time part pm am ceo
cto cfo vp ii iii iv inc llc ltd co etc faq url usd rn monday tuesday wednesday thursday friday saturday sunday
january february march april may june july august september october november december""".split())
_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{1,5}\b")
_TOOLISH = re.compile(r"(?<![\w.])(?:[A-Za-z][A-Za-z0-9]*(?:\+\+|#)|\.NET|[A-Za-z][A-Za-z0-9]*\.(?:js|JS|NET))(?![\w])")
_CAMEL = re.compile(r"\b[A-Z][a-z]+[A-Z][A-Za-z0-9]*\b")
_CAPITALIZED = re.compile(r"(?<=[a-z,;(] )[A-Z][a-z]{3,}\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
_HEADINGS = (
    ("Experience", re.compile(r"^\W*(?:work |professional )?(?:experience|employment|work history)\W*$", re.I | re.M)),
    ("Education", re.compile(r"^\W*education\W*$", re.I | re.M)),
    ("Skills", re.compile(r"^\W*(?:technical |core )?(?:skills|expertise|competencies)\b.*$", re.I | re.M)))
_ODD = re.compile("[�-]")
_TITLE_NOISE = set("""senior sr staff principal lead junior jr associate ii iii iv i of the and for a an to in remote
hybrid us usa contract""".split())


def read_file(path: Path) -> tuple[str, str]:
    """(the file's text, how it was read) as a parser would get it: pdftotext for a PDF when installed, else
    shortlist-ai, as the chat reads a resume. ValueError when nothing here can read it."""
    if path.suffix.lower() == ".pdf":
        if exe := shutil.which("pdftotext"):
            try:
                done = subprocess.run([exe, "-enc", "UTF-8", str(path), "-"], capture_output=True, text=True,
                                      timeout=READ_TIMEOUT)
            except (OSError, subprocess.SubprocessError):
                done = None
            if done and done.returncode == 0:
                return done.stdout, "pdftotext"
        if text := resume_text(path):
            return text, "shortlist-ai"
        raise ValueError(NO_READER)
    return resume_text(path), "text"


def _pattern(term: str) -> re.Pattern:
    """The term as a whole word, so "Go" doesn't match "Google" and "C" doesn't match "CI"."""
    return re.compile(rf"(?<![\w+#.]){re.escape(term)}(?![\w+#])", re.I)


def _extra_terms(text: str, known: str, skip: set[str], plain: int) -> dict[str, int]:
    """{term: mentions} for the tools and acronyms in `text` that the skills catalog doesn't already cover. A
    capitalized word in mid-sentence (Python, Rust) counts after `plain` mentions."""
    found: dict[str, int] = {}
    for rx, floor in ((_TOOLISH, 1), (_CAMEL, 1), (_ACRONYM, 1), (_CAPITALIZED, plain)):
        counts: dict[str, int] = {}
        for m in rx.finditer(text):
            counts[m.group(0)] = counts.get(m.group(0), 0) + 1
        for term, n in counts.items():
            low = term.lower()
            if n >= floor and low not in _SKIP and low not in prep._STOP and low not in skip \
                    and not _pattern(term).search(known):
                found[term] = max(found.get(term, 0), n)
    return found


def keywords(title: str, company: str, description: str) -> list[dict]:
    """The posting's keywords, requirements first: [{term, kind (must | nice | mentioned), count, pattern}], at most
    MOST. `pattern` is the regex the resume is checked with (the catalog's, so aliases count)."""
    asks = prep.asks(description, most=80)
    must = "\n".join(line for line, kind in asks if kind in ("need", "do"))
    nice = "\n".join(line for line, kind in asks if kind == "nice")
    skip = {w.lower() for w in re.findall(r"\w+", f"{title} {company}")}
    out, covered = [], ""
    for skill in catalog():
        if not (n := len(skill.pattern.findall(description))):
            continue
        covered += " " + " ".join(m.group(0) for m in skill.pattern.finditer(description))
        kind = "must" if skill.found_in(must) else "nice" if skill.found_in(nice) else "mentioned"
        out.append({"term": skill.name, "kind": kind, "count": n, "pattern": skill.pattern})
    # Tools and acronyms come from the requirement lines when the posting has any, else from all of it.
    # In the whole posting a capitalized word needs two mentions to count (one is as likely a place or a name).
    source = "\n".join(line for line, _ in asks)
    for term, n in _extra_terms(source or description, covered, skip, 1 if source else 2).items():
        kind = "must" if _pattern(term).search(must) else "nice" if _pattern(term).search(nice) else "mentioned"
        out.append({"term": term, "kind": kind, "count": n, "pattern": _pattern(term)})
    rank = {"must": 0, "nice": 1, "mentioned": 2}
    out.sort(key=lambda k: (rank[k["kind"]], -k["count"], k["term"].lower()))
    return out[:MOST]


def format_checks(text: str, title: str) -> list[str]:
    """What in the extracted text would make a parser drop or misread something, each as a sentence to act on."""
    if len(text.strip()) < MIN_TEXT:
        return ["The file has almost no readable text: a scanned or image-only PDF is invisible to a parser. "
                "Export it again from the document, not from a picture."]
    out = []
    if not _EMAIL.search(text):
        out.append("No email address in the text: parsers read contact details from the text, not from an icon.")
    if not _PHONE.search(text):
        out.append("No phone number in the text.")
    if gone := [name for name, rx in _HEADINGS if not rx.search(text)]:
        out.append(f"No {' or '.join(gone)} heading found on a line of its own: parsers split a resume by its "
                   "standard headings.")
    if _ODD.search(text):
        out.append("Some symbols came out as boxes or private-use characters (often bullets or icons): use plain "
                   "bullets and fonts that embed their letters.")
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z+#.]*", title) if w.lower() not in _TITLE_NOISE]
    if words and not any(_pattern(w).search(text) for w in words):
        out.append(f"None of the title's words ({', '.join(words)}) appear: recruiters search by title, and "
                   "an ATS ranks by it.")
    return out


def check(cfg: Config, store: Store, key: str, resume: Path | None = None) -> dict:
    """The ATS check of a job's resume: {key, company, title, file, tailored, read_with, chars, score (0-100, must-haves
    count double), found, missing (each {term, kind, count}), checks}. `resume`: a file to check instead of the one
    kept with the job. ValueError when there's no posting text, no resume or nothing can read it."""
    job, _ = store.find(key)
    posting = store.linked(job) or job
    if not posting.description.strip():
        raise ValueError(f"{job.display_company}: {job.title} has no posting text to take keywords from: add it first")
    kept = None if resume else store.package(job.key).resume()
    path = resume or resume_for(cfg, store, job)
    if not path:
        raise ValueError("no resume to check: tailor one for this job, or set one in Settings > Resume")
    text, how = read_file(Path(path).expanduser())
    kws = keywords(posting.title, posting.display_company, posting.description)
    rows = [{"term": k["term"], "kind": k["kind"], "count": k["count"], "found": bool(k["pattern"].search(text))}
            for k in kws]
    weight = {"must": MUST_WEIGHT, "nice": 1, "mentioned": 1}
    total = sum(weight[r["kind"]] for r in rows)
    got = sum(weight[r["kind"]] for r in rows if r["found"])
    result = {"key": job.key, "company": job.display_company, "title": job.title, "file": Path(path).name,
              "tailored": bool(kept), "read_with": how, "chars": len(text.strip()),
              "score": round(100 * got / total) if total else None,
              "found": [{k: r[k] for k in ("term", "kind", "count")} for r in rows if r["found"]],
              "missing": [{k: r[k] for k in ("term", "kind", "count")} for r in rows if not r["found"]],
              "checks": format_checks(text, posting.title)}
    if not resume:  # a check of some other file isn't the job's: only the job's own resume is kept for the page
        try:
            prepare.save_ats(store, job, posting, result, Path(path))
        except OSError:
            pass  # the check still answers; the page just won't show it again after a reload
    return result


def render(r: dict) -> str:
    """The check as the text `jobwatch ats` prints."""
    which = "tailored for this job" if r["tailored"] else "your general resume, not tailored for this job"
    out = [f"{r['company']}: {r['title']}", f"Resume: {r['file']} ({which}; read with {r['read_with']}, "
           f"{r['chars']:,} characters)"]
    if r["score"] is None:
        out.append("The posting names no keywords to check.")
    else:
        total = len(r["found"]) + len(r["missing"])
        out.append(f"Keywords: {len(r['found'])} of {total} found ({r['score']}%, must-haves count double)")
    label = {"must": "asked for", "nice": "nice to have", "mentioned": "mentioned"}
    if r["missing"]:
        out += ["", "Missing from the resume's text:"]
        out += [f"  {m['term']}  ({label[m['kind']]}, {m['count']}x in the posting)" for m in r["missing"]]
    if r["found"]:
        out += ["", "Found: " + ", ".join(f["term"] for f in r["found"])]
    if r["checks"]:
        out += ["", "How a parser reads it:"] + [f"  - {c}" for c in r["checks"]]
    elif r["score"] is not None:
        out += ["", "How a parser reads it: nothing to fix."]
    out += ["", "Add a keyword only where it's true of you; a missing one is a prompt to look, not an order."]
    return "\n".join(out)
