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
