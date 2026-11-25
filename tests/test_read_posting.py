"""The extension's posting reader (chrome-extension/read-posting.js): the description of a LinkedIn or Indeed job page,
run with node against made-up pages, and the content script's own guard: it reads nothing unless jobwatch's Read posting
button opened the page."""
# ruff: noqa: E501  (page text as the sites write it)

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from jobwatch import filltext

from .test_filltext import INDEED_PAGE, LINKEDIN_PAGE, REAL_SHAPE, SIGN_IN

SCRIPT = Path(__file__).resolve().parent.parent / "chrome-extension" / "read-posting.js"
needs_node = pytest.mark.skipif(not shutil.which("node"), reason="needs node")

LI = "https://www.linkedin.com/jobs/view/4000000001/#jobwatch-read"
IN = "https://www.indeed.com/viewjob?jk=9cf96221e712e37e"


def run_js(tmp_path, body: str):
    js = tmp_path / "case.js"
    js.write_text(f"const R = require({json.dumps(str(SCRIPT))});\n{body}", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@needs_node
def test_it_reads_a_linkedin_page_the_way_the_python_reader_does(tmp_path):
    got = run_js(tmp_path, f"""const doc = {{ body: {{ innerText: {json.dumps(LINKEDIN_PAGE)} }}, querySelector: (s) => s === 'h1' ? {{ innerText: 'Platform Engineer' }} : null }};
console.log(JSON.stringify(R.readPage(doc, {json.dumps(LI)})));""")
    py = filltext.posting_from_page("linkedin", LINKEDIN_PAGE)
    assert got["text"] == py.text and got["closed"] is True and py.closed
    assert (got["site"], got["id"], got["title"]) == ("linkedin", "4000000001", "Platform Engineer")


@needs_node
def test_it_reads_an_indeed_page_from_its_description_element_or_its_text(tmp_path):
    got = run_js(tmp_path, f"""const page = {json.dumps(INDEED_PAGE)};
const sel = {{ '#jobDescriptionText': {{ innerText: 'x'.repeat(300) }}, h1: {{ innerText: 'Platform Engineer' }},
  '[data-testid="inlineHeader-companyName"], [data-company-name="true"]': {{ innerText: 'Initech' }} }};
const withElement = {{ body: {{ innerText: page }}, querySelector: (s) => sel[s] || null }};
const textOnly = {{ body: {{ innerText: page }}, querySelector: () => null }};
console.log(JSON.stringify([R.readPage(withElement, {json.dumps(IN)}), R.readPage(textOnly, {json.dumps(IN)})]));""")
    element, text = got
    assert element["text"] == "x" * 300 and element["company"] == "Initech" and element["id"] == "9cf96221e712e37e"
    assert text["text"] == filltext.posting_from_page("indeed", INDEED_PAGE).text


@needs_node
def test_it_sees_the_closed_banner_of_a_real_page_on_both_sites(tmp_path):
    expired = INDEED_PAGE.replace("Job details\n", "Job details\nThis job has expired on Indeed\n")
    got = run_js(tmp_path, f"""const page = (t) => ({{ body: {{ innerText: t }}, querySelector: () => null }});
console.log(JSON.stringify([R.readPage(page({json.dumps(REAL_SHAPE)}), {json.dumps(LI)}).closed,
  R.readPage(page({json.dumps(expired)}), {json.dumps(IN)}).closed, R.readPage(page({json.dumps(INDEED_PAGE)}), {json.dumps(IN)}).closed]));""")
    assert got == [True, True, False]


@needs_node
def test_a_page_with_no_posting_says_why_and_other_pages_are_refused(tmp_path):
    got = run_js(tmp_path, f"""const wall = {{ body: {{ innerText: {json.dumps(SIGN_IN)} }}, querySelector: () => null }};
console.log(JSON.stringify([R.readPage(wall, {json.dumps(LI)}), R.readPage(wall, 'https://www.linkedin.com/feed/'),
  R.readPage(wall, 'https://www.linkedin.com/jobs/view/abc/'), R.siteOf('https://example.com/jobs/view/1/')]));""")
    wall, feed, noid, other = got
    assert "asks to sign in" in wall["error"]
    assert "isn't a LinkedIn or Indeed job page" in feed["error"]
    assert "which job" in noid["error"] and other == ""


@needs_node
def test_the_ids_come_from_the_address(tmp_path):
    got = run_js(tmp_path, """console.log(JSON.stringify([
  R.jobId('linkedin', 'https://www.linkedin.com/jobs/view/senior-engineer-at-initech-4000000001/?refId=x'),
  R.jobId('indeed', 'https://www.indeed.com/viewjob?jk=9cf96221e712e37e&from=x'),
  R.jobId('indeed', 'https://www.indeed.com/viewjob?jk=zzz'), R.siteOf('https://www.indeed.com/m/viewjob?jk=9cf96221e712e37e')]));""")
    assert got == ["4000000001", "9cf96221e712e37e", "", "indeed"]


@needs_node
def test_the_content_script_reads_nothing_unless_the_read_posting_button_opened_the_page(tmp_path):
    """On a LinkedIn job page opened any other way (no #jobwatch-read), the script sends no message at all; on a page the
    button opened it sends the description once, and the tab's address loses the marker."""
    def load(location_href, hash_):
        return f"""const sent = [];
globalThis.chrome = {{ runtime: {{ id: 'x', sendMessage: async (m) => {{ sent.push(m); return {{ ok: true, said: 'saved' }}; }} }} }};
globalThis.location = {{ href: {json.dumps(location_href)}, hash: {json.dumps(hash_)}, pathname: '/jobs/view/4000000001/', search: '' }};
const banner = {{ style: {{}}, setAttribute() {{}} }};
globalThis.document = {{ body: {{ innerText: {json.dumps(LINKEDIN_PAGE)} }}, querySelector: () => null, getElementById: () => null,
  createElement: () => banner, documentElement: {{ appendChild() {{}} }} }};
globalThis.history = {{ replaceState(a, b, url) {{ globalThis.location.href = url; }} }};
globalThis.window = {{ close() {{ sent.push('closed'); }} }};
delete require.cache[require.resolve({json.dumps(str(SCRIPT))})];  // run_js loaded it once already, with no page
require({json.dumps(str(SCRIPT))});
setTimeout(() => {{ console.log(JSON.stringify({{ sent, banner: banner.textContent || null }})); process.exit(0); }}, 100);"""

    other_way = run_js(tmp_path, load("https://www.linkedin.com/jobs/view/4000000001/", ""))
    assert other_way == {"sent": [], "banner": None}  # no message, and not even its banner
    got = run_js(tmp_path, load(LI, "#jobwatch-read"))
    sent = got["sent"]
    assert got["banner"] == "jobwatch: saved", got
    assert len(sent) == 1 and sent[0]["type"] == "readPosting" and sent[0]["id"] == "4000000001"
    assert sent[0]["text"].startswith("We are hiring a Platform Engineer") and sent[0]["closed"] is True
