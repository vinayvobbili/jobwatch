"""Reading postings by itself, the extension's half: the scheduler's rules (chrome-extension/auto-read.js, pure functions) and
the worker that carries them out (auto-reader.js, run against a fake chrome with a clock the test moves). Run with node
on made-up pages and a fake jobwatch; nothing ever reaches LinkedIn or Indeed."""
# ruff: noqa: E501  (JavaScript cases in strings)

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from jobwatch import config

EXT = Path(__file__).resolve().parent.parent / "chrome-extension"
needs_node = pytest.mark.skipif(not shutil.which("node"), reason="needs node")


def run_pure(tmp_path, body: str):
    """`body` with `A` (auto-read.js) in scope; it prints one JSON value."""
    js = tmp_path / "pure.js"
    js.write_text(f"const A = require({json.dumps(str(EXT / 'auto-read.js'))});\n{body}", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# --- the limits ------------------------------------------------------------------------------------------------------


@needs_node
def test_the_extensions_limits_are_the_servers(tmp_path):
    """The two halves enforce the same numbers: the defaults and the hard ceilings."""
    got = run_pure(tmp_path, "console.log(JSON.stringify(A.LIMITS));")
    assert (got["DAILY_DEFAULT"], got["DAILY_MAX"], got["TOTAL_MAX"]) == (config.AUTOREAD_PER_DAY, config.AUTOREAD_DAILY_MAX, config.AUTOREAD_DAILY_MAX)
    assert (got["PAUSE_MIN"], got["PAUSE_MAX"], got["PAUSE_FLOOR"], got["SPREAD"]) == (
        config.AUTOREAD_PAUSE_MIN, config.AUTOREAD_PAUSE_MAX, config.AUTOREAD_PAUSE_FLOOR, config.AUTOREAD_SPREAD)
    assert (got["DAILY_DEFAULT"], got["DAILY_MAX"], got["PAUSE_MIN"], got["PAUSE_MAX"]) == (25, 50, 120, 180)


@needs_node
def test_no_answer_from_jobwatch_goes_past_the_ceilings(tmp_path):
    got = run_pure(tmp_path, """console.log(JSON.stringify([
  A.limitsFrom(undefined), A.limitsFrom({ limits: { per_day: 500, pause_min: 1, pause_max: 2 } }),
  A.limitsFrom({ limits: { per_day: -4, pause_min: 'soon', pause_max: null } }), A.limitsFrom({ limits: { per_day: 5, pause_min: 600, pause_max: 900 } }),
  A.limitsFrom({ limits: { per_day: 10, pause_min: 99999, pause_max: 99999 } })]));""")
    assert got == [
        {"perDay": 25, "pauseMin": 120, "pauseMax": 180},
        {"perDay": 50, "pauseMin": 60, "pauseMax": 90},    # ceiling on reads, floor on the pause, a spread kept
        {"perDay": 1, "pauseMin": 120, "pauseMax": 180},
        {"perDay": 5, "pauseMin": 600, "pauseMax": 900},   # tighter is fine
        {"perDay": 10, "pauseMin": 7200, "pauseMax": 7230},
    ]


@needs_node
def test_each_pause_is_a_random_time_from_two_to_three_minutes(tmp_path):
    got = run_pure(tmp_path, """const L = A.limitsFrom();
const lows = [0, 0.25, 0.5, 0.75, 0.999999999].map((r) => A.pauseMs(L, () => r));
const many = Array.from({ length: 2000 }, () => A.pauseMs(L));
console.log(JSON.stringify({ lows, min: Math.min(...many), max: Math.max(...many), distinct: new Set(many).size }));""")
    assert got["lows"][0] == 120000 and got["lows"][2] == 150000 and 179990 <= got["lows"][4] <= 180000
    assert 120000 <= got["min"] and got["max"] <= 180000
    assert got["distinct"] > 1000  # never a fixed interval


# --- the day's counters ----------------------------------------------------------------------------------------------


@needs_node
def test_each_site_has_its_cap_and_both_together_never_pass_the_ceiling(tmp_path):
    got = run_pure(tmp_path, """const L = A.limitsFrom();
const s = (li, ind) => ({ ...A.freshState('2026-11-28'), linkedin: li, indeed: ind });
const big = A.limitsFrom({ limits: { per_day: 50 } });
console.log(JSON.stringify([A.remaining(s(0, 0), L), A.remaining(s(25, 3), L), A.remaining(s(25, 25), L), A.remaining(s(20, 25), big),
  A.remaining(s(30, 19), big), A.remaining(s(50, 0), big), A.remaining(s(0, 0), big)]));""")
    assert got == [
        {"linkedin": 25, "indeed": 25},
        {"linkedin": 0, "indeed": 22},   # LinkedIn used up its own 25
        {"linkedin": 0, "indeed": 0},
        {"linkedin": 5, "indeed": 5},    # 45 read: only 5 more of the 50, even though Indeed's own cap is 50
        {"linkedin": 1, "indeed": 1},
        {"linkedin": 0, "indeed": 0},
        {"linkedin": 50, "indeed": 50},
    ]


@needs_node
def test_a_new_calendar_day_starts_the_counters_again_and_ends_the_stop(tmp_path):
    got = run_pure(tmp_path, """const L = A.limitsFrom();
let s = { ...A.freshState('2026-11-28'), linkedin: 25, indeed: 4, tried: ['a'], noText: 1 };
s = A.afterRead({ ...s, current: { site: 'linkedin' } }, { kind: 'trouble', site: 'linkedin', trouble: { kind: 'signin', why: 'LinkedIn asked for a sign-in' } }, 1000, L);
const same = A.rollDay(s, '2026-11-28');
const next = A.rollDay(s, '2026-11-29');
console.log(JSON.stringify({ sameStopped: same.pausedDay, next: [next.linkedin, next.indeed, next.tried, next.noText, next.pausedDay, next.day],
  localDay: A.localDay(new Date(2026, 0, 5, 23, 59)), midnight: A.localDay(new Date(2026, 11, 31, 0, 0)) }));""")
    assert got["sameStopped"] == "2026-11-28"
    assert got["next"] == [0, 0, [], 0, "", "2026-11-29"]
    assert got["localDay"] == "2026-01-05" and got["midnight"] == "2026-12-31"


@needs_node
def test_the_next_job_is_one_with_reads_left_that_was_not_opened_today(tmp_path):
    got = run_pure(tmp_path, """const L = A.limitsFrom();
const readUrl = (u) => (u.startsWith('https://www.') ? u : '');
const jobs = [{ key: 'a', site: 'linkedin', url: 'https://www.linkedin.com/jobs/view/4000000001/' }, { key: 'b', site: 'indeed', url: 'https://www.indeed.com/viewjob?jk=9cf96221e712e37e' },
  { key: 'c', site: 'linkedin', url: 'http://evil.example/x' }, { key: 'd', site: 'twitter', url: 'https://www.twitter.com/x' }];
const s = (o) => ({ ...A.freshState('d'), ...o });
console.log(JSON.stringify([A.pick(jobs, s({}), L, readUrl).key, A.pick(jobs, s({ tried: ['a'] }), L, readUrl).key,
  A.pick(jobs, s({ linkedin: 25 }), L, readUrl).key, A.pick(jobs, s({ linkedin: 25, indeed: 25 }), L, readUrl),
  A.pick(jobs.slice(2), s({}), L, readUrl), A.pick(undefined, s({}), L, readUrl)]));""")
    assert got == ["a", "b", "b", None, None, None]


# --- what to do now ----------------------------------------------------------------------------------------------------


DECIDE = """const L = A.limitsFrom();
const base = { ...A.freshState('d'), nextAt: 1000 };
const ctx = (o = {}) => ({ now: 5000, day: 'd', limits: L, active: { onSite: false, idle: 'active' }, haveWindow: true, ...o });
const d = (s, c) => A.decide({ ...base, ...s }, ctx(c)).action;
"""


@needs_node
def test_it_reads_only_when_on_not_stopped_not_busy_under_the_caps_and_the_pause_is_over(tmp_path):
    got = run_pure(tmp_path, DECIDE + """console.log(JSON.stringify({
  go: d({}), off: d({ mode: 'off' }), paused: d({ mode: 'paused' }), stopped: d({ pausedDay: 'd' }), yesterdaysStop: d({ pausedDay: 'c' }),
  busy: d({ current: { tabId: 1, startedAt: 4000 } }), stale: d({ current: { tabId: 1, startedAt: 1 } }, { now: 100000 }),
  capped: d({ linkedin: 25, indeed: 25 }), oneSiteCapped: d({ linkedin: 25 }), wait: d({ nextAt: 9000 }), waitUntil: A.decide({ ...base, nextAt: 9000 }, ctx()).until }));""")
    assert got == {"go": "read", "off": "off", "paused": "paused", "stopped": "stopped", "yesterdaysStop": "read", "busy": "busy",
                   "stale": "stale", "capped": "capped", "oneSiteCapped": "read", "wait": "wait", "waitUntil": 9000}


@needs_node
def test_never_two_pages_at_once_the_page_being_read_blocks_everything_else(tmp_path):
    got = run_pure(tmp_path, DECIDE + """const reading = { current: { tabId: 7, startedAt: 4900 } };
console.log(JSON.stringify([d(reading), d({ ...reading, nextAt: 0 }), d({ ...reading, nextAt: 0 }, { now: 4900 + A.LIMITS.TAB_MS - 1 }),
  d({ ...reading, nextAt: 0 }, { now: 4900 + A.LIMITS.TAB_MS })]));""")
    assert got == ["busy", "busy", "busy", "stale"]  # past its time it is ended as one with no text, never given a neighbour


@needs_node
def test_it_does_not_read_while_the_person_is_active_on_linkedin_or_indeed(tmp_path):
    got = run_pure(tmp_path, DECIDE + """const on = (idle) => ({ active: { onSite: true, idle } });
console.log(JSON.stringify({ activeOnSite: A.decide({ ...base }, ctx(on('active'))), idleOnSite: d({}, on('idle')), lockedOnSite: d({}, on('locked')),
  activeElsewhere: d({}, { active: { onSite: false, idle: 'active' } }), noWindow: A.decide({ ...base }, ctx({ haveWindow: false })).why,
  sites: ['https://www.linkedin.com/feed/', 'https://uk.indeed.com/jobs?q=x', 'https://example.com/linkedin.com', 'nonsense', 'https://notlinkedin.com/'].map(A.onJobSite) }));""")
    assert got["activeOnSite"] == {"action": "defer", "until": 5000 + 30000, "why": "busy"}
    assert (got["idleOnSite"], got["lockedOnSite"], got["activeElsewhere"]) == ("read", "read", "read")  # the person's idle, or elsewhere
    assert got["noWindow"] == "no window"
    assert got["sites"] == [True, True, False, False, False]


# --- the first sign of trouble ------------------------------------------------------------------------------------------


@needs_node
@pytest.mark.parametrize("seen, kind, words", [
    ({"wall": "signin"}, "signin", "LinkedIn asked for a sign-in"),
    ({"wall": "captcha"}, "captcha", "LinkedIn showed a security check"),
    ({"wall": "restricted"}, "restricted", "account notice"),
    ({"wall": "blocked"}, "blocked", "too many requests"),
    ({"status": 429}, "blocked", "HTTP 429"),
    ({"status": 999}, "blocked", "HTTP 999"),
    ({"status": 403, "wall": ""}, "blocked", "HTTP 403"),
])
def test_each_sign_of_trouble_from_the_page_is_named(tmp_path, seen, kind, words):
    got = run_pure(tmp_path, f"console.log(JSON.stringify(A.troubleFromPage('linkedin', {json.dumps(seen)})));")
    assert got["kind"] == kind and words in got["why"]


@needs_node
def test_a_page_that_is_only_empty_is_not_trouble_and_ordinary_statuses_are_fine(tmp_path):
    got = run_pure(tmp_path, """console.log(JSON.stringify([A.troubleFromPage('linkedin', { wall: '', status: 200 }), A.troubleFromPage('indeed', { status: 404 }),
  A.troubleFromPage('indeed', {}), A.troubleFromPage('indeed', undefined)]));""")
    assert got == [None, None, None, None]


@needs_node
@pytest.mark.parametrize("url, kind", [
    ("https://www.linkedin.com/authwall?trk=x&sessionRedirect=y", "signin"),
    ("https://www.linkedin.com/login?session_redirect=x", "signin"),
    ("https://www.linkedin.com/uas/login?x=1", "signin"),
    ("https://www.linkedin.com/checkpoint/challenge/abc", "captcha"),
    ("https://secure.indeed.com/auth?continue=x", "signin"),
    ("https://www.indeed.com/account/login", "signin"),
    ("https://www.linkedin.com/jobs/view/4000000001/", None),
    ("https://www.indeed.com/viewjob?jk=9cf96221e712e37e", None),
    ("https://www.linkedin.com/feed/", None),
    ("nonsense", None),
])
def test_a_tab_sent_to_a_sign_in_or_security_page_is_trouble(tmp_path, url, kind):
    got = run_pure(tmp_path, f"console.log(JSON.stringify(A.troubleFromUrl({json.dumps(url)})));")
    assert (got and got["kind"]) == kind


@needs_node
def test_trouble_stops_the_day_with_a_message_naming_the_site_and_the_way_back(tmp_path):
    got = run_pure(tmp_path, """const L = A.limitsFrom();
const s = { ...A.freshState('d'), current: { tabId: 1, key: 'k', site: 'linkedin', startedAt: 1 } };
const after = A.afterRead(s, { kind: 'trouble', site: 'linkedin', trouble: { kind: 'signin', why: 'LinkedIn asked for a sign-in' } }, 10000, L, () => 0);
console.log(JSON.stringify({ after, decide: A.decide(after, { now: 10000000, day: 'd', limits: L, active: {}, haveWindow: true }).action,
  next: A.decide(after, { now: 10000000, day: 'e', limits: L, active: {}, haveWindow: true }).action }));""")
    after = got["after"]
    assert after["pausedReason"] == "Auto-read paused: LinkedIn asked for a sign-in. Resumes tomorrow, or press Resume after you check LinkedIn."
    assert after["pausedDay"] == "d" and after["pausedKind"] == "signin" and after["current"] is None and after["nextAt"] == 10000 + 120000
    assert got["decide"] == "stopped" and got["next"] == "read"  # tomorrow it would read again, once the day rolls over


@needs_node
def test_two_pages_in_a_row_with_no_posting_stop_the_day_and_a_read_between_them_does_not(tmp_path):
    got = run_pure(tmp_path, """const L = A.limitsFrom();
const go = (s, kind) => A.afterRead({ ...s, current: { site: 'indeed' } }, { kind, site: 'indeed' }, 0, L);
const s0 = A.freshState('d');
const one = go(s0, 'no_text'), two = go(one, 'no_text');
const broken = go(go(go(s0, 'no_text'), 'read'), 'no_text');
const cancelled = go(go(go(s0, 'no_text'), 'cancelled'), 'error');
console.log(JSON.stringify({ one: [one.noText, one.pausedDay], two: [two.noText, two.pausedDay, two.pausedKind, two.pausedReason], broken: [broken.noText, broken.pausedDay],
  cancelled: [cancelled.noText, cancelled.pausedDay] }));""")
    assert got["one"] == [1, ""]
    assert got["two"][:3] == [2, "d", "no_text"] and "2 pages in a row had no posting text" in got["two"][3] and "Indeed" in got["two"][3]
    assert got["broken"] == [1, ""]
    assert got["cancelled"] == [1, ""]  # a closed tab or jobwatch being down neither counts nor clears


# --- the person's controls and what they see -------------------------------------------------------------------------------


@needs_node
def test_pause_resume_and_off_and_resume_clears_the_stop_after_a_fresh_pause(tmp_path):
    got = run_pure(tmp_path, """const L = A.limitsFrom();
let s = { ...A.freshState('d'), nextAt: 5, noText: 1, linkedin: 3 };
const stoppedS = A.afterRead({ ...s, current: { site: 'linkedin' } }, { kind: 'trouble', site: 'linkedin', trouble: { kind: 'blocked', why: 'x' } }, 0, L);
const paused = A.command(s, 'pause', 1000, L), off = A.command(s, 'off', 1000, L);
const resumed = A.command(stoppedS, 'resume', 1000, L, () => 0), on = A.command(off, 'on', 1000, L, () => 0.5);
let bad = ''; try { A.command(s, 'shout', 1, L); } catch (e) { bad = e.message; }
console.log(JSON.stringify({ paused: paused.mode, off: off.mode, resumed: [resumed.mode, resumed.pausedDay, resumed.noText, resumed.nextAt, resumed.linkedin],
  on: [on.mode, on.nextAt], bad }));""")
    assert got["paused"] == "paused" and got["off"] == "off"
    assert got["resumed"] == ["on", "", 0, 1000 + 120000, 3]  # the stop is cleared; today's count stays
    assert got["on"] == ["on", 1000 + 150000] and "unknown command" in got["bad"]


STATUS = """const L = A.limitsFrom();
const V = (o, day = 'd') => A.view({ ...A.freshState('d'), serverOn: true, ...o }, { limits: L, day });
const line = (o, now = 0, day = 'd') => A.statusLine(V(o, day), now);
"""


@needs_node
def test_the_status_line_says_how_many_today_and_when_the_next_read_is(tmp_path):
    got = run_pure(tmp_path, STATUS + """console.log(JSON.stringify([
  line({ linkedin: 2, indeed: 1, queued: 9, nextAt: 120000 }), line({ linkedin: 2, indeed: 1, queued: 9, nextAt: 45000 }, 0), line({ linkedin: 3, queued: 99, nextAt: 130000 }),
  line({ linkedin: 3, queued: 0, nextAt: 10 }), line({ linkedin: 3, queued: 4, current: { tabId: 1, startedAt: 1 } }),
  line({ linkedin: 25, indeed: 25, queued: 5 }), line({ linkedin: 1, queued: 3, deferred: true }),
  line({ mode: 'paused' }), line({ mode: 'off' }), line({ serverOn: false }), line({ pausedDay: 'd', pausedReason: 'Auto-read paused: x.' }), line({ pausedDay: 'c', queued: 2, nextAt: 60000 })]));""")
    assert got == [
        "Reading postings: 3 of 12 today · next in 2m",
        "Reading postings: 3 of 12 today · next in 45s",
        "Reading postings: 3 of 50 today · next in 3m",   # what is waiting is capped by what the day still allows
        "Reading postings: 3 today · nothing waiting",
        "Reading postings: 3 of 7 today · reading one now",
        "Reading postings: 50 today · done for today, back tomorrow",
        "Reading postings: 1 of 4 today · waiting until you leave LinkedIn or Indeed",
        "Reading postings is paused. Press Resume to continue.",
        "Auto-read is off in this browser.",
        "Reading postings is off in jobwatch's Settings.",
        "Auto-read paused: x.",
        "Reading postings: 0 of 2 today · next in 1m",    # yesterday's stop is over
    ]


@needs_node
def test_the_buttons_follow_the_state(tmp_path):
    got = run_pure(tmp_path, STATUS + """console.log(JSON.stringify({ waiting: V({ queued: 2 }).buttons, paused: V({ mode: 'paused' }).buttons, off: V({ mode: 'off' }).buttons,
  stopped: V({ pausedDay: 'd', pausedReason: 'x' }).buttons, disabled: V({ serverOn: false }).buttons, states: [V({}).state, V({ queued: 1 }).state, V({ mode: 'paused' }).state] }));""")
    assert got == {"waiting": ["pause", "off"], "paused": ["resume", "off"], "off": ["on"], "stopped": ["resume", "off"], "disabled": [],
                   "states": ["empty", "waiting", "paused"]}


# --- the worker, with a fake chrome and a clock the test moves --------------------------------------------------------------


def worker_case(tmp_path, body: str):
    """auto-reader.js loaded in node with a fake chrome (storage, alarms, idle, tabs, windows, action), a fake clock (`clock`,
    moved with `at(ms)`) and a fake jobwatch (`jobwatch.queue`, `.answers`, with every request in `calls`). `lastTab` is the
    newest tab opened; `read(tab)` delivers what read-posting.js would send from it. Prints what `body` prints."""
    for name in ("auto-reader.js", "auto-read.js", "read-posting.js", "lib.js"):
        shutil.copy(EXT / name, tmp_path / name)
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (tmp_path / "case.mjs").write_text(f"""let clock = Date.UTC(2026, 10, 28, 15, 0, 0);
Date.now = () => clock;
const kept = {{}}, tabs = [], removed = [], alarms = [], calls = [], badge = [];
let idleState = 'idle', activeTab = {{ id: 1, url: 'https://example.com/' }}, windows = true;
const jobwatch = {{ enabled: true, limits: {{ per_day: 25, pause_min: 120, pause_max: 180 }}, jobs: [], waiting: 0, postingAnswer: {{ ok: true, status: 200, body: {{ where: 'today', has_text: true }} }} }};
const keys = (k) => (Array.isArray(k) ? k : [k]);
globalThis.chrome = {{
  storage: {{ local: {{
    get: async (k) => (k === 'settings' ? {{ settings: {{ serverUrl: 'http://127.0.0.1:8765', token: 'secret' }} }} : Object.fromEntries(keys(k).filter((x) => x in kept).map((x) => [x, structuredClone(kept[x])]))),
    set: async (o) => Object.assign(kept, structuredClone(o)) }} }},
  alarms: {{ create: (name, info) => alarms.push([name, info]), get: async () => null }},
  idle: {{ queryState: async () => idleState, setDetectionInterval() {{}} }},
  tabs: {{ query: async () => (activeTab ? [activeTab] : []), create: async (o) => {{ const t = {{ id: 100 + tabs.length, ...o }}; tabs.push(t); return t; }},
    remove: async (id) => {{ removed.push(id); }} }},
  windows: {{ getLastFocused: async () => {{ if (!windows) throw new Error('none'); return {{ id: 9 }}; }} }},
  action: {{ setBadgeText: async (o) => badge.push(o.text), setBadgeBackgroundColor: async () => {{}}, setTitle: async () => {{}} }},
}};
globalThis.fetch = async (url, init = {{}}) => {{
  const path = url.replace('http://127.0.0.1:8765', '');
  const body = init.body ? JSON.parse(init.body) : null;
  calls.push({{ path, method: init.method || 'GET', body }});
  let answer = {{ ok: true, status: 200, body: {{ ok: true }} }};
  if (path.startsWith('/ext/read-queue')) answer = {{ ok: true, status: 200, body: {{ enabled: jobwatch.enabled, limits: jobwatch.limits, waiting: jobwatch.waiting, jobs: jobwatch.jobs }} }};
  if (path === '/ext/posting') answer = jobwatch.postingAnswer;
  return {{ ok: answer.ok, status: answer.status, json: async () => answer.body }};
}};
await import('./auto-read.js');
await import('./read-posting.js');
const A = await import('./auto-reader.js');
const at = (ms) => {{ clock += ms; }};
const li = (n, extra = {{}}) => ({{ key: `manual:umbrella:job-${{n}}`, site: 'linkedin', url: `https://www.linkedin.com/jobs/view/${{4000000000 + n}}/`, title: `Job ${{n}}`, company: 'Umbrella', ...extra }});
const ind = (n) => ({{ key: `manual:hooli:job-${{n}}`, site: 'indeed', url: `https://www.indeed.com/viewjob?jk=${{String(n).padStart(16, 'a')}}`, title: `Indeed ${{n}}`, company: 'Hooli' }});
const TEXT = 'We are hiring a platform engineer to build services in Python. '.repeat(8);
const sender = (tab) => ({{ tab: {{ id: tab.id, url: tab.url.replace('#jobwatch-read', '') }} }});
const read = async (tab, extra = {{}}) => {{
  const onSite = await A.owns(sender(tab));
  return onSite ? A.onPosting({{ text: TEXT, title: 'Job', company: 'Umbrella', closed: false, ...extra }}, sender(tab)) : null;
}};
const state = () => structuredClone(kept.autoRead);
const posts = () => calls.filter((c) => c.path === '/ext/posting');
const reports = () => calls.filter((c) => c.path === '/ext/read-report').map((c) => c.body);
const queries = () => calls.filter((c) => c.path.startsWith('/ext/read-queue')).map((c) => c.path);
const lastTab = () => tabs[tabs.length - 1];
// the first tick only sets the first pause; the clock then moves past the pause so the next one reads
const ready = async () => {{ await A.tick(); at(181000); }};
{body}""", encoding="utf-8")
    r = subprocess.run(["node", str(tmp_path / "case.mjs")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@needs_node
def test_a_read_opens_one_inactive_tab_with_the_readers_marker_and_closes_it_once_the_text_is_copied(tmp_path):
    got = worker_case(tmp_path, """jobwatch.jobs = [li(1), li(2)]; jobwatch.waiting = 2;
await A.tick();                       // the very first tick: only the first pause is set, nothing is opened
const none = tabs.length;
at(181000); await A.tick();
const opened = { ...lastTab() }, count = tabs.length;
await A.tick(); at(60000); await A.tick();         // the page is still being read (within its time): no second one
const afterWait = tabs.length;
await read(lastTab());
console.log(JSON.stringify({ none, opened, count, afterWait, posting: posts()[0].body, removed, state: state(), query: queries()[0] }));""")
    assert got["none"] == 0 and got["count"] == 1 and got["afterWait"] == 1  # never two tabs at once
    assert got["opened"]["active"] is False and got["opened"]["windowId"] == 9
    assert got["opened"]["url"] == "https://www.linkedin.com/jobs/view/4000000001/#jobwatch-read"
    assert got["posting"] == {"linkedin": "4000000001", "company": "Umbrella", "title": "Job", "text": got["posting"]["text"], "closed": False, "auto": True}
    assert got["removed"] == [100]  # closed right after the text was copied
    assert (got["state"]["linkedin"], got["state"]["indeed"], got["state"]["current"]) == (1, 0, None)
    assert got["query"] == "/ext/read-queue?linkedin=25&indeed=25&limit=5"


@needs_node
def test_the_pause_after_a_read_is_two_to_three_minutes_and_the_next_page_waits_for_it(tmp_path):
    got = worker_case(tmp_path, """jobwatch.jobs = [li(1), li(2), li(3)]; jobwatch.waiting = 3;
await ready(); await A.tick(); await read(lastTab());
const first = state(), readAt = clock;
at(100000); await A.tick();                   // 100 s after the read: too soon
const soon = tabs.length;
at(81000); await A.tick();                    // 181 s: past the longest pause
console.log(JSON.stringify({ pause: first.nextAt - readAt, soon, later: tabs.length, alarms: alarms.filter((a) => a[0] === 'autoread-next').length > 0 }));""")
    assert 120000 <= got["pause"] <= 180000 and got["soon"] == 1 and got["later"] == 2 and got["alarms"]


@needs_node
def test_the_daily_cap_stops_it_for_the_day_and_a_new_day_starts_it_again(tmp_path):
    got = worker_case(tmp_path, """jobwatch.limits = { per_day: 3, pause_min: 120, pause_max: 180 };
jobwatch.jobs = Array.from({ length: 9 }, (_, i) => li(i + 1)); jobwatch.waiting = 9;
await ready();
for (let i = 0; i < 6; i++) { await A.tick(); if (tabs.length > i) await read(lastTab()); at(181000); }
const today = { tabs: tabs.length, state: state() };
const queriesToday = queries().length;
await A.tick(); const noMoreQuery = queries().length === queriesToday;  // capped: jobwatch is not even asked
at(24 * 3600 * 1000); await A.tick();
console.log(JSON.stringify({ today: today.tabs, count: today.state.linkedin, noMoreQuery, tomorrow: tabs.length, tomorrowCount: state().linkedin }));""")
    assert got["today"] == 3 and got["count"] == 3 and got["noMoreQuery"] is True
    assert got["tomorrow"] == 4 and got["tomorrowCount"] == 1  # the counters started again with the new day


@needs_node
def test_both_sites_together_never_pass_fifty_a_day_whatever_jobwatch_says(tmp_path):
    got = worker_case(tmp_path, """jobwatch.limits = { per_day: 500, pause_min: 1, pause_max: 2 };   // a jobwatch asking for the impossible
for (let i = 1; i <= 40; i++) jobwatch.jobs.push(li(i), ind(i));
jobwatch.waiting = 80;
await ready();
for (let i = 0; i < 70; i++) {
  await A.tick();
  if (tabs.length > i) await read(lastTab());
  at(91000);                                           // longer than the longest pause jobwatch's answer is clamped to
}
const s = state();
console.log(JSON.stringify({ tabs: tabs.length, linkedin: s.linkedin, indeed: s.indeed, status: (await A.status()).state }));""")
    assert got["tabs"] == 50 and got["linkedin"] + got["indeed"] == 50  # 50 and not one more, though jobwatch offered 80 jobs and 500 a site
    assert got["status"] == "capped"


@needs_node
def test_a_pause_never_goes_under_the_floor_however_small_jobwatch_says_it_is(tmp_path):
    got = worker_case(tmp_path, """jobwatch.limits = { per_day: 25, pause_min: 1, pause_max: 2 };
jobwatch.jobs = [li(1), li(2)]; jobwatch.waiting = 2;
await ready(); await A.tick(); await read(lastTab());
const pause = state().nextAt - clock;
await A.tick();
console.log(JSON.stringify({ pause }));""")
    assert 60000 <= got["pause"] <= 90000


@needs_node
def test_nothing_is_read_while_it_is_off_paused_or_jobwatchs_setting_is_off(tmp_path):
    got = worker_case(tmp_path, """jobwatch.jobs = [li(1)]; jobwatch.waiting = 1;
await ready();
await A.command('off'); at(181000); await A.tick(); const off = tabs.length;
await A.command('on'); await A.command('pause'); at(181000); await A.tick(); const paused = tabs.length;
await A.command('resume'); jobwatch.enabled = false; at(181000); await A.tick(); const disabled = tabs.length;
const s = await A.status();
console.log(JSON.stringify({ off, paused, disabled, state: s.state, reports: reports().map((r) => r.event) }));""")
    assert (got["off"], got["paused"], got["disabled"]) == (0, 0, 0)
    assert got["state"] == "disabled"
    assert got["reports"] == ["off", "on", "paused", "resumed"]


@needs_node
def test_it_does_not_read_while_the_person_is_active_on_linkedin_and_reads_when_they_go_idle_or_switch_tab(tmp_path):
    got = worker_case(tmp_path, """jobwatch.jobs = [li(1)]; jobwatch.waiting = 1;
await ready();
activeTab = { id: 5, url: 'https://www.linkedin.com/feed/' }; idleState = 'active';
await A.tick(); const busy = tabs.length;
at(31000); await A.tick(); const stillBusy = tabs.length;
const deferred = state().deferred, status = (await A.status()).state;
idleState = 'idle'; await A.tick(); const idleReads = tabs.length;
console.log(JSON.stringify({ busy, stillBusy, deferred, status, idleReads }));""")
    assert (got["busy"], got["stillBusy"], got["deferred"], got["status"], got["idleReads"]) == (0, 0, True, "deferred", 1)


@needs_node
def test_a_tab_switch_away_from_linkedin_lets_it_read(tmp_path):
    got = worker_case(tmp_path, """jobwatch.jobs = [li(1)]; jobwatch.waiting = 1;
await ready();
activeTab = { id: 5, url: 'https://www.linkedin.com/feed/' }; idleState = 'active';
await A.tick(); const before = tabs.length;
activeTab = { id: 6, url: 'https://news.example/' };      // the person switches to another tab
await A.tick();
console.log(JSON.stringify({ before, after: tabs.length }));""")
    assert got == {"before": 0, "after": 1}


@needs_node
@pytest.mark.parametrize("failure, reason_part", [
    ({"error": "the page doesn't show the posting: it asks to sign in.", "wall": "signin"}, "LinkedIn asked for a sign-in"),
    ({"error": "captcha", "wall": "captcha"}, "LinkedIn showed a security check"),
    ({"error": "refused", "status": 429, "wall": "blocked"}, "HTTP 429"),
    ({"error": "refused", "status": 999}, "HTTP 999"),
    ({"error": "refused", "status": 403}, "HTTP 403"),
    ({"error": "notice", "wall": "restricted"}, "account notice"),
])
def test_the_first_sign_of_trouble_stops_the_day_shows_a_badge_tells_jobwatch_and_leaves_the_tab(tmp_path, failure, reason_part):
    got = worker_case(tmp_path, f"""jobwatch.jobs = [li(1), li(2)]; jobwatch.waiting = 2;
await ready(); await A.tick();
const owns = await A.owns(sender(lastTab()));
await A.onFailed({json.dumps(failure)}, sender(lastTab()));
const s = state(), badgeNow = badge[badge.length - 1];
at(4 * 3600 * 1000); await A.tick();                  // hours later, the same day
const status = await A.status();
console.log(JSON.stringify({{ owns, stopped: s.pausedDay === s.day, reason: s.pausedReason, badge: badgeNow, tabs: tabs.length, removed, reports: reports(), status }}));""")
    assert got["owns"] is True and got["stopped"] is True
    assert got["reason"].startswith("Auto-read paused: ") and reason_part in got["reason"] and "Resumes tomorrow, or press Resume after you check LinkedIn." in got["reason"]
    assert got["badge"] == "!" and got["tabs"] == 1 and got["removed"] == []  # nothing more opened, the tab is the person's to look at
    assert got["status"]["state"] == "stopped" and got["status"]["buttons"] == ["resume", "off"] and got["status"]["reason"] == got["reason"]
    kinds = [(r.get("outcome"), r.get("event")) for r in got["reports"]]
    assert kinds == [("trouble", None), (None, "paused")] and got["reports"][1]["reason"] == got["reason"]


@needs_node
def test_a_tab_sent_to_the_authwall_stops_the_day_and_stays_open(tmp_path):
    got = worker_case(tmp_path, """jobwatch.jobs = [li(1)]; jobwatch.waiting = 1;
await ready(); await A.tick();
const tab = lastTab();
await A.onTabUpdated(tab.id, { url: 'https://www.linkedin.com/authwall?trk=x' }, { id: tab.id, url: 'https://www.linkedin.com/authwall?trk=x' });
const s = state();
console.log(JSON.stringify({ kind: s.pausedKind, stopped: s.pausedDay === s.day, removed, current: s.current }));""")
    assert got == {"kind": "signin", "stopped": True, "removed": [], "current": None}


@needs_node
def test_a_tab_that_goes_somewhere_else_is_a_page_with_no_text_and_two_of_them_stop_the_day(tmp_path):
    got = worker_case(tmp_path, """jobwatch.jobs = [li(1), li(2), li(3)]; jobwatch.waiting = 3;
await ready();
const outcomes = [];
for (let i = 0; i < 3; i++) {
  await A.tick();
  if (tabs.length > i) { const t = lastTab(); await A.onTabUpdated(t.id, { status: 'complete' }, { id: t.id, url: 'https://www.linkedin.com/jobs/collections/recommended/' }); }
  outcomes.push(state().noText + ':' + (state().pausedDay === state().day));
  at(181000);
}
console.log(JSON.stringify({ outcomes, tabs: tabs.length, removed, reports: reports().map((r) => r.outcome || r.event) }));""")
    assert got["outcomes"] == ["1:false", "2:true", "2:true"]
    assert got["tabs"] == 2 and got["removed"] == [100, 101]  # an empty page is closed; after the second, nothing more
    assert got["reports"] == ["no_text", "no_text", "paused"]


@needs_node
def test_a_page_with_no_posting_is_closed_and_the_job_is_not_tried_again_today(tmp_path):
    got = worker_case(tmp_path, """jobwatch.jobs = [li(1), li(2)]; jobwatch.waiting = 2;
await ready(); await A.tick();
await A.onFailed({ error: 'the page has no posting text on it', wall: '' }, sender(lastTab()));
const one = state(); at(181000);
await A.tick(); const second = lastTab().url;
console.log(JSON.stringify({ removed, noText: one.noText, stopped: one.pausedDay === one.day, tried: one.tried, second, report: reports()[0] }));""")
    assert got["removed"] == [100] and got["noText"] == 1 and got["stopped"] is False
    assert got["tried"] == ["manual:umbrella:job-1"] and got["second"].endswith("4000000002/#jobwatch-read")
    assert got["report"] == {"outcome": "no_text", "key": "manual:umbrella:job-1", "site": "linkedin", "reason": "the page has no posting text on it"}


@needs_node
def test_a_tab_the_person_closes_is_no_trouble_and_a_page_that_never_answers_counts_as_no_text(tmp_path):
    got = worker_case(tmp_path, """jobwatch.jobs = [li(1), li(2), li(3)]; jobwatch.waiting = 3;
await ready(); await A.tick();
await A.onTabRemoved(lastTab().id);
const closed = { noText: state().noText, stopped: state().pausedDay === state().day, current: state().current, reports: reports().map((r) => r.outcome) };
at(181000); await A.tick();                                  // the next page opens... and never answers
at(76000); await A.tick();                                   // past its time: ended, and its tab closed
const hung = { noText: state().noText, removed, current: state().current };
console.log(JSON.stringify({ closed, hung }));""")
    assert got["closed"] == {"noText": 0, "stopped": False, "current": None, "reports": ["cancelled"]}
    assert got["hung"] == {"noText": 1, "removed": [101], "current": None}


@needs_node
def test_a_jobwatch_that_is_not_running_is_no_trouble_and_opens_nothing(tmp_path):
    got = worker_case(tmp_path, """globalThis.fetch = async () => { throw new Error('refused'); };
await ready(); await A.tick();
const s = state();
console.log(JSON.stringify({ tabs: tabs.length, stopped: s.pausedDay === s.day, wait: s.nextAt - clock }));""")
    assert got["tabs"] == 0 and got["stopped"] is False and got["wait"] > 0


@needs_node
def test_a_page_that_is_not_the_job_asked_for_is_refused_and_nothing_is_sent(tmp_path):
    got = worker_case(tmp_path, """jobwatch.jobs = [li(1)]; jobwatch.waiting = 1;
await ready(); await A.tick();
const t = lastTab();
let refused = '';
try { await A.onPosting({ text: TEXT, title: 'x', company: 'y' }, { tab: { id: t.id, url: 'https://www.linkedin.com/jobs/view/4000000077/' } }); } catch (e) { refused = e.message; }
console.log(JSON.stringify({ refused, posts: posts().length, noText: state().noText, removed }));""")
    assert "doesn't show the job's posting" in got["refused"] and got["posts"] == 0 and got["noText"] == 1 and got["removed"] == [100]


@needs_node
def test_only_the_page_being_read_belongs_to_the_auto_reader(tmp_path):
    got = worker_case(tmp_path, """jobwatch.jobs = [li(1)]; jobwatch.waiting = 1;
await ready(); const before = await A.owns(sender({ id: 100, url: 'https://www.linkedin.com/jobs/view/4000000001/' }));
await A.tick(); const t = lastTab();
const mine = await A.owns(sender(t));
const other = await A.owns(sender({ id: 7, url: t.url }));
const none = await A.owns({});
const page = await A.owns({ tab: undefined });
console.log(JSON.stringify({ before, mine, other, none, page }));""")
    assert got == {"before": False, "mine": True, "other": False, "none": False, "page": False}


@needs_node
def test_the_status_is_what_the_popup_and_page_show(tmp_path):
    got = worker_case(tmp_path, """jobwatch.jobs = [li(1), li(2), li(3), li(4)]; jobwatch.waiting = 4;
await ready(); await A.tick(); await read(lastTab());
const s = await A.status();
console.log(JSON.stringify({ s, pause: clock }));""")
    s = got["s"]
    assert (s["paired"], s["state"], s["done"], s["planned"], s["buttons"]) == (True, "waiting", 1, 4, ["pause", "off"])
    assert 120000 <= s["nextAt"] - got["pause"] <= 180000
