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
def test_jobwatchs_page_may_ask_only_for_a_job_page_and_only_from_its_own_address(tmp_path):
    """Read posting from jobwatch's page: the tab opened is a LinkedIn or Indeed job's, with the reader's marker, and the
    asking page must be local and on the port the extension is paired with, whatever local name the person types."""
    got = run_js(tmp_path, """const ask = (o, s) => R.sameJobwatch(o, s);
console.log(JSON.stringify([
  R.readUrl('https://www.linkedin.com/jobs/view/4000000001/?refId=x'), R.readUrl('https://www.indeed.com/viewjob?jk=9cf96221e712e37e'),
  R.readUrl('https://www.linkedin.com/feed/'), R.readUrl('https://evil.example/jobs/view/4000000001/'), R.readUrl('nonsense'),
  ask('http://jobwatch.localhost:8765', 'http://127.0.0.1:8765'), ask('http://127.0.0.1:8765', 'http://127.0.0.1:8765'),
  ask('http://localhost:8765', 'http://jobwatch.localhost:8765'),
  ask('http://jobwatch.localhost:9000', 'http://127.0.0.1:8765'), ask('https://jobwatch.localhost:8765', 'http://127.0.0.1:8765'),
  ask('http://evil.example:8765', 'http://127.0.0.1:8765'), ask('http://localhost.evil.example:8765', 'http://127.0.0.1:8765'),
  ask('', 'http://127.0.0.1:8765')]));""")
    assert got == ["https://www.linkedin.com/jobs/view/4000000001/?refId=x#jobwatch-read",
                   "https://www.indeed.com/viewjob?jk=9cf96221e712e37e#jobwatch-read", "", "", "",
                   True, True, True, False, False, False, False, False]


@needs_node
def test_the_bridge_passes_on_only_the_fields_the_page_uses(tmp_path):
    bridge = SCRIPT.parent / "page-bridge.js"
    js = tmp_path / "bridge.js"
    js.write_text(f"""const B = require({json.dumps(str(bridge))});
console.log(JSON.stringify([B.doneMessage({{ key: 'k', ok: true, closed: true, has_text: true, said: 'done', token: 'secret', where: 'queue' }}),
  B.doneMessage({{ key: 'k', ok: false, error: 'no' }}), B.doneMessage({{ key: 'k', error: 'x' }}), B.doneMessage(null)]));""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    done = "jobwatch:read-posting-done"
    assert json.loads(r.stdout) == [
        {"type": done, "key": "k", "ok": True, "closed": True, "has_text": True, "said": "done"},
        {"type": done, "key": "k", "ok": False, "error": "no"}, {"type": done, "key": "k", "ok": False, "error": "x"},
        {"type": done, "key": "", "ok": True}]


@needs_node
def test_the_bridge_tells_the_page_what_the_extension_can_do_and_an_old_one_can_do_nothing(tmp_path):
    """The ping's answer becomes the page's capability list; an extension from before `ping` says "unknown message"
    (ok: false), or nothing, which is an empty list, so the page reads the old way."""
    bridge = SCRIPT.parent / "page-bridge.js"
    js = tmp_path / "caps.js"
    js.write_text(f"""const B = require({json.dumps(str(bridge))});
console.log(JSON.stringify([B.capsText({{ ok: true, capabilities: ['readInBackground'] }}),
  B.capsText({{ ok: false, error: 'Something went wrong: unknown message ping' }}), B.capsText(undefined), B.capsText({{ ok: true }}),
  B.capsText({{ ok: true, capabilities: ['readInBackground', 'two words', 7] }})]));""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ["readInBackground", "", "", "", "readInBackground"]


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


# --- the tab closes itself once the posting is read: the service worker removes it (chrome.tabs.remove) -------------

EXT = SCRIPT.parent


def content_script_case(tmp_path, page_text: str, answers: dict):
    """read-posting.js on a page jobwatch's button opened, its banner delay cut to a few ms, `answers` the service
    worker's reply to each message type ("throw" makes the send fail). The messages it sent, and whether it closed itself."""
    return run_js(tmp_path, f"""const sent = [];
const answers = {json.dumps(answers)};
globalThis.chrome = {{ runtime: {{ id: 'x', sendMessage: async (m) => {{
  sent.push(m.type);
  const a = answers[m.type];
  if (a === 'throw') throw new Error('Extension context invalidated');
  return a; }} }} }};
globalThis.location = {{ href: {json.dumps(LI)}, hash: '#jobwatch-read', pathname: '/jobs/view/4000000001/', search: '' }};
const banner = {{ style: {{}}, setAttribute() {{}} }};
globalThis.document = {{ body: {{ innerText: {json.dumps(page_text)} }}, querySelector: () => null, getElementById: () => null,
  createElement: () => banner, documentElement: {{ appendChild() {{}} }} }};
globalThis.history = {{ replaceState() {{}} }};
globalThis.window = {{ close() {{ sent.push('window.close'); }} }};
const later = globalThis.setTimeout;
globalThis.setTimeout = (f, ms) => later(f, ms >= 2000 ? 5 : ms);  // the banner's 2.5 s and 6 s
delete require.cache[require.resolve({json.dumps(str(SCRIPT))})];  // run_js loaded it once already, with no page
require({json.dumps(str(SCRIPT))});
later(() => {{ console.log(JSON.stringify({{ sent }})); process.exit(0); }}, 300);""")["sent"]


@needs_node
def test_a_read_posting_asks_the_service_worker_to_close_its_tab(tmp_path):
    sent = content_script_case(tmp_path, LINKEDIN_PAGE, {"readPosting": {"ok": True, "said": "saved"}, "closeReadTab": {"ok": True}})
    assert sent == ["readPosting", "closeReadTab"]  # the worker closed it: the page did not need to


@needs_node
@pytest.mark.parametrize("reply", [{"ok": False, "error": "no"}, None, "throw"])
def test_the_page_closes_itself_only_when_the_worker_does_not_answer_ok(tmp_path, reply):
    sent = content_script_case(tmp_path, LINKEDIN_PAGE, {"readPosting": {"ok": True, "said": "saved"}, "closeReadTab": reply})
    assert sent == ["readPosting", "closeReadTab", "window.close"]


@needs_node
def test_a_page_that_could_not_be_read_stays_open_for_the_person(tmp_path):
    """A sign-in wall: the failure is reported (the page that asked says so), and nothing closes the tab."""
    sent = content_script_case(tmp_path, SIGN_IN, {"readFailed": {"ok": True}})
    assert sent == ["readFailed"]


@needs_node
def test_a_posting_jobwatch_refused_stays_open(tmp_path):
    sent = content_script_case(tmp_path, LINKEDIN_PAGE, {"readPosting": {"ok": False, "error": "sign in first"}})
    assert sent == ["readPosting"]


JOB_TAB = {"id": 5, "url": "https://www.linkedin.com/jobs/view/4000000001/"}


def background_case(tmp_path, body: str):
    """background.js (the service worker) loaded in node with a fake chrome and fetch: `send(msg, tab)` delivers a message
    as a content script in `tab` would, and answers its reply; `closed` lists the tabs chrome.tabs.remove was given."""
    for name in ("background.js", "logic.js", "passive.js", "read-posting.js", "lib.js"):
        shutil.copy(EXT / name, tmp_path / name)
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (tmp_path / "case.mjs").write_text(f"""const kept = {{}};
const closed = [];
let onMessage;
let jobwatchAnswers = {{ ok: true, status: 200, body: {{ where: 'queue', closed: false }} }};
const none = {{ addListener() {{}} }};
const keys = (k) => (Array.isArray(k) ? k : [k]);
globalThis.chrome = {{
  runtime: {{ onMessage: {{ addListener: (f) => {{ onMessage = f; }} }} }},
  action: {{ onClicked: none }}, sidePanel: {{ setOptions: async () => {{}} }}, windows: {{ onRemoved: none }},
  tabs: {{ onRemoved: none, onCreated: none, onUpdated: none, remove: async (id) => {{ closed.push(id); }}, sendMessage: async () => {{}} }},
  storage: {{
    local: {{ get: async () => ({{ settings: {{ serverUrl: 'http://127.0.0.1:8765', token: 'secret' }} }}) }},
    session: {{
      get: async (k) => Object.fromEntries(keys(k).filter((x) => x in kept).map((x) => [x, kept[x]])),
      set: async (o) => Object.assign(kept, o),
      remove: async (k) => keys(k).forEach((x) => delete kept[x]),
    }},
  }},
}};
globalThis.fetch = async () => ({{ ok: jobwatchAnswers.ok, status: jobwatchAnswers.status, json: async () => jobwatchAnswers.body }});
await import('./background.js');
const send = (msg, tab) => new Promise((resolve) => onMessage(msg, {{ tab }}, resolve));
const text = 'We are hiring a Platform Engineer. '.repeat(10);
const read = (tab) => send({{ type: 'readPosting', text, title: 'Platform Engineer', company: 'Initech', closed: false }}, tab);
{body}""", encoding="utf-8")
    r = subprocess.run(["node", str(tmp_path / "case.mjs")], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@needs_node
def test_the_worker_closes_the_tab_once_its_posting_was_read_and_only_once(tmp_path):
    got = background_case(tmp_path, f"""const tab = {json.dumps(JOB_TAB)};
const before = await send({{ type: 'closeReadTab' }}, tab);
const readReply = await read(tab);
const first = await send({{ type: 'closeReadTab' }}, tab);
const again = await send({{ type: 'closeReadTab' }}, tab);
console.log(JSON.stringify({{ before, readOk: readReply.ok, first, again, closed }}));""")
    assert got["before"]["ok"] is False and "not read" in got["before"]["error"]  # nothing read yet: nothing closes
    assert got["readOk"] is True and got["first"] == {"ok": True}
    assert got["again"]["ok"] is False  # the permission is used up with the tab
    assert got["closed"] == [5]


@needs_node
def test_the_worker_does_not_close_a_tab_whose_read_failed(tmp_path):
    """jobwatch refusing the text (a bad token), the page being a sign-in wall or a captcha (readFailed), or the text being
    too short: each leaves the tab open for the person."""
    got = background_case(tmp_path, f"""const tab = {json.dumps(JOB_TAB)};
jobwatchAnswers = {{ ok: false, status: 403, body: {{ error: 'no' }} }};
const refused = await read(tab);
const afterRefusal = await send({{ type: 'closeReadTab' }}, tab);
const wall = await send({{ type: 'readFailed', error: 'it asks to sign in.' }}, tab);
const afterWall = await send({{ type: 'closeReadTab' }}, tab);
const short = await send({{ type: 'readPosting', text: 'too short' }}, tab);
const afterShort = await send({{ type: 'closeReadTab' }}, tab);
console.log(JSON.stringify({{ refused: refused.ok, wall: wall.ok, short: short.ok,
  after: [afterRefusal.ok, afterWall.ok, afterShort.ok], closed }}));""")
    assert got["refused"] is False and got["short"] is False and got["wall"] is True
    assert got["after"] == [False, False, False] and got["closed"] == []


@needs_node
def test_the_worker_closes_only_the_tab_that_asks_and_that_was_read(tmp_path):
    """Another tab, a tab id named in the message, a page with no tab and a tab that has since gone elsewhere are all refused."""
    got = background_case(tmp_path, f"""const tab = {json.dumps(JOB_TAB)};
const other = {{ id: 6, url: 'https://www.linkedin.com/jobs/view/4000000002/' }};
const feed = {{ id: 5, url: 'https://www.linkedin.com/feed/' }};
const indeed = {{ id: 8, url: 'https://www.indeed.com/viewjob?jk=9cf96221e712e37e' }};
await read(tab);
const results = [
  await send({{ type: 'closeReadTab' }}, other),                  // a job tab nobody read
  await send({{ type: 'closeReadTab', tabId: 5 }}, other),        // naming the read tab does not help
  await send({{ type: 'closeReadTab', tabId: 5 }}, undefined),    // not from a tab at all
  await send({{ type: 'closeReadTab' }}, feed),                   // the read tab, now not a job page
  await send({{ type: 'closeReadTab' }}, {{ id: 9, url: 'https://example.com/jobs/view/4000000001/' }}),
  await send({{ type: 'closeReadTab' }}, indeed),                 // an Indeed job tab nobody read
];
const own = await send({{ type: 'closeReadTab' }}, tab);
console.log(JSON.stringify({{ refused: results.map((r) => r.ok), own: own.ok, closed }}));""")
    assert got == {"refused": [False] * 6, "own": True, "closed": [5]}


@needs_node
def test_an_indeed_posting_that_was_read_is_closed_too(tmp_path):
    got = background_case(tmp_path, """const tab = { id: 8, url: 'https://www.indeed.com/viewjob?jk=9cf96221e712e37e' };
await read(tab);
const r = await send({ type: 'closeReadTab' }, tab);
console.log(JSON.stringify({ ok: r.ok, closed }));""")
    assert got == {"ok": True, "closed": [8]}
