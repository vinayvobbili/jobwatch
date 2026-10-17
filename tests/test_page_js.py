import json
import re
import shutil
import subprocess
from importlib import resources

import pytest


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_page_script_parses(tmp_path):
    """A syntax error in the page's script leaves a blank page with no test failing elsewhere: node reads it."""
    page = resources.files("jobwatch").joinpath("static/index.html").read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    assert scripts
    js = tmp_path / "page.js"
    js.write_text("\n".join(scripts), encoding="utf-8")
    r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def page_function(name: str) -> str:
    """One top-level function's source from the page's script (it ends at the first closing brace in column 0)."""
    page = resources.files("jobwatch").joinpath("static/index.html").read_text(encoding="utf-8")
    m = re.search(rf"^function {name}\(.*?^}}$", page, re.S | re.M)
    assert m, f"no function {name} in the page"
    return m.group(0)


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_todays_quick_narrowing(tmp_path):
    jobs = {
        "remote": {"where": ["remote"], "fit": {"score": 82}, "salary_max": 260000},
        "city": {"where": ["onsite"], "fit": {"score": 65}, "salary_max": 180000},
        "both": {"where": ["remote", "onsite"], "fit": None, "salary_max": None},  # not scored, no pay listed
        "nowhere": {"where": [], "fit": {"score": 50}, "salary_max": 300000},
    }
    views = {
        "off": {"where": "any", "fit": 0, "pay": 0},
        "remote": {"where": "remote", "fit": 0, "pay": 0},
        "onsite": {"where": "onsite", "fit": 0, "pay": 0},
        "fit70": {"where": "any", "fit": 70, "pay": 0},
        "pay250": {"where": "any", "fit": 0, "pay": 250000},
        "all": {"where": "remote", "fit": 80, "pay": 250000},
    }
    js = tmp_path / "narrow.js"
    js.write_text(page_function("quickNarrow") + f"""
const jobs = {json.dumps(jobs)}, views = {json.dumps(views)};
const out = {{}};
for (const [v, view] of Object.entries(views)) out[v] = Object.keys(jobs).filter(k => quickNarrow(jobs[k], view));
console.log(JSON.stringify(out));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {
        "off": ["remote", "city", "both", "nowhere"],
        "remote": ["remote", "both", "nowhere"],     # no location given isn't hidden
        "onsite": ["city", "both", "nowhere"],
        "fit70": ["remote", "both"],                 # not scored yet still shows
        "pay250": ["remote", "both", "nowhere"],     # no listed pay still shows
        "all": ["remote", "both"],
    }
